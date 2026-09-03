"""结果合理性检查 —— 「防 GG」第五道防线。

SQL 执行成功 ≠ 结果正确。这里对返回结果做二次核验：

  1. 列缺失（columns 为空）→ FAIL，折算成校验失败走修复回路
     —— 通常是 SQL 结构写错（如 SELECT 了空列表 / 视图解析失败）。
  2. 空结果（rows 为空）→ 不阻断，但通过 reason 标记出来，
     让 answer 层直接返回「无数据」，而不是把空结果丢给 LLM 编数字。
  3. NaN / Inf / 行数触顶 → 告警级（warnings），附在最终回答里提示用户。

设计原则（面试可讲）：检查的强度要匹配风险的强度——
  列缺失会直接产出「错答案」→ 硬阻断；
  空结果是「没数据」而非「错数据」→ 软返回，但切断 LLM 脑补的通道。
"""
from __future__ import annotations

import math
from typing import List, Tuple

PASS = "pass"
FAIL = "fail"


def check_result(columns, rows, row_limit: int = 200
                 ) -> Tuple[str, str, List[str]]:
    """返回 (status, reason, warnings)。status ∈ {PASS, FAIL}。

    - PASS：结果可用（含空结果——由 reason 提示 answer 层安全处理）
    - FAIL：结果不可用，需走修复回路
    """
    warnings: List[str] = []

    # 检查点 1：列缺失（硬阻断）
    if columns is None or len(columns) == 0:
        return FAIL, "查询未返回任何列（SQL 结构可能有误）", warnings

    # 检查点 2：空结果（软返回，交给 answer 层安全作答）
    if not rows or len(rows) == 0:
        return PASS, "查询结果为空", ["结果为空"]

    # 检查点 3：非数值结果（告警级）
    for r in rows:
        for v in r:
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                warnings.append(f"检测到非数值结果 {v}，请核对指标口径")

    # 检查点 4：行数触顶（告警级，结果可能被截断）
    if len(rows) >= row_limit:
        warnings.append(f"返回行数达到上限 {row_limit}，结果可能被截断")

    return PASS, "OK", warnings
