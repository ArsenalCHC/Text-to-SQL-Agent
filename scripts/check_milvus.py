"""连接性 / 健康检测：确认能否连上 Milvus 独立库 text2sql_demo。

用法：
  python scripts/check_milvus.py
  MILVUS_HOST=127.0.0.1 MILVUS_PORT=19555 python scripts/check_milvus.py

本机连不到服务器的 19555 属正常；真正连通在服务器上执行。
"""
from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("check_milvus")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.milvus_store import MilvusStore, load_milvus_config


def main():
    cfg = load_milvus_config(os.path.join(ROOT, "config", "milvus.yaml"))
    store = MilvusStore(cfg)
    host = os.getenv("MILVUS_HOST", cfg["milvus"].get("host"))
    port = os.getenv("MILVUS_PORT", cfg["milvus"].get("port"))
    db_name = cfg["milvus"].get("database")
    print(f"目标: {host}:{port}  独立库: {db_name}")
    if store.health_check():
        print("✅ 连通正常，独立库可用")
        sys.exit(0)
    print("❌ 无法连通。请确认：")
    print("   1) 在服务器上执行（本机无 Milvus）")
    print("   2) Milvus gRPC 端口是否为 19555，或设置 MILVUS_HOST/MILVUS_PORT")
    sys.exit(1)


if __name__ == "__main__":
    main()
