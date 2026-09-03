"""Day 4 验证：EXPLAIN 预演 + 结果合理性检查 + execute 纳入修复回路 + 置信度联动。

四个场景：
  1. EXPLAIN 预演拦截：引用不存在列的 SQL（静态白名单放行、编译报错）→ 修复 → 成功
  2. 空结果安全直出：极严 WHERE → 空结果 → answer 直出「无数据」，LLM 不被调来作答
  3. 执行报错走修复：首次执行抛错 → 走 repair → 第二次成功
  4. 置信度联动：修复 1 次后 answer 含「建议人工核对」

运行：python verify_day4.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent.graph import build_graph
from src.agent.nodes import AgentNodes

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ecommerce_daily.db")
GOOD_SQL = ("SELECT date, month_progress FROM v_category_daily "
            "WHERE platform='天猫' AND category='血压计' ORDER BY date DESC LIMIT 1;")
# 静态白名单放行（列检查是告警级），但 EXPLAIN 会在编译阶段报「不存在的列」
BAD_COLUMN_SQL = "SELECT nonexistent_col FROM daily_metrics;"
# 极严 WHERE：语法/编译都通过，但执行返回 0 行
EMPTY_SQL = ("SELECT date, month_progress FROM v_category_daily "
             "WHERE platform='天猫' AND category='不存在的品类';")


class FakeRetriever:
    def build_context(self, question: str) -> str:
        return (
            "## 指标口径（已物化，直接 SELECT）\n"
            "- 指标 月进度（字段 month_progress）：月金额 / 月目标。已物化到字段，直接 SELECT。\n"
            "## 业务术语 -> 字段映射\n"
            "- 业务术语「血压计」对应条件：category = '血压计'。\n"
            "- 业务术语「天猫」对应条件：platform = '天猫'。\n"
            "## 相似问法的正确 SQL 样例\n"
            f"- 问法：天猫血压计本月进度是多少？\n- SQL：{GOOD_SQL}\n"
        )


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0) if self.replies else "```sql\nSELECT 1;\n```"


def run_case(title, llm_replies, db=DB):
    llm = ScriptedLLM(llm_replies)
    graph = build_graph(llm, FakeRetriever(), db, max_repair=2)
    final = graph.invoke({"question": "天猫血压计本月进度是多少？"})
    print(f"=== {title} ===")
    print(f"  sql        : {final.get('sql', '')[:80]}...")
    print(f"  校验       : ok={final.get('validation_ok')} reason={final.get('validation_reason')}")
    print(f"  修复次数   : {final.get('repair_count', 0)}  置信度: {final.get('confidence')}")
    print(f"  行数       : {len(final.get('rows') or [])}  列: {final.get('columns')}")
    print(f"  LLM 调用   : {len(llm.calls)} 次")
    print(f"  answer预览 : {(final.get('answer') or '')[:150]}")
    print()
    return final, llm


def main():
    # 场景 1：EXPLAIN 预演拦截不存在的列 → 修复 → 成功
    f1, llm1 = run_case(
        "场景1 EXPLAIN 预演拦截",
        [f"```sql\n{BAD_COLUMN_SQL}\n```", f"```sql\n{GOOD_SQL}\n```", "天猫血压计最新月进度已达标。"],
    )
    assert f1["validation_ok"] is True, "场景1 修复后应通过"
    assert f1.get("repair_count") == 1, "场景1 应恰好修复 1 次"
    assert "预演通过" in f1.get("validation_reason", ""), "场景1 修复成功后 reason 应含预演通过"
    assert "nonexistent_col" in llm1.calls[1][-1]["content"], "场景1 修复提示应回传失败原因"

    # 场景 2：空结果安全直出（LLM 不被调来作答）
    f2, llm2 = run_case(
        "场景2 空结果安全直出",
        [f"```sql\n{EMPTY_SQL}\n```"],  # 只有 1 条回复（生成 SQL），没有作答回复
    )
    assert f2["validation_ok"] is True, "场景2 空结果不应算失败"
    assert len(f2.get("rows") or []) == 0, "场景2 应返回 0 行"
    assert "查询结果为空" in f2["answer"], "场景2 应直出「查询结果为空」"
    assert len(llm2.calls) == 1, "场景2 LLM 只应被调用 1 次（生成 SQL），不调用来作答"

    # 场景 3：执行报错走修复（首次执行抛错 → repair → 第二次成功）
    import src.agent.nodes as nodes_mod
    orig_query = nodes_mod.query
    call_counter = [0]

    def flaky(db_path, sql, row_limit=200):
        call_counter[0] += 1
        if call_counter[0] == 1:
            raise RuntimeError("模拟执行期报错")
        return orig_query(db_path, sql, row_limit)

    nodes_mod.query = flaky
    try:
        f3, llm3 = run_case(
            "场景3 执行报错走修复",
            [f"```sql\n{GOOD_SQL}\n```", f"```sql\n{GOOD_SQL}\n```", "修复后结果正确。"],
        )
    finally:
        nodes_mod.query = orig_query
    assert f3["validation_ok"] is True, "场景3 修复后应成功"
    assert f3.get("repair_count") == 1, "场景3 应恰好修复 1 次（执行报错也走修复）"
    assert "执行报错" in llm3.calls[1][-1]["content"], "场景3 修复提示应回传执行报错原因"

    # 场景 4：置信度联动（单元级 + 整图级）
    assert AgentNodes._confidence(0) == 1.0
    assert abs(AgentNodes._confidence(1) - 0.6) < 1e-9
    assert abs(AgentNodes._confidence(2) - 0.2) < 1e-9
    assert "建议人工核对" in f1["answer"], "场景1 修复 1 次后 answer 应提示人工核对"

    print("Day4 验证：4/4 场景 PASS")
    print("  - EXPLAIN 预演：静态白名单放行的「不存在的列」被编译级检查拦截")
    print("  - 空结果直出：空结果不交给 LLM 编数字，直接安全返回")
    print("  - execute 走修复：执行报错不再被固定边吞掉，走同一条自修复回路")
    print("  - 置信度联动：修复越多置信度越低，回答里提示人工核对")


if __name__ == "__main__":
    main()
