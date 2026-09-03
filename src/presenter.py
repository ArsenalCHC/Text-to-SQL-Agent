"""结果呈现层 —— 把 Agent 最终状态打包成结构化审计轨迹（人审展示用）。

Day 5 核心：除自然语言 answer 外，还输出一份完整可审计的 trace
（问题 / SQL / 校验 / 修复次数 / 置信度 / 告警 / 原始 rows），
Day 6 FastAPI 与 Day 7 Streamlit 都消费这个结构，把「AI 到底做了什么」透明展示给用户。
"""
from __future__ import annotations

from typing import Any, Dict

# (state key, 中文标签) 顺序即前端展示顺序
_TRACE_FIELDS = [
    ("question", "问题"),
    ("answer", "回答"),
    ("sql", "SQL"),
    ("columns", "列"),
    ("rows", "行"),
    ("fact_text", "关键数字"),
    ("table_md", "结果表格"),
    ("validation_ok", "校验通过"),
    ("validation_reason", "校验说明"),
    ("explain_plan", "EXPLAIN 预演"),
    ("repair_count", "修复次数"),
    ("confidence", "置信度"),
    ("warnings", "静态告警"),
    ("result_warnings", "结果告警"),
    ("error", "错误"),
]


def build_trace(state: Dict[str, Any]) -> Dict[str, Any]:
    """把 Agent 最终状态转为可 JSON 序列化的审计轨迹。"""
    return {k: state.get(k) for k, _ in _TRACE_FIELDS}


def trace_labels() -> Dict[str, str]:
    """state key -> 中文标签 映射，供前端渲染。"""
    return dict(_TRACE_FIELDS)


def summarize(state: Dict[str, Any]) -> str:
    """单行摘要，用于日志 / 列表页快速浏览。"""
    if state.get("error"):
        return f"[失败] {state.get('error')}"
    if state.get("validation_ok") is False:
        return f"[未通过] {state.get('validation_reason')}"
    n = len(state.get("rows") or [])
    conf = state.get("confidence")
    conf_s = f"{conf:.0%}" if isinstance(conf, float) else str(conf)
    return f"[成功] {n} 行，修复 {state.get('repair_count', 0)} 次，置信度 {conf_s}"
