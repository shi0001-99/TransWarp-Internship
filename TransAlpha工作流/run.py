#!/usr/bin/env python
"""
TransAlpha 量化投资系统 - CLI 入口 (对应 docs/workflow/main_auto_workflow.md)

8 个自动化环节 + 4 个人工审查暂停点：
  ③ 信息收集 → ⓪ 人工审查① → ④ 公司研究 → ⓪ 人工审查②
  → ⑤ 因子打分 → ⑥ 组合构建 → ⓪ 人工审查③
  → ⑦ 回测校验 → ⑧ 风险检查 → ⓪ 人工审查④
  → ⑨ 调仓执行 → ⑩ 归因复盘

用法:
  python run.py              # 运行完整流水线 (8环节, 4个暂停)
  python run.py --collect    # 仅 ③ 信息收集
  python run.py --research   # 仅 ④ 公司研究（依赖③结果）
  python run.py --score      # 仅 ⑤ 因子打分（依赖④结果）
  python run.py --portfolio  # 仅 ⑥ 组合构建（依赖⑤结果）
  python run.py --backtest   # 仅 ⑦ 回测校验
  python run.py --risk       # 仅 ⑧ 风险检查（依赖⑦结果）
  python run.py --rebalance  # 仅 ⑨ 调仓执行
  python run.py --review     # 仅 ⑩ 归因复盘
  python run.py --status     # 查看当前流水线状态
  python run.py --reset      # 重置流水线 (清空输出)

自动化跳过审查（无人值守测试用）:
  python run.py --auto-approve   # 4个人工审查点全部自动放行
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline import (          # noqa: E402
    run_pipeline,
    run_info_collection_stage,
    run_company_research_stage,
    run_factor_scoring_stage,
    run_portfolio_stage,
    run_backtest_stage,
    run_risk_check_stage,
    run_rebalance_stage,
    run_attribution_stage,
    show_status,
    reset_pipeline,
    set_auto_approve,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run.py",
        description="TransAlpha 量化投资系统 CLI (10步流水线, 对应 main_auto_workflow.md)",
    )
    p.add_argument("--collect", action="store_true", help="仅 ③ 信息收集")
    p.add_argument("--research", action="store_true", help="仅 ④ 公司研究")
    p.add_argument("--score", action="store_true", help="仅 ⑤ 因子打分")
    p.add_argument("--portfolio", action="store_true", help="仅 ⑥ 组合构建")
    p.add_argument("--backtest", action="store_true", help="仅 ⑦ 回测校验")
    p.add_argument("--risk", action="store_true", help="仅 ⑧ 风险检查")
    p.add_argument("--rebalance", action="store_true", help="仅 ⑨ 调仓执行")
    p.add_argument("--review", action="store_true", help="仅 ⑩ 归因复盘")
    p.add_argument("--status", action="store_true", help="查看当前流水线状态")
    p.add_argument("--reset", action="store_true", help="重置流水线并清空所有输出")
    p.add_argument("--auto-approve", action="store_true",
                   help="无人值守模式: 4个人工审查点自动放行（用于测试/CI）")
    p.add_argument("--start-stage", type=int, default=1,
                   help="流水线启动位置: 1=③开始 3=④开始 5=⑤开始 7=⑥开始 9=⑦开始 11=⑧开始 13=⑨开始 15=⑩开始")
    p.add_argument("--top-n", type=int, default=10, help="⑤因子打分 Top N (默认10)")
    p.add_argument("--research-top-n", type=int, default=50,
                   help="④公司研究候选上限 (默认50, 牛市可放大到100)")
    p.add_argument("--per-sector-quota", type=int, default=15,
                   help="方案C 每板块固定配额 (默认15)")
    p.add_argument("--truncation-mode", type=str, default="weighted",
                   choices=["weighted", "cap_first", "heat_first"],
                   help="方案A 截断模式: weighted=加权(默认) / cap_first=市值优先 / heat_first=热度优先")
    p.add_argument("--monitor-duration", type=int, default=10,
                   help="调仓执行/监控运行秒数 (默认10秒, 短测试用)")
    return p


def main() -> None:
    args = build_parser().parse_args()

    if args.auto_approve:
        set_auto_approve(True)

    if args.status:
        show_status()
        return
    if args.reset:
        reset_pipeline()
        return

    # 单环节模式
    if args.collect:
        run_info_collection_stage()
        return
    if args.research:
        run_company_research_stage(
            research_top_n=args.research_top_n,
            per_sector_quota=args.per_sector_quota,
            truncation_mode=args.truncation_mode,
        )
        return
    if args.score:
        run_factor_scoring_stage(top_n=args.top_n)
        return
    if args.portfolio:
        run_portfolio_stage()
        return
    if args.backtest:
        run_backtest_stage()
        return
    if args.risk:
        run_risk_check_stage()
        return
    if args.rebalance:
        run_rebalance_stage(duration=args.monitor_duration)
        return
    if args.review:
        run_attribution_stage()
        return

    # 默认: 运行完整流水线
    run_pipeline(
        start_stage=args.start_stage,
        monitor_duration=args.monitor_duration,
        top_n=args.top_n,
        research_top_n=args.research_top_n,
        per_sector_quota=args.per_sector_quota,
        truncation_mode=args.truncation_mode,
    )


if __name__ == "__main__":
    main()
