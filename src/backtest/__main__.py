# -*- coding: utf-8 -*-
"""回测模块独立 CLI 入口：python -m src.backtest --start ... --end ...

示例:
  python -m src.backtest --start 2023-01-01 --end 2024-06-30
  python -m src.backtest --start 2023-01-01 --end 2024-06-30 \
      --pool 600519 000858 --rebalance weekly --top 5
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TransAlpha ⑧ 回测校验")
    parser.add_argument("--start", required=True, help="起始日 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日 YYYY-MM-DD")
    parser.add_argument("--pool", default=None, help="候选池，逗号分隔代码；缺省=中证500成分")
    parser.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly"])
    parser.add_argument("--top", type=int, default=5, help="每期选 N 只")
    parser.add_argument("--capital", type=float, default=1_000_000.0, help="初始资金")
    parser.add_argument("--out", default=None, help="输出目录（缺省 output/backtest）")
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    args = parser.parse_args(argv)

    from .runner import BacktestConfig, BacktestRunner
    from .report import export_backtest_result
    from pathlib import Path

    pool = [s.strip() for s in args.pool.split(",")] if args.pool else None

    cfg = BacktestConfig(
        initial_capital=args.capital,
        start_date=args.start, end_date=args.end,
        rebalance=args.rebalance, top_n=args.top,
    )
    runner = BacktestRunner(cfg=cfg)
    result = runner.run(stock_pool=pool)

    paths = export_backtest_result(
        result, output_dir=Path(args.out) if args.out else None)

    m = result.get("metrics", {})
    print("\n=== 回测完成 ===")
    print(f"区间: {result.get('start_date')} ~ {result.get('end_date')}")
    print(f"候选池规模: {result.get('pool_size')}")
    print(f"累计收益: {m.get('total_return', 0):.2%}")
    print(f"年化: {m.get('annual_return', 0):.2%}   夏普: {m.get('sharpe', 0):.2f}")
    print(f"最大回撤: {m.get('max_drawdown', 0):.2%}   Calmar: {m.get('calmar', 0):.2f}")
    print(f"交易笔数: {m.get('n_trades', 0)}   胜率: {m.get('win_rate', 0):.2%}")
    print("\n输出文件:")
    for name, p in paths.items():
        print(f"  {name}: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())