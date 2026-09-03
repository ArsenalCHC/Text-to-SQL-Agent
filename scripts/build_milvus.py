"""在服务器上执行：把语义层写入 Milvus 独立库 text2sql_demo。

前置：
  - 服务器已部署 Milvus 2.6（gRPC 19555），且 4 张空闲 GPU(4-7) 可用
  - 安装依赖：pip install -r requirements.txt（torch 走 CUDA 版）
  - 建议以空闲卡运行：  set CUDA_VISIBLE_DEVICES=4,5,6,7
                        python scripts/build_milvus.py

用法：
  python scripts/build_milvus.py            # 增量入库（已存在集合则追加）
  python scripts/build_milvus.py --drop     # 先删库内集合再建（全量重建）
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_milvus")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.embed import embed  # 懒加载 torch/sentence-transformers
from src.milvus_store import MilvusStore, load_milvus_config
from src.semantic_loader import load_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", action="store_true", help="全量重建（先删集合）")
    ap.add_argument("--cfg", default=os.path.join(ROOT, "config", "milvus.yaml"))
    args = ap.parse_args()

    cfg = load_milvus_config(args.cfg)
    store = MilvusStore(cfg)
    store.connect()

    if args.drop:
        # 仅删除本独立库内的 4 个集合，绝不碰业务库
        for name in store.collections.values():
            if __import__("pymilvus").utility.has_collection(name):
                __import__("pymilvus").utility.drop_collection(name)
                logger.info("删除集合 %s", name)

    store.ensure_all(drop=False)

    all_docs = load_all()
    total = 0
    for key, docs in all_docs.items():
        col = store.collections[key]
        n = store.upsert(col, docs, embed)
        total += n
        logger.info("[%s] 入库 %d 条 -> %s", key, n, col)
    logger.info("完成，共入库 %d 条语义文档", total)


if __name__ == "__main__":
    main()
