"""ETL：6 接口 -> 统一事实表 daily_metrics。

流程：HTTP 拉取原生 JSON -> 按 field_map 归一化 -> 增量写入数据库（SQLite / ClickHouse 可插拔）。
增量策略：DELETE 该日期范围 + 平台 + 维度，再 INSERT，避免重复拉取。

真实接口（config.mock=false）要点：
  - 日期参数格式 YYYYMMDD（如 start_date=20260821），库内 date 列仍存 ISO 格式
  - 返回结构 {data:[...], errCode:0, totalNum, pageSize, pageNum, rowCount, message}
  - 分页：pageNum 从 1 起、pageSize 固定 1000，翻页直到取满 totalNum
  - 金额字段可能返回字符串（"311.8"），归一化时统一转 float
"""
import os
import sys
import json
import urllib.request
import urllib.parse
from datetime import date, timedelta

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etl.schema import UNIFIED_COLUMNS  # noqa: E402
from etl import mock_data  # noqa: E402

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "datasources.yaml")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ecommerce_daily.db")

# 数值型统一列：归一化时把接口返回的字符串金额转成 float，避免存成 TEXT
NUMERIC_COLUMNS = {
    "daily_amount", "daily_qty", "month_amount", "month_qty",
    "year_amount", "year_qty", "month_target", "year_target",
    "month_progress", "year_progress",
}

PAGE_SIZE = 1000  # 与接口返回 pageSize 对齐
MAX_PAGES = 200   # 防死循环兜底


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _to_float(v):
    """字符串/数字 -> float；空值或非法值 -> None（SQL NULL）。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize(raw_rows, source):
    """原生 JSON -> 统一行（platform / dimension_type 由 source 决定）。"""
    fmap = source["field_map"]
    out = []
    for r in raw_rows:
        row = {col: None for col in UNIFIED_COLUMNS}
        row["platform"] = source["platform"]
        row["dimension_type"] = source["dimension_type"]
        for native_key, unified_col in fmap.items():
            if unified_col in row and native_key in r:
                row[unified_col] = r[native_key]
        # 数值列统一转 float
        for col in NUMERIC_COLUMNS:
            row[col] = _to_float(row[col])
        out.append(row)
    return out


def _fetch_page(url, params, timeout=15):
    """单页 GET，返回解析后的 dict；网络/JSON 错误直接抛给上层。"""
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_http(sources, start_d, end_d):
    """真实接口拉取：YYYYMMDD 日期参数 + 分页 + errCode 检查。单接口失败不影响其他。"""
    raw = {}
    for s in sources:
        name = s["name"]
        # 基础参数：start_date / end_date 用 YYYYMMDD；其他静态参数从 static_params 透传
        params = {}
        for p in s.get("params", []):
            if p == "start_date":
                params[p] = start_d.strftime("%Y%m%d")
            elif p == "end_date":
                params[p] = end_d.strftime("%Y%m%d")
        params.update(s.get("static_params", {}))
        rows = []
        page_num = 1
        total_num = None
        last_first = None
        try:
            while page_num <= MAX_PAGES:
                p = dict(params)
                p["pageNum"] = page_num
                p["pageSize"] = PAGE_SIZE
                resp = _fetch_page(s["url"], p)
                if resp.get("errCode") not in (0, None, "0"):
                    print(f"[WARN] {name} errCode={resp.get('errCode')} message={resp.get('message')}")
                    break
                data = resp.get("data") or []
                if not data:
                    break
                # 防死循环：接口若忽略 pageNum 参数，每页返回相同首页，检测到重复即停
                first_key = repr(data[0])
                if first_key == last_first:
                    print(f"[WARN] {name} 第 {page_num} 页与上页重复，疑似分页参数无效，停止翻页")
                    break
                last_first = first_key
                rows.extend(data)
                total_num = resp.get("totalNum") or resp.get("rowCount") or len(rows)
                if len(rows) >= int(total_num) or len(data) < PAGE_SIZE:
                    break
                page_num += 1
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {name} 拉取失败: {e}")
            rows = []
        raw[name] = rows
    return raw


def sync(db_path=DB_PATH, start=None, end=None, config=None, db=None, backend=None):
    """拉取 + 归一化 + 增量写库。

    - 默认 backend='sqlite'（向后兼容 python -m etl.sync 走本地 SQLite）
    - 生产：sync(backend='clickhouse', start=..., end=...) 走 ClickHouse（读 config/clickhouse.yaml）
    - 也可直接传入 db=Database 实例（完全自定义）
    """
    config = config or load_config()
    end_d = end or date.today()
    start_d = start or (end_d - timedelta(days=30))
    # 后端选择：显式 db 对象 > backend 参数 > 默认 SQLite
    if db is None:
        from src.database import create_database
        db = create_database(backend or "sqlite", db_path=db_path)
    db.init_schema()
    if config.get("mock"):
        raw = mock_data.generate(config["sources"], start_d, end_d)
    else:
        raw = _fetch_http(config["sources"], start_d, end_d)
    total = 0
    cols = list(UNIFIED_COLUMNS)
    for source in config["sources"]:
        rows = _normalize(raw.get(source["name"], []), source)
        db.delete_range(start_d, end_d, source["platform"], source["dimension_type"])
        db.insert_rows(cols, [[r[c] for c in cols] for r in rows])
        total += len(rows)
    db.close()
    return total


if __name__ == "__main__":
    n = sync()
    print(f"ETL 完成，写入 {n} 行 -> {os.path.abspath(DB_PATH)}")
