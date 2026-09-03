"""FastAPI 服务 —— 把 LangGraph 问数链路暴露为 HTTP 接口。

Day 6 核心：把离线可测的 Agent（graph.invoke）包成对外可调的服务。

端点：
  GET  /health   健康检测（DB 可读 + 图已就绪）
  POST /chat     主入口：{question} -> 完整审计轨迹（answer/sql/置信度/告警/rows）
  POST /sql      调试用：{question} -> 只返回生成的 SQL + 校验结果

设计要点（面试可讲）：
  - 图通过构造注入，本机可用假图离线测；服务器用 build_default_graph 接真 Ollama/Milvus
  - 返回结构复用 Day5 的 build_trace，把「AI 做了什么」透明给调用方
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

from src.database import Database  # noqa: E402  仅用于 health 判断
from src.presenter import build_trace


class ChatRequest(BaseModel):
    question: str


class SQLRequest(BaseModel):
    question: str


def create_app(graph, db_path: Optional[str] = None) -> FastAPI:
    """组装 FastAPI 应用。graph 为已编译的 LangGraph 图（可注入假图做离线测试）。"""
    app = FastAPI(title="智能问数系统", description="鱼跃电商日报 NL2SQL 智能问数", version="1.0.0")

    @app.get("/health")
    def health() -> dict:
        if isinstance(db_path, Database):
            db_ok = db_path.ping()
        else:
            db_ok = bool(db_path) and os.path.exists(db_path)
        return {
            "status": "ok" if db_ok and graph is not None else "degraded",
            "db_readable": db_ok,
            "graph_ready": graph is not None,
        }

    @app.post("/chat")
    def chat(req: ChatRequest) -> dict:
        """主入口：一次完整问数，返回可审计轨迹。"""
        final = graph.invoke({"question": req.question})
        return build_trace(final)

    @app.post("/sql")
    def sql(req: SQLRequest) -> dict:
        """调试用：返回生成的 SQL 与校验结果，不关心最终回答。"""
        final = graph.invoke({"question": req.question})
        return {
            "question": req.question,
            "sql": final.get("sql"),
            "validation_ok": final.get("validation_ok"),
            "validation_reason": final.get("validation_reason"),
            "repair_count": final.get("repair_count"),
            "warnings": final.get("warnings"),
        }

    return app
