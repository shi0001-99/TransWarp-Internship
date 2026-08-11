# -*- coding: utf-8 -*-
"""六维打分体系（强对齐 TransAlpha 选股逻辑的历史 proxy 版）

镜像 TransAlpha 的打分权重与算法思路，但全部因子基于「历史可回放」数据：
  - 基本面 (40)：ROE/营收增速/现金流/负债 —— 用 PIT 对齐的财报 pubDate
  - 技术面 (40)：均线多头/量能趋势/换手/动量 —— 用历史K线
  - 资金/量能 (20)：有主力净流入用其方向，否则用换手 proxy 兜底
  - 情绪 proxy（附加，进报告）：市场热度近似

算法移植 TransAlpha data_fetcher 的 check_ma_alignment / check_volume_trend_3day。
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

# 买卖门槛（对齐 TransAlpha stock-scoring 文档）
FUND_BUY_THRESHOLD = 24   # 基本面 ≥ 24/40
TECH_BUY_THRESHOLD = 16   # 技术面 ≥ 16/40（宽池 proxy 略降，避免过度保守）
TOTAL_BUY_THRESHOLD = 50  # 综合 ≥ 50/100
TOP_N_DEFAULT = 5         # 每次再平衡选 N 只


# ─── 技术因子（移植 TransAlpha StockAnalyzer）─────────────────
def ma_alignment(history: pd.DataFrame) -> float:
    """均线多头排列得分 (0~100)，对齐 check_ma_alignment。"""
    if history is None or len(history) < 20:
        return 0.0
    closes = history["close"].dropna().values
    if len(closes) < 20:
        return 0.0
    ma5 = float(closes[-5:].mean())
    ma10 = float(closes[-10:].mean())
    ma20 = float(closes[-20:].mean())
    price = float(closes[-1])
    price_above_all = price > ma5 and price > ma10 and price > ma20
    if ma5 > ma10 > ma20 and price_above_all:
        return 100.0
    elif ma5 < ma10 < ma20:
        return 0.0
    elif price_above_all:
        return 75.0
    else:
        return 50.0


def volume_trend(history: pd.DataFrame) -> float:
    """近3日量能趋势得分 (0~100)，对齐 check_volume_trend_3day。"""
    if history is None or len(history) < 3:
        return 0.0
    vols = history["volume"].astype(float).tolist()[-3:]
    if len(vols) < 3 or any(v <= 0 for v in vols):
        return 0.0
    if vols[1] > vols[0] and vols[2] > vols[1]:
        return 100.0
    if vols[2] > vols[0]:
        return 60.0
    return 20.0


def momentum_pct(history: pd.DataFrame, days: int = 20) -> float:
    """N 日动量涨跌幅 (%)。"""
    if history is None or len(history) < days + 1:
        return 0.0
    closes = history["close"].astype(float)
    if len(closes) <= days:
        return 0.0
    now = float(closes.iloc[-1])
    ago = float(closes.iloc[-(days + 1)])
    if ago == 0:
        return 0.0
    return (now / ago - 1) * 100


def turnover_level(history: pd.DataFrame, lookback: int = 5) -> float:
    """近 N 日平均换手率（%）。"""
    if history is None or len(history) == 0 or "turn" not in history.columns:
        return 0.0
    turns = history["turn"].astype(float).dropna().tail(lookback)
    return float(turns.mean()) if len(turns) else 0.0


# ─── 基本面打分（PIT 对齐）────────────────────────────────────────────
def score_fundamental(fin: dict[str, Any]) -> float:
    """基本面得分（满分 40）。

    fin: {roe, profit_growth, ocf, debt_ratio, ...}（PIT 取各时点最新）
    """
    score = 0.0
    roe = fin.get("roe")
    if roe is not None:
        score += 10 if roe >= 0.15 else (8 if roe >= 0.10 else (6 if roe >= 0.05 else 3))
    pg = fin.get("profit_growth")
    if pg is not None:
        score += 10 if pg >= 30 else (8 if pg >= 15 else (6 if pg >= 5 else 3))
    ocf = fin.get("ocf")
    if ocf is not None and ocf > 0:
        score += 8
    debt = fin.get("debt_ratio")
    if debt is not None:
        score += 12 if debt <= 0.60 else (8 if debt <= 0.75 else 4)
    return max(0.0, min(40.0, score))


# ─── 六维综合打分 ─────────────────────────────────────────────────────
def score_one_stock(history: pd.DataFrame, fin: dict[str, Any],
                    fund_inflow: Optional[float] = None,
                    hot_sentiment: float = 0.5) -> dict[str, Any]:
    """对单只股票计算六维得分。

    Returns: {fund, tech, capital, sentiment, total, buy}
    """
    ma = ma_alignment(history)
    vt = volume_trend(history)
    mom = momentum_pct(history, 20)
    turn = turnover_level(history, 5)

    # 技术面 (40) = 均线(12) + 量能(8) + 换手(6) + 动量(14)
    ma_s = 12 * (ma / 100.0)
    vt_s = 8 * (vt / 100.0)
    turn_s = 6 if 3 <= turn <= 10 else (3 if 1 <= turn <= 15 else 1)
    mom_s = 14 * (1 / (1 + np.exp(-mom / 10.0)))
    tech = min(40.0, ma_s + vt_s + turn_s + mom_s)

    fund = score_fundamental(fin)

    # 资金/量能 (20)：有净流入用方向，否则用换手兜底
    if fund_inflow is not None:
        capital = 20 if fund_inflow > 0 else (10 if abs(fund_inflow) < 1e6 else 4)
    else:
        capital = 20 if turn >= 3 else (12 if turn >= 1 else 6)

    sentiment = float(hot_sentiment)
    total = min(100.0, fund + tech + capital)
    return {
        "ma": ma, "volume_trend": vt, "momentum_20d": round(mom, 2),
        "turnover": round(turn, 2),
        "fund": round(fund, 2), "tech": round(tech, 2),
        "capital": round(capital, 2), "sentiment": sentiment,
        "total": round(total, 2),
        "buy": (fund >= FUND_BUY_THRESHOLD and tech >= TECH_BUY_THRESHOLD
                and total >= TOTAL_BUY_THRESHOLD),
    }


def select_top_n(scores: list[dict[str, Any]], codes: list[str],
                 n: int = TOP_N_DEFAULT, force_buy: bool = True) -> list[str]:
    """按综合分排序选 Top N。force_buy=True 时优先 buy==True 的。"""
    paired = sorted(zip(codes, scores), key=lambda x: x[1].get("total", 0), reverse=True)
    selected: list[str] = []
    for code, sc in paired:
        if force_buy and not sc.get("buy"):
            continue
        selected.append(code)
        if len(selected) >= n:
            break
    # 合格不足 n 时，按分数补齐，保证满仓
    if len(selected) < n:
        for code, sc in paired:
            if code not in selected:
                selected.append(code)
            if len(selected) >= n:
                break
    return selected