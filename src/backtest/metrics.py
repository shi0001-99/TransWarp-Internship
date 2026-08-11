# -*- coding: utf-8 -*-
"""回测绩效指标计算（移植 QuantBacktest.analysis.metrics 公式）。

涵盖收益/风险/风险调整/市场风险/交易类指标，与双基准对照。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# 年化交易日数（A股）
TRADING_DAYS = 244


def compute_returns(nav: pd.Series) -> pd.Series:
    if len(nav) < 2:
        return pd.Series(dtype=float)
    return nav.pct_change().dropna()


def total_return(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    return float(nav.iloc[-1] / nav.iloc[0] - 1)


def annual_return(nav: pd.Series, freq: int = TRADING_DAYS) -> float:
    if len(nav) < 2:
        return 0.0
    n_years = len(nav) / freq
    if n_years <= 0:
        return 0.0
    return float((nav.iloc[-1] / nav.iloc[0]) ** (1 / n_years) - 1)


def annual_volatility(returns: pd.Series, freq: int = TRADING_DAYS) -> float:
    if len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(freq))


def max_drawdown(nav: pd.Series) -> tuple[float, Any, Any]:
    if len(nav) < 2:
        return 0.0, nav.index[0] if len(nav) else None, nav.index[0] if len(nav) else None
    running_max = nav.cummax()
    dd = nav / running_max - 1
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    return float(dd.min()), peak, trough


def sharpe_ratio(returns: pd.Series, rf: float = 0.0, freq: int = TRADING_DAYS) -> float:
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    excess = returns - rf / freq
    return float(np.sqrt(freq) * excess.mean() / excess.std())


def sortino_ratio(returns: pd.Series, rf: float = 0.0, freq: int = TRADING_DAYS) -> float:
    if len(returns) < 2:
        return 0.0
    excess = returns - rf / freq
    downside = excess[excess < 0]
    if len(downside) < 1:
        return 0.0
    downside_std = np.sqrt((downside ** 2).mean())
    if downside_std == 0:
        return 0.0
    return float(np.sqrt(freq) * excess.mean() / downside_std)


def calmar_ratio(nav: pd.Series, freq: int = TRADING_DAYS) -> float:
    ann = annual_return(nav, freq)
    mdd, _, _ = max_drawdown(nav)
    if mdd == 0:
        return 0.0
    return float(ann / abs(mdd))


def alpha_beta(strategy_returns: pd.Series, benchmark_returns: pd.Series,
               rf: float = 0.0, freq: int = TRADING_DAYS) -> tuple[float, float]:
    common = strategy_returns.index.intersection(benchmark_returns.index)
    if len(common) < 10:
        return 0.0, 0.0
    s = strategy_returns.loc[common].values
    b = benchmark_returns.loc[common].values
    if b.std() == 0:
        return 0.0, 0.0
    beta = float(np.cov(s, b, ddof=1)[0, 1] / np.var(b, ddof=1))
    alpha = float(s.mean() - beta * b.mean())
    return alpha * freq, beta


def information_ratio(strategy_returns: pd.Series, benchmark_returns: pd.Series,
                      freq: int = TRADING_DAYS) -> float:
    common = strategy_returns.index.intersection(benchmark_returns.index)
    if len(common) < 10:
        return 0.0
    excess = strategy_returns.loc[common] - benchmark_returns.loc[common]
    if excess.std() == 0:
        return 0.0
    return float(np.sqrt(freq) * excess.mean() / excess.std())


def excess_curve(nav: pd.Series, benchmark: pd.Series) -> pd.Series:
    """超额净值曲线：对齐起点后的策略/基准比值。"""
    common = nav.index.intersection(benchmark.index)
    if len(common) < 2:
        return pd.Series(dtype=float)
    s = (nav.loc[common] / nav.loc[common].iloc[0])
    b = (benchmark.loc[common] / benchmark.loc[common].iloc[0])
    return s / b - 1


def win_rate(pnl_list: list[float]) -> float:
    if not pnl_list:
        return 0.0
    return float(sum(1 for p in pnl_list if p > 0) / len(pnl_list))


def profit_factor(pnl_list: list[float]) -> float:
    gains = sum(p for p in pnl_list if p > 0)
    losses = -sum(p for p in pnl_list if p < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def compute_all_metrics(nav: pd.Series,
                        benchmarks: dict[str, pd.Series] | None = None,
                        trade_pnl: list[float] | None = None,
                        initial_capital: float = 1_000_000.0) -> dict[str, Any]:
    """计算全套指标。benchmarks: {name: nav_series}。"""
    nav = nav.dropna().astype(float)
    if len(nav) < 2:
        return {"error": "净值序列过短"}

    rets = compute_returns(nav)
    metrics: dict[str, Any] = {
        "total_return": total_return(nav),
        "annual_return": annual_return(nav),
        "annual_volatility": annual_volatility(rets),
        "max_drawdown": max_drawdown(nav)[0],
        "sharpe": sharpe_ratio(rets),
        "sortino": sortino_ratio(rets),
        "calmar": calmar_ratio(nav),
    }

    # 基准对照（双基准）
    if benchmarks:
        for name, bench in benchmarks.items():
            bench = bench.dropna()
            if len(bench) < 2:
                continue
            brets = compute_returns(bench)
            alpha, beta = alpha_beta(rets, brets)
            metrics[f"{name}_total_return"] = total_return(bench)
            metrics[f"{name}_excess_return"] = total_return(nav) - total_return(bench)
            metrics[f"{name}_alpha"] = alpha
            metrics[f"{name}_beta"] = beta
            metrics[f"{name}_ir"] = information_ratio(rets, brets)

    # 交易指标
    if trade_pnl:
        metrics["n_trades"] = len(trade_pnl)
        metrics["win_rate"] = win_rate(trade_pnl)
        metrics["profit_factor"] = profit_factor(trade_pnl)
        wins = [p for p in trade_pnl if p > 0]
        losses = [p for p in trade_pnl if p < 0]
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        metrics["avg_win"] = avg_win
        metrics["avg_loss"] = avg_loss
        metrics["payoff_ratio"] = (abs(avg_win) / abs(avg_loss)) if avg_loss else 0.0

    return metrics


def format_metrics(metrics: dict) -> dict:
    out = {}
    for k, v in metrics.items():
        if isinstance(v, float):
            out[k] = f"{v*100:.2f}%" if abs(v) < 1 else f"{v:.4f}"
        else:
            out[k] = v
    return out