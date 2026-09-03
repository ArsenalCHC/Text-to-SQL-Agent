"""启动智能问数 HTTP 服务（服务器上运行）。

用法：
  python scripts/run_api.py                     # 默认 0.0.0.0:8000
  python scripts/run_api.py --port 8001         # 指定端口
  DB_PATH=data/ecommerce_daily.db python scripts/run_api.py   # 指定 DB

注意：需要先完成 Day2 Milvus 入库 + GPU4-7 起独立 Ollama，否则图组装时会连不上。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "data", "ecommerce_daily.db")


def main():
    parser = argparse.ArgumentParser(description="智能问数 FastAPI 服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--db", default=os.getenv("DB_PATH", DEFAULT_DB), help="SQLite 路径（backend=sqlite 时生效）")
    parser.add_argument("--backend", default=os.getenv("DB_BACKEND", "sqlite"),
                        choices=["sqlite", "clickhouse"], help="数据库后端（生产选 clickhouse）")
    args = parser.parse_args()

    from src.agent.graph import build_default_graph
    from src.api.server import create_app

    if args.backend == "clickhouse":
        from src.database import create_database
        db = create_database("clickhouse")
        graph = build_default_graph(db=db)
        app = create_app(graph, db)
    else:
        graph = build_default_graph(args.db)
        app = create_app(graph, args.db)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
