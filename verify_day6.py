"""Day 6 验证：FastAPI 服务离线测试（假图 + TestClient，不连真实 Ollama/Milvus）。

场景：
  1. /health 返回 db_readable + graph_ready
  2. /chat 返回完整审计轨迹（answer/sql/table_md/confidence/repair_count）
  3. /sql 返回生成的 SQL + 校验结果
  4. 坏问题（永远吐坏 SQL）也能正常返回错误轨迹，不抛 500

运行：python verify_day6.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient

from src.agent.graph import build_graph
from src.api.server import create_app

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ecommerce_daily.db")
GOOD_SQL = ("SELECT date, month_progress FROM v_category_daily "
            "WHERE platform='天猫' AND category='血压计' ORDER BY date DESC LIMIT 1;")
BAD_SQL = "DROP TABLE daily_metrics;"


class FakeRetriever:
    def build_context(self, question: str) -> str:
        return "## 指标口径\n- month_progress 已物化\n"


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0) if self.replies else "```sql\nSELECT 1;\n```"


def main():
    # 假图：正常回答 + 解读
    llm = ScriptedLLM([f"```sql\n{GOOD_SQL}\n```", "血压计月进度已达标。"])
    graph = build_graph(llm, FakeRetriever(), DB, max_repair=2, enable_narrative=True)
    app = create_app(graph, DB)
    client = TestClient(app)

    # 场景 1：/health
    r = client.get("/health")
    assert r.status_code == 200, "health 应 200"
    body = r.json()
    assert body["db_readable"] is True and body["graph_ready"] is True, "health 应就绪"

    # 场景 2：/chat 完整轨迹
    r = client.post("/chat", json={"question": "天猫血压计本月进度是多少？"})
    assert r.status_code == 200, "chat 应 200"
    t = r.json()
    for k in ("question", "answer", "sql", "table_md", "confidence", "repair_count", "validation_ok"):
        assert k in t, f"轨迹应含 {k}"
    assert "0.97" in t["table_md"] or "month_progress" in t["table_md"], "表格应含真实数据"
    assert t["validation_ok"] is True

    # 场景 3：/sql
    r = client.post("/sql", json={"question": "天猫血压计本月进度是多少？"})
    assert r.status_code == 200, "sql 应 200"
    s = r.json()
    assert s["validation_ok"] is True and "SELECT" in s["sql"].upper(), "/sql 应返回合法 SQL"

    # 场景 4：坏问题不抛 500（返回错误轨迹）
    llm_bad = ScriptedLLM([f"```sql\n{BAD_SQL}\n```"] * 10)
    graph_bad = build_graph(llm_bad, FakeRetriever(), DB, max_repair=2)
    client_bad = TestClient(create_app(graph_bad, DB))
    r = client_bad.post("/chat", json={"question": "随便问"})
    assert r.status_code == 200, "坏问题也应 200（错误在轨迹里，不在 HTTP 层）"
    tb = r.json()
    assert tb["validation_ok"] is False, "坏问题应校验失败"
    assert "未能生成合规 SQL" in tb["answer"], "坏问题应致歉"

    print("Day6 验证：4/4 场景 PASS")
    print("  - /health：DB 可读 + 图就绪")
    print("  - /chat：返回完整审计轨迹（answer/sql/table_md/confidence/repair_count）")
    print("  - /sql：返回生成的 SQL + 校验结果")
    print("  - 坏问题：错误体现在轨迹里，HTTP 层不抛 500")
    print()
    print("=== /chat 返回示例（截断） ===")
    print(f"  question : {t['question']}")
    print(f"  sql      : {t['sql'][:60]}...")
    print(f"  answer   : {t['answer'][:80]}...")


if __name__ == "__main__":
    main()
