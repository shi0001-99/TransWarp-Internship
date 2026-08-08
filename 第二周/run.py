#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TransAlpha 量化投资系统 — CLI 启动脚本
======================================

用法:
  python run.py              # 运行完整流水线
  python run.py --screen     # 仅运行选股筛选
  python run.py --analyze    # 仅运行趋势分析
  python run.py --kelly      # 仅运行凯利仓位
  python run.py --monitor    # 仅运行实时监控
  python run.py --status     # 查看当前状态
  python run.py --reset      # 重置流水线

源代码位于 src/ 目录
测试位于 tests/ 目录
文档位于 docs/ 目录
中间结果位于 output/ 目录
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
SRC_DIR = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def main():
    print("=" * 50)
    print("  TransAlpha 量化投资系统 (CLI)")
    print("  启动入口: run.py")
    print("  源代码:   src/")
    print("  测试:     tests/")
    print("  输出:     output/")
    print("=" * 50)
    print()

    args = sys.argv[1:]
    if not args:
        args = ["run"]

    try:
        from src.pipeline import main as pipeline_main
        sys.argv = sys.argv[:1] + args
        pipeline_main()
    except ImportError as e:
        print(f"启动失败: {e}")
        print("   请先安装依赖: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"运行异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()