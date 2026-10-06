"""SQLite 存储层: 证书身份、修订、事件、图片、链接核对、投影、技能证据、简历。

设计要点:
  - certificates 承载"身份"(同一证书补发/续期/复验都挂在同一身份下);
  - certificate_revisions 保存每次元数据变更的不可变快照;
  - events 是事实源(获奖/补发/续期/撤销/更名/链接核对/时钟校正...);
  - cert_projection 是事件驱动的读模型缓存, 实时计算才是状态权威。
"""
from __future__ import annotations

import os
import sqlite3

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issuers (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL
);

-- 签发机构名称历史(更名不改身份)
CREATE TABLE IF NOT EXISTS issuer_names (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id    INTEGER NOT NULL REFERENCES issuers(id),
  name         TEXT NOT NULL,
  effective_at TEXT NOT NULL,   -- 更名生效时间
  recorded_at  TEXT NOT NULL,
  event_id     INTEGER
);

CREATE TABLE IF NOT EXISTS certificates (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  public_id    TEXT UNIQUE NOT NULL,      -- 对外稳定标识 CRT-0001
  title        TEXT NOT NULL,
  issuer_id    INTEGER NOT NULL REFERENCES issuers(id),
  level        TEXT,                       -- 描述性等级(仅展示, 不参与评分)
  growth_goal  TEXT,                       -- 成长目标
  issued_on    TEXT NOT NULL,              -- 首次获奖日期 YYYY-MM-DD
  valid_from   TEXT,                       -- ISO 时间或 NULL
  valid_until  TEXT,                       -- ISO 日期/时间或 NULL(长期有效)
  expiry_tz    TEXT NOT NULL DEFAULT 'UTC',-- 到期判定所用时区(签发方时区)
  verify_url   TEXT,
  rev          INTEGER NOT NULL DEFAULT 1, -- 当前修订号
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS certificate_revisions (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  certificate_id INTEGER NOT NULL REFERENCES certificates(id),
  rev            INTEGER NOT NULL,
  payload_json   TEXT NOT NULL,
  event_id       INTEGER,
  created_at     TEXT NOT NULL,
  UNIQUE(certificate_id, rev)
);

-- 事件溯源: 同一证书的补发图片/续期/新获奖是不同事件类型
CREATE TABLE IF NOT EXISTS events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,  -- 全局单调序号
  certificate_id  INTEGER REFERENCES certificates(id),
  issuer_id       INTEGER REFERENCES issuers(id),
  type            TEXT NOT NULL,
  payload_json    TEXT NOT NULL,
  occurred_at     TEXT NOT NULL,   -- 业务生效时间(追溯撤销可为过去)
  recorded_at     TEXT NOT NULL,   -- 校正后的服务器时间
  clock_offset_ms INTEGER NOT NULL,-- 记录时使用的时钟偏移
  idempotency_key TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS images (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  image_uid      TEXT UNIQUE NOT NULL,
  certificate_id INTEGER NOT NULL REFERENCES certificates(id),
  event_id       INTEGER,
  sha256         TEXT NOT NULL,
  width          INTEGER,
  height         INTEGER,
  original_path  TEXT NOT NULL,   -- 私密原件(永不对外服务)
  derived_path   TEXT,            -- 公开派生图(脱敏后); 失败为 NULL
  extracted_json TEXT,            -- 识别出的个人编号/元数据
  redactions_json TEXT,           -- 脱敏区域
  status         TEXT NOT NULL,   -- ok | failed
  error          TEXT,
  is_current     INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS link_checks (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  certificate_id INTEGER NOT NULL REFERENCES certificates(id),
  url            TEXT NOT NULL,
  outcome        TEXT NOT NULL,   -- reachable | unreachable | error
  detail         TEXT,
  checked_at     TEXT NOT NULL
);

-- 事件驱动投影(缓存; 权威状态以实时计算为准)
CREATE TABLE IF NOT EXISTS cert_projection (
  certificate_id INTEGER PRIMARY KEY,
  validity       TEXT NOT NULL,   -- valid | expiring_soon | expired | revoked
  verification   TEXT NOT NULL,   -- self_reported | source_checked | link_failed
  valid_until    TEXT,
  last_event_id  INTEGER NOT NULL,
  updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_evidence (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  skill          TEXT NOT NULL,
  certificate_id INTEGER NOT NULL REFERENCES certificates(id),
  state          TEXT NOT NULL,   -- current | expired | revoked | unverified
  updated_at     TEXT NOT NULL,
  UNIQUE(skill, certificate_id)
);

CREATE TABLE IF NOT EXISTS resumes (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  title      TEXT NOT NULL,
  created_at TEXT NOT NULL,
  frozen_at  TEXT                 -- 冻结后内容不可变
);

CREATE TABLE IF NOT EXISTS resume_items (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  resume_id      INTEGER NOT NULL REFERENCES resumes(id),
  certificate_id INTEGER NOT NULL REFERENCES certificates(id),
  snapshot_json  TEXT NOT NULL,   -- 加入/冻结时的快照
  UNIQUE(resume_id, certificate_id)
);

-- 冻结后发生的证书状态变化, 以"附注"形式呈现, 不改写冻结内容
CREATE TABLE IF NOT EXISTS resume_notices (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  resume_id      INTEGER NOT NULL REFERENCES resumes(id),
  certificate_id INTEGER NOT NULL REFERENCES certificates(id),
  notice         TEXT NOT NULL,
  created_at     TEXT NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
