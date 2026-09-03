"""可插拔数据库后端：SQLite（demo/离线）与 ClickHouse（生产）统一抽象。

设计要点（面试可讲）：
  - 把「建表 / 只读查询 / EXPLAIN 预演 / 范围删除 / 批量写入」收敛到统一接口，
    demo 用 SQLite 零依赖跑通全链路，生产切 ClickHouse 只改一处 backend 配置。
  - 调用方（etl.sync 写库、agent.nodes 读库）只面对 Database 接口，不关心底层引擎。
  - ClickHouse 侧：MergeTree + 按月分区，重刷 = ALTER TABLE DELETE（mutations_sync 同步）+ 批量 INSERT。

为什么抽象这一层：SQLite 是单机嵌入式（零运维、可复现），适合面试演示；
ClickHouse 是列存 OLAP（按 date 分区、聚合快），适合生产 NL2SQL。
两者查询都是「SELECT 聚合 + 日期范围 + 维度过滤」，接口天然一致，故可插拔。
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from typing import List, Tuple

from etl.schema import SCHEMA_SQL, UNIFIED_COLUMNS  # noqa: E402

# 统一列名顺序（写库 insert 时对齐）
_COLUMNS = list(UNIFIED_COLUMNS)


class Database:
    """数据库后端抽象基类。子类实现 6 个方法。"""

    backend = "base"

    def init_schema(self) -> None:
        raise NotImplementedError

    def query(self, sql: str, row_limit: int = 200) -> Tuple[List[str], List[tuple]]:
        raise NotImplementedError

    def explain(self, sql: str) -> str:
        raise NotImplementedError

    def delete_range(self, start: date, end: date, platform: str, dimension_type: str) -> None:
        raise NotImplementedError

    def insert_rows(self, columns: List[str], rows: List[list]) -> None:
        raise NotImplementedError

    def ping(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SQLiteDatabase(Database):
    """SQLite 后端：demo / 离线 / 单测。复用 etl.schema 的建表 SQL。"""

    backend = "sqlite"

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None

    def init_schema(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def delete_range(self, start: date, end: date, platform: str, dimension_type: str) -> None:
        self._conn.execute(
            "DELETE FROM daily_metrics WHERE date BETWEEN ? AND ? AND platform=? AND dimension_type=?",
            (start.isoformat(), end.isoformat(), platform, dimension_type))
        self._conn.commit()

    def insert_rows(self, columns: List[str], rows: List[list]) -> None:
        placeholders = ",".join("?" for _ in columns)
        sql = f"INSERT INTO daily_metrics ({','.join(columns)}) VALUES ({placeholders})"
        self._conn.executemany(sql, [tuple(r) for r in rows])
        self._conn.commit()

    def query(self, sql: str, row_limit: int = 200) -> Tuple[List[str], List[tuple]]:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            cur = conn.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = [tuple(r) for r in cur.fetchmany(row_limit)]
            return columns, rows
        finally:
            conn.close()

    def explain(self, sql: str) -> str:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            plan = conn.execute(f"EXPLAIN {sql}").fetchall()
            return f"预演通过（{len(plan)} 条执行计划）"
        finally:
            conn.close()

    def ping(self) -> bool:
        return os.path.exists(self.db_path)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ClickHouse 建表 DDL：列存 + MergeTree，按 date 月分区，排序键用非 Nullable 列（避免 Nullable 排序键的坑）
CH_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    date            Date,
    platform        String,
    dimension_type  String,
    product_line    Nullable(String),
    category        Nullable(String),
    store           Nullable(String),
    store_type      Nullable(String),
    daily_amount    Nullable(Float64),
    daily_qty       Nullable(Float64),
    month_amount    Nullable(Float64),
    month_qty       Nullable(Float64),
    year_amount     Nullable(Float64),
    year_qty        Nullable(Float64),
    month_target    Nullable(Float64),
    year_target     Nullable(Float64),
    month_progress  Nullable(Float64),
    year_progress   Nullable(Float64)
) ENGINE = MergeTree
PARTITION BY toYYYYMM(date)
ORDER BY (date, platform, dimension_type)
"""

