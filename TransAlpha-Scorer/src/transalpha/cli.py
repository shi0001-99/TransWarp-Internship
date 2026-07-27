import argparse
import json
import sys
import os
from datetime import datetime
from .scoring.composite_scorer import CompositeScorer
from .scoring.position_sizer import PositionSizer
from .config import SCORING_CONFIG


def print_score_result(result: dict, position: dict = None):
    print("=" * 60)
    print(f"股票代码: {result['stock_code']}")
    print(f"股票名称: {result['stock_name']}")
    print(f"所属行业: {result['industry']}")
    print("-" * 60)

    if result["is_blacklisted"]:
        print("【黑名单剔除】")
        for reason in result["blacklist_reasons"]:
            print(f"  - {reason}")
        print("=" * 60)
        return

    print("【价值基本面维度】(权重40%)")
    vf = result["value_fundamental"]
    print(f"  PE分位打分: {vf['pe_score']}分")
    print(f"  PB分位打分: {vf['pb_score']}分")
    print(f"  ROE打分: {vf['roe_score']}分")
    print(f"  现金流打分: {vf['cash_flow_score']}分")
    print(f"  增长稳定性打分: {vf['growth_stability_score']}分")
    print(f"  盈利质量打分: {vf['earnings_quality_score']}分")
    print(f"  资产负债率打分: {vf['debt_ratio_score']}分")
    print(f"  -> 价值基本面总分: {vf['value_fundamental_score']}分")
    print()

    print("【趋势动量维度】(权重45%)")
    tm = result["trend_momentum"]
    print(f"  5日涨跌幅打分: {tm['five_day_return_score']}分")
    print(f"  20日涨跌幅打分: {tm['twenty_day_return_score']}分")
    print(f"  60日动量打分: {tm['sixty_day_momentum_score']}分")
    print(f"  资金流入周期打分: {tm['fund_inflow_days_score']}分")
    print(f"  -> 趋势动量总分: {tm['trend_momentum_score']}分")
    if tm["is_chase_high"]:
        print(f"  追高预警: 近3日涨幅{tm['three_day_return']:.1f}%")
    print()

    print("【四大维度打分】")
    dim = result["dimensions"]
    print(f"  宏观维度打分: {dim['macro_score']}分 (权重15%)")
    print(f"  资金维度打分: {dim['fund_flow_score']}分 (权重10%)")
    print(f"  事件消息打分: {dim['event_score']}分 (权重10%)")
    print()

    print("【综合Alpha总分】")
    print(f"  综合得分: {result['overall_score']}分")
    print(f"  评级: {result['rating']}")
    print(f"  是否进入候选池: {'是' if result['meets_threshold'] else '否'}")
    print()

    if result["warnings"]:
        print("【风控预警】")
        for warning in result["warnings"]:
            print(f"  - {warning}")

    if position:
        print()
        print("【持仓建议】")
        print(f"  建议仓位比例: {position['suggested_ratio']}%")
        print(f"  建议持仓市值: {position['suggested_value']:.0f}元")
        if position['suggested_shares']:
            print(f"  建议持仓股数: {position['suggested_shares']}股")
        print(f"  操作建议: {position['action']}")

    print("=" * 60)


def print_batch_summary(suggestions: list):
    print("\n" + "=" * 70)
    print("【批量评分汇总 & 持仓建议】")
    print("=" * 70)
    print(f"{'代码':<10} {'名称':<10} {'综合得分':<8} {'评级':<8} {'建议仓位':<8} {'建议市值':<12} {'建议':<10}")
    print("-" * 70)
    for s in suggestions:
        print(f"{s['stock_code']:<10} {s['stock_name']:<10} {s['overall_score']:<8} {s['rating']:<8} {str(s['suggested_ratio'])+'%':<8} {s['suggested_value']:<12.0f} {s['action']:<10}")
    print("=" * 70)


def save_results(results: list, output_dir: str = "output"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"batch_score_{timestamp}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"结果已保存至: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="TransAlpha小组个股多维度融合打分系统")
    parser.add_argument("stock_codes", nargs="*", help="股票代码（如：000001.SZ），可多个")
    parser.add_argument("-b", "--batch", help="批量评分，逗号分隔股票代码")
    parser.add_argument("-o", "--output", action="store_true", help="保存结果到文件")
    parser.add_argument("-j", "--json", action="store_true", help="输出JSON格式")
    parser.add_argument("--config", action="store_true", help="显示当前打分配置")
    parser.add_argument("--capital", type=float, default=1000000, help="总资金（默认100万）")
    parser.add_argument("--max-positions", type=int, default=5, help="最大持仓数（默认5）")

    args = parser.parse_args()

    if args.config:
        print(json.dumps(SCORING_CONFIG, ensure_ascii=False, indent=2))
        return

    codes = []
    if args.batch:
        codes = [c.strip() for c in args.batch.split(",") if c.strip()]
    elif args.stock_codes:
        codes = args.stock_codes
    else:
        parser.print_help()
        return

    scorer = CompositeScorer()
    sizer = PositionSizer(total_capital=args.capital, max_positions=args.max_positions)

    results = []
    for code in codes:
        try:
            result = scorer.calculate_composite_score(code)
            results.append(result)
        except Exception as e:
            print(f"{code} 计算失败: {e}", file=sys.stderr)

    if args.output:
        save_results(results)

    if len(codes) == 1 and not args.batch:
        r = results[0] if results else None
        if r:
            pos = sizer.suggest_single_position(r, None)
            if args.json:
                output = {**r, "position_suggestion": pos}
                print(json.dumps(output, ensure_ascii=False, indent=2))
            else:
                print_score_result(r, pos)
    else:
        suggestions = sizer.suggest_portfolio(results, {})
        if args.json:
            print(json.dumps(suggestions, ensure_ascii=False, indent=2))
        else:
            for r in results:
                pos = next((s for s in suggestions if s.get("stock_code") == r.get("stock_code")), None)
                print_score_result(r, pos)
            print_batch_summary(suggestions)


if __name__ == "__main__":
    main()
