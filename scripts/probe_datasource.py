"""探测真实数据源：逐接口拉第 1 页，打印连通性 / errCode / totalNum / 首行字段。

用途：跑 sync 前先确认服务器能访问内网网关、接口返回格式符合预期，
      避免直接 sync 把库 DELETE 掉却拉不到数据。

用法（默认拉最近 3 天，轻量）：
    python scripts/probe_datasource.py
指定日期范围（YYYY-MM-DD）：
    python scripts/probe_datasource.py 2026-08-01 2026-08-03
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etl.sync import load_config, _fetch_page  # noqa: E402


def main():
    args = sys.argv[1:]
    if len(args) >= 2:
        start_d = date.fromisoformat(args[0])
        end_d = date.fromisoformat(args[1])
    else:
        end_d = date.today()
        start_d = end_d - timedelta(days=3)

    config = load_config()
    print(f"mock={config.get('mock')}  探测日期 {start_d} ~ {end_d}\n")

    for s in config["sources"]:
        params = {"pageNum": 1, "pageSize": 1000}
        for p in s.get("params", []):
            if p == "start_date":
                params[p] = start_d.strftime("%Y%m%d")
            elif p == "end_date":
                params[p] = end_d.strftime("%Y%m%d")
        name = s["name"]
        try:
            resp = _fetch_page(s["url"], params)
            data = resp.get("data") or []
            print(f"[OK] {name}")
            print(f"     errCode={resp.get('errCode')}  message={resp.get('message')}  "
                  f"totalNum={resp.get('totalNum')}  pageSize={resp.get('pageSize')}  本页={len(data)}")
            if data:
                print(f"     首行字段: {sorted(data[0].keys())}")
                print(f"     首行值  : {data[0]}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {name} -> {e}")
        print()


if __name__ == "__main__":
    main()
