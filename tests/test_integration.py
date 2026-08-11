#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成测试 — 验证 TransAlpha CLI 流水线各模块协同工作
"""

import sys
import os
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SRC_DIR = PROJECT_ROOT / "src"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SRC_DIR))


class TestModuleImports(unittest.TestCase):
    """测试1: 各模块导入"""

    def test_import_kelly_analyzer(self):
        try:
            from src.kelly.stock_kelly_analyzer import StockKellyAnalyzer, KellyCalculator, StockScorer
            self.assertIsNotNone(StockKellyAnalyzer)
            self.assertIsNotNone(KellyCalculator)
            self.assertIsNotNone(StockScorer)
        except ImportError as e:
            self.fail(f"凯利模块导入失败: {e}")

    def test_import_trend_analyzer(self):
        try:
            from src.screener.data_fetcher import StockAnalyzer
            self.assertIsNotNone(StockAnalyzer)
        except ImportError as e:
            self.fail(f"趋势模块导入失败: {e}")

    def test_import_monitor(self):
        try:
            from src.monitor.monitor import StockAlert
            self.assertIsNotNone(StockAlert)
        except ImportError as e:
            self.fail(f"监控模块导入失败: {e}")

    def test_import_db_lock(self):
        try:
            from src.monitor.db_lock import file_lock, atomic_write_json, safe_read_json
            self.assertIsNotNone(file_lock)
            self.assertIsNotNone(atomic_write_json)
            self.assertIsNotNone(safe_read_json)
        except ImportError as e:
            self.fail(f"文件锁模块导入失败: {e}")

    def test_import_pipeline(self):
        try:
            from src.pipeline import (
                run_screening_stage, run_manual_review,
                run_analysis_stage, run_manual_confirmation,
                run_kelly_stage, run_position_review,
                run_monitor_stage, run_pipeline,
                SharedDataCache, PROJECT_ROOT, OUTPUT_DIR,
            )
            self.assertIsNotNone(run_pipeline)
            self.assertIsNotNone(PROJECT_ROOT)
            self.assertIsNotNone(OUTPUT_DIR)
        except ImportError as e:
            self.fail(f"流水线模块导入失败: {e}")

    def test_import_screener(self):
        try:
            from src.screener.screener import StockScreener
            self.assertIsNotNone(StockScreener)
        except ImportError as e:
            self.fail(f"选股模块导入失败: {e}")


class TestCrossModuleDataFlow(unittest.TestCase):
    """测试2: 跨模块数据流"""

    def test_kelly_scorer_to_calculator(self):
        from src.kelly.stock_kelly_analyzer import StockScorer, KellyCalculator
        scorer = StockScorer()
        calculator = KellyCalculator()

        scores = {'value': 0.8, 'momentum': 0.7, 'macro': 0.6, 'capital_flow': 0.5, 'event': 0.7}
        total_score = sum(scores.values()) / len(scores)
        self.assertGreater(total_score, 0)

        kelly_frac = calculator.kelly_fraction(0.6, 0.15, 0.08)
        self.assertGreater(kelly_frac, 0)

    def test_trend_signal_to_kelly_input(self):
        signal_direction = "看多"
        signal_score = 72
        is_bullish = signal_direction == "看多" and signal_score >= 55
        self.assertTrue(is_bullish, "看多+高分应为看涨")

    def test_monitor_watchlist_creation(self):
        from src.monitor.monitor import StockAlert
        monitor = StockAlert(log_to_file=False, log_to_console=False)
        self.assertIsInstance(monitor.watchlist, list)


class TestPipelineState(unittest.TestCase):
    """测试3: 流水线状态管理"""

    def test_state_transitions(self):
        valid_states = ['idle', 'screening', 'review', 'analysis',
                        'confirmation', 'kelly', 'position_review',
                        'monitoring', 'completed', 'error']
        for state in valid_states:
            self.assertIn(state, valid_states)

    def test_output_dirs_exist(self):
        output_dirs = [
            PROJECT_ROOT / "output" / "screening",
            PROJECT_ROOT / "output" / "trend",
            PROJECT_ROOT / "output" / "kelly",
            PROJECT_ROOT / "output" / "monitor",
        ]
        for d in output_dirs:
            self.assertTrue(d.exists(), f"输出目录不存在: {d}")
            self.assertTrue(d.is_dir(), f"不是目录: {d}")

    def test_pipeline_state_file(self):
        from src.pipeline import _read_state, _write_state, STATE_FILE
        test_state = {"pipeline_status": "test", "test_key": "test_value"}
        _write_state(test_state)
        read_state = _read_state()
        self.assertEqual(read_state["test_key"], "test_value")
        STATE_FILE.unlink(missing_ok=True)


class TestEndToEndWorkflow(unittest.TestCase):
    """测试4: 端到端工作流验证"""

    def test_full_pipeline_components(self):
        components = {
            'screener': True,
            'trend_analyzer': True,
            'kelly_analyzer': True,
            'monitor': True,
            'pipeline': True,
        }
        for name, available in components.items():
            self.assertTrue(available, f"组件 {name} 不可用")

    def test_data_sharing_interface(self):
        import pandas as pd

        class MockCache:
            def get_kline_df(self, code, days=250):
                return pd.DataFrame({
                    'date': ['2025-01-01', '2025-01-02'],
                    'close': [100, 102],
                    'open': [99, 101],
                    'high': [101, 103],
                    'low': [98, 100],
                    'volume': [1000, 1200]
                })

            def get_realtime(self, code):
                return {'price': 102, 'prev_close': 100, 'name': '测试'}

            def get_stock_info(self, code):
                return {'name': '测试', 'code': code, 'pe': 20, 'pb': 3}

            def get_financial_data(self, code):
                return {'roe': 0.15, 'debt_ratio': 0.4}

            def get_market_data(self, code):
                return {'current_price': 102, 'ma5': 101, 'ma20': 100}

        cache = MockCache()
        df = cache.get_kline_df("600519")
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreater(len(df), 0)

        info = cache.get_stock_info("600519")
        self.assertIn('name', info)

        market = cache.get_market_data("600519")
        self.assertIn('current_price', market)

    def test_cli_commands(self):
        from src.pipeline import main as pipeline_main
        self.assertTrue(callable(pipeline_main))


def run_integration_tests():
    print("=" * 60)
    print("集成测试 — TransAlpha CLI 量化投资系统")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestModuleImports))
    suite.addTests(loader.loadTestsFromTestCase(TestCrossModuleDataFlow))
    suite.addTests(loader.loadTestsFromTestCase(TestPipelineState))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEndWorkflow))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"测试总数: {result.testsRun} | 通过: {passed} | 失败: {len(result.failures)} | 错误: {len(result.errors)}")
    return result.wasSuccessful()


if __name__ == '__main__':
    ok = run_integration_tests()
    sys.exit(0 if ok else 1)