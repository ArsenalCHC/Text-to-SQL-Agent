"""结果格式化 —— 关键数字直出，不经 LLM 二次加工。

Day 5 核心（对应「防 GG」第六道防线）：
SQL 返回的 rows 直接格式化为「关键数字 + Markdown 表格」作为权威答案，
LLM 只做可选的解读（数字一律以表格为准）。

这样彻底解决 Day 3 实测暴露的问题——LLM 把真实值 0.97 说成 62.3%。
金额字段（*_amount / *_target）自动加 ¥ 与千分位，符合国内财务展示习惯。
"""
from __future__ import annotations

from typing import List

_AMOUNT_SUFFIXES = ("amount", "target")


def _is_amount(col: str) -> bool:
    return bool(col) and col.endswith(_AMOUNT_SUFFIXES)


def format_cell(v, col: str | None = None) -> str:
    """单个单元格的展示文本：None→—；金额加 ¥ 千分位；浮点统一两位小数。"""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        s = f"{v:,.2f}"
        return f"¥{s}" if _is_amount(col or "") else s
    if isinstance(v, int):
        s = f"{v:,}"
        return f"¥{s}" if _is_amount(col or "") else s
    # 字符串兜底：金额列尝试数字格式化
    if _is_amount(col or ""):
        try:
            return f"¥{float(v):,.2f}"
        except (TypeError, ValueError):
            return str(v)
    return str(v)


def format_table(columns: List[str], rows: List[tuple], max_rows: int = 50) -> str:
    """Markdown 表格，直接由 rows 生成，不依赖 LLM（权威数据源）。"""
    if not columns:
        return "（无列信息）"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines = [header, sep]
    for r in rows[:max_rows]:
        cells = [format_cell(v, columns[i]) for i, v in enumerate(r)]
        lines.append("| " + " | ".join(cells) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n> 仅展示前 {max_rows} 行，共 {len(rows)} 行。")
    return "\n".join(lines)


def format_fact(columns: List[str], rows: List[tuple], max_rows: int = 5) -> str:
    """关键数字事实直出：一行一个「列名=值」。用于 answer 的权威数字摘录。"""
    if not columns:
        return "（无数据）"
    lines = []
    for i, r in enumerate(rows[:max_rows], 1):
        pairs = "，".join(
            f"{columns[j]}={format_cell(v, columns[j])}" for j, v in enumerate(r)
        )
        lines.append(f"{i}. {pairs}")
    if len(rows) > max_rows:
        lines.append(f"…（共 {len(rows)} 行，其余见下方表格）")
    return "\n".join(lines)
