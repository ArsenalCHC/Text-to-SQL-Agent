"""只读查询执行器（支持 SQLite 与 ClickHouse 两种后端）。

安全要点：
  - SQLite 以 URI 只读模式打开（mode=ro），就算 SQL 校验被绕过也写不进去
  - 行数上限保护（row_limit），防止全表扫描拖垮服务
  - db 参数既可以是 SQLite 文件路径（向后兼容），也可以是 Database 实例（生产 ClickHouse）
"""
from __future__ import annotations

import sqlite3
from typing import List, Tuple

from src.database import Database  # noqa: E402  仅用于 isinstance 判断

DEFAULT_DB = None  # 由调用方注入


def query(db, sql: str, row_limit: int = 200
          ) -> Tuple[List[str], List[tuple]]:
    """执行只读 SELECT，返回 (columns, rows)。异常向上抛（由节点捕获转错误态）。

    db 传 Database 实例时走对应后端；传字符串路径时走 SQLite（向后兼容）。
    """
    if isinstance(db, Database):
        return db.query(sql, row_limit)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(row_limit)
        return columns, [tuple(r) for r in rows]
    finally:
        conn.close()


def explain(db, sql: str) -> str:
    """EXPLAIN 预演 —— 「防 GG」第四道防线（编译级检查）。

    只让数据库编译这条 SQL、产出执行计划，但不真正执行。
    好处：静态校验（正则白名单）抓不到的问题——比如引用不存在的列、
    视图里没有的字段、括号不配对等——在这里会在 prepare 阶段直接抛错，
    而这些错误在真正执行前就能被拦截，且不会产生任何副作用。

    异常向上抛，由 validate 节点捕获后折算成 validation_ok=False 走修复回路。
    """
    if isinstance(db, Database):
        return db.explain(sql)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        plan = conn.execute(f"EXPLAIN {sql}").fetchall()
        return f"预演通过（{len(plan)} 条执行计划）"
    finally:
        conn.close()
