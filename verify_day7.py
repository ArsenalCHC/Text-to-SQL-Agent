"""Day 7 验证：Streamlit 前端离线校验（模块可导入 + Demo 图可端到端跑通）。

说明：Streamlit 界面渲染需在服务器上 `streamlit run` 才能可视化；
本机做两层离线校验：
  1. 模块可导入（streamlit 已装，导入不触发 main()）
  2. Demo 图（脚本化 LLM/检索器）能端到端 produce 带真实数据的回答

运行：python verify_day7.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ecommerce_daily.db")

from src.db import query  # noqa: E402
from src.formatter import format_cell  # noqa: E402


def main():
    # 1) 模块可导入（streamlit 导入 + 顶层类/函数定义，不触发 main()）
    from src.ui import app as ui_app
    assert hasattr(ui_app, "main"), "app 应有 main()"
    assert hasattr(ui_app, "render_answer"), "app 应有 render_answer()"
    assert hasattr(ui_app, "get_graph"), "app 应有 get_graph()"
    assert hasattr(ui_app, "_build_demo_graph"), "app 应有 _build_demo_graph()"

    # 2) Demo 图端到端跑通
    graph = ui_app._build_demo_graph(DB)
    final = graph.invoke({"question": "天猫血压计本月进度是多少？（数据时间范围：2026-08-22 ~ 2026-08-28）"})
    assert final["validation_ok"] is True, "Demo 图应校验通过"
    assert "month_progress" in final.get("table_md", ""), "表格应含真实列"
    _cols, _rows = query(DB, ui_app.DEMO_SQL)
    _ground = format_cell(_rows[0][1], _cols[1])
    assert _ground in final.get("table_md", ""), "表格应含真实数字（直出，从 DB 取 ground truth）"
    assert final.get("answer"), "应有回答"

    # 3) 模拟 render_answer 所需的字段完整性（trace 字段都在）
    for k in ("question", "answer", "sql", "table_md", "confidence", "repair_count",
              "validation_ok", "validation_reason", "warnings", "result_warnings"):
        assert k in final or final.get(k) is not None, f"render_answer 依赖字段 {k} 应可用"

    print("Day7 验证：3/3 场景 PASS")
    print("  - 模块可导入：streamlit 导入 + 函数定义齐全，不触发 main()")
    print("  - Demo 图端到端：脚本化 LLM/检索器 produce 带真实数据的回答")
    print("  - render_answer 字段完整性：审计轨迹字段齐全")
    print()
    print("=== Demo 图回答预览 ===")
    print(final["answer"])


if __name__ == "__main__":
    main()
