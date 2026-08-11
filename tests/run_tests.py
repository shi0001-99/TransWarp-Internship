#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TransAlpha 量化投资系统 — 测试运行器
一键运行所有模块测试

用法: python run_tests.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
TESTS_DIR = Path(__file__).parent.resolve()

sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(TESTS_DIR))

def main():
    print("=" * 70)
    print("🧪 TransAlpha 量化投资系统 — 全模块测试")
    print("=" * 70)
    print()

    results = {}
    test_modules = [
        ("test_kelly", "📊 Kelly 凯利分析模块"),
        ("test_monitor", "📡 Monitor 实时监控模块"),
        ("test_trend", "📈 Trend 趋势分析模块"),
        ("test_integration", "🔗 集成测试"),
    ]

    for module_name, display_name in test_modules:
        print(f"\n{'─' * 50}")
        print(f"运行 {display_name}...")
        print(f"{'─' * 50}")

        try:
            module = __import__(module_name)
            runner_func = getattr(module, f'run_{module_name.split("_", 1)[1]}_tests', None)

            if runner_func:
                results[display_name] = runner_func()
            else:
                import unittest
                loader = unittest.TestLoader()
                suite = loader.loadTestsFromModule(module)
                runner = unittest.TextTestRunner(verbosity=0)
                result = runner.run(suite)
                results[display_name] = result.wasSuccessful()

        except Exception as e:
            print(f"❌ {display_name} 执行异常: {e}")
            results[display_name] = False

    print(f"\n{'=' * 70}")
    print("📊 测试总结")
    print(f"{'=' * 70}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed

    for name, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {status}  {name}")

    print(f"\n  总计: {total} 个测试套件, {passed} 通过, {failed} 失败")

    if failed == 0:
        print("\n🎉 所有测试通过！")
    else:
        print(f"\n⚠️  有 {failed} 个测试套件失败，请检查日志")

    return failed == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)