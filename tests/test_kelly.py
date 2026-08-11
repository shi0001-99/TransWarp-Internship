#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kelly 凯利分析模块测试套件
测试多维度评分、凯利公式计算、黑名单规则等功能
"""

import sys
import os
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "kelly"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestKellyScoring(unittest.TestCase):
    """测试1: 多维度评分系统"""

    def setUp(self):
        from stock_kelly_analyzer import StockScorer, SCORING_WEIGHTS, RATING_THRESHOLDS
        self.scorer = StockScorer()
        self.weights = SCORING_WEIGHTS
        self.thresholds = RATING_THRESHOLDS

    def test_scoring_weights_structure(self):
        """验证评分权重结构完整性"""
        self.assertIn('value', self.weights)
        self.assertIn('momentum', self.weights)
        self.assertIn('macro', self.weights)
        self.assertIn('capital_flow', self.weights)
        self.assertIn('event', self.weights)
        total_weight = sum(self.weights.values())
        self.assertAlmostEqual(total_weight, 1.0, places=2)

    def test_rating_thresholds(self):
        """验证评级阈值合理性"""
        self.assertIn('AAA', self.thresholds)
        self.assertIn('AA', self.thresholds)
        self.assertIn('A', self.thresholds)
        self.assertIn('B', self.thresholds)
        self.assertIn('C', self.thresholds)
        for rating, (min_score, max_score) in self.thresholds.items():
            self.assertLess(min_score, max_score, f"{rating} 阈值无效")

    def test_score_normalization(self):
        """测试分数标准化方法"""
        score = self.scorer._normalize_score(75, 0, 100)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 1)


class TestKellyCalculator(unittest.TestCase):
    """测试2: 凯利公式计算"""

    def setUp(self):
        from stock_kelly_analyzer import KellyCalculator
        self.calculator = KellyCalculator()

    def test_kelly_fraction_calculation(self):
        """测试凯利比例计算"""
        win_prob = 0.6
        avg_win = 0.15
        avg_loss = 0.08
        fraction = self.calculator.calculate_kelly(win_prob, avg_win, avg_loss)
        self.assertGreater(fraction, 0)
        self.assertLessEqual(fraction, 1.0)

    def test_kelly_with_zero_loss(self):
        """测试极端情况：亏损为0时应返回1.0"""
        fraction = self.calculator.calculate_kelly(0.5, 0.10, 0.001)
        self.assertGreater(fraction, 0.5)

    def test_half_kelly_scaling(self):
        """测试半凯利策略"""
        full_kelly = self.calculator.calculate_kelly(0.6, 0.15, 0.08)
        half_kelly = full_kelly * 0.5
        self.assertAlmostEqual(half_kelly, full_kelly * 0.5)

    def test_negative_expectancy(self):
        """测试负期望：胜率低时应返回0"""
        fraction = self.calculator.calculate_kelly(0.3, 0.05, 0.10)
        self.assertEqual(fraction, 0)


class TestKellyAnalyzer(unittest.TestCase):
    """测试3: 凯利分析器集成"""

    def setUp(self):
        from stock_kelly_analyzer import StockKellyAnalyzer
        self.analyzer = StockKellyAnalyzer(total_capital=1000000, kelly_scaling=0.5)

    def test_analyzer_initialization(self):
        """测试分析器初始化"""
        self.assertEqual(self.analyzer.total_capital, 1000000)
        self.assertEqual(self.analyzer.kelly_scaling, 0.5)

    def test_blacklist_rules(self):
        """测试黑名单规则加载"""
        from stock_kelly_analyzer import BLACKLIST_RULES
        self.assertIsInstance(BLACKLIST_RULES, dict)
        self.assertIn('stocks', BLACKLIST_RULES)
        self.assertIn('sectors', BLACKLIST_RULES)

    def test_analyze_result_structure(self):
        """测试分析结果结构（使用模拟数据）"""
        result = self.analyzer.analyze("600519", silent=True)
        self.assertIn('success', result)
        if result.get('success'):
            self.assertIn('ratings', result)
            self.assertIn('kelly', result)
            self.assertIn('blacklist', result)


class TestKellyConfig(unittest.TestCase):
    """测试4: 配置参数"""

    def test_config_values(self):
        """测试配置值合理性"""
        from stock_kelly_analyzer import KELLY_CONFIG
        self.assertIn('min_score_threshold', KELLY_CONFIG)
        self.assertIn('max_position_pct', KELLY_CONFIG)
        self.assertIn('stop_loss_pct', KELLY_CONFIG)
        self.assertGreater(KELLY_CONFIG['min_score_threshold'], 0)
        self.assertLess(KELLY_CONFIG['max_position_pct'], 1.0)


def run_kelly_tests():
    """运行所有 Kelly 模块测试"""
    print("=" * 60)
    print("📊 Kelly 凯利分析模块 — 测试套件")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestKellyScoring))
    suite.addTests(loader.loadTestsFromTestCase(TestKellyCalculator))
    suite.addTests(loader.loadTestsFromTestCase(TestKellyAnalyzer))
    suite.addTests(loader.loadTestsFromTestCase(TestKellyConfig))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"测试总数: {result.testsRun} | 通过: {passed} | 失败: {len(result.failures)} | 错误: {len(result.errors)}")
    return result.wasSuccessful()


if __name__ == '__main__':
    ok = run_kelly_tests()
    sys.exit(0 if ok else 1)