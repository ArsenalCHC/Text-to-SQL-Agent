"""SQL 静态校验器 —— 「防 GG」第三道防线（仅 SELECT / 白名单 / 禁危险操作）。

生成 SQL 真正执行前必过此关：
  1. 只允许单条 SELECT（可带 EXPLAIN 前缀做预演）
  2. 禁止多语句（防注入 / 链式破坏）
  3. 禁止 DDL/DML/危险关键字（DROP/DELETE/UPDATE/INSERT/...）
  4. 表名必须在白名单（杜绝越权查别的表）
  5. 列名白名单（告警级，不阻断，给业务核对提示）
"""
import re

FORBIDDEN_KEYWORDS = [
    "drop", "delete", "update", "insert", "alter", "create", "truncate",
    "merge", "grant", "revoke", "exec", "execute", "attach", "pragma", "replace",
]

# SELECT 列表中出现的这些词视为函数 / 关键字，不做列白名单检查
_SKIP_COL_TOKENS = {
    "SUM", "AVG", "COUNT", "MIN", "MAX", "AS", "DISTINCT", "CASE", "WHEN",
    "THEN", "ELSE", "END", "AND", "OR",
}


class SQLValidator:
    def __init__(self, allowed_tables, allowed_columns):
        self.allowed_tables = set(allowed_tables)
        self.allowed_columns = set(allowed_columns)

    def validate(self, sql):
        """返回 (ok: bool, reason: str, warnings: list)。"""
        warnings = []
        if not sql or not sql.strip():
            return False, "SQL 为空", warnings
        s = sql.strip()
        if s.endswith(";"):
            s = s[:-1]
        if ";" in s:  # 多语句
            return False, "禁止多条语句（防链式破坏 / 注入）", warnings
        low = s.lower()
        explain = low.startswith("explain")
        if explain:
            low = low[7:].strip()
        if not low.startswith("select"):
            return False, "仅允许 SELECT 查询（只读）", warnings
        for kw in FORBIDDEN_KEYWORDS:
            if re.search(r"\b" + kw + r"\b", low):
                return False, f"禁止关键字: {kw.upper()}", warnings
        tables = re.findall(r"(?:from|join)\s+([a-zA-Z_][\w]*)", low)
        for t in tables:
            if t not in self.allowed_tables:
                return False, f"非法表: {t}（不在白名单 {sorted(self.allowed_tables)}）", warnings
        # 列白名单（告警级）
        m = re.search(r"select\s+(.*?)\s+from", low, re.DOTALL)
        if m:
            for c in re.findall(r"([a-zA-Z_][\w]*)\s*", m.group(1)):
                if not c:
                    continue
                if c.upper() in _SKIP_COL_TOKENS:
                    continue
                if c not in self.allowed_columns and c not in self.allowed_tables:
                    warnings.append(f"列 {c} 不在白名单（请确认是否拼错 / 越权）")
        return True, "OK" + (" (explain)" if explain else ""), warnings
