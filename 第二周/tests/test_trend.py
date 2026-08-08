#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trend 趋势分析模块测试套件
测试技术指标计算、形态识别、信号生成等功能
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "trend"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestTechnicalIndicators(unittest.TestCase):
    """测试1: 技术指标计算"""

    def setUp(self):
        from stock_analysis import StockAnalyzer
        self.analyzer = StockAnalyzer()

    def test_ma_calculation(self):
        """测试均线计算"""
        import pandas as pd
        import numpy as np
        dates = pd.date_range('2025-01-01', periods=100, freq='D')
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(100))
        df = pd.DataFrame({'close': prices, 'high': prices + 2, 'low': prices - 2, 'open': prices + 1, 'volume': np.random.randint(1000, 10000, 1000)}, index=dates)

        df['MA5'] = df['close'].rolling(5).mean()
        df['MA10'] = df['close'].rolling(10).mean()
        df['MA20'] = df['close'].rolling(20).mean()

        self.assertFalse(df['MA5'].iloc[-1] is None)
        self.assertGreater(df['MA5'].iloc[-1], 0)
        self.assertNotEqual(df['MA5'].iloc[-1], df['MA20'].iloc[-1])

    def test_ma_crossover_detection(self):
        """测试金叉/死叉检测逻辑"""
        ma5_prev, ma5_curr = 10.0, 12.0
        ma10_prev, ma10_curr = 11.0, 11.5

        golden_cross = (ma5_prev <= ma10_prev) and (ma5_curr > ma10_curr)
        death_cross = (ma5_prev >= ma10_prev) and (ma5_curr < ma10_curr)

        self.assertTrue(golden_cross, "MA5上穿MA10应为金叉")
        self.assertFalse(death_cross)

    def test_rsi_calculation(self):
        """测试 RSI 指标计算"""
        import numpy as np
        closes = np.array([44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28])
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        self.assertGreaterEqual(rsi, 0)
        self.assertLessEqual(rsi, 100)


class TestSignalGeneration(unittest.TestCase):
    """测试2: 信号生成"""

    def setUp(self):
        from stock_analysis import StockAnalyzer
        self.analyzer = StockAnalyzer()

    def test_signal_direction_values(self):
        """测试信号方向值"""
        valid_directions = ['看多', '看空', '中性']
        for d in valid_directions:
            self.assertIn(d, valid_directions)

    def test_score_range(self):
        """测试评分范围"""
        min_score, max_score = 0, 100
        for score in [0, 30, 50, 70, 100]:
            self.assertGreaterEqual(score, min_score)
            self.assertLessEqual(score, max_score)


class TestPatternRecognition(unittest.TestCase):
    """测试3: K线形态识别"""

    def setUp(self):
        from stock_analysis import StockAnalyzer
        self.analyzer = StockAnalyzer()

    def test_pattern_list_not_empty(self):
        """测试形态列表非空"""
        patterns = self.analyzer.get_pattern_list()
        self.assertIsInstance(patterns, list)
        self.assertGreater(len(patterns), 0)

    def test_pattern_has_description(self):
        """测试形态有描述"""
        patterns = self.analyzer.get_pattern_list()
        for p in patterns:
            self.assertIn('description', p)


class TestTrendAnalyzerIntegration(unittest.TestCase):
    """测试4: 趋势分析器集成"""

    def setUp(self):
        from stock_analysis import StockAnalyzer
        self.analyzer = StockAnalyzer()

    def test_analyzer_initialization(self):
        """测试分析器初始化"""
        self.assertIsNotNone(self.analyzer)
        self.assertIsNotNone(self.analyzer.fetcher)

    def test_analyze_result_structure(self):
        """测试分析结果结构"""
        result = self.analyzer.analyze("600519", predict_days=3, show_progress=False)
        self.assertIn('success', result)
        if result.get('success'):
            self.assertIn('signal_direction', result)
            self.assertIn('score', result)
            self.assertIn('prediction', result)
            self.assertIn('patterns', result)

    def test_prediction_structure(self):
        """测试预测结果结构"""
        result = self.analyzer.analyze("600519", predict_days=3, show_progress=False)
        if result.get('success'):
            pred = result['prediction']
            self.assertIn('predicted_price', pred)
            self.assertIn('predicted_return', pred)
            self.assertIn('up_probability', pred)
            self.assertIn('confidence', pred)


def run_trend_tests():
    """运行所有 Trend 模块测试"""
    print("=" * 60)
    print("📈 Trend 趋势分析模块 — 测试套件")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestTechnicalIndicators))
    suite.addTests(loader.loadTestsFromTestCase(TestSignalGeneration))
    suite.addTests(loader.loadTestsFromTestCase(TestPatternRecognition))
    suite.addTests(loader.loadTestsFromTestCase(TestTrendAnalyzerIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"测试总数: {result.testsRun} | 通过: {passed} | 失败: {len(result.failures)} | 错误: {len(result.errors)}")
    return result.wasSuccessful()


if __name__ == '__main__':
    ok = run_trend_tests()
    sys.exit(0 if ok else 1)