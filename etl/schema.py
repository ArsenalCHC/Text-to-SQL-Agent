"""建表 + 视图定义（统一事实表 daily_metrics）。

为什么建这张表：把 6 个长相各异的电商日报接口洗成一张结构稳定、字段统一的表，
Agent 永远只面对它，SQL 生成难度骤降，且能做精确聚合 / JOIN / 对比。
"""
import sqlite3
import os

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    platform TEXT NOT NULL,
    dimension_type TEXT NOT NULL,
    product_line TEXT,
    category TEXT,
    store TEXT,
    store_type TEXT,
    daily_amount REAL,
    daily_qty REAL,
    month_amount REAL,
    month_qty REAL,
    year_amount REAL,
    year_qty REAL,
    month_target REAL,
    year_target REAL,
    month_progress REAL,
    year_progress REAL
);
CREATE INDEX IF NOT EXISTS idx_dm_date ON daily_metrics(date);
CREATE INDEX IF NOT EXISTS idx_dm_platform ON daily_metrics(platform);
CREATE INDEX IF NOT EXISTS idx_dm_dim ON daily_metrics(dimension_type);

-- 常用视图：降低 Agent 检索 / 生成难度
CREATE VIEW IF NOT EXISTS v_category_daily AS
SELECT date, platform, product_line, category,
       daily_amount, daily_qty, month_amount, month_qty,
       year_amount, year_qty, month_target, year_target,
       month_progress, year_progress
FROM daily_metrics WHERE dimension_type = 'category';

CREATE VIEW IF NOT EXISTS v_store_daily AS
SELECT date, platform, store_type, store,
       daily_amount, month_amount, year_amount,
       month_target, year_target, month_progress, year_progress
FROM daily_metrics WHERE dimension_type = 'store';

CREATE VIEW IF NOT EXISTS v_platform_summary AS
SELECT date, platform,
       SUM(daily_amount) AS daily_amount,
       SUM(month_amount) AS month_amount,
       SUM(year_amount) AS year_amount,
       SUM(month_target) AS month_target,
       SUM(year_target) AS year_target
FROM daily_metrics GROUP BY date, platform;
"""

# 统一字段（供 SQL 校验器做列白名单）
UNIFIED_COLUMNS = [
    "date", "platform", "dimension_type", "product_line", "category",
    "store", "store_type", "daily_amount", "daily_qty", "month_amount",
    "month_qty", "year_amount", "year_qty", "month_target", "year_target",
    "month_progress", "year_progress",
]

# 白名单表（供 SQL 校验器使用）—— 只允许查这些，杜绝越权
ALLOWED_TABLES = ["daily_metrics", "v_category_daily", "v_store_daily", "v_platform_summary"]


def init_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
