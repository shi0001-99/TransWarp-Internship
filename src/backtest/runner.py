# -*- coding: utf-8 -*-
"""回测主循环：宽池周度选股 → 撮合（成本/T+1/涨跌停/停牌）→ 逐日盯市。

设计借鉴 QuantBacktest.engine.vector_turnover 的逐日推进思路，但数据与打分
全部来自 TransAlpha 的 proxy 体系，项目自治。支持中证500 / 沪深300 双基准对照。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from .data_loader import DataLoader
from . import costs as cost_mod
from . import metrics as metric_mod
from . import proxy_metrics as pm
from . import rules as rule_mod


@dataclass
class BacktestConfig:
    """回测配置。"""
    initial_capital: float = 1_000_000.0
    start_date: str = ""                 # YYYY-MM-DD
    end_date: str = ""                   # YYYY-MM-DD
    lookback_days: int = 250             # 预取K线长度（含预热）
    rebalance: str = "monthly"           # weekly / monthly
    top_n: int = 5                       # 每期选 N 只
    max_single_fund: float = 0.25        # 单票仓位上限（对齐 TransAlpha 25%）
    stop_loss_ma20: bool = True          # MA20 跌破减半
    commission: float = 0.00025
    stamp_tax: float = 0.0005
    slippage: float = 0.001


@dataclass
class Trade:
    """单笔交易记录。"""
    date: str
    code: str
    side: str          # buy / sell
    price: float
    shares: float
    amount: float
    fee: float
    pnl: float = 0.0   # 卖出时记已实现盈亏


class BacktestRunner:

    def __init__(self, cfg: Optional["BacktestConfig"] = None,
                 loader: Optional["DataLoader"] = None):
        self.cfg = cfg or BacktestConfig()
        self.loader = loader or DataLoader()
        self.cost_cfg = cost_mod.CostConfig(
            commission_rate=self.cfg.commission,
            stamp_tax=self.cfg.stamp_tax,
            slippage=self.cfg.slippage,
        )

    # ================= 主入口 =================
    def run(self, stock_pool=None) -> dict[str, Any]:
        cfg = self.cfg
        start, end = cfg.start_date, cfg.end_date
        if not start or not end:
            raise ValueError("必须设置 start_date 与 end_date")
        warm_start = (pd.Timestamp(start) - pd.Timedelta(days=cfg.lookback_days)).strftime("%Y-%m-%d")

        pool = self._normalize_pool(stock_pool)
        if not pool:
            raise ValueError("候选池为空")

        # 1. 拉取全池历史K线（含预热期）
        histories: dict[str, pd.DataFrame] = {}
        warnings: list[str] = []
        for c in pool:
            try:
                df = self.loader.kline(c, warm_start, end)
                if df is not None and len(df):
                    histories[c] = df.sort_values("date")
            except Exception as e:  # noqa: BLE001
                warnings.append(f"{c}:K线失败 {e}")
        if not histories:
            raise RuntimeError("候选池历史K线全部拉取失败")

        # 2. 财务 PIT
        fin = self._load_pit(list(histories.keys()), start, end, warnings)

        # 3. 双基准
        bench_dfs = {
            "csi500": self.loader.index_kline("sh.000905", start, end),
            "hs300": self.loader.index_kline("sh.000300", start, end),
        }

        # 4. 逐日模拟
        result = self._simulate(histories, list(histories.keys()), fin, bench_dfs)
        result["warnings"] = warnings
        result["pool_size"] = len(histories)
        result["cfg"] = self.cfg
        return result

    # ================= 主模拟 =================
    def _simulate(self, histories, pool, fin, bench_dfs) -> dict[str, Any]:
        cfg = self.cfg
        cash = cfg.initial_capital
        holdings: dict[str, float] = {}     # code -> 持仓股数
        available: dict[str, float] = {}    # code -> 可卖股数 (T+1)
        avg_cost: dict[str, float] = {}     # code -> 持仓均价

        trades: list[Trade] = []
        curve: list[dict] = []
        stopped_codes: set[str] = set()

        all_dates = sorted({d for h in histories.values() for d in h["date"]})
        all_dates = [d for d in all_dates
                     if pd.Timestamp(cfg.start_date) <= d <= pd.Timestamp(cfg.end_date)]
        if not all_dates:
            raise ValueError("区间内无交易日")

        rebal_set = self._rebalance_dates(all_dates, cfg.rebalance)

        for i, day in enumerate(all_dates):
            day = pd.Timestamp(day)
            # 当日行情索引
            day_rows = {}
            for c, h in histories.items():
                sub = h[h["date"] == day]
                if len(sub):
                    day_rows[c] = sub.iloc[-1]

            # --- 止损（每日，MA20 跌破一次性清仓 + 状态锁）---
            if cfg.stop_loss_ma20:
                for c in list(holdings):
                    if c not in day_rows or c not in available:
                        continue
                    if c in stopped_codes:
                        continue
                    close = float(day_rows[c]["close"])
                    win = histories[c][histories[c]["date"] <= day]
                    if len(win) < 20:
                        continue
                    ma20 = float(win["close"].iloc[-20:].mean())
                    if close < ma20:
                        sellable = available.get(c, 0)
                        qty = min(holdings[c], sellable)
                        if qty > 0:
                            cash = self._execute_sell(
                                c, qty, day_rows[c], day, cash, holdings,
                                available, avg_cost, trades)
                            # 反应在 holdings / available
                            holdings[c] -= qty
                            available[c] -= qty
                            if holdings[c] <= 1e-9:
                                holdings.pop(c, None)
                                available.pop(c, None)
                                avg_cost.pop(c, None)
                                stopped_codes.add(c)

            # --- 再平衡（首日或再平衡日）---
            if i == 0 or day in rebal_set:
                stopped_codes.clear()
                scores = {}
                for c in pool:
                    hist = histories[c]
                    win = hist[hist["date"] <= day]
                    if len(win) < 20:
                        continue
                    f = fin.get(c, {})
                    inflow = self._fund_inflow_like(c, win)
                    scores[c] = pm.score_one_stock(win, f, fund_inflow=inflow)
                target = pm.select_top_n(
                    [scores.get(c, {"total": 0, "buy": False}) for c in pool],
                    pool, n=cfg.top_n) if scores else []
                cash = self._rebalance(day, day_rows, target, cash, holdings,
                                       available, avg_cost, trades)

            # --- 盯市 ---
            mv = cash
            for c, q in holdings.items():
                if c in day_rows:
                    mv += float(q) * float(day_rows[c]["close"])
            curve.append({"date": day.date().isoformat(), "equity": round(mv, 2)})

        if not curve:
            raise ValueError("回测区间内无有效净值点")

        # 归一化净值
        nav = pd.Series([r["equity"] for r in curve],
                        index=pd.to_datetime([r["date"] for r in curve]))
        nav = nav / nav.iloc[0]

        # 双基准归一化
        benches = {}
        for name, df in bench_dfs.items():
            if df is not None and len(df) and "value" in df.columns:
                s = pd.Series(df["value"].values, index=pd.to_datetime(df["date"]))
                s = s.reindex(nav.index).ffill().dropna()
                if len(s) and s.iloc[0] != 0:
                    benches[name] = s / s.iloc[0]

        # equity_curve DataFrame（含基准列、净值、收益率）
        eq_df = pd.DataFrame(curve)
        eq_df["equity_norm"] = eq_df["equity"] / eq_df["equity"].iloc[0]
        eq_df["ret"] = eq_df["equity_norm"].pct_change().fillna(0)
        for name, s in benches.items():
            eq_df[name] = s.reindex(pd.to_datetime(eq_df["date"])).values

        # 交易统计
        pnl_list = [t.pnl for t in trades if t.pnl not in (None, 0)]
        metrics = metric_mod.compute_all_metrics(
            nav, benchmarks=benches, trade_pnl=pnl_list,
            initial_capital=cfg.initial_capital)
        metrics["n_buys"] = sum(1 for t in trades if t.side == "buy")
        metrics["n_sells"] = sum(1 for t in trades if t.side == "sell")
        metrics["n_trades"] = len(trades)
        metrics["total_trade_value"] = round(sum(t.amount for t in trades), 2)

        return {
            "cfg": cfg, "nav": nav, "curve": eq_df, "trades": trades,
            "benchmarks": benches, "metrics": metrics,
            "pool_size": len(histories), "start_date": str(all_dates[0].date()),
            "end_date": str(all_dates[-1].date()),
        }

    # ================= 撮合 =================
    def _rebalance(self, day, day_rows, target, cash, holdings, available,
                   avg_cost, trades) -> float:
        """把持仓调整到目标集 target（等权、单票<=max_single_fund、计成本、T+1）。

        资金通过返回值回传（Python 参数无法按引用修改 int/float）。
        """
        cfg = self.cfg
        n_target = max(1, len(target))
        weight = min(1.0 / n_target, cfg.max_single_fund)
        day_s = day.date().isoformat()

        # 先卖：卖出不在 target 的持仓（仅可卖部分）
        for c in list(holdings):
            if c not in target:
                sellable = available.get(c, 0)
                if sellable > 0 and c in day_rows:
                    cash = self._execute_sell(
                        c, sellable, day_rows[c], day_s, cash, holdings,
                        available, avg_cost, trades)
            if holdings.get(c, 0) <= 1e-9:
                holdings.pop(c, None)
                available.pop(c, None)
                avg_cost.pop(c, None)

        # 再买：等权目标市值 = weight × 当前组合市值
        mv_estimate = cash
        for c, q in holdings.items():
            if c in day_rows:
                mv_estimate += float(q) * float(day_rows[c]["close"])
        budget_per = mv_estimate * weight

        for c in target:
            if c in day_rows and c not in holdings:
                row = day_rows[c]
                price = float(row["close"])
                px = cost_mod.applied_price(price, "buy", cfg.slippage)
                if px <= 0 or not self._can_trade(row, c, "buy"):
                    continue
                shares = int((budget_per * 0.98) / px)  # 留现金余量避免成本溢出
                if shares <= 0:
                    continue
                amount = shares * px
                fee = cost_mod.compute_trade_cost(amount, "buy", self.cost_cfg)
                if amount + fee > cash:
                    s2 = int((cash if cash > fee else 0) / px)
                    if s2 <= 0:
                        continue
                    shares = s2
                    amount = shares * px
                    fee = cost_mod.compute_trade_cost(amount, "buy", self.cost_cfg)
                cash = self._execute_buy(
                    c, shares, px, day_s, cash, holdings, available, avg_cost, trades)

        return cash

    def _execute_buy(self, code, shares, px, day_s, cash, holdings, available,
                     avg_cost, trades) -> float:
        """"买入。返回更新后现金。"""
        amount = shares * px
        fee = cost_mod.compute_trade_cost(amount, "buy", self.cost_cfg)
        if amount + fee > cash:
            return cash  # 现金不足，跳过
        prev_cost = avg_cost.get(code, 0) * holdings.get(code, 0)
        holdings[code] = holdings.get(code, 0) + shares
        avg_cost[code] = (prev_cost + amount) / holdings[code]
        available.setdefault(code, holdings[code])  # T+1 从持仓中取可卖数
        trades.append(Trade(date=str(day_s), code=code, side="buy",
                            price=round(px, 3), shares=shares,
                            amount=round(amount, 2), fee=round(fee, 2)))
        return cash - (amount + fee)

    def _execute_sell(self, code, qty, row, day_s, cash, holdings, available,
                      avg_cost, trades) -> float:
        """"卖出。返回当日现金。"""
        px = cost_mod.applied_price(float(row["close"]), "sell", self.cfg.slippage)
        amount = qty * px
        fee = cost_mod.compute_trade_cost(amount, "sell", self.cost_cfg)
        cost_basis = avg_cost.get(code, 0) * qty
        pnl = amount - fee - cost_basis
        holdings[code] = holdings.get(code, 0) - qty
        available[code] = max(0.0, available.get(code, 0) - qty)
        trades.append(Trade(date=str(day_s), code=code, side="sell",
                            price=round(px, 3), shares=qty,
                            amount=round(amount, 2), fee=round(fee, 2), pnl=round(pnl, 2)))
        return cash + (amount - fee)

    @staticmethod
    def _can_trade(row, code, side) -> bool:
        return rule_mod.is_tradable(row, code, side)

    # ================= 辅助 =================
    def _normalize_pool(self, stock_pool):
        if stock_pool is None:
            pool = self._load_universe()
        else:
            pool = stock_pool
        out = []
        for c in pool:
            s = str(c).strip()
            if not s:
                continue
            for pre in ("sh.", "sz."):
                if s.startswith(pre):
                    s = s[len(pre):]
                    break
            out.append(s)
        return out

    def _load_universe(self) -> list[str]:
        df = self.loader.csi500_components(self.cfg.end_date)
        out = []
        if df is not None and len(df) and "code" in df.columns:
            for c in df["code"].tolist():
                s = str(c).strip()
                for pre in ("sh.", "sz."):
                    if s.startswith(pre):
                        s = s[len(pre):]
                        break
                if s:
                    out.append(s)
        return out

    def _load_pit(self, pool, start, end=None, warnings=None) -> dict[str, dict]:
        """拉取财务并对齐 pubDate。简化：取区间内最新一次财报（含 start 年份）。"""
        warnings = warnings or []
        out: dict[str, dict] = {c: {} for c in pool}
        start_y = pd.Timestamp(start).year
        end_y = pd.Timestamp(end if end else self.cfg.end_date).year
        for c in pool:
            fin = {}
            for y in range(end_y, start_y - 1, -1):
                done = False
                for q in (4, 3, 2, 1):
                    try:
                        fr = self.loader.financial(c, y, q)
                        if fr is not None and len(fr):
                            r = fr.iloc[0]
                            pub = r.get("pubDate", "")
                            if pd.isna(pub) or not str(pub).strip():
                                continue
                            fin = {
                                "roe": self._v(r, "roe"),
                                "profit_growth": self._v(r, "profit_growth"),
                                "ocf": self._v(r, "ocf"),
                                "debt_ratio": self._v(r, "debt_ratio"),
                                "gross_margin": self._v(r, "gross_margin"),
                                "pubDate": str(pub),
                            }
                            done = True
                            break
                    except Exception as e:  # noqa: BLE001
                        warnings.append(f"{c} {y}Q{q} 财报失败 {e}")
                        continue
                if done:
                    break
            fin["pub_timeline"] = self._fin_timeline(c, start_y, end_y, warnings)
            out[c] = fin
        return out

    def _fin_timeline(self, code, sy, ey, warnings):
        tl = {}
        for y in range(sy, ey + 1):
            for q in (4, 3, 2, 1):
                try:
                    fr = self.loader.financial(code, y, q)
                    if fr is not None and len(fr):
                        r = fr.iloc[0]
                        pub = r.get("pubDate")
                        if pub and not pd.isna(pub):
                            tl[str(pub)] = {
                                "roe": self._v(r, "roe"),
                                "profit_growth": self._v(r, "profit_growth"),
                                "ocf": self._v(r, "ocf"),
                                "debt_ratio": self._v(r, "debt_ratio"),
                            }
                except Exception:
                    continue
        return tl

    def _fund_inflow_like(self, code, win) -> float | None:
        """资金流 proxy：用近5日净流入近似（无净流入则退化为换手/成交额强度符号）。"""
        if win is None or len(win) < 5:
            return None
        # 若含净流入列（东财降级未取到），否则用换手正负近似
        if "net_mf_amt" in win.columns:
            arr = win["net_mf_amt"].astype(float)
            return float(arr.sum())
        # 否则返回成交额均值（>0 方向由换手阈值接管打分内逻辑）
        if "amount" in win.columns:
            amv = win["amount"].astype(float).tail(5)
            return float(amv.mean()) if len(amv) else None
        return None

    def _rebalance_dates(self, dates, freq) -> set:
        """返回需再平衡的日期（每周五 / 每月最后交易日）。"""
        s = pd.Series(dates)
        idx = []
        if freq == "monthly":
            grp = s.groupby(s.dt.to_period("M")).apply(lambda x: x.index[-1])
            idx = list(grp.values)
        else:
            week = s.dt.isocalendar()["week"].astype(str) + "-" + s.dt.isocalendar()["year"].astype(str)
            grp = pd.Series(range(len(s))).groupby(week).apply(lambda x: int(x.index[-1]))
            idx = list(grp.values)
        return {dates[i] for i in idx}

    def _trade_metrics(self, trades):
        sells = [t for t in trades if t.side == "sell"]
        buys = [t for t in trades if t.side == "buy"]
        return {
            "n_buys": len(buys), "n_sells": len(sells),
            "n_trades": len(trades),
            "total_trade_value": round(sum(t.amount for t in trades), 2),
        }

    @staticmethod
    def _v(row, key):
        v = row.get(key)
        try:
            return float(v) if v is not None and v == v else None
        except (TypeError, ValueError):
            return None


def run_backtest(start_date: str, end_date: str, stock_pool=None,
                 initial_capital: float = 1_000_000.0, rebalance: str = "monthly",
                 top_n: int = 5) -> dict[str, Any]:
    """便捷入口：构造配置并运行，返回 result dict。"""
    cfg = BacktestConfig(
        initial_capital=initial_capital,
        start_date=start_date, end_date=end_date,
        rebalance=rebalance, top_n=top_n,
    )
    runner = BacktestRunner(cfg=cfg)
    return runner.run(stock_pool=stock_pool)