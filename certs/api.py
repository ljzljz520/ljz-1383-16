"""HTTP 接口层(仅标准库)。

路由分三类:
  /api/admin/*   站主管理接口(需 Bearer 令牌, 令牌取环境变量 ADMIN_TOKEN)
  /api/public/*  访客只读接口(脱敏数据 + 派生图)
  其余路径       静态站点文件(个人主页)

事务与并发: 每个请求独立连接, 写操作使用 BEGIN IMMEDIATE 串行化;
续期/撤销等携带 Idempotency-Key 的重复提交返回首次结果。
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import service
from .clock import parse_instant
from .db import connect, init_db

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-token")
DEFAULT_DB = os.environ.get("CERTS_DB", "data/certificates.db")
PRIVATE_DIR = os.environ.get("CERTS_PRIVATE_DIR", "data/private/originals")
PUBLIC_DIR = os.environ.get("CERTS_PUBLIC_DIR", "data/public/derived")
STATIC_ROOT = os.path.dirname(os.path.abspath(__file__)) + "/.."


def default_fetcher(url: str, timeout: float = 5.0):
    """默认链接核对器: HEAD 失败回退 GET; 2xx/3xx 视为可访问。"""
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "cert-evidence/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 400, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code in (405, 501):
            req = urllib.request.Request(url, method="GET",
                                         headers={"User-Agent": "cert-evidence/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status < 400, f"HTTP {resp.status}"
        return False, f"HTTP {exc.code}"


class App:
    """应用状态: 数据库路径、时钟、链接核对器(可注入便于测试)。"""

    def __init__(self, db_path: str = DEFAULT_DB, fetcher=None,
                 static_root: str = STATIC_ROOT):
        self.db_path = db_path
        self.fetcher = fetcher or default_fetcher
        self.static_root = os.path.abspath(static_root)
        init_db(db_path)
        conn = connect(db_path)
        try:
            self.clock = service.load_clock(conn)   # 恢复持久化的时钟偏移
        finally:
            conn.close()

    def conn(self):
        return connect(self.db_path)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CertEvidence/1.0"
        protocol_version = "HTTP/1.1"

        # ---------------------------------------------------------- 工具
        def _send(self, code: int, body: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _error(self, code: int, err: str, message: str):
            self._json(code, {"error": err, "message": message})

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length else b""

        def _json_body(self) -> dict:
            raw = self._body()
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise service.DomainError("bad_json", "请求体不是合法 JSON")

        def _authorized(self) -> bool:
            auth = self.headers.get("Authorization", "")
            if auth == f"Bearer {ADMIN_TOKEN}":
                return True
            self._error(401, "unauthorized", "管理接口需要有效令牌")
            return False

        def _idem(self) -> str | None:
            return self.headers.get("Idempotency-Key")

        def log_message(self, fmt, *args):            # 静默访问日志
            pass

        # ---------------------------------------------------------- 路由
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/public/certificates":
                return self._public_wall()
            m = re.fullmatch(r"/api/public/images/([0-9a-f]{12})\.png", path)
            if m:
                return self._public_image(m.group(1))
            if path == "/api/admin/reconcile":
                if not self._authorized():
                    return
                return self._admin_reconcile()
            m = re.fullmatch(r"/api/admin/certificates/(\d+)/events", path)
            if m:
                if not self._authorized():
                    return
                return self._admin_events(int(m.group(1)))
            if path == "/api/admin/skills":
                if not self._authorized():
                    return
                return self._admin_skills()
            m = re.fullmatch(r"/api/admin/resumes/(\d+)", path)
            if m:
                if not self._authorized():
                    return
                return self._admin_resume(int(m.group(1)))
            return self._static(path)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if not path.startswith("/api/admin/"):
                return self._error(404, "not_found", "接口不存在")
            if not self._authorized():
                return
            try:
                return self._admin_post(path)
            except service.DomainError as exc:
                code = 404 if exc.code == "not_found" else 400
                return self._error(code, exc.code, exc.message)
            except ValueError as exc:
                return self._error(400, "bad_input", str(exc))

        # ---------------------------------------------------------- 公共接口
        def _public_wall(self):
            conn = app.conn()
            try:
                self._json(200, service.public_wall(conn, app.clock))
            finally:
                conn.close()

        def _public_image(self, image_uid: str):
            """仅服务脱敏派生图; 私密原件无任何对外路由。"""
            conn = app.conn()
            try:
                row = conn.execute(
                    "SELECT derived_path FROM images WHERE image_uid=? AND status='ok'",
                    (image_uid,)).fetchone()
            finally:
                conn.close()
            if not row or not row["derived_path"] or not os.path.exists(row["derived_path"]):
                return self._error(404, "not_found", "图片不存在")
            with open(row["derived_path"], "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        # ---------------------------------------------------------- 管理接口
        def _admin_post(self, path: str):
            conn = app.conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                result, code = self._dispatch_admin(conn, path)
                conn.execute("COMMIT")
                self._json(code, result)
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

        def _dispatch_admin(self, conn, path: str):
            if path == "/api/admin/issuers":
                body = self._json_body()
                if not body.get("name"):
                    raise service.DomainError("bad_input", "缺少机构名称 name")
                return service.create_issuer(conn, app.clock, body["name"].strip()), 201

            m = re.fullmatch(r"/api/admin/issuers/(\d+)/rename", path)
            if m:
                body = self._json_body()
                if not body.get("name"):
                    raise service.DomainError("bad_input", "缺少新名称 name")
                eff = parse_instant(body["effective_at"]) if body.get("effective_at") else None
                return service.rename_issuer(conn, app.clock, int(m.group(1)),
                                             body["name"].strip(), eff), 200

            if path == "/api/admin/certificates":
                body = self._json_body()
                for field in ("title", "issuer_id", "issued_on"):
                    if body.get(field) in (None, ""):
                        raise service.DomainError("bad_input", f"缺少字段 {field}")
                return service.record_award(
                    conn, app.clock, title=body["title"],
                    issuer_id=int(body["issuer_id"]), issued_on=body["issued_on"],
                    valid_until=body.get("valid_until"),
                    expiry_tz=body.get("expiry_tz", "UTC"),
                    growth_goal=body.get("growth_goal"), level=body.get("level"),
                    verify_url=body.get("verify_url"), skills=body.get("skills"),
                    valid_from=body.get("valid_from"),
                    idempotency_key=self._idem()), 201

            m = re.fullmatch(r"/api/admin/certificates/(\d+)/images", path)
            if m:
                data = self._body()
                if not data:
                    raise service.DomainError("bad_input", "请求体为空, 需要图片字节")
                result = service.attach_image(conn, app.clock, int(m.group(1)), data,
                                              PRIVATE_DIR, PUBLIC_DIR, self._idem())
                return result, (201 if result["status"] == "ok" else 422)

            m = re.fullmatch(r"/api/admin/certificates/(\d+)/renew", path)
            if m:
                body = self._json_body()
                if not body.get("new_valid_until"):
                    raise service.DomainError("bad_input", "缺少 new_valid_until")
                return service.renew(conn, app.clock, int(m.group(1)),
                                     new_valid_until=body["new_valid_until"],
                                     reason=body.get("reason"),
                                     idempotency_key=self._idem()), 200

            m = re.fullmatch(r"/api/admin/certificates/(\d+)/revoke", path)
            if m:
                body = self._json_body()
                eff = parse_instant(body["effective_at"]) if body.get("effective_at") else None
                return service.revoke(conn, app.clock, int(m.group(1)),
                                      effective_at=eff, reason=body.get("reason"),
                                      idempotency_key=self._idem()), 200

            m = re.fullmatch(r"/api/admin/certificates/(\d+)/link-check", path)
            if m:
                return service.check_link(conn, app.clock, int(m.group(1)),
                                          app.fetcher), 200

            if path == "/api/admin/sweep":
                changed = service.sweep(conn, app.clock)
                return {"changed": changed}, 200

            if path == "/api/admin/clock":
                body = self._json_body()
                if "offset_ms" not in body:
                    raise service.DomainError("bad_input", "缺少 offset_ms")
                return service.correct_clock(conn, app.clock,
                                             int(body["offset_ms"]),
                                             body.get("source", "manual")), 200

            if path == "/api/admin/resumes":
                body = self._json_body()
                if not body.get("title"):
                    raise service.DomainError("bad_input", "缺少简历标题 title")
                return service.create_resume(conn, app.clock, body["title"]), 201

            m = re.fullmatch(r"/api/admin/resumes/(\d+)/items", path)
            if m:
                body = self._json_body()
                return service.add_resume_item(conn, app.clock, int(m.group(1)),
                                               int(body["certificate_id"])), 201

            m = re.fullmatch(r"/api/admin/resumes/(\d+)/freeze", path)
            if m:
                return service.freeze_resume(conn, app.clock, int(m.group(1))), 200

            raise service.DomainError("not_found", "接口不存在")

        def _admin_reconcile(self):
            conn = app.conn()
            try:
                drift = service.reconcile(conn, app.clock)
                self._json(200, {"drift": drift, "count": len(drift),
                                 "note": "公开读取以实时计算为准; 投影漂移由 sweep 补齐"})
            finally:
                conn.close()

        def _admin_events(self, cid: int):
            conn = app.conn()
            try:
                rows = conn.execute(
                    "SELECT id, type, payload_json, occurred_at, recorded_at,"
                    " clock_offset_ms FROM events WHERE certificate_id=? ORDER BY id",
                    (cid,)).fetchall()
                self._json(200, {"events": [dict(r) for r in rows]})
            finally:
                conn.close()

        def _admin_skills(self):
            conn = app.conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM skill_evidence ORDER BY skill, id").fetchall()
                self._json(200, {"skills": [dict(r) for r in rows]})
            finally:
                conn.close()

        def _admin_resume(self, rid: int):
            conn = app.conn()
            try:
                resume = conn.execute("SELECT * FROM resumes WHERE id=?",
                                      (rid,)).fetchone()
                if not resume:
                    return self._error(404, "not_found", "简历不存在")
                items = conn.execute(
                    "SELECT * FROM resume_items WHERE resume_id=?", (rid,)).fetchall()
                notices = conn.execute(
                    "SELECT * FROM resume_notices WHERE resume_id=?", (rid,)).fetchall()
                self._json(200, {
                    "resume": dict(resume),
                    "items": [json.loads(i["snapshot_json"]) for i in items],
                    "notices": [dict(n) for n in notices],
                })
            finally:
                conn.close()

        # ---------------------------------------------------------- 静态站点
        _DENY_DIRS = ("data", "certs", "tests", ".git")   # 私密原件/代码不对外

        def _static(self, path: str):
            if path in ("/", ""):
                path = "/index.html"
            rel = os.path.normpath(path).lstrip("/")
            if rel.split("/", 1)[0] in self._DENY_DIRS:
                return self._error(404, "not_found", "页面不存在")
            full = os.path.abspath(os.path.join(app.static_root, rel))
            if not full.startswith(app.static_root) or not os.path.isfile(full):
                return self._error(404, "not_found", "页面不存在")
            ctype = {".html": "text/html; charset=utf-8",
                     ".css": "text/css", ".js": "application/javascript",
                     ".png": "image/png", ".jpg": "image/jpeg",
                     ".svg": "image/svg+xml"}.get(
                         os.path.splitext(full)[1], "application/octet-stream")
            with open(full, "rb") as fh:
                self._send(200, fh.read(), ctype)

    return Handler


def run(host: str = "127.0.0.1", port: int = 8000, app: App | None = None):
    app = app or App()
    server = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"证书证据系统已启动: http://{host}:{port}/certificates.html")
    print(f"管理接口令牌来自环境变量 ADMIN_TOKEN(默认仅开发用)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run(port=port)