CH_VIEWS_SQL = """
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


def _coerce_value(v):
    """把 ClickHouse 返回的原生类型归一化，和 SQLite 侧（字符串日期 + float 数值）保持一致。"""
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


class ClickHouseDatabase(Database):
    """ClickHouse 后端：生产。惰性 import / 惰性连接，demo 模式不触发 clickhouse-connect。"""

    backend = "clickhouse"

    def __init__(self, config: dict):
        self.config = config or {}
        self._client = None

    def _get_client(self):
        if self._client is None:
            import clickhouse_connect  # 惰性 import，SQLite 模式无需安装
            c = self.config
            self._client = clickhouse_connect.get_client(
                host=os.getenv("CLICKHOUSE_HOST", c.get("host", "127.0.0.1")),
                port=int(os.getenv("CLICKHOUSE_PORT", c.get("port", 8123))),
                username=os.getenv("CLICKHOUSE_USER", c.get("username", "default")),
                password=os.getenv("CLICKHOUSE_PASSWORD", c.get("password", "")),
                database=os.getenv("CLICKHOUSE_DB", c.get("database", "default")),
                secure=bool(c.get("secure", False)),
                connect_timeout=int(c.get("connect_timeout", 10)),
            )
        return self._client

    def init_schema(self) -> None:
        client = self._get_client()
        client.command(CH_TABLE_SQL)
        for stmt in _split_sql(CH_VIEWS_SQL):
            if stmt.strip():
                client.command(stmt)

    def delete_range(self, start: date, end: date, platform: str, dimension_type: str) -> None:
        client = self._get_client()
        # 同步等待 mutation 完成（mutations_sync=1），避免 INSERT 前旧数据未删干净
        client.command(
            "ALTER TABLE daily_metrics DELETE WHERE "
            f"date >= '{start.isoformat()}' AND date <= '{end.isoformat()}' "
            f"AND platform = '{platform}' AND dimension_type = '{dimension_type}'",
            settings={"mutations_sync": 1})

    def insert_rows(self, columns: List[str], rows: List[list]) -> None:
        if not rows:
            return
        client = self._get_client()
        client.insert("daily_metrics", rows, column_names=columns)

    def query(self, sql: str, row_limit: int = 200) -> Tuple[List[str], List[tuple]]:
        client = self._get_client()
        result = client.query(sql)
        columns = list(result.column_names)
        rows = [tuple(_coerce_value(v) for v in r) for r in result.result_rows[:row_limit]]
        return columns, rows

    def explain(self, sql: str) -> str:
        client = self._get_client()
        plan = client.query(f"EXPLAIN {sql}")
        n = len(plan.result_rows) if plan.result_rows else 0
        return f"预演通过（{n} 行执行计划）"

    def ping(self) -> bool:
        try:
            return bool(self._get_client().ping())
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None


def _split_sql(script: str) -> List[str]:
    """按分号切分多语句 DDL（朴素切分，视图脚本里无分号嵌套）。"""
    return [s for s in script.split(";") if s.strip()]


def load_clickhouse_config(path: str | None = None) -> dict:
    import yaml
    cfg_path = path or os.getenv(
        "CLICKHOUSE_CFG",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "config", "clickhouse.yaml"))
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("clickhouse", {})


def create_database(backend: str, db_path: str | None = None,
                    ch_config: dict | None = None) -> Database:
    """工厂：按 backend 返回对应后端实例。

    backend='sqlite'      -> SQLiteDatabase(db_path)
    backend='clickhouse'  -> ClickHouseDatabase(ch_config or load_clickhouse_config())
    """
    if backend == "clickhouse":
        return ClickHouseDatabase(ch_config if ch_config is not None else load_clickhouse_config())
    if backend == "sqlite":
        default = db_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ecommerce_daily.db")
        return SQLiteDatabase(db_path or default)
    raise ValueError(f"未知 backend: {backend}（可选 sqlite / clickhouse）")
