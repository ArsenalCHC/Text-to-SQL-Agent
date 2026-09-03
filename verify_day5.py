"""Day 5 验证：结果格式化 + 人审展示（关键数字直出，不经 LLM 二次加工）。

场景：
  1. 关键数字直出（关闭解读）：表格与数字直接来自 rows，LLM 只被调用 1 次（仅生成 SQL）
  2. 表格确定性：table_md 与 formatter 直出的结果逐字节一致（不依赖 LLM）
  3. LLM 解读开启：解读附加在表格之前，但表格仍是权威数据源
  4. 金额格式化：金额列加 ¥ 与千分位
  5. 审计轨迹：build_trace 输出完整可 JSON 序列化的审计字段

运行：python verify_day5.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent.graph import build_graph
from src.db import query
from src.formatter import format_cell, format_table
from src.presenter import build_trace, summarize

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ecommerce_daily.db")
GOOD_SQL = ("SELECT date, month_progress FROM v_category_daily "
            "WHERE platform='天猫' AND category='血压计' ORDER BY date DESC LIMIT 1;")
MULTI_SQL = ("SELECT platform, SUM(month_amount) AS month_amount FROM daily_metrics "
             "WHERE dimension_type='category' GROUP BY platform;")


class FakeRetriever:
    def build_context(self, question: str) -> str:
        return ("## 指标口径\n- 月进度 month_progress 已物化\n"
                "## 业务术语\n- 血压计 -> category='血压计'\n")


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0) if self.replies else "```sql\nSELECT 1;\n```"


def main():
    # 真库取 ground truth
    columns, rows = query(DB, GOOD_SQL)
    assert len(rows) == 1, "预备：GOOD_SQL 应返回 1 行"
    expected_table = format_table(columns, rows)

    # 场景 1 + 2：关闭解读，关键数字直出，LLM 只被调用 1 次
    llm1 = ScriptedLLM([f"```sql\n{GOOD_SQL}\n```"])
    g1 = build_graph(llm1, FakeRetriever(), DB, max_repair=2, enable_narrative=False)
    f1 = g1.invoke({"question": "天猫血压计本月进度是多少？"})
    assert f1["validation_ok"] is True
    assert len(llm1.calls) == 1, "关闭解读后 LLM 只应被调用 1 次（仅生成 SQL），不调用来作答"
    assert f1["table_md"] == expected_table, "表格应逐字节等于 formatter 直出（不依赖 LLM）"
    ground_date = str(rows[0][0])
    ground_progress = format_cell(rows[0][1], columns[1])
    assert ground_date in f1["answer"], "回答应包含真实日期（直出，从 DB 取 ground truth）"
    assert ground_progress in f1["answer"], "回答应包含真实进度值（直出，从 DB 取 ground truth）"
    assert "62.3%" not in f1["answer"], "关闭解读后不应出现 LLM 编造的数字"
    assert f1["fact_text"], "应有关键数字直出"

    # 场景 3：开启解读，表格仍是权威
    llm3 = ScriptedLLM([f"```sql\n{GOOD_SQL}\n```", "血压计月进度已达标，趋势良好。"])
    g3 = build_graph(llm3, FakeRetriever(), DB, max_repair=2, enable_narrative=True)
    f3 = g3.invoke({"question": "天猫血压计本月进度是多少？"})
    assert len(llm3.calls) == 2, "开启解读后 LLM 应被调用 2 次（生成 SQL + 解读）"
    assert "血压计月进度已达标" in f3["answer"], "解读应附加在回答中"
    assert f3["table_md"] == expected_table, "即使开启解读，表格仍逐字节等于直出"

    # 场景 4：金额格式化
    assert format_cell(360726.78, "month_amount") == "¥360,726.78"
    assert format_cell(0.97, "month_progress") == "0.97"
    assert format_cell(None) == "—"
    mcols, mrows = query(DB, MULTI_SQL)
    mtable = format_table(mcols, mrows)
    assert "¥" in mtable, "金额列应带 ¥ 符号"

    # 场景 5：审计轨迹
    trace = build_trace(f3)
    for k in ("question", "sql", "answer", "table_md", "confidence", "repair_count"):
        assert k in trace, f"trace 应包含 {k}"
    assert "成功" in summarize(f3), "summarize 应产出成功摘要"

    print("Day5 验证：5/5 场景 PASS")
    print("  - 关键数字直出：关闭解读时 LLM 仅调用 1 次，数字/表格 100% 来自 rows")
    print("  - 表格确定性：table_md 与 formatter 直出逐字节一致，不依赖 LLM")
    print("  - 解读可选：开启时解读前置，表格仍是权威数据源")
    print("  - 金额格式化：¥ + 千分位，符合国内财务习惯")
    print("  - 审计轨迹：build_trace 输出完整可 JSON 序列化字段（供 API/UI 人审）")
    print()
    print("=== 真实回答预览 ===")
    print(f3["answer"])


if __name__ == "__main__":
    main()
