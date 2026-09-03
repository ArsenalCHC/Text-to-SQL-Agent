"""语义资产加载 —— 把 schema / metrics / glossary / examples 转成待入库 Doc 列表。

这样 Agent 在回答「血压计本月进度」时，能同时召回：
  - glossary: 血压计 -> category='血压计'
  - metrics:  月进度 -> month_progress（已物化，直接用）
  - examples: 相似的自然语言问法 -> 正确 SQL
  - schema:   v_category_daily 的可用字段
"""
from __future__ import annotations

import json
import os
from typing import Dict, List

import yaml

from src.milvus_store import Doc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEMANTIC_DIR = os.path.join(ROOT, "semantic")


def _load_yaml(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------- schema 集合内容（手写结构化描述，便于精确召回） ----------------
_SCHEMA_DOCS: List[Dict] = [
    {
        "text": (
            "表 daily_metrics：电商销售统一事实表。字段含 date(日期), "
            "platform(平台:天猫/京东/拼多多), dimension_type(维度:category/store), "
            "product_line(产品线), category(品类:血压计/制氧机/血糖仪/雾化器), "
            "store(店铺名), store_type(店铺类型:自营/POP), "
            "daily_amount(当日销售额,元), daily_qty(当日销量,件), "
            "month_amount(当月累计销售额,已物化), month_qty(当月累计销量), "
            "year_amount(当年累计销售额,已物化), year_qty(当年累计销量), "
            "month_target(月目标), year_target(年目标), "
            "month_progress(月进度=月金额/月目标,已物化,直接SELECT), "
            "year_progress(年进度=年金额/年目标,已物化,直接SELECT)。"
        ),
        "payload": {
            "object": "table",
            "name": "daily_metrics",
            "columns": [
                "date", "platform", "dimension_type", "product_line", "category",
                "store", "store_type", "daily_amount", "daily_qty", "month_amount",
                "month_qty", "year_amount", "year_qty", "month_target", "year_target",
                "month_progress", "year_progress",
            ],
            "materialized": ["month_amount", "year_amount", "month_progress", "year_progress"],
        },
    },
    {
        "text": (
            "视图 v_category_daily：品类日报，来自 daily_metrics 且 dimension_type='category'。"
            "含 date, platform, product_line, category 及日/月/年金额、销量、目标、进度。"
            "适合按品类(如血压计/制氧机)查询销售与进度。"
        ),
        "payload": {"object": "view", "name": "v_category_daily", "filter": "dimension_type='category'"},
    },
    {
        "text": (
            "视图 v_store_daily：店铺日报，来自 daily_metrics 且 dimension_type='store'。"
            "含 date, platform, store_type(自营/POP), store 及日/月/年金额、目标、进度。"
            "适合按店铺或店铺类型查询。"
        ),
        "payload": {"object": "view", "name": "v_store_daily", "filter": "dimension_type='store'"},
    },
    {
        "text": (
            "视图 v_platform_summary：集团平台汇总，按 date, platform 聚合。"
            "字段为 daily_amount, month_amount, year_amount, month_target, year_target 的求和。"
            "适合看各平台整体日/月/年销售额，不含品类或店铺明细。"
        ),
        "payload": {"object": "view", "name": "v_platform_summary", "group_by": ["date", "platform"]},
    },
]


def load_schema_docs() -> List[Doc]:
    return [Doc(text=d["text"], source="schema.py", payload=d["payload"]) for d in _SCHEMA_DOCS]


def load_metric_docs() -> List[Doc]:
    cfg = _load_yaml(os.path.join(SEMANTIC_DIR, "metrics.yaml"))
    docs = []
    for m in cfg.get("metrics", []):
        text = (
            f"指标 {m['name']}（字段 {m['sql_ref']}）：{m.get('definition','')}。"
            f"{m.get('note','')}"
        )
        docs.append(Doc(text=text, source="metrics.yaml",
                        payload={"name": m["name"], "sql_ref": m["sql_ref"],
                                 "definition": m.get("definition", "")}))
    return docs


def load_glossary_docs() -> List[Doc]:
    cfg = _load_yaml(os.path.join(SEMANTIC_DIR, "glossary.yaml"))
    docs = []
    for t in cfg.get("terms", []):
        text = f"业务术语「{t['term']}」对应条件：{t['maps_to']}。"
        docs.append(Doc(text=text, source="glossary.yaml",
                        payload={"term": t["term"], "maps_to": t["maps_to"]}))
    return docs


def load_example_docs() -> List[Doc]:
    data = _load_json(os.path.join(SEMANTIC_DIR, "examples.json"))
    docs = []
    for ex in data:
        text = f"问法：{ex['question']}\nSQL：{ex['sql']}"
        docs.append(Doc(text=text, source="examples.json",
                        payload={"question": ex["question"], "sql": ex["sql"]}))
    return docs


def load_all() -> Dict[str, List[Doc]]:
    """返回 {schema, metrics, glossary, examples: [Doc,...]}。"""
    return {
        "schema": load_schema_docs(),
        "metrics": load_metric_docs(),
        "glossary": load_glossary_docs(),
        "examples": load_example_docs(),
    }
