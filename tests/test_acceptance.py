"""验收测试: 证书奖项证据管理。

覆盖需求点:
  1.  补发图片/续期/新获奖是不同事件, 上传图片不新增成就
  2.  图片处理失败不破坏既有证据
  3.  个人编号识别 + 公开派生图/私密原件分离
  4.  签发机构更名(身份不变, 历史可查)
  5.  链接可访问=来源仍在, 不声称权威认证; 链接失效状态
  6.  午夜到期的时区处理
  7.  追溯撤销
  8.  服务器时钟校正
  9.  续期与撤回并发 + 幂等重试
 10.  实时计算 vs 事件驱动投影的对账
 11.  状态传播到技能证据/简历候选, 冻结简历不被覆盖
 12.  访客墙不含捏造的含金量评分
"""
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

from certs import service
from certs.api import App, make_handler
from certs.clock import Clock
from certs.db import connect, init_db
from certs.pngtool import make_png, read_png
from http.server import ThreadingHTTPServer

UTC = timezone.utc


class ManualClock(Clock):
    """测试用可推进时钟(偏移量同样生效)。"""

    def __init__(self, now):
        super().__init__(0)
        self._now = now

    def now(self):
        return self._now + timedelta(milliseconds=self.offset_ms)

    def set(self, dt):
        self._now = dt


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="certs-test-")
        self.db = os.path.join(self.tmp, "t.db")
        self.priv = os.path.join(self.tmp, "private")
        self.pub = os.path.join(self.tmp, "public")
        init_db(self.db)
        self.conn = connect(self.db)
        self.clock = ManualClock(datetime(2026, 10, 6, 0, 0, 0, tzinfo=UTC))
        self.issuer = service.create_issuer(self.conn, self.clock, "示例认证中心")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def award(self, **kw):
        args = dict(title="Python 高级工程师", issuer_id=self.issuer["id"],
                    issued_on="2025-10-01", valid_until="2027-10-06",
                    expiry_tz="Asia/Shanghai", growth_goal="进阶分布式系统",
                    verify_url="https://verify.example.com/cert/ABC-12345",
                    skills=["Python", "后端开发"])
        args.update(kw)
        return service.record_award(self.conn, self.clock, **args)

    def png_with_pii(self):
        return make_png(60, 30, (180, 190, 200), texts={
            "ocr_text": "姓名：张三 证书编号: ABC-12345 身份证号 110101199001011234",
            "pii_boxes": json.dumps([{"x": 1, "y": 1, "w": 20, "h": 8}]),
        })

    # ---------------------------------------------------------- 1. 事件语义
    def test_reissue_renew_award_are_distinct_events(self):
        cert = self.award()
        r1 = service.attach_image(self.conn, self.clock, cert["id"],
                                  self.png_with_pii(), self.priv, self.pub)
        self.assertEqual(r1["event_type"], "IMAGE_ATTACHED")
        r2 = service.attach_image(self.conn, self.clock, cert["id"],
                                  self.png_with_pii(), self.priv, self.pub)
        self.assertEqual(r2["event_type"], "IMAGE_REISSUED")   # 补发
        service.renew(self.conn, self.clock, cert["id"], new_valid_until="2027-10-06")

        n_certs = self.conn.execute("SELECT COUNT(*) c FROM certificates").fetchone()["c"]
        self.assertEqual(n_certs, 1, "补发图片/续期不得新增成就")
        types = [r["type"] for r in self.conn.execute(
            "SELECT type FROM events WHERE certificate_id=? ORDER BY id", (cert["id"],))]
        self.assertEqual(types, ["AWARDED", "IMAGE_ATTACHED", "IMAGE_REISSUED", "RENEWED"])
        revs = self.conn.execute(
            "SELECT COUNT(*) c FROM certificate_revisions WHERE certificate_id=?",
            (cert["id"],)).fetchone()["c"]
        self.assertEqual(revs, 2, "获奖与续期各产生一个修订; 图片不产生修订")

        other = self.award(title="数据结构认证")            # 新获奖 => 新身份
        self.assertNotEqual(other["id"], cert["id"])
        n_certs = self.conn.execute("SELECT COUNT(*) c FROM certificates").fetchone()["c"]
        self.assertEqual(n_certs, 2)

    # ---------------------------------------------------------- 2. 图片失败
    def test_image_failure_keeps_existing_evidence(self):
        cert = self.award()
        ok = service.attach_image(self.conn, self.clock, cert["id"],
                                  self.png_with_pii(), self.priv, self.pub)
        bad = service.attach_image(self.conn, self.clock, cert["id"],
                                   b"not-a-png-at-all", self.priv, self.pub)
        self.assertEqual(bad["status"], "failed")
        self.assertEqual(bad["event_type"], "IMAGE_FAILED")
        cur = self.conn.execute(
            "SELECT image_uid FROM images WHERE certificate_id=? AND is_current=1",
            (cert["id"],)).fetchone()
        self.assertEqual(cur["image_uid"], ok["image_uid"], "失败不得替换既有派生图")
        wall = service.public_wall(self.conn, self.clock)
        self.assertEqual(wall["total"], 1)
        self.assertIsNotNone(wall["groups"]["valid"][0]["image"])

    # ---------------------------------------------------------- 3. PII 与公私分离
    def test_pii_extracted_and_derived_separated(self):
        cert = self.award()
        r = service.attach_image(self.conn, self.clock, cert["id"],
                                 self.png_with_pii(), self.priv, self.pub)
        self.assertEqual(r["extracted"]["personal_ids"], ["110101199001011234"])
        self.assertEqual(r["extracted"]["certificate_no"], "ABC-12345")
        img = self.conn.execute("SELECT * FROM images WHERE image_uid=?",
                                (r["image_uid"],)).fetchone()
        self.assertTrue(img["original_path"].startswith(self.priv))
        self.assertTrue(img["derived_path"].startswith(self.pub))
        with open(img["original_path"], "rb") as fh:          # 原件保留全部信息
            self.assertIn("110101199001011234".encode("latin-1"), fh.read())
        with open(img["derived_path"], "rb") as fh:           # 派生图无 PII 字节
            derived = fh.read()
        self.assertNotIn(b"110101199001011234", derived)
        self.assertNotIn("张三".encode("utf-8"), derived)
        self.assertEqual(read_png(derived)["texts"], {}, "派生图不得携带元数据")

    # ---------------------------------------------------------- 4. 机构更名
    def test_issuer_rename_keeps_identity(self):
        cert = self.award()
        service.rename_issuer(self.conn, self.clock, self.issuer["id"], "示例国际认证集团")
        wall = service.public_wall(self.conn, self.clock)
        issuer = wall["groups"]["valid"][0]["issuer"]
        self.assertEqual(issuer["name"], "示例国际认证集团")
        self.assertEqual(issuer["former_names"], ["示例认证中心"])
        row = self.conn.execute("SELECT issuer_id FROM certificates WHERE id=?",
                                (cert["id"],)).fetchone()
        self.assertEqual(row["issuer_id"], self.issuer["id"], "更名不改变机构身份")

    # ---------------------------------------------------------- 5. 链接核对语义
    def test_link_check_semantics(self):
        cert = self.award()
        st = service.compute_status(self.conn, cert["id"], self.clock.now())
        self.assertEqual(st["verification"], "self_reported")   # 初始自报

        r = service.check_link(self.conn, self.clock, cert["id"],
                               lambda url: (True, "HTTP 200"))
        self.assertEqual(r["outcome"], "reachable")
        st = service.compute_status(self.conn, cert["id"], self.clock.now())
        self.assertEqual(st["verification"], "source_checked")  # 已核对来源
        self.assertIn("不构成权威机构", r["note"], "不得声称权威认证")

        service.check_link(self.conn, self.clock, cert["id"],
                           lambda url: (False, "HTTP 404"))
        st = service.compute_status(self.conn, cert["id"], self.clock.now())
        self.assertEqual(st["verification"], "link_failed")     # 链接失效
        sk = self.conn.execute("SELECT state FROM skill_evidence WHERE certificate_id=?",
                               (cert["id"],)).fetchone()
        self.assertEqual(sk["state"], "unverified", "链接失效应传播到技能证据")

    # ---------------------------------------------------------- 6. 午夜到期与时区
    def test_midnight_expiry_across_timezone(self):
        cert = self.award(valid_until="2026-10-06", expiry_tz="Asia/Shanghai")
        # 上海 10-07 00:00 == UTC 10-06 16:00
        before = datetime(2026, 10, 6, 15, 59, 59, tzinfo=UTC)
        after = datetime(2026, 10, 6, 16, 0, 0, tzinfo=UTC)
        st = service.compute_status(self.conn, cert["id"], before)
        self.assertEqual(st["validity"], "expiring_soon")
        st = service.compute_status(self.conn, cert["id"], after)
        self.assertEqual(st["validity"], "expired", "上海午夜即到期, 不早不晚")

    # ---------------------------------------------------------- 7. 追溯撤销
    def test_retroactive_revocation(self):
        cert = self.award()
        past = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)      # 生效时间在过去
        service.revoke(self.conn, self.clock, cert["id"],
                       effective_at=past, reason="签发机构追溯撤销")
        st = service.compute_status(self.conn, cert["id"], self.clock.now())
        self.assertEqual(st["validity"], "revoked")
        self.assertEqual(st["revoked_at"], "2026-09-01T00:00:00Z")
        earlier = service.compute_status(self.conn, cert["id"],
                                         datetime(2026, 8, 1, tzinfo=UTC))
        self.assertEqual(earlier["validity"], "valid", "生效之前的历史时点仍应有效")

    # ---------------------------------------------------------- 8. 时钟校正
    def test_clock_correction(self):
        cert = self.award(valid_until="2026-10-06", expiry_tz="UTC")
        self.assertEqual(service.compute_status(
            self.conn, cert["id"], self.clock.now())["validity"], "expiring_soon")
        # 服务器时钟慢 2 天, 校正后真实时间已过期
        service.correct_clock(self.conn, self.clock, 2 * 86400 * 1000, source="ntp")
        st = service.compute_status(self.conn, cert["id"], self.clock.now())
        self.assertEqual(st["validity"], "expired")
        ev = self.conn.execute(
            "SELECT * FROM events WHERE type='CLOCK_CORRECTED'").fetchone()
        self.assertIsNotNone(ev, "时钟校正必须留痕")
        self.assertEqual(json.loads(ev["payload_json"])["new_offset_ms"], 172800000)
        restored = service.load_clock(self.conn)
        self.assertEqual(restored.offset_ms, 172800000, "偏移量需持久化")

    # ---------------------------------------------------------- 9. 续期/撤销并发
    def test_renew_revoke_concurrency_and_idempotency(self):
        cert = self.award()
        errors = []

        def do_renew(i):
            try:
                conn = connect(self.db)
                conn.execute("BEGIN IMMEDIATE")
                service.renew(conn, self.clock, cert["id"],
                              new_valid_until="2028-10-06",
                              idempotency_key=f"renew-{i}")
                conn.execute("COMMIT")
                conn.close()
            except Exception as exc:                            # noqa: BLE001
                errors.append(exc)

        def do_revoke():
            try:
                conn = connect(self.db)
                conn.execute("BEGIN IMMEDIATE")
                service.revoke(conn, self.clock, cert["id"], reason="并发撤销")
                conn.execute("COMMIT")
                conn.close()
            except Exception as exc:                            # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=do_renew, args=(i,)) for i in range(5)]
        threads += [threading.Thread(target=do_revoke) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

        revokes = self.conn.execute(
            "SELECT COUNT(*) c FROM events WHERE certificate_id=? AND type='REVOKED'",
            (cert["id"],)).fetchone()["c"]
        self.assertEqual(revokes, 3)
        renews = self.conn.execute(
            "SELECT COUNT(*) c FROM events WHERE certificate_id=? AND type='RENEWED'",
            (cert["id"],)).fetchone()["c"]
        self.assertEqual(renews, 5, "不同幂等键的续期都应记录")
        st = service.compute_status(self.conn, cert["id"], self.clock.now())
        self.assertEqual(st["validity"], "revoked", "撤销优先: 并发结果必须确定")
        proj = self.conn.execute("SELECT validity FROM cert_projection WHERE certificate_id=?",
                                 (cert["id"],)).fetchone()
        self.assertEqual(proj["validity"], "revoked", "投影与实时计算一致")

        # 幂等重试: 相同键重复续期不产生新事件
        service.renew(self.conn, self.clock, cert["id"],
                      new_valid_until="2028-10-06", idempotency_key="renew-0")
        renews2 = self.conn.execute(
            "SELECT COUNT(*) c FROM events WHERE certificate_id=? AND type='RENEWED'",
            (cert["id"],)).fetchone()["c"]
        self.assertEqual(renews2, 5, "幂等重试不得重复记录")

    # ---------------------------------------------------------- 10. 实时 vs 事件驱动
    def test_projection_drift_and_reconcile(self):
        cert = self.award(valid_until="2026-10-06", expiry_tz="UTC")
        proj = self.conn.execute("SELECT validity FROM cert_projection").fetchone()
        self.assertEqual(proj["validity"], "expiring_soon")
        self.clock.set(datetime(2026, 10, 7, 0, 0, 1, tzinfo=UTC))   # 跨过午夜
        drift = service.reconcile(self.conn, self.clock)
        self.assertEqual(len(drift), 1, "时间流逝后投影必然漂移(无事件触发)")
        self.assertEqual(drift[0]["computed"]["validity"], "expired")
        wall = service.public_wall(self.conn, self.clock)
        self.assertNotIn("valid", wall["groups"], "公开读取以实时计算为准")
        changed = service.sweep(self.conn, self.clock)
        self.assertEqual(changed, [cert["id"]])
        self.assertEqual(service.reconcile(self.conn, self.clock), [], "sweep 后无漂移")

    # ---------------------------------------------------------- 11. 传播与冻结
    def test_propagation_and_frozen_resume(self):
        cert = self.award()
        draft = service.create_resume(self.conn, self.clock, "候选简历")
        frozen = service.create_resume(self.conn, self.clock, "历史简历")
        service.add_resume_item(self.conn, self.clock, draft["id"], cert["id"])
        service.add_resume_item(self.conn, self.clock, frozen["id"], cert["id"])
        service.freeze_resume(self.conn, self.clock, frozen["id"])
        before = self.conn.execute(
            "SELECT snapshot_json FROM resume_items WHERE resume_id=?",
            (frozen["id"],)).fetchone()["snapshot_json"]

        service.revoke(self.conn, self.clock, cert["id"], reason="撤销")

        after = self.conn.execute(
            "SELECT snapshot_json FROM resume_items WHERE resume_id=?",
            (frozen["id"],)).fetchone()["snapshot_json"]
        self.assertEqual(before, after, "冻结简历内容绝不被覆盖")
        notices = self.conn.execute(
            "SELECT notice FROM resume_notices WHERE resume_id=?",
            (frozen["id"],)).fetchall()
        self.assertEqual(len(notices), 1, "冻结后变化以附注呈现")
        self.assertIn("revoked", notices[0]["notice"])
        self.assertIn("冻结后发生变化", notices[0]["notice"])

        draft_snap = json.loads(self.conn.execute(
            "SELECT snapshot_json FROM resume_items WHERE resume_id=?",
            (draft["id"],)).fetchone()["snapshot_json"])
        self.assertEqual(draft_snap["validity"], "revoked", "候选简历跟随最新状态")
        sk = self.conn.execute("SELECT state FROM skill_evidence WHERE certificate_id=?",
                               (cert["id"],)).fetchone()
        self.assertEqual(sk["state"], "revoked", "技能证据同步失效")

    # ---------------------------------------------------------- 12. 不捏造评分
    def test_wall_has_no_fabricated_scores(self):
        self.award()
        wall = service.public_wall(self.conn, self.clock)
        blob = json.dumps(wall, ensure_ascii=False).lower()
        for forbidden in ("score", "rank", "含金量", "weight", "level_value"):
            self.assertNotIn(f'"{forbidden}"', blob, f"访客墙不得出现 {forbidden}")
        self.assertIn("sort_note", wall)
        self.assertIn("verification_note", wall)


class ApiCase(unittest.TestCase):
    """HTTP 层: 鉴权、隐私隔离、并发提交。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="certs-api-")
        cls.app = App(db_path=os.path.join(cls.tmp, "api.db"),
                      fetcher=lambda url: (True, "HTTP 200"),
                      static_root="/workspace")
        import certs.api as api_mod
        cls._priv, cls._pub = api_mod.PRIVATE_DIR, api_mod.PUBLIC_DIR
        api_mod.PRIVATE_DIR = os.path.join(cls.tmp, "private")
        api_mod.PUBLIC_DIR = os.path.join(cls.tmp, "public")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        import certs.api as api_mod
        api_mod.PRIVATE_DIR, api_mod.PUBLIC_DIR = cls._priv, cls._pub
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _req(self, method, path, body=None, token="dev-admin-token", headers=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, {"raw": raw}

    def test_admin_requires_token(self):
        code, _ = self._req("POST", "/api/admin/issuers", {"name": "X"}, token=None)
        self.assertEqual(code, 401)
        code, _ = self._req("POST", "/api/admin/issuers", {"name": "X"}, token="wrong")
        self.assertEqual(code, 401)

    def test_full_flow_over_http(self):
        code, issuer = self._req("POST", "/api/admin/issuers", {"name": "HTTP 认证中心"})
        self.assertEqual(code, 201)
        code, cert = self._req("POST", "/api/admin/certificates", {
            "title": "云计算架构师", "issuer_id": issuer["id"],
            "issued_on": "2026-01-01", "valid_until": "2027-01-01",
            "expiry_tz": "Asia/Shanghai", "growth_goal": "云原生进阶",
            "verify_url": "https://verify.example.com/x"})
        self.assertEqual(code, 201)
        png = make_png(30, 20, (1, 2, 3), texts={"ocr_text": "证书编号: CLD-999"})
        code, img = self._req("POST", f"/api/admin/certificates/{cert['id']}/images", png)
        self.assertEqual(code, 201)
        self.assertEqual(img["extracted"]["certificate_no"], "CLD-999")

        code, wall = self._req("GET", "/api/public/certificates", token=None)
        self.assertEqual(code, 200)
        item = wall["groups"]["valid"][0]
        self.assertEqual(item["verification"], "self_reported")
        self.assertIsNotNone(item["image"])

        # 派生图可公开访问; 私密原件目录不可访问
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{item['image']['url']}", timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            self.assertTrue(resp.read().startswith(b"\x89PNG"))
        code, _ = self._req("GET", "/data/private/originals/x.png", token=None)
        self.assertEqual(code, 404, "私密原件目录不得对外服务")

        code, chk = self._req("POST", f"/api/admin/certificates/{cert['id']}/link-check")
        self.assertEqual(chk["outcome"], "reachable")
        code, wall = self._req("GET", "/api/public/certificates", token=None)
        self.assertEqual(wall["groups"]["valid"][0]["verification"], "source_checked")

    def test_concurrent_renew_revoke_http(self):
        code, issuer = self._req("POST", "/api/admin/issuers", {"name": "并发测试机构"})
        code, cert = self._req("POST", "/api/admin/certificates", {
            "title": "并发测试证书", "issuer_id": issuer["id"],
            "issued_on": "2026-01-01", "valid_until": "2026-12-31"})
        results = []

        def call(path, body, key):
            results.append(self._req("POST", path, body,
                                     headers={"Idempotency-Key": key}))

        threads = []
        for i in range(4):
            threads.append(threading.Thread(
                target=call,
                args=(f"/api/admin/certificates/{cert['id']}/renew",
                      {"new_valid_until": "2028-01-01"}, f"http-renew-{i}")))
        for i in range(2):
            threads.append(threading.Thread(
                target=call,
                args=(f"/api/admin/certificates/{cert['id']}/revoke",
                      {"reason": "并发撤销"}, f"http-revoke-{i}")))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(all(r[0] == 200 for r in results), f"并发请求出错: {results}")

        code, wall = self._req("GET", "/api/public/certificates", token=None)
        revoked = wall["groups"].get("revoked", [])
        self.assertEqual(len(revoked), 1, "并发后状态确定: 已撤销")

        code, ev = self._req("GET", f"/api/admin/certificates/{cert['id']}/events")
        types = [e["type"] for e in ev["events"]]
        self.assertEqual(types.count("RENEWED"), 4)
        self.assertEqual(types.count("REVOKED"), 2)

        # 幂等重放: 重复键不再产生事件
        self._req("POST", f"/api/admin/certificates/{cert['id']}/renew",
                  {"new_valid_until": "2028-01-01"},
                  headers={"Idempotency-Key": "http-renew-0"})
        code, ev = self._req("GET", f"/api/admin/certificates/{cert['id']}/events")
        types = [e["type"] for e in ev["events"]]
        self.assertEqual(types.count("RENEWED"), 4, "幂等重放不得新增事件")


if __name__ == "__main__":
    unittest.main(verbosity=2)
