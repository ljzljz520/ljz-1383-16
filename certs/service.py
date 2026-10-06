"""领域服务: 证书证据管理的核心规则。

事件语义(同一证书身份下的不同事件, 绝不因上传图片而新增成就):
  AWARDED          新获奖      —— 创建证书身份与首个修订
  IMAGE_ATTACHED   首次附图    —— 仅补充证据, 身份不变
  IMAGE_REISSUED   补发图片    —— 替换图片, 身份不变
  IMAGE_FAILED     图片处理失败 —— 记录事实, 不影响既有证据
  RENEWED          续期        —— 延长有效期(产生新修订)
  REVOKED          撤销        —— 支持追溯生效(occurred_at 可为过去)
  ISSUER_RENAMED   机构更名    —— 名称历史, 机构身份不变
  LINK_CHECKED     链接核对    —— 可访问仅说明来源仍在
  CLOCK_CORRECTED  时钟校正    —— 服务器时钟偏移调整

状态权威: 公开读取一律使用 compute_status() 实时计算;
cert_projection 仅为事件驱动缓存, reconcile() 用于发现并校正漂移。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import pngtool
from .clock import Clock, iso, parse_instant, to_utc
from .db import get_meta, set_meta

VALIDITY = ("valid", "expiring_soon", "expired", "revoked")
VERIFICATION = ("self_reported", "source_checked", "link_failed")
EXPIRING_SOON_DAYS = 30

VERIFICATION_NOTE = "链接可访问仅说明来源仍然存在, 不构成权威机构对证书真实性的认证"
SORT_NOTE = "按状态分组、获奖时间排序; 不提供也不暗示任何含金量评分"


class DomainError(Exception):
    """业务规则冲突(如证书不存在、重复提交)。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- 基础工具

def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _now_iso(clock: Clock) -> str:
    return iso(clock.now())


def _append_event(conn: sqlite3.Connection, clock: Clock, *,
                  type_: str, payload: dict,
                  certificate_id: int | None = None,
                  issuer_id: int | None = None,
                  occurred_at: datetime | None = None,
                  idempotency_key: str | None = None) -> sqlite3.Row:
    """追加事件(事实源)。幂等键冲突时返回既有事件, 保证重试安全。"""
    if idempotency_key:
        row = conn.execute("SELECT * FROM events WHERE idempotency_key=?",
                           (idempotency_key,)).fetchone()
        if row:
            return row
    cur = conn.execute(
        "INSERT INTO events(certificate_id, issuer_id, type, payload_json,"
        " occurred_at, recorded_at, clock_offset_ms, idempotency_key)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (certificate_id, issuer_id, type_, _dump(payload),
         iso(to_utc(occurred_at)) if occurred_at else _now_iso(clock),
         _now_iso(clock), clock.offset_ms, idempotency_key))
    return conn.execute("SELECT * FROM events WHERE id=?", (cur.lastrowid,)).fetchone()


