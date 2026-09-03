"""LangGraph 节点实现。

节点职责单一化，全部通过构造函数注入依赖（LLM / 检索器 / 校验器 / DB），
因此每个节点都能用假依赖做离线单测——Day 3 在无 GPU / 无 Milvus 的本机即可整图验证。

Day 4 增量（对应「防 GG」四条防线）：
  - validate：静态白名单通过后追加 EXPLAIN 预演（编译级检查）
  - execute：执行成功后追加结果合理性检查（列缺失 / 空结果 / NaN / 触顶）
  - route_after_execute：execute 失败也走同一条修复回路（不再固定进 answer）
  - answer：空结果安全直出（不交给 LLM 编数字）+ 置信度联动的人工核对提示
"""
from __future__ import annotations

import logging
from typing import Optional

from src.agent import prompts
from src.agent.state import AgentState
from src.db import explain, query
from src.formatter import format_fact, format_table
from src.llm import extract_sql
from src.result_check import FAIL, check_result
from src.sql_validator import SQLValidator

logger = logging.getLogger(__name__)


class AgentNodes:
    def __init__(self, llm, retriever, validator: SQLValidator,
                 db_path: str, max_repair: int = 2, row_limit: int = 200,
                 enable_narrative: bool = True):
        self.llm = llm                       # callable(messages)->str
        self.retriever = retriever           # .build_context(question)->str
        self.validator = validator
        self.db_path = db_path
        self.max_repair = max_repair
        self.row_limit = row_limit
        self.enable_narrative = enable_narrative  # 是否让 LLM 做解读（数字仍以表格为准）

    # ---------------- 1. 语义检索 ----------------
    def retrieve(self, state: AgentState) -> dict:
        question = state["question"]
        try:
            context = self.retriever.build_context(question)
        except Exception as e:  # noqa: BLE001
            # 检索失败不阻断流程：退化为空上下文（LLM 仅靠系统提示约束）
            logger.warning("语义检索失败，退化为空上下文: %s", e)
            context = ""
        return {"context": context, "repair_count": 0,
                "llm_messages": [{"role": "system", "content": prompts.SYSTEM_SQL_GEN}]}

    # ---------------- 2. SQL 生成（含修复重入） ----------------
    def generate(self, state: AgentState) -> dict:
        messages = list(state.get("llm_messages") or [])
        if not messages:
            messages = [{"role": "system", "content": prompts.SYSTEM_SQL_GEN}]
        # 自修复判据：已生成过 SQL 且进入过修复流程（repair 节点已把计数 +1）
        if state.get("sql") and (state.get("repair_count", 0) or 0) > 0:
            # 自修复路径：历史里已有 system/user/assistant，只需追加失败原因
            messages = messages + [{
                "role": "user", "content": prompts.REPAIR_TMPL.format(
                    sql=state["sql"], reason=state.get("validation_reason", ""),
                    warnings="\n".join(state.get("warnings") or []) or "无")},
            ]
        else:
            # 首次生成
            messages = messages + [{
                "role": "user",
                "content": prompts.USER_SQL_TMPL.format(
                    context=state.get("context", ""), question=state["question"]),
            }]
        try:
            out = self.llm(messages)
        except Exception as e:  # noqa: BLE001
            return {"sql": "", "error": f"LLM 调用失败: {e}"}
        sql = extract_sql(out)
        # 记录到对话历史，供下轮修复引用
        new_messages = messages + [{"role": "assistant", "content": out}]
        return {"sql": sql, "llm_messages": new_messages}

    # ---------------- 3. 静态校验 + EXPLAIN 预演 ----------------
    def validate(self, state: AgentState) -> dict:
        sql = state.get("sql") or ""
        ok, reason, warnings = self.validator.validate(sql)
        if not ok:
            return {"validation_ok": ok, "validation_reason": reason,
                    "warnings": warnings}
        # 静态白名单通过 → EXPLAIN 预演：抓「不存在的列 / 视图字段」等编译级错误
        try:
            plan = explain(self.db_path, sql)
        except Exception as e:  # noqa: BLE001
            return {"validation_ok": False,
                    "validation_reason": f"SQL 编译失败（EXPLAIN 预演）: {e}",
                    "warnings": warnings}
        return {"validation_ok": True,
                "validation_reason": f"{reason}；{plan}",
                "warnings": warnings,
                "explain_plan": plan}

    # ---------------- 4. 只读执行 + 结果合理性检查 ----------------
    def execute(self, state: AgentState) -> dict:
        try:
            columns, rows = query(self.db_path, state["sql"], row_limit=self.row_limit)
        except Exception as e:  # noqa: BLE001
            # 执行报错折算成校验失败，走修复回路
            return {"validation_ok": False,
                    "validation_reason": f"SQL 执行报错: {e}",
                    "warnings": []}
        status, reason, warnings = check_result(columns, rows, self.row_limit)
        if status == FAIL:
            # 列缺失等结构性问题：不可用，走修复
            return {"validation_ok": False,
                    "validation_reason": reason,
                    "warnings": warnings,
                    "columns": columns, "rows": rows}
        # PASS：结果可用（空结果也走这里，由 answer 层安全直出）
        return {"validation_ok": True,
                "columns": columns, "rows": rows,
                "result_warnings": warnings}

    # ---------------- 5. 结果作答（Day 5：关键数字直出，LLM 只做可解读） ----------------
    def answer(self, state: AgentState) -> dict:
        if state.get("error"):
            return {"answer": f"问数失败：{state['error']}"}
        if not state.get("validation_ok", False):
            reason = state.get("validation_reason", "未知原因")
            return {"answer": f"抱歉，本次未能生成合规 SQL（{reason}），"
                              f"已重试 {state.get('repair_count', 0)} 次。请换种问法或联系管理员。",
                    "error": reason}
        rows = state.get("rows") or []
        columns = state.get("columns") or []

        # 空结果安全直出：不交给 LLM，从根上杜绝「对空结果编数字」
        if not rows:
            return {"answer": "查询结果为空：当前条件下没有匹配的数据，请确认筛选条件是否过严。"}

        # Day 5：关键数字与表格直接来自 rows，不经 LLM 二次加工（权威）
        fact_text = format_fact(columns, rows, max_rows=5)
        table_md = format_table(columns, rows, max_rows=50)

        # LLM 只做可选解读：数字一律引用表格，禁止自行计算 / 编造
        narrative = ""
        if self.enable_narrative:
            try:
                narrative = self.llm([{
                    "role": "user",
                    "content": prompts.NARRATE_TMPL.format(
                        question=state["question"], sql=state["sql"],
                        columns=columns, n=len(rows), table=table_md),
                }]).strip()
            except Exception as e:  # noqa: BLE001
                logger.warning("LLM 解读失败，退化为纯表格直出: %s", e)
                narrative = ""

        # 置信度联动：修复越多，越要提醒人工核对
        confidence = self._confidence(state.get("repair_count", 0) or 0)
        suffix = ""
        if confidence < 0.7:
            suffix = (f"\n\n> ⚠️ 本次共自动修复 {state.get('repair_count', 0)} 次，"
                      f"置信度 {confidence:.0%}，建议人工核对原始数据。")
        result_warnings = state.get("result_warnings") or []
        if result_warnings:
            suffix += "\n> ⚠️ " + "；".join(result_warnings)

        parts = []
        if narrative:
            parts.append(narrative)
        parts.append(f"**查询结果（共 {len(rows)} 行）**")
        parts.append(table_md)
        answer = "\n\n".join(parts) + suffix
        return {"answer": answer, "fact_text": fact_text,
                "table_md": table_md, "confidence": confidence}

    # ---------------- 路由 ----------------
    def route_after_validate(self, state: AgentState) -> str:
        if state.get("error"):
            return "answer"
        if state.get("validation_ok"):
            return "execute"
        # 校验失败（含 EXPLAIN 预演失败）统一走修复回路
        if (state.get("repair_count", 0) or 0) < self.max_repair:
            return "repair"
        return "answer"

    def route_after_execute(self, state: AgentState) -> str:
        """execute 之后的新条件边（Day 4 新增）。

        执行成功 → answer；执行报错 / 结果检查 FAIL → 走同一条修复回路；
        修复超限 → answer 致歉。这样 execute 的错误不再被固定边吞掉。
        """
        if state.get("error"):
            return "answer"
        if state.get("validation_ok"):
            return "answer"
        if (state.get("repair_count", 0) or 0) < self.max_repair:
            return "repair"
        return "answer"

    def bump_repair(self, state: AgentState) -> dict:
        """条件边进入 generate 前无法改状态，这里用独立小节点自增修复计数。"""
        return {"repair_count": (state.get("repair_count", 0) or 0) + 1}

    @staticmethod
    def _confidence(repair_count: int) -> float:
        """修复次数越多，置信度越低：0→1.0，1→0.6，2→0.2。

        0.4 的步长保证「修复 1 次（0.6）即低于 0.7 阈值」，从而触发人工核对提示——
        第一次写错本身就是值得用户留意的信号。
        """
        return max(0.0, 1.0 - repair_count * 0.4)
