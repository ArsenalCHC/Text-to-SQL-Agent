"""Day 8 验证：评测 harness 离线自检。

场景：
  1. mock 后端基线：10 题全部 exact_match + exec_success + non_empty（验证 harness 本身）
  2. normalize() 归一化边界：大小写/空白/尾分号
  3. 自修复可被评测捕获：mock LLM 先吐坏 SQL 再吐正确 SQL -> repair_count 被计入

运行：python verify_day8.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eval.run_eval import _GoldLLM, _Retriever, evaluate, normalize

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ecommerce_daily.db")
GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval", "gold_set.json")


def main():
    # 场景 1：mock 基线
    agg, results = evaluate(DB, GOLD, backend="mock")
    assert agg["exact_match"] == agg["total"], "mock 基线应 100% exact_match"
    assert agg["exec_success"] == agg["total"], "mock 基线应 100% exec_success"
    assert agg["non_empty"] == agg["total"], "mock 基线应 100% non_empty"

    # 场景 2：normalize 边界
    assert normalize("  SELECT date FROM t;  ") == "select date from t"
    assert normalize("select\na\nfrom t") == "select a from t"
    assert normalize(None) == ""

    # 场景 3：自修复被评测捕获（先坏后好 -> repair_count=1）
    from src.agent.graph import build_graph

    class FlakyLLM:
        def __init__(self, good_sql):
            self.good_sql = good_sql
            self.n = 0

        def __call__(self, messages):
            self.n += 1
            if self.n == 1:
                return "```sql\nDROP TABLE daily_metrics;\n```"
            return f"```sql\n{self.good_sql}\n```"

    good = "SELECT date, month_progress FROM v_category_daily WHERE platform='天猫' AND category='血压计' ORDER BY date DESC LIMIT 1;"
    graph = build_graph(FlakyLLM(good), _Retriever(), DB, max_repair=2, enable_narrative=False)
    final = graph.invoke({"question": "天猫血压计本月进度"})
    assert final["repair_count"] == 1, "先坏后好应恰好修复 1 次，且被 harness 捕获"

    print("Day8 验证：3/3 场景 PASS")
    print(f"  - mock 基线：{agg['total']} 题 exact_match/exec/non_empty 全 100%（harness 自检通过）")
    print("  - normalize：大小写/空白/尾分号归一化正确")
    print("  - 自修复可评测：repair_count 被计入评测指标")
    print()
    print("服务器上跑真 LLM 评测：python eval/run_eval.py --backend ollama")


if __name__ == "__main__":
    main()
