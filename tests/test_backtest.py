#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测校验模块（src/backtest/）单元测试。
覆盖：成本 / 规则 / 六维打分 / 绩效指标 / 回测主循环（mock 数据，禁网络）。
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestCosts(unittest.TestCase):
    """交易成本计算。"""
    def setUp(self):
        import backtest.costs as c
        self.cost = c.CostConfig()

    def test_buy_cost_has_no_stamp(self):
        from backtest import costs as c
        cfg = self.cost
        fee = c.compute_trade_cost(10000, "buy", cfg)
        # 佣金(≥5) + 印花税0 + 过户 + 滑点 = 2.5+0+0.1+10 = 12.6 左右
        self.assertGreater(fee, 0)
        self.assertTrue(fee > 5)  # 至少佣金底限

    def test_sell_cost_includes_stamp(self):
        from backtest import costs as c
        cfg = self.cost
        buy = c.compute_trade_cost(10000, "buy", cfg)
        sell = c.compute_trade_cost(10000, "sell", cfg)
        self.assertGreater(sell, buy)  # 卖出多印花税

    def test_applied_price(self):
        from backtest import costs as c
        self.assertGreater(c.applied_price(10, "buy", 0.001), 10)
        self.assertLess(c.applied_price(10, "sell", 0.001), 10)


class TestRules(unittest.TestCase):
    """A股交易规则。"""
    def test_limit_ratio(self):
        from backtest import rules as r
        self.assertAlmostEqual(r.limit_ratio("600519"), 0.10)
        self.assertAlmostEqual(r.limit_ratio("688001"), 0.20)
        self.assertAlmostEqual(r.limit_ratio("300750"), 0.20)

    def test_stop_lose_on_limit_down(self):
        from backtest import rules as r
        row = {"close": 9.0, "prev_close": 10.0, "tradestatus": 1}
        self.assertTrue(r.is_limit_down(9.0, 10.0, "600519"))
        self.assertFalse(r.is_tradable(row, "600519", "sell"))  # 跌停不可卖


class TestProxyMetrics(unittest.TestCase):
    """六维打分。"""
    def setUp(self):
        import backtest.proxy_metrics as pm
        self.pm = pm
        dates = pd.date_range("2025-01-01", periods=60, freq="D")
        closes = np.linspace(10, 15, 60)  # 持续上行，多头排列
        df = pd.DataFrame({
            "date": dates, "close": closes,
            "volume": np.full(60, 5000), "turn": np.full(60, 3.0),
        })
        self.df = df

    def test_ma_alignment_bullish(self):
        s = self.pm.ma_alignment(self.df)
        self.assertAlmostEqual(s, 100.0)  # 多头排列

    def test_score_bounds(self):
        fin = {"roe": 0.18, "profit_growth": 25.0, "ocf": 1e8, "debt_ratio": 0.4}
        sc = self.pm.score_one_stock(self.df, fin, fund_inflow=1e7)
        self.assertLessEqual(sc["total"], 100)
        self.assertGreaterEqual(sc["total"], 0)
        self.assertIn("buy", sc)

    def test_select_top_n(self):
        scores = [
            {"total": 80, "buy": True}, {"total": 70, "buy": True},
            {"total": 60, "buy": False}, {"total": 40, "buy": True},
        ]
        sel = self.pm.select_top_n(scores, ["a", "b", "c", "d"], n=2)
        self.assertEqual(len(sel), 2)
        self.assertIn("a", sel)


class TestMetrics(unittest.TestCase):
    """绩效指标。"""
    def test_sharpe_and_drawdown(self):
        from backtest import metrics as m
        nav = pd.Series(np.linspace(1.0, 1.8, 244))
        rets = m.compute_returns(nav)
        self.assertGreater(m.total_return(nav), 0)
        self.assertGreater(m.sharpe_ratio(rets), 0)
        mdd, _, _ = m.max_drawdown(nav)
        self.assertLessEqual(mdd, 0)

    def test_compute_all_metrics_has_core_keys(self):
        from backtest import metrics as m
        nav = pd.Series(np.cumsum(np.random.RandomState(1).randn(100)) + 100)
        out = m.compute_all_metrics(nav)
        for k in ("total_return", "annual_return", "max_drawdown", "sharpe", "sortino"):
            self.assertIn(k, out)


