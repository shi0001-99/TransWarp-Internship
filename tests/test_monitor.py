#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor 实时监控模块测试套件
测试预警规则、分级系统、文件锁、原子写入等功能
"""

import sys
import os
import json
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "monitor"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestFileLock(unittest.TestCase):
    """测试1: 跨进程文件锁"""

    def setUp(self):
        from db_lock import file_lock, atomic_write_json, safe_read_json
        self.file_lock = file_lock
        self.atomic_write = atomic_write_json
        self.safe_read = safe_read_json
        self.tmp_dir = tempfile.mkdtemp()

    def test_file_lock_context_manager(self):
        """测试文件锁上下文管理器"""
        lock_path = os.path.join(self.tmp_dir, "test.lock")
        with self.file_lock(lock_path, timeout=2) as lock:
            self.assertIsNotNone(lock)

    def test_atomic_write_json(self):
        """测试原子写入 JSON"""
        test_path = os.path.join(self.tmp_dir, "test.json")
        test_data = {"key": "value", "number": 42, "list": [1, 2, 3]}
        self.atomic_write(test_path, test_data)
        result = self.safe_read(test_path)
        self.assertEqual(result, test_data)

    def test_safe_read_nonexistent(self):
        """测试读取不存在的文件"""
        result = self.safe_read("/nonexistent/path/file.json", default={})
        self.assertEqual(result, {})

    def test_safe_read_corrupted(self):
        """测试读取损坏的 JSON"""
        corrupt_path = os.path.join(self.tmp_dir, "corrupt.json")
        with open(corrupt_path, 'w') as f:
            f.write("not valid json{{{")
        result = self.safe_read(corrupt_path, default={"fallback": True})
        self.assertEqual(result, {"fallback": True})

    def test_atomic_write_creates_directory(self):
        """测试原子写入自动创建目录"""
        deep_path = os.path.join(self.tmp_dir, "a", "b", "c", "test.json")
        self.atomic_write(deep_path, {"nested": True})
        result = self.safe_read(deep_path)
        self.assertEqual(result, {"nested": True})


class TestAlertRules(unittest.TestCase):
    """测试2: 七大预警规则"""

    def setUp(self):
        from monitor import StockAlert
        self.monitor = StockAlert(log_to_file=False, log_to_console=False)

    def test_cost_percentage_above(self):
        """测试盈利百分比预警"""
        stock = {
            "code": "600519", "name": "贵州茅台", "type": "individual",
            "cost": 1000.0,
            "alerts": {"cost_pct_above": 15.0, "cost_pct_below": -10.0}
        }
        data = {"price": 1150.0, "prev_close": 1000.0}
        alerts, level = self.monitor.check_alerts(stock, data)
        self.assertGreater(len(alerts), 0, "盈利15%应触发预警")

    def test_cost_percentage_below(self):
        """测试亏损百分比预警"""
        stock = {
            "code": "600519", "name": "贵州茅台", "type": "individual",
            "cost": 1000.0,
            "alerts": {"cost_pct_above": 15.0, "cost_pct_below": -10.0}
        }
        data = {"price": 880.0, "prev_close": 1000.0}
        alerts, level = self.monitor.check_alerts(stock, data)
        self.assertGreater(len(alerts), 0, "亏损12%应触发预警")

    def test_change_pct_alert(self):
        """测试日内涨跌幅预警"""
        stock = {
            "code": "600519", "name": "贵州茅台", "type": "individual",
            "cost": 1000.0,
            "alerts": {"change_pct_above": 4.0, "change_pct_below": -4.0}
        }
        data = {"price": 1050.0, "prev_close": 1000.0}
        alerts, level = self.monitor.check_alerts(stock, data)
        has_change = any('大涨' in text or '大跌' in text for _, text in alerts)
        self.assertTrue(has_change, "日内涨幅5%应触发预警")

    def test_volume_surge_detection(self):
        """测试放量异动检测"""
        stock = {
            "code": "600519", "name": "贵州茅台", "type": "individual",
            "cost": 1000.0,
            "alerts": {"volume_surge": 2.0}
        }
        data = {"price": 1020.0, "prev_close": 1000.0, "volume": 50000, "volume_ma5": 10000}
        alerts, level = self.monitor.check_alerts(stock, data)
        has_volume = any('放量' in text or '缩量' in text for _, text in alerts)
        self.assertTrue(has_volume, "成交量5日均量5倍应触发放量预警")


class TestAlertLevel(unittest.TestCase):
    """测试3: 分级预警系统"""

    def setUp(self):
        from monitor import StockAlert
        self.monitor = StockAlert(log_to_file=False, log_to_console=False)

    def test_critical_level(self):
        """测试紧急级别判定"""
        weights = [3, 3, 3]
        level = self.monitor._calculate_alert_level([('a', 'x'), ('b', 'x'), ('c', 'x')], weights, 'individual')
        self.assertEqual(level, 'critical')

    def test_warning_level(self):
        """测试警告级别判定"""
        weights = [2, 2]
        level = self.monitor._calculate_alert_level([('a', 'x'), ('b', 'x')], weights, 'individual')
        self.assertEqual(level, 'warning')

    def test_info_level(self):
        """测试提醒级别判定"""
        weights = [1]
        level = self.monitor._calculate_alert_level([('a', 'x')], weights, 'individual')
        self.assertEqual(level, 'info')

    def test_etf_threshold_difference(self):
        """测试 ETF 与个股阈值差异"""
        stock = [s for s in self.monitor.watchlist if s.get('type') == 'individual']
        if stock:
            self.assertEqual(stock[0]['alerts']['change_pct_above'], 4.0)
        etf = [s for s in self.monitor.watchlist if s.get('type') == 'etf']
        if etf:
            self.assertEqual(etf[0]['alerts']['change_pct_above'], 2.0)


class TestSmartSchedule(unittest.TestCase):
    """测试4: 智能监控频率"""

    def setUp(self):
        from monitor import StockAlert
        self.monitor = StockAlert(log_to_file=False, log_to_console=False)

    def test_schedule_returns_mode(self):
        """测试调度返回模式"""
        schedule = self.monitor.should_run_now()
        self.assertIn('mode', schedule)
        self.assertIn(schedule['mode'], ['market', 'lunch', 'after_hours', 'night', 'weekend'])

    def test_interval_is_valid(self):
        """测试间隔值有效"""
        schedule = self.monitor.should_run_now()
        interval = schedule.get('interval', 0)
        self.assertGreater(interval, 0)
        self.assertIn(interval, [60, 300, 600, 1800, 3600])


class TestMonitorIntegration(unittest.TestCase):
    """测试5: 监控集成测试"""

    def setUp(self):
        from monitor import StockAlert
        self.monitor = StockAlert(log_to_file=False, log_to_console=False)

    def test_watchlist_structure(self):
        """测试 watchlist 数据结构"""
        for stock in self.monitor.watchlist:
            self.assertIn('code', stock)
            self.assertIn('name', stock)
            self.assertIn('type', stock)
            self.assertIn('alerts', stock)

    def test_run_once_returns_list(self):
        """测试 run_once 返回类型"""
        result = self.monitor.run_once(smart_mode=False)
        self.assertIsInstance(result, list)

    def test_duplicate_alert_prevention(self):
        """测试防重复预警机制"""
        stock = self.monitor.watchlist[0]
        data = self.monitor.fetch_sina_realtime([stock['code']])
        if stock['code'] in data:
            alerts1, _ = self.monitor.check_alerts(stock, data[stock['code']])
            for alert_type, _ in alerts1:
                self.monitor.record_alert(stock['code'], alert_type)
            alerts2, _ = self.monitor.check_alerts(stock, data[stock['code']])
            self.assertEqual(len(alerts2), 0, "30分钟内不应重复触发相同预警")


def run_monitor_tests():
    """运行所有 Monitor 模块测试"""
    print("=" * 60)
    print("📡 Monitor 实时监控模块 — 测试套件")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestFileLock))
    suite.addTests(loader.loadTestsFromTestCase(TestAlertRules))
    suite.addTests(loader.loadTestsFromTestCase(TestAlertLevel))
    suite.addTests(loader.loadTestsFromTestCase(TestSmartSchedule))
    suite.addTests(loader.loadTestsFromTestCase(TestMonitorIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"测试总数: {result.testsRun} | 通过: {passed} | 失败: {len(result.failures)} | 错误: {len(result.errors)}")
    return result.wasSuccessful()


if __name__ == '__main__':
    ok = run_monitor_tests()
    sys.exit(0 if ok else 1)