"""Milvus 存储层 —— 独立库 text2sql_demo，与生产业务库物理隔离。

职责：
  1. 连接 + 建独立库（绝不触碰业务库）
  2. 为 4 类语义资产建集合：dense 向量 + BM25 全文稀疏向量（混合检索）
  3. 入库（text 经 BM25 Function 自动产出 sparse）
  4. 混合检索：dense(语义) + sparse(BM25 全文)，RRFRanker 融合

依赖：pymilvus>=2.6,<2.7（与服务器 Milvus 2.6 匹配）。
文档依据：https://milvus.io/docs/full-text-search.md
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Iterable, List

import yaml
from pymilvus import (
    AnnSearchRequest,
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    Function,
    FunctionType,
    RRFRanker,
    db,
    connections,
    utility,
)

logger = logging.getLogger(__name__)

DIM = 1024
TOP_K = 5
DENSE_METRIC = "IP"      # bge-m3 归一化向量用内积
SPARSE_METRIC = "BM25"   # BM25 Function 生成的稀疏向量，索引/检索均用 BM25


@dataclass
class Doc:
    """一条待入库的语义文档。"""
    text: str                 # 用于嵌入 + 全文检索的可读文本
    source: str               # 来源（如 metrics.yaml / glossary.yaml）
    payload: dict = field(default_factory=dict)  # 结构化元数据


def load_milvus_config(path: str = "config/milvus.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class MilvusStore:
    def __init__(self, cfg: dict):
        m = cfg["milvus"]
        self.host = os.getenv("MILVUS_HOST", m.get("host", "127.0.0.1"))
        self.port = os.getenv("MILVUS_PORT", str(m.get("port", 19555)))
        self.database = m.get("database", "text2sql_demo")
        self.timeout = int(m.get("timeout", 10))
        self.collections = {k: v["name"] for k, v in cfg.get("collections", {}).items()}
        self._connected = False

    # ---------------- 连接 / 建独立库 ----------------
    def connect(self, alias: str = "default") -> None:
        if self._connected:
            return
        connections.connect(
            alias=alias, host=self.host, port=self.port, timeout=self.timeout
        )
        # 独立库：不存在则创建；绝不触碰业务库
        existing = db.list_database(using=alias)
        if self.database not in existing:
            logger.info("创建独立数据库 %s", self.database)
            db.create_database(self.database, using=alias)
        db.using_database(self.database, using=alias)
        self._connected = True

    def health_check(self) -> bool:
        try:
            self.connect()
            utility.list_collections()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("Milvus 健康检测失败: %s", e)
            return False

    # ---------------- 集合定义 ----------------
    def _make_schema(self) -> CollectionSchema:
        """固定 4 字段：text(全文) / dense(语义) / sparse(BM25 自动产出) / source / payload。"""
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(
                name="text",
                dtype=DataType.VARCHAR,
                max_length=4096,
                enable_analyzer=True,
                analyzer_params={"type": "chinese"},  # 中文分词
            ),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=DIM),
            # BM25 Function 的输出字段：必须显式声明，无需指定 dim
            FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="payload", dtype=DataType.JSON),
        ]
        schema = CollectionSchema(fields, enable_dynamic_field=False)
        schema.add_function(
            Function(
                name="text_bm25",
                input_field_names=["text"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )
        return schema

    def ensure_collection(self, name: str, drop: bool = False) -> Collection:
        if utility.has_collection(name):
            if drop:
                utility.drop_collection(name)
            else:
                return Collection(name)
        col = Collection(name, self._make_schema())
        col.create_index(
            "dense",
            {
                "index_type": "HNSW",
                "metric_type": DENSE_METRIC,
                "params": {"M": 8, "efConstruction": 200},
            },
        )
        col.create_index(
            "sparse",
            {
                "index_type": "SPARSE_INVERTED_INDEX",
                "metric_type": SPARSE_METRIC,
                "params": {"inverted_index_algo": "DAAT_MAXSCORE", "bm25_k1": 1.2, "bm25_b": 0.75},
            },
        )
        col.load()
        return col

    def ensure_all(self, drop: bool = False) -> dict:
        self.connect()
        return {k: self.ensure_collection(v, drop=drop) for k, v in self.collections.items()}

    # ---------------- 入库 ----------------
    def upsert(self, collection: str, docs: Iterable[Doc], embedder) -> int:
        """embedder: callable(texts:list[str]) -> list[list[float]]。"""
        self.connect()
        col = Collection(collection)
        docs = list(docs)
        if not docs:
            return 0
        texts = [d.text for d in docs]
        vecs = embedder(texts)
        data = [
            texts,                       # text
            vecs,                        # dense
            [d.source for d in docs],    # source
            [d.payload for d in docs],   # payload
            # sparse 由 BM25 Function 从 text 自动生成，不传
        ]
        col.insert(data)
        col.flush()
        logger.info("集合 %s 入库 %d 条", collection, len(docs))
        return len(docs)

    # ---------------- 混合检索 ----------------
    def hybrid_search(
        self, collection: str, query: str, query_vec: List[float], top_k: int = TOP_K
    ) -> list:
        self.connect()
        col = Collection(collection)
        dense_req = AnnSearchRequest(
            [query_vec],
            "dense",
            {"metric_type": DENSE_METRIC, "params": {"nprobe": 10}},
            limit=top_k,
        )
        sparse_req = AnnSearchRequest(
            [query],
            "sparse",
            {"metric_type": SPARSE_METRIC, "params": {}},
            limit=top_k,
        )
        res = col.hybrid_search(
            [dense_req, sparse_req],
            RRFRanker(),
            limit=top_k,
            output_fields=["text", "source", "payload"],
        )
        hits = res[0] if res else []
        return [
            {
                "text": h.entity.get("text"),
                "source": h.entity.get("source"),
                "payload": h.entity.get("payload"),
                "score": h.score,
            }
            for h in hits
        ]
