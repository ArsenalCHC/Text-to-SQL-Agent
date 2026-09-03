"""模拟 6 个电商日报接口返回的原始 JSON（按各平台原生字段名）。

作用：无需真实接口凭证即可端到端演示 ETL 归一化。
真实环境把 config.mock 设为 false，sync.py 会改走 HTTP 拉取。
"""
import random
import itertools
from datetime import date, timedelta

# 维度字段词表（用于生成类目 / 店铺组合）
VOCAB = {
    "product_line": ["呼吸治疗", "家用检测", "医疗影像", "护理耗材"],
    "category": ["血压计", "制氧机", "血糖仪", "雾化器", "轮椅"],
    "store": ["鱼跃官方旗舰店", "鱼跃医疗器械旗舰店", "鱼跃健康自营店"],
    "store_type": ["自营", "POP"],
}

# 指标基准（模拟真实量级，单位：元）
_METRIC_DEFS = {
    "daily_amount": ("day_base", 1.0),
    "daily_qty": ("day_base", 1 / 140.0),
    "month_amount": ("month_base", 1.0),
    "month_qty": ("month_base", 1 / 140.0),
    "year_amount": ("year_base", 1.0),
    "year_qty": ("year_base", 1 / 140.0),
    "month_target": ("m_target", 1.0),
    "year_target": ("y_target", 1.0),
    "month_progress": ("month_base/m_target", 1.0),
    "year_progress": ("year_base/y_target", 1.0),
}


def _combos(dim_fields):
    """根据 source 含哪些维度字段，生成有限的维度组合。"""
    if not dim_fields:
        return [{}]
    keys = list(dim_fields.keys())
    value_lists = [VOCAB[k] for k in keys]
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*value_lists)]
    return combos[:6]  # 控制规模，避免笛卡尔爆炸


def generate_source(source, start, end):
    """按 source 的 field_map 原生字段名生成模拟行。"""
    fmap = source["field_map"]
    rev = {v: k for k, v in fmap.items()}          # 统一列 -> 原生字段名（如 date -> '日期'）
    dim_fields = {v: k for k, v in fmap.items() if v in VOCAB}  # 统一维度 -> 原生名
    native_metric_keys = [k for k, v in fmap.items()
                          if v not in ("date",) and v not in VOCAB]
    rows = []
    d = start
    while d <= end:
        for combo in _combos(dim_fields):
            day_base = random.uniform(5000, 50000)
            month_base = day_base * random.uniform(20, 28)
            year_base = month_base * random.uniform(8, 11)
            m_target = month_base * random.uniform(0.9, 1.3)
            y_target = year_base * random.uniform(0.8, 1.2)
            ctx = {
                "day_base": day_base, "month_base": month_base,
                "year_base": year_base, "m_target": m_target, "y_target": y_target,
            }
            row = {rev["date"]: d.isoformat()}
            for unified_dim, native_key in dim_fields.items():
                row[native_key] = combo[unified_dim]
            for nk in native_metric_keys:
                unified = fmap[nk]
                if unified in _METRIC_DEFS:
                    expr, scale = _METRIC_DEFS[unified]
                    if "/" in expr:
                        a, b = expr.split("/")
                        val = ctx[a] / ctx[b]
                    else:
                        val = ctx[expr]
                    row[nk] = round(val * scale, 2)
            rows.append(row)
        d += timedelta(days=1)
    return rows


def generate(sources, start, end):
    return {s["name"]: generate_source(s, start, end) for s in sources}