def _get_cert(conn: sqlite3.Connection, certificate_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM certificates WHERE id=?", (certificate_id,)).fetchone()
    if not row:
        raise DomainError("not_found", f"证书 #{certificate_id} 不存在")
    return row


# ---------------------------------------------------------------- 实时状态计算(权威)

def expiry_instant(valid_until: str, expiry_tz: str) -> datetime:
    """计算到期时刻(aware UTC)。

    - 纯日期 YYYY-MM-DD: 以签发方时区该日结束为准, 即次日 00:00(当地)到期;
      这正确处理"午夜到期"的跨时区边界。
    - 带时间的 ISO: naive 视为签发方时区, aware 直接使用。
    """
    tz = ZoneInfo(expiry_tz)
    text = valid_until.strip()
    if len(text) == 10 and text[4] == "-":            # 纯日期
        y, m, d = int(text[0:4]), int(text[5:7]), int(text[8:10])
        local_midnight = datetime(y, m, d, 0, 0, 0, tzinfo=tz) + timedelta(days=1)
        return local_midnight.astimezone(timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def compute_status(conn: sqlite3.Connection, certificate_id: int,
                   now: datetime, *, expiring_days: int = EXPIRING_SOON_DAYS) -> dict:
    """实时计算证书状态(公开读取的唯一权威)。

    判定顺序: 撤销(含追溯) > 到期 > 临期 > 有效; 核对状态独立成维度。
    """
    cert = _get_cert(conn, certificate_id)
    now = to_utc(now)

    revoked_at = None
    for ev in conn.execute(
            "SELECT * FROM events WHERE certificate_id=? AND type='REVOKED'"
            " ORDER BY id", (certificate_id,)):
        occurred = parse_instant(ev["occurred_at"])
        if occurred <= now:                          # 追溯撤销: 生效时间在过去即已撤销
            revoked_at = occurred
    if revoked_at is not None:
        validity = "revoked"
    else:
        exp = None
        if cert["valid_until"]:
            exp = expiry_instant(cert["valid_until"], cert["expiry_tz"])
        if exp is None:
            validity = "valid"
        elif now >= exp:
            validity = "expired"
        elif exp - now <= timedelta(days=expiring_days):
            validity = "expiring_soon"
        else:
            validity = "valid"
        revoked_at = None

    check = conn.execute(
        "SELECT * FROM link_checks WHERE certificate_id=?"
        " ORDER BY id DESC LIMIT 1", (certificate_id,)).fetchone()
    if check is None:
        verification = "self_reported"               # 自报: 从未核对过来源
    elif check["outcome"] == "reachable":
        verification = "source_checked"              # 已核对来源(≠权威认证)
    else:
        verification = "link_failed"                 # 来源链接失效

    return {
        "validity": validity,
        "verification": verification,
        "valid_until": cert["valid_until"],
        "expiry_tz": cert["expiry_tz"],
        "revoked_at": iso(revoked_at) if revoked_at else None,
        "computed_at": iso(now),
    }


# ---------------------------------------------------------------- 事件驱动投影(缓存)

def _refresh_projection(conn: sqlite3.Connection, clock: Clock,
                        certificate_id: int, last_event_id: int) -> None:
    """事件触发时同步刷新投影。时间自然流逝(到期)由 sweep() 补齐。"""
    status = compute_status(conn, certificate_id, clock.now())
    conn.execute(
        "INSERT INTO cert_projection(certificate_id, validity, verification,"
        " valid_until, last_event_id, updated_at) VALUES(?,?,?,?,?,?)"
        " ON CONFLICT(certificate_id) DO UPDATE SET validity=excluded.validity,"
        " verification=excluded.verification, valid_until=excluded.valid_until,"
        " last_event_id=excluded.last_event_id, updated_at=excluded.updated_at",
        (certificate_id, status["validity"], status["verification"],
         status["valid_until"], last_event_id, _now_iso(clock)))


def sweep(conn: sqlite3.Connection, clock: Clock) -> list[int]:
    """时间驱动的"滴答": 把已随时间改变状态的投影补齐(如午夜到期)。"""
    changed = []
    now = clock.now()
    for row in conn.execute("SELECT certificate_id, validity FROM cert_projection"):
        status = compute_status(conn, row["certificate_id"], now)
        if status["validity"] != row["validity"]:
            conn.execute(
                "UPDATE cert_projection SET validity=?, valid_until=?, updated_at=?"
                " WHERE certificate_id=?",
                (status["validity"], status["valid_until"], _now_iso(clock),
                 row["certificate_id"]))
            changed.append(row["certificate_id"])
            _propagate(conn, clock, row["certificate_id"])
    return changed


def reconcile(conn: sqlite3.Connection, clock: Clock) -> list[dict]:
    """对比实时计算与事件驱动投影, 返回漂移清单(校正前的事实报告)。"""
    drift = []
    now = clock.now()
    for row in conn.execute("SELECT * FROM cert_projection"):
        status = compute_status(conn, row["certificate_id"], now)
        if (status["validity"] != row["validity"]
                or status["verification"] != row["verification"]):
            drift.append({
                "certificate_id": row["certificate_id"],
                "projected": {"validity": row["validity"],
                              "verification": row["verification"]},
                "computed": {"validity": status["validity"],
                             "verification": status["verification"]},
            })
    return drift


# ---------------------------------------------------------------- 传播: 技能证据与简历

_SKILL_STATE = {"valid": "current", "expiring_soon": "current",
                "expired": "expired", "revoked": "revoked"}


def _propagate(conn: sqlite3.Connection, clock: Clock, certificate_id: int) -> None:
    """状态变化传播到技能证据与简历候选; 冻结简历只加附注, 不改写。"""
    status = compute_status(conn, certificate_id, clock.now())
    skill_state = _SKILL_STATE[status["validity"]]
    if status["verification"] == "link_failed" and skill_state == "current":
        skill_state = "unverified"

    for row in conn.execute(
            "SELECT * FROM skill_evidence WHERE certificate_id=?", (certificate_id,)):
        if row["state"] != skill_state:
            conn.execute("UPDATE skill_evidence SET state=?, updated_at=? WHERE id=?",
                         (skill_state, _now_iso(clock), row["id"]))

    cert = _get_cert(conn, certificate_id)
    issuer = current_issuer_name(conn, cert["issuer_id"], clock.now())
    for item in conn.execute(
            "SELECT ri.*, r.frozen_at FROM resume_items ri"
            " JOIN resumes r ON r.id = ri.resume_id"
            " WHERE ri.certificate_id=?", (certificate_id,)):
        snap = json.loads(item["snapshot_json"])
        if item["frozen_at"] is None:                # 简历候选(未冻结): 跟随最新状态
            snap.update({
                "validity": status["validity"],
                "verification": status["verification"],
                "valid_until": status["valid_until"],
                "issuer_name": issuer,
                "captured_at": _now_iso(clock),
            })
            conn.execute("UPDATE resume_items SET snapshot_json=? WHERE id=?",
                         (_dump(snap), item["id"]))
        else:                                        # 冻结简历: 不覆盖, 追加附注
            if (snap.get("validity") != status["validity"]
                    or snap.get("verification") != status["verification"]):
                notice = (f"冻结后发生变化: 证书《{cert['title']}》状态由 "
                          f"{snap.get('validity')}/{snap.get('verification')} 变为 "
                          f"{status['validity']}/{status['verification']}")
                dup = conn.execute(
                    "SELECT 1 FROM resume_notices WHERE resume_id=?"
                    " AND certificate_id=? AND notice=?",
                    (item["resume_id"], certificate_id, notice)).fetchone()
                if not dup:
                    conn.execute(
                        "INSERT INTO resume_notices(resume_id, certificate_id,"
                        " notice, created_at) VALUES(?,?,?,?)",
                        (item["resume_id"], certificate_id, notice, _now_iso(clock)))
                # 冻结快照保持原样, 比较基准始终是冻结时刻的内容


# ---------------------------------------------------------------- 签发机构

def create_issuer(conn, clock: Clock, name: str) -> dict:
    now = _now_iso(clock)
    cur = conn.execute("INSERT INTO issuers(created_at) VALUES(?)", (now,))
    issuer_id = cur.lastrowid
    ev = _append_event(conn, clock, type_="ISSUER_CREATED",
                       payload={"name": name}, issuer_id=issuer_id)
    conn.execute(
        "INSERT INTO issuer_names(issuer_id, name, effective_at, recorded_at, event_id)"
        " VALUES(?,?,?,?,?)", (issuer_id, name, now, now, ev["id"]))
    return {"id": issuer_id, "name": name}


def rename_issuer(conn, clock: Clock, issuer_id: int, new_name: str,
                  effective_at: datetime | None = None) -> dict:
    """机构更名: 保留名称历史, 机构身份与既有证书归属不变。"""
    if not conn.execute("SELECT 1 FROM issuers WHERE id=?", (issuer_id,)).fetchone():
        raise DomainError("not_found", f"签发机构 #{issuer_id} 不存在")
    now = _now_iso(clock)
    ev = _append_event(conn, clock, type_="ISSUER_RENAMED",
                       payload={"new_name": new_name}, issuer_id=issuer_id,
                       occurred_at=effective_at)
    conn.execute(
        "INSERT INTO issuer_names(issuer_id, name, effective_at, recorded_at, event_id)"
        " VALUES(?,?,?,?,?)",
        (issuer_id, new_name,
         iso(to_utc(effective_at)) if effective_at else now, now, ev["id"]))
    return {"id": issuer_id, "name": new_name, "event_id": ev["id"]}


def current_issuer_name(conn, issuer_id: int, now: datetime) -> str:
    row = conn.execute(
        "SELECT name FROM issuer_names WHERE issuer_id=? AND effective_at<=?"
        " ORDER BY effective_at DESC, id DESC LIMIT 1",
        (issuer_id, iso(to_utc(now)))).fetchone()
    if not row:                                      # 所有名称都未生效: 取最早记录
        row = conn.execute(
            "SELECT name FROM issuer_names WHERE issuer_id=?"
            " ORDER BY effective_at, id LIMIT 1", (issuer_id,)).fetchone()
    return row["name"]


def issuer_former_names(conn, issuer_id: int, now: datetime) -> list[str]:
    current = current_issuer_name(conn, issuer_id, now)
    names = [r["name"] for r in conn.execute(
        "SELECT DISTINCT name FROM issuer_names WHERE issuer_id=?", (issuer_id,))]
    return [n for n in names if n != current]


# ---------------------------------------------------------------- 证书生命周期

def _next_public_id(conn) -> str:
    row = conn.execute("SELECT COUNT(*) AS c FROM certificates").fetchone()
    return f"CRT-{row['c'] + 1:04d}"


def record_award(conn, clock: Clock, *, title: str, issuer_id: int,
                 issued_on: str, valid_until: str | None, expiry_tz: str = "UTC",
                 growth_goal: str | None = None, level: str | None = None,
                 verify_url: str | None = None, skills: list[str] | None = None,
                 valid_from: str | None = None,
                 idempotency_key: str | None = None) -> dict:
    """新获奖: 创建证书身份 + 首个修订 + AWARDED 事件。"""
    if idempotency_key:
        ev = conn.execute("SELECT * FROM events WHERE idempotency_key=?",
                          (idempotency_key,)).fetchone()
        if ev:
            return {"id": ev["certificate_id"], "duplicated": True}
    if not conn.execute("SELECT 1 FROM issuers WHERE id=?", (issuer_id,)).fetchone():
        raise DomainError("not_found", f"签发机构 #{issuer_id} 不存在")
    if valid_until:
        expiry_instant(valid_until, expiry_tz)       # 提前校验日期与时区合法性
    now = _now_iso(clock)
    cur = conn.execute(
        "INSERT INTO certificates(public_id, title, issuer_id, level, growth_goal,"
        " issued_on, valid_from, valid_until, expiry_tz, verify_url, rev,"
        " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)",
        (_next_public_id(conn), title, issuer_id, level, growth_goal,
         issued_on, valid_from, valid_until, expiry_tz, verify_url, now, now))
    cid = cur.lastrowid
    ev = _append_event(conn, clock, type_="AWARDED",
                       payload={"title": title, "issued_on": issued_on,
                                "valid_until": valid_until, "expiry_tz": expiry_tz},
                       certificate_id=cid, idempotency_key=idempotency_key)
    payload = {"title": title, "issuer_id": issuer_id, "level": level,
               "growth_goal": growth_goal, "issued_on": issued_on,
               "valid_from": valid_from, "valid_until": valid_until,
               "expiry_tz": expiry_tz, "verify_url": verify_url}
    conn.execute(
        "INSERT INTO certificate_revisions(certificate_id, rev, payload_json,"
        " event_id, created_at) VALUES(?,?,?,?,?)",
        (cid, 1, _dump(payload), ev["id"], now))
    for skill in (skills or []):
        conn.execute(
            "INSERT INTO skill_evidence(skill, certificate_id, state, updated_at)"
            " VALUES(?,?,?,?) ON CONFLICT(skill, certificate_id) DO NOTHING",
            (skill, cid, "current", now))
    _refresh_projection(conn, clock, cid, ev["id"])
    _propagate(conn, clock, cid)
    return {"id": cid, "public_id": _get_cert(conn, cid)["public_id"], "event_id": ev["id"]}


def attach_image(conn, clock: Clock, certificate_id: int, data: bytes,
                 private_dir: str, public_dir: str,
                 idempotency_key: str | None = None) -> dict:
    """上传证书图片: 识别元数据 -> 脱敏派生 -> 公私分离存储。

    同一证书重复上传是 IMAGE_REISSUED(补发)事件, 不会新增成就;
    解析失败记录 IMAGE_FAILED, 保留既有证据不受影响。
    """
    cert = _get_cert(conn, certificate_id)
    now = _now_iso(clock)
    sha = hashlib.sha256(data).hexdigest()
    image_uid = uuid.uuid4().hex[:12]
    original_path = os.path.join(private_dir, f"{sha}.png")
    os.makedirs(private_dir, exist_ok=True)
    with open(original_path, "wb") as fh:            # 私密原件(含全部元数据)
        fh.write(data)

    has_prior_ok = conn.execute(
        "SELECT 1 FROM images WHERE certificate_id=? AND status='ok'",
        (certificate_id,)).fetchone() is not None
    try:
        derived, extracted, applied = pngtool.make_derived(data)
        meta = pngtool.read_png(data)
        width, height = meta["width"], meta["height"]
        error = None
    except pngtool.PngError as exc:
        derived, extracted, applied = None, {}, []
        width = height = None
        error = str(exc)

    if error is not None:
        ev = _append_event(conn, clock, type_="IMAGE_FAILED",
                           payload={"sha256": sha, "error": error},
                           certificate_id=certificate_id,
                           idempotency_key=idempotency_key)
        conn.execute(
            "INSERT INTO images(image_uid, certificate_id, event_id, sha256, width,"
            " height, original_path, derived_path, extracted_json, redactions_json,"
            " status, error, is_current, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?, 'failed', ?, 0, ?)",
            (image_uid, certificate_id, ev["id"], sha, width, height,
             original_path, None, _dump(extracted), _dump(applied), error, now))
        _refresh_projection(conn, clock, certificate_id, ev["id"])
        return {"image_uid": image_uid, "status": "failed", "error": error,
                "event_type": "IMAGE_FAILED"}

    os.makedirs(public_dir, exist_ok=True)
    derived_path = os.path.join(public_dir, f"{image_uid}.png")
    with open(derived_path, "wb") as fh:             # 公开派生图(已脱敏)
        fh.write(derived)

    event_type = "IMAGE_REISSUED" if has_prior_ok else "IMAGE_ATTACHED"
    ev = _append_event(conn, clock, type_=event_type,
                       payload={"sha256": sha, "replaces_prior": has_prior_ok},
                       certificate_id=certificate_id, idempotency_key=idempotency_key)
    conn.execute("UPDATE images SET is_current=0 WHERE certificate_id=?",
                 (certificate_id,))
    conn.execute(
        "INSERT INTO images(image_uid, certificate_id, event_id, sha256, width,"
        " height, original_path, derived_path, extracted_json, redactions_json,"
        " status, error, is_current, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?, 'ok', NULL, 1, ?)",
        (image_uid, certificate_id, ev["id"], sha, width, height,
         original_path, derived_path, _dump(extracted), _dump(applied), now))
    _refresh_projection(conn, clock, certificate_id, ev["id"])
    return {"image_uid": image_uid, "status": "ok", "event_type": event_type,
            "extracted": extracted, "redactions": applied,
            "derived_url": f"/api/public/images/{image_uid}.png",
            "title_unchanged": cert["title"]}


def _bump_revision(conn, clock: Clock, certificate_id: int, event_id: int,
                   **changes) -> int:
    cert = _get_cert(conn, certificate_id)
    new_rev = cert["rev"] + 1
    sets, vals = [], []
    for key, val in changes.items():
        sets.append(f"{key}=?")
        vals.append(val)
    conn.execute(f"UPDATE certificates SET {', '.join(sets)}, rev=?, updated_at=?"
                 " WHERE id=?", (*vals, new_rev, _now_iso(clock), certificate_id))
    cert = _get_cert(conn, certificate_id)
    payload = {k: cert[k] for k in ("title", "issuer_id", "level", "growth_goal",
                                    "issued_on", "valid_from", "valid_until",
                                    "expiry_tz", "verify_url")}
    conn.execute(
        "INSERT INTO certificate_revisions(certificate_id, rev, payload_json,"
        " event_id, created_at) VALUES(?,?,?,?,?)",
        (certificate_id, new_rev, _dump(payload), event_id, _now_iso(clock)))
    return new_rev


def renew(conn, clock: Clock, certificate_id: int, *, new_valid_until: str,
          reason: str | None = None, idempotency_key: str | None = None) -> dict:
    """续期: 同一证书身份延长有效期(新修订 + RENEWED 事件)。"""
    cert = _get_cert(conn, certificate_id)
    expiry_instant(new_valid_until, cert["expiry_tz"])
    ev = _append_event(conn, clock, type_="RENEWED",
                       payload={"old_valid_until": cert["valid_until"],
                                "new_valid_until": new_valid_until, "reason": reason},
                       certificate_id=certificate_id, idempotency_key=idempotency_key)
    if conn.execute("SELECT 1 FROM certificate_revisions WHERE event_id=?",
                    (ev["id"],)).fetchone():
        return {"id": certificate_id, "duplicated": True, "event_id": ev["id"]}
    rev = _bump_revision(conn, clock, certificate_id, ev["id"],
                         valid_until=new_valid_until)
    _refresh_projection(conn, clock, certificate_id, ev["id"])
    _propagate(conn, clock, certificate_id)
    return {"id": certificate_id, "rev": rev, "event_id": ev["id"],
            "valid_until": new_valid_until}


def revoke(conn, clock: Clock, certificate_id: int, *,
           effective_at: datetime | None = None, reason: str | None = None,
           idempotency_key: str | None = None) -> dict:
    """撤销: 支持追溯生效(effective_at 在过去 => 立即视为已撤销)。"""
    _get_cert(conn, certificate_id)
    ev = _append_event(conn, clock, type_="REVOKED",
                       payload={"reason": reason,
                                "effective_at": iso(to_utc(effective_at)) if effective_at else None},
                       certificate_id=certificate_id, occurred_at=effective_at,
                       idempotency_key=idempotency_key)
    _refresh_projection(conn, clock, certificate_id, ev["id"])
    _propagate(conn, clock, certificate_id)
    return {"id": certificate_id, "event_id": ev["id"],
            "effective_at": ev["occurred_at"]}


def check_link(conn, clock: Clock, certificate_id: int, fetcher) -> dict:
    """核对验证链接。可访问 => source_checked(仅说明来源仍在)。"""
    cert = _get_cert(conn, certificate_id)
    if not cert["verify_url"]:
        raise DomainError("no_verify_url", "该证书未登记验证链接")
    try:
        ok, detail = fetcher(cert["verify_url"])
        outcome = "reachable" if ok else "unreachable"
    except Exception as exc:                          # 网络异常不等于证书无效
        outcome, detail = "error", f"{type(exc).__name__}: {exc}"
    now = _now_iso(clock)
    conn.execute(
        "INSERT INTO link_checks(certificate_id, url, outcome, detail, checked_at)"
        " VALUES(?,?,?,?,?)", (certificate_id, cert["verify_url"], outcome, detail, now))
    ev = _append_event(conn, clock, type_="LINK_CHECKED",
                       payload={"url": cert["verify_url"], "outcome": outcome,
                                "detail": detail},
                       certificate_id=certificate_id)
    _refresh_projection(conn, clock, certificate_id, ev["id"])
    _propagate(conn, clock, certificate_id)
    return {"id": certificate_id, "outcome": outcome, "detail": detail,
            "note": VERIFICATION_NOTE}


def correct_clock(conn, clock: Clock, new_offset_ms: int, source: str = "manual") -> dict:
    """服务器时钟校正: 调整偏移并留痕(后续事件使用新偏移)。"""
    old = clock.offset_ms
    clock.set_offset_ms(new_offset_ms)
    set_meta(conn, "clock_offset_ms", str(new_offset_ms))
    _append_event(conn, clock, type_="CLOCK_CORRECTED",
                  payload={"old_offset_ms": old, "new_offset_ms": new_offset_ms,
                           "source": source})
    return {"old_offset_ms": old, "new_offset_ms": new_offset_ms}


def load_clock(conn) -> Clock:
    """用持久化的偏移量恢复时钟。"""
    return Clock(int(get_meta(conn, "clock_offset_ms", "0") or 0))


# ---------------------------------------------------------------- 简历

def create_resume(conn, clock: Clock, title: str) -> dict:
    cur = conn.execute("INSERT INTO resumes(title, created_at) VALUES(?,?)",
                       (title, _now_iso(clock)))
    return {"id": cur.lastrowid, "title": title}


def add_resume_item(conn, clock: Clock, resume_id: int, certificate_id: int) -> dict:
    resume = conn.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
    if not resume:
        raise DomainError("not_found", f"简历 #{resume_id} 不存在")
    if resume["frozen_at"]:
        raise DomainError("frozen", "简历已冻结, 不能新增条目")
    cert = _get_cert(conn, certificate_id)
    status = compute_status(conn, certificate_id, clock.now())
    snap = {
        "public_id": cert["public_id"], "title": cert["title"],
        "issuer_name": current_issuer_name(conn, cert["issuer_id"], clock.now()),
        "validity": status["validity"], "verification": status["verification"],
        "valid_until": status["valid_until"], "captured_at": _now_iso(clock),
    }
    conn.execute(
        "INSERT INTO resume_items(resume_id, certificate_id, snapshot_json)"
        " VALUES(?,?,?) ON CONFLICT(resume_id, certificate_id)"
        " DO UPDATE SET snapshot_json=excluded.snapshot_json",
        (resume_id, certificate_id, _dump(snap)))
    return {"resume_id": resume_id, "certificate_id": certificate_id}


def freeze_resume(conn, clock: Clock, resume_id: int) -> dict:
    conn.execute("UPDATE resumes SET frozen_at=? WHERE id=? AND frozen_at IS NULL",
                 (_now_iso(clock), resume_id))
    return {"id": resume_id, "frozen_at": _now_iso(clock)}


# ---------------------------------------------------------------- 公共访客墙

_VALIDITY_ORDER = {"valid": 0, "expiring_soon": 1, "expired": 2, "revoked": 3}


def public_wall(conn, clock: Clock) -> dict:
    """访客墙数据: 文字 + 脱敏派生图; 明确标注状态, 不含任何评分。"""
    now = clock.now()
    items = []
    for cert in conn.execute("SELECT * FROM certificates ORDER BY id"):
        status = compute_status(conn, cert["id"], now)
        img = conn.execute(
            "SELECT * FROM images WHERE certificate_id=? AND is_current=1"
            " AND status='ok'", (cert["id"],)).fetchone()
        items.append({
            "public_id": cert["public_id"],
            "title": cert["title"],
            "issuer": {
                "name": current_issuer_name(conn, cert["issuer_id"], now),
                "former_names": issuer_former_names(conn, cert["issuer_id"], now),
            },
            "level": cert["level"],
            "growth_goal": cert["growth_goal"],
            "issued_on": cert["issued_on"],
            "valid_until": cert["valid_until"],
            "expiry_tz": cert["expiry_tz"],
            "validity": status["validity"],
            "verification": status["verification"],
            "verify_url": cert["verify_url"],
            "verification_note": VERIFICATION_NOTE,
            "image": ({"url": f"/api/public/images/{img['image_uid']}.png",
                       "width": img["width"], "height": img["height"],
                       "redacted": True} if img else None),
        })
    groups: dict[str, list] = {k: [] for k in VALIDITY}
    for it in items:
        groups[it["validity"]].append(it)
    for grp in groups.values():
        grp.sort(key=lambda it: (it["issued_on"], it["public_id"]), reverse=True)
    return {
        "generated_at": iso(now),
        "sort_note": SORT_NOTE,
        "verification_note": VERIFICATION_NOTE,
        "groups": {k: v for k, v in groups.items() if v},
        "total": len(items),
    }
