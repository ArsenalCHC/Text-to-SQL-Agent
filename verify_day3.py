"""Day 3 验证：无 GPU / 无 Milvus / 无 Ollama 的整图离线验证。

三个场景：
  1. 正常链路：假 LLM 直接吐正确 SQL → 校验通过 → 真库执行 → 有数字返回
  2. 自修复链路：假 LLM 先吐 DROP（被校验拦截）→ 收到失败原因后吐正确 SQL → 成功
  3. 熔断链路：假 LLM 永远吐坏 SQL → 重试 max_repair 次后致歉退出，不死循环

运行：python verify_day3.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent.graph import build_graph

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ecommerce_daily.db")
GOOD_SQL = ("SELECT date, month_progress FROM v_category_daily "
            "WHERE platform='天猫' AND category='血压计' ORDER BY date DESC LIMIT 1;")
BAD_SQL = "DROP TABLE daily_metrics;"


class FakeRetriever:
    """模拟 Milvus 混合检索返回的上下文。"""
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
    """按剧本依次返回回复，记录收到的消息供断言。"""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0) if self.replies else self.replies and "" or "```sql\nSELECT 1;\n```"


def run_case(title, llm_replies, expect_repair=None):
    llm = ScriptedLLM(llm_replies)
    graph = build_graph(llm, FakeRetriever(), DB, max_repair=2)
    final = graph.invoke({"question": "天猫血压计本月进度是多少？"})
    print(f"=== {title} ===")
    print(f"  sql        : {final.get('sql', '')[:80]}...")
    print(f"  校验       : ok={final.get('validation_ok')} reason={final.get('validation_reason')}")
    print(f"  修复次数   : {final.get('repair_count', 0)}")
    print(f"  行数       : {len(final.get('rows') or [])}  列: {final.get('columns')}")
    answer = (final.get('answer') or '')[:120]
    print(f"  answer预览 : {answer}")
    print()
    return final


def main():
    # 场景 1：一次成功
    f1 = run_case("场景1 正常链路", [f"```sql\n{GOOD_SQL}\n```", "天猫血压计最新月进度为 62.3%，达到月目标六成以上。"])
    assert f1["validation_ok"] is True, "场景1 应校验通过"
    assert len(f1["rows"]) == 1, "场景1 应返回 1 行"
    assert f1.get("repair_count", 0) == 0, "场景1 不应有修复"

    # 场景 2：先坏后好（自修复）
    f2 = run_case(
        "场景2 自修复链路",
        [
            f"```sql\n{BAD_SQL}\n```",                                  # 第1次：坏 SQL 被拦截
            f"```sql\n{GOOD_SQL}\n```",                                  # 修复：正确 SQL
            "修复后结果：天猫血压计最新月进度为 62.3%。",                    # 作答
        ],
    )
    assert f2["validation_ok"] is True, "场景2 修复后应通过"
    assert f2.get("repair_count") == 1, "场景2 应恰好修复 1 次"
    assert len(f2["rows"]) == 1, "场景2 应返回 1 行"

    # 场景 3：永远坏 → 熔断
    f3 = run_case("场景3 熔断链路", [f"```sql\n{BAD_SQL}\n```"] * 10)
    assert f3.get("validation_ok") is False, "场景3 最终应失败"
    assert f3.get("repair_count") == 2, "场景3 应恰好重试 2 次后熔断（不死循环）"
    assert "未能生成合规 SQL" in f3["answer"], "场景3 应致歉退出"

    print("Day3 验证：3/3 场景 PASS")
    print("  - 正常链路：检索→生成→校验→执行→作答 全通")
    print("  - 自修复链路：坏 SQL 被拦截后带失败原因重生成，1 次修复成功")
    print("  - 熔断链路：重试上限生效，不死循环烧 GPU")


if __name__ == "__main__":
    main()
