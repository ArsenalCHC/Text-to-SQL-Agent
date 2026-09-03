"""评测脚本 —— 用 eval/gold_set.json 对问数 Agent 做端到端评测。

后端可切换：
  python eval/run_eval.py                    # mock：脚本化 LLM 直接回填 gold SQL（离线 100% 基线）
  python eval/run_eval.py --backend ollama   # 真 LLM（服务器），测真实生成准确率

指标：
  exact_match  生成 SQL 与 gold SQL 归一化后完全一致的比例（结构正确性）
  exec_success 生成 SQL 通过校验+执行的比例（能否真正跑通）
  non_empty    结果非空的比例（能否查到数据）
  avg_repair   平均自修复次数（越低越好，反映一次成对率）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_DB = os.path.join(ROOT, "data", "ecommerce_daily.db")
DEFAULT_GOLD = os.path.join(ROOT, "eval", "gold_set.json")


def normalize(sql: str) -> str:
    """归一化：小写 + 压缩空白 + 去尾分号，用于结构比较。"""
    s = re.sub(r"\s+", " ", (sql or "").strip().lower())
    return s.rstrip(";").rstrip()


class _Retriever:
    """评测用假检索器：评测只关心「生成 SQL 是否正确」，不依赖 Milvus。"""

    def build_context(self, question: str) -> str:
        return ("## 指标口径\n- month_progress/year_progress/month_amount/month_qty/daily_amount 已物化，直接 SELECT\n"
                "## 业务术语\n- 血压计 -> category='血压计'，天猫 -> platform='天猫'，京东 -> platform='京东'\n")


class _GoldLLM:
    """mock 后端：直接回填 gold SQL，用于验证 harness 本身（应得 100% 基线）。"""

    def __init__(self, sql: str):
        self.sql = sql
        self.calls = []

    def __call__(self, messages):
        self.calls.append(messages)
        last = messages[-1]["content"]
        if "查询结果" in last or "解读" in last:
            return "（评测）结果如上表。"
        return f"```sql\n{self.sql}\n```"


def _build_ollama_llm():
    from src.llm import OllamaLLM
    return OllamaLLM.from_config()


def evaluate(db_path: str = DEFAULT_DB, gold_path: str = DEFAULT_GOLD, backend: str = "mock"):
    from src.agent.graph import build_graph
    from src.presenter import summarize

    cases = json.load(open(gold_path, encoding="utf-8"))
    results = []
    for c in cases:
        llm = _GoldLLM(c["sql"]) if backend == "mock" else _build_ollama_llm()
        graph = build_graph(llm, _Retriever(), db_path, max_repair=2, enable_narrative=False)
        final = graph.invoke({"question": c["question"]})
        results.append({
            "id": c["id"],
            "question": c["question"],
            "exact_match": normalize(final.get("sql")) == normalize(c["sql"]),
            "exec_success": final.get("validation_ok") is True,
            "non_empty": len(final.get("rows") or []) > 0,
            "repair_count": final.get("repair_count", 0),
            "summary": summarize(final),
        })

    n = len(results)
    agg = {
        "backend": backend,
        "total": n,
        "exact_match": sum(r["exact_match"] for r in results),
        "exec_success": sum(r["exec_success"] for r in results),
        "non_empty": sum(r["non_empty"] for r in results),
        "avg_repair": round(sum(r["repair_count"] for r in results) / n, 3) if n else 0,
    }
    return agg, results


def main():
    parser = argparse.ArgumentParser(description="智能问数评测")
    parser.add_argument("--backend", default="mock", choices=["mock", "ollama"])
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--gold", default=DEFAULT_GOLD)
    parser.add_argument("--out", default=None, help="可选：把结果写为 JSON 报告")
    args = parser.parse_args()

    agg, results = evaluate(args.db, args.gold, args.backend)

    print(f"=== 评测结果（backend={agg['backend']}，共 {agg['total']} 题） ===")
    print(f"  SQL 结构一致（exact_match）: {agg['exact_match']}/{agg['total']}")
    print(f"  校验+执行成功（exec_success）: {agg['exec_success']}/{agg['total']}")
    print(f"  结果非空（non_empty）: {agg['non_empty']}/{agg['total']}")
    print(f"  平均修复次数: {agg['avg_repair']}")
    print()
    for r in results:
        flag = "✅" if r["exact_match"] else "❌"
        print(f"  {flag} [{r['id']}] {r['question']}  ->  {r['summary']}")

    if args.out:
        json.dump({"agg": agg, "results": results}, open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"\n报告已写入 {args.out}")


if __name__ == "__main__":
    main()
