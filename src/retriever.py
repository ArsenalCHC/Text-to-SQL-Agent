"""语义检索编排 —— 给定自然语言问题，从 4 个集合做混合检索并拼成 prompt 上下文。

设计要点：
  - 一次问题，四类上下文全部召回（schema/metrics/glossary/examples），
    让 LLM 既有「表结构」又有「口径」还有「相似样例」，显著降低写错 SQL 的概率。
  - 返回结构化命中（含 payload），方便后续做置信度评估 / 人审展示。
"""
from __future__ import annotations

from typing import Dict, List

from src.milvus_store import MilvusStore


class SemanticRetriever:
    def __init__(self, store: MilvusStore, embedder, top_k: int = 5):
        self.store = store
        self.embedder = embedder
        self.top_k = top_k

    def retrieve(self, query: str) -> Dict[str, list]:
        qvec = self.embedder([query])[0]
        out: Dict[str, list] = {}
        for key, col in self.store.collections.items():
            out[key] = self.store.hybrid_search(col, query, qvec, top_k=self.top_k)
        return out

    def build_context(self, query: str, top_k: int = 3) -> str:
        """拼成可读上下文，供 SQL 生成 prompt 直接引用。"""
        res = self.retrieve(query)
        header = {
            "schema": "可用表/视图结构",
            "metrics": "指标口径（已物化，直接 SELECT）",
            "glossary": "业务术语 -> 字段映射",
            "examples": "相似问法的正确 SQL 样例",
        }
        parts: List[str] = []
        for key, hits in res.items():
            picked = [h for h in hits if h.get("text")][:top_k]
            if not picked:
                continue
            parts.append(f"## {header.get(key, key)}")
            for h in picked:
                parts.append(f"- {h['text']}")
        return "\n".join(parts)
