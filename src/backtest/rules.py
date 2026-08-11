# -*- coding: utf-8 -*-
"""A股交易规则（移植 QuantBacktest.engine.market_rules 逻辑）。

- 涨跌停：主板 ±10%，科创/创业板 ±20%，北交 ±30%
- 停牌：tradestatus=0 或停牌时价格缺失
- T+1：当日买入次日可卖（在 runner 中用 available 跟踪）
"""
from __future__ import annotations


def limit_ratio(code: str) -> float:
    """个股涨跌停幅度。"""
    code = str(code)
    if code.startswith(("688", "689", "300", "301")):
        return 0.20  # 科创/创业板
    if code.startswith(("4", "8", "92")):
        return 0.30  # 北交
    return 0.10  # 主板


def is_limit_up(close: float, prev_close: float, code: str, tol: float = 1e-4) -> bool:
    """判定当日是否涨停（或一字涨停）。"""
    if prev_close <= 0:
        return False
    return close >= prev_close * (1 + limit_ratio(code) - tol)


def is_limit_down(close: float, prev_close: float, code: str, tol: float = 1e-4) -> bool:
    if prev_close <= 0:
        return False
    return close <= prev_close * (1 - limit_ratio(code) + tol)


def is_tradable(row, code: str, side: str) -> bool:
    """判定股票当日是否可交易（buy:涨停不可买；sell:跌停不可卖；停牌不可）。
    row 应含 close/prev_close/tradestatus 等。
    """
    if row.get("tradestatus") in (0, None):
        return False
    close = row.get("close", 0)
    prev = row.get("prev_close", 0)
    if side == "buy" and is_limit_up(close, prev, code):
        return False
    if side == "sell" and is_limit_down(close, prev, code):
        return False
    return True