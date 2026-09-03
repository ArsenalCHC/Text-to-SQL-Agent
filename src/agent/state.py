"""LangGraph Agent 状态定义（TypedDict，LangGraph 官方推荐写法）。

一次问数流转全程的状态都在这里，节点只读写这份状态——
这也是面试时讲 LangGraph 的核心点：状态是唯一事实源，节点是无副作用的变换。

Day 4 新增三处状态：
  - explain_plan：EXPLAIN 预演结果（编译级检查的产物，供排查/展示）
  - confidence：置信度（随修复次数递减，驱动最终回答里的人工核对提示）
  - result_warnings：结果合理性检查的告警（NaN/触顶等，附在回答里提示用户）
"""
from __future__ import annotations

from typing import List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    # 输入
    question: str            # 用户原始问题

    # 检索
    context: str             # 语义检索拼出的上下文（schema/口径/术语/样例）

    # 生成
    sql: str                 # LLM 生成的 SQL
    llm_messages: List[dict] # 生成/修复共用的对话历史（含系统提示与失败反馈）

    # 校验（静态白名单 + EXPLAIN 预演）
    validation_ok: bool
    validation_reason: str
    warnings: List[str]      # 静态校验的列白名单告警
    explain_plan: str        # EXPLAIN 预演结果（编译级检查产物）
    repair_count: int        # 已自修复次数

    # 执行 + 结果合理性检查
    columns: List[str]
    rows: List[tuple]
    result_warnings: List[str]  # 结果合理性检查告警（NaN / 触顶等）

    # 输出
    confidence: float        # 置信度（随修复次数递减）
    answer: str              # 面向用户的最终回答
    fact_text: str           # 关键数字（直接来自 rows，权威，不经 LLM）
    table_md: str            # Markdown 结果表格（直接来自 rows，权威）
    error: Optional[str]     # 非空表示本次问数失败（含原因）
