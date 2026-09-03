"""LangGraph 图编排 —— 智能问数主链路。

拓扑：
    START → retrieve → generate → validate(静态+EXPLAIN预演) ─┬─ ok → execute(执行+结果检查) ─┬─ ok → answer → END
                                                             ├─ fail(可修复) → repair(计数+1) → generate
                                                             └─ fail(超限/致命) → answer(致歉) → END

设计要点（面试可讲）：
  - 节点依赖全部构造注入，可整图离线测试（假 LLM / 假检索器）
  - validate 与 execute 两种失败都统一折算为 validation_ok=False，共用一条自修复回路
  - EXPLAIN 预演在静态白名单之后补编译级检查；结果合理性检查在 execute 之后补语义级检查
  - 修复上限 max_repair 防 LLM 无限循环烧 GPU
"""
from __future__ import annotations

import logging
import os

import yaml

from src.agent.nodes import AgentNodes
from src.agent.state import AgentState
from src.sql_validator import SQLValidator

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_agent_config(cfg_path: str | None = None) -> dict:
    path = cfg_path or os.getenv("LLM_CFG", os.path.join(ROOT, "config", "llm.yaml"))
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_graph(llm, retriever, db_path: str,
                allowed_tables=None, allowed_columns=None,
                max_repair: int = 2, row_limit: int = 200,
                enable_narrative: bool = True):
    """组装并编译图。llm: callable(messages)->str；retriever: .build_context(q)->str。"""
    from langgraph.graph import END, START, StateGraph

    if allowed_tables is None or allowed_columns is None:
        from etl.schema import ALLOWED_TABLES, UNIFIED_COLUMNS
        allowed_tables = allowed_tables or ALLOWED_TABLES
        allowed_columns = allowed_columns or UNIFIED_COLUMNS

    validator = SQLValidator(allowed_tables, allowed_columns)
    nodes = AgentNodes(llm, retriever, validator, db_path,
                       max_repair=max_repair, row_limit=row_limit,
                       enable_narrative=enable_narrative)

    g = StateGraph(AgentState)
    g.add_node("retrieve", nodes.retrieve)
    g.add_node("generate", nodes.generate)
    g.add_node("validate", nodes.validate)
    g.add_node("repair", nodes.bump_repair)     # 只做计数自增的小节点
    g.add_node("execute", nodes.execute)
    g.add_node("answer", nodes.answer)

    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "validate")
    g.add_edge("repair", "generate")
    g.add_edge("answer", END)
    g.add_conditional_edges(
        "validate",
        nodes.route_after_validate,
        {"execute": "execute", "repair": "repair", "answer": "answer"},
    )
    # Day 4：execute 之后也改成条件边，执行报错 / 结果检查失败走同一条修复回路
    g.add_conditional_edges(
        "execute",
        nodes.route_after_execute,
        {"repair": "repair", "answer": "answer"},
    )
    return g.compile()


def build_default_graph(db_path: str | None = None, enable_narrative: bool | None = None, db=None):
    """服务器上的一键组装：真 Ollama + 真 Milvus 检索器。

    db 传 Database 实例时走对应后端（如生产 ClickHouse）；否则用 db_path（SQLite 路径，向后兼容）。
    enable_narrative 传 None 时从 llm.yaml 读取；传 bool 时覆盖配置（供 UI 开关）。
    """
    from src.embed import embed
    from src.llm import OllamaLLM
    from src.milvus_store import MilvusStore, load_milvus_config
    from src.retriever import SemanticRetriever

    agent_cfg = load_agent_config()
    llm = OllamaLLM.from_config()
    store = MilvusStore(load_milvus_config())
    retriever = SemanticRetriever(store, embed)
    if enable_narrative is None:
        enable_narrative = agent_cfg["agent"].get("enable_narrative", True)
    target_db = db if db is not None else db_path
    return build_graph(
        llm, retriever, target_db,
        max_repair=agent_cfg["agent"]["max_repair"],
        row_limit=agent_cfg["agent"]["row_limit"],
        enable_narrative=enable_narrative,
    )