class _MockLoader:
    """禁网络的 DataLoader 替代：确定性伪行情。"""
    def __init__(self, codes, n=180, seed=7):
        self.codes = codes
        self.n = n
        rng = np.random.RandomState(seed)
        self._prices = {c: 10 + np.cumsum(rng.randn(n)) for i, c in enumerate(codes)}
        self.start = (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")
        self.end = datetime.now().strftime("%Y-%m-%d")
        self.dates = pd.bdate_range(self.start, periods=n)

    def kline(self, code, start, end):
        import backtest.data_loader as dl
        rows = []
        px = self._prices[code]
        for i, d in enumerate(self.dates):
            rows.append({
                "date": d, "open": float(px[i]), "high": float(px[i] + 0.5),
                "low": float(px[i] - 0.5), "close": float(px[i]),
                "volume": 5000.0, "amount": 5000 * px[i], "turn": 3.0,
                "pctChg": 0.0, "tradestatus": 1.0, "isST": 0.0,
            })
        df = pd.DataFrame(rows)
        return df

    def financial(self, code, year, quarter):
        # 返回带 pubDate 的单行
        return pd.DataFrame([{
            "code": code, "pubDate": f"{year}-0{quarter}-15",
            "statDate": f"{year}-0{quarter}-31", "roe": 0.15,
            "net_margin": 0.2, "gross_margin": 0.4,
            "ocf": 1e8, "debt_ratio": 0.4,
            "MBRevenue": 1e9, "netProfit": 1e8,
            "profit_growth": 20.0, "npMargin": 0.2, "gpMargin": 0.4,
            "roeAvg": 0.15, "dtProfit": 20.0,
            "totalAssets": 5e9, "totalLiab": 2e9, "bsp": 8.0,
            "netOperatingCashFlow": 1e8,
        }])

    def index_kline(self, bs_index, start, end):
        return pd.DataFrame({
            "date": self.dates[:120],
            "value": np.linspace(4000, 5000, 120),
        })

    def csi500_components(self, date):
        return pd.DataFrame({"updateDate": [date], "code": self.codes})


class TestRunner(unittest.TestCase):
    """回测主循环（mock loader，禁网络）。"""
    def setUp(self):
        from backtest.runner import BacktestConfig, BacktestRunner
        codes = ["600519", "000858", "000001", "600036", "000333", "002415"]
        self.loader = _MockLoader(codes)
        self.cfg = BacktestConfig(
            initial_capital=1_000_000.0,
            start_date=self.loader.dates[40].strftime("%Y-%m-%d"),
            end_date=self.loader.dates[-1].strftime("%Y-%m-%d"),
            rebalance="monthly", top_n=3,
        )
        self.runner = BacktestRunner(cfg=self.cfg, loader=self.loader)

    def test_run_produces_curve_and_trades(self):
        result = self.runner.run(stock_pool=list(self.loader.codes))
        self.assertIn("curve", result)
        self.assertGreater(len(result["curve"]), 0)
        self.assertIn("metrics", result)
        self.assertIn("total_return", result["metrics"])

    def test_run_export_three_files(self):
        from backtest.report import export_backtest_result
        result = self.runner.run(stock_pool=list(self.loader.codes))
        with tempfile.TemporaryDirectory() as td:
            paths = export_backtest_result(result, output_dir=Path(td))
            for key in ("equity_curve", "metrics", "trade_log"):
                self.assertTrue(paths[key].exists(), msg=f"{key} 未生成")


class TestReportJsonSafe(unittest.TestCase):
    def test_numpy_to_json_safe(self):
        from backtest.report import _json_safe
        d = {"a": np.float64(1.5), "b": np.int64(3), "nan": float("nan")}
        out = _json_safe(d)
        import json
        json.dumps(out)  # 不能抛异常
        self.assertIsNone(out["nan"])


if __name__ == "__main__":
    unittest.main()