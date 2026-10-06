"""演示数据: 初始化签发机构、证书、图片、核对记录、技能与简历。

用法: python3 -m certs.seed [db_path]
幂等: 已存在数据(有证书)时直接跳过。
"""
from __future__ import annotations

import json
import os
import sys

from . import service
from .db import connect, init_db
from .pngtool import make_png

DB = os.environ.get("CERTS_DB", "data/certificates.db")
PRIV = os.environ.get("CERTS_PRIVATE_DIR", "data/private/originals")
PUB = os.environ.get("CERTS_PUBLIC_DIR", "data/public/derived")


def _demo_png(cert_no: str, holder: str, id_no: str, color):
    return make_png(320, 200, color, texts={
        "ocr_text": f"姓名：{holder} 证书编号: {cert_no} 身份证号 {id_no}",
        "pii_boxes": json.dumps([
            {"x": 20, "y": 150, "w": 280, "h": 18},   # 身份证号行
            {"x": 20, "y": 30, "w": 120, "h": 16},    # 姓名区域
        ]),
    })


def main(db_path: str = DB) -> None:
    init_db(db_path)
    conn = connect(db_path)
    try:
        if conn.execute("SELECT COUNT(*) c FROM certificates").fetchone()["c"]:
            print("已存在数据, 跳过种子初始化")
            return
        clock = service.load_clock(conn)

        org1 = service.create_issuer(conn, clock, "全国信息技术水平考试中心")
        org2 = service.create_issuer(conn, clock, "云帆开源社区")
        service.rename_issuer(conn, clock, org2["id"], "云帆开源基金会")

        c1 = service.record_award(
            conn, clock, title="高级软件设计师", issuer_id=org1["id"],
            issued_on="2024-05-18", valid_until="2027-05-18",
            expiry_tz="Asia/Shanghai", level="高级",
            growth_goal="补齐系统架构设计能力, 冲刺架构师认证",
            verify_url="https://verify.example.org/certs/SD-2024-0518",
            skills=["系统设计", "软件工程"])
        service.attach_image(conn, clock, c1["id"],
                             _demo_png("SD-2024-0518", "林墨", "110101199505126714",
                                       (52, 68, 110)), PRIV, PUB)
        service.check_link(conn, clock, c1["id"], lambda url: (True, "HTTP 200"))

        c2 = service.record_award(
            conn, clock, title="云原生容器认证工程师", issuer_id=org2["id"],
            issued_on="2025-09-01", valid_until="2026-10-20",
            expiry_tz="Asia/Shanghai", level="工程师",
            growth_goal="深入 Kubernetes 源码, 向平台工程方向发展",
            verify_url="https://certs.yunfan.example.org/CN-88901",
            skills=["Kubernetes", "云原生"])
        service.attach_image(conn, clock, c2["id"],
                             _demo_png("CN-88901", "林墨", "110101199505126714",
                                       (35, 90, 80)), PRIV, PUB)
        service.check_link(conn, clock, c2["id"], lambda url: (True, "HTTP 200"))

        c3 = service.record_award(
            conn, clock, title="英语六级证书", issuer_id=org1["id"],
            issued_on="2022-06-15", valid_until=None,
            expiry_tz="Asia/Shanghai", growth_goal="无障碍阅读英文技术文献",
            skills=["英语"])
        service.attach_image(conn, clock, c3["id"],
                             _demo_png("CET6-220615-773", "林墨", "110101199505126714",
                                       (110, 60, 60)), PRIV, PUB)

        c4 = service.record_award(
            conn, clock, title="旧版网页设计认证", issuer_id=org2["id"],
            issued_on="2021-03-10", valid_until="2023-03-10",
            expiry_tz="Asia/Shanghai", growth_goal="早期前端能力证明",
            verify_url="https://old.yunfan.example.org/WD-1123",
            skills=["前端开发"])
        service.check_link(conn, clock, c4["id"], lambda url: (False, "HTTP 404"))

        resume = service.create_resume(conn, clock, "2026 秋招简历(候选)")
        for cid in (c1["id"], c2["id"], c3["id"]):
            service.add_resume_item(conn, clock, resume["id"], cid)

        print(f"种子数据完成: {db_path}")
        print(f"  证书 {c1['public_id']} {c2['public_id']} {c3['public_id']} {c4['public_id']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DB)
