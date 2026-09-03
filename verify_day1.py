"""Day 1 验证脚本：跑通 ETL + 建表 + SQL 校验器。

运行：python verify_day1.py
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from etl.sync import sync, DB_PATH  # noqa: E402
from etl.schema import ALLOWED_TABLES, UNIFIED_COLUMNS  # noqa: E402
from src.sql_validator import SQLValidator  # noqa: E402

n = sync()
print(f"[ETL] 写入 {n} 行 -> {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cnt = conn.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0]
print(f"[DB] daily_metrics 总行数: {cnt}")
print("[DB] 样例(天猫/血压计 最近3天):")
for r in conn.execute(
    "SELECT date, platform, category, month_amount, month_progress "
    "FROM v_category_daily WHERE platform='天猫' AND category='血压计' "
    "ORDER BY date DESC LIMIT 3"
):
    print("   ", r)

v = SQLValidator(ALLOWED_TABLES, set(UNIFIED_COLUMNS))
tests = [
    ("SELECT month_progress FROM v_category_daily WHERE platform='天猫' AND category='血压计' LIMIT 1", True),
    ("DROP TABLE daily_metrics", False),
    ("SELECT * FROM secret_table", False),
    ("SELECT month_amount; DROP TABLE daily_metrics", False),
    ("UPDATE daily_metrics SET month_amount=0", False),
    ("SELECT SUM(month_amount) AS m FROM daily_metrics WHERE platform='京东'", True),
]
print("[VALIDATOR]")
for sql, expect_ok in tests:
    ok, reason, warns = v.validate(sql)
    flag = "PASS" if ok == expect_ok else "FAIL"
    print(f"   [{flag}] ok={ok} reason={reason} | {sql[:55]}")
    for w in warns:
        print(f"        warn: {w}")
conn.close()
print("[DONE] Day 1 核心链路验证完成")
