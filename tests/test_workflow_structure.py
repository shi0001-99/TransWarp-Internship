#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TransAlpha 工作流结构验证测试脚本

模拟运行 8 步工作流（③~⑩），生成各环节的 mock 输出文件，
然后验证 output/ 目录结构是否与 docs/workflow 文档定义一致。

用法：
    python test_workflow_structure.py           # 生成mock + 验证
    python test_workflow_structure.py --validate # 仅验证（不生成mock）
    python test_workflow_structure.py --clean    # 清理mock文件
"""
import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# 项目根目录（tests/ 的上一级）
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

# ============================================================
# 期望的目录结构定义（依据 docs/workflow/main_auto_workflow.md）
# ============================================================
EXPECTED_STRUCTURE = {
    # 环节③ 信息收集
    "info-collection": {
        "step": "③ 信息收集",
        "files": {
            "market_data.json": {
                "required_fields": ["timestamp", "data_source", "degraded", "total_stocks", "stocks"],
            },
        },
    },
    # 环节④ 公司研究
    "company-research": {
        "step": "④ 公司研究",
        "files": {
            "research_reports.json": {
                "required_fields": ["timestamp", "total_researched", "reports"],
            },
        },
    },
    # 环节⑤ 因子打分
    "factor-scoring": {
        "step": "⑤ 因子打分",
        "files": {
            "top10_stocks.json": {
                "required_fields": ["success", "data"],
            },
        },
    },
    # 环节⑥ 组合构建
    "portfolio-construction": {
        "step": "⑥ 组合构建",
        "files": {
            "portfolio.json": {
                "required_fields": ["date", "total_position", "positions"],
            },
        },
    },
    # 环节⑦ 回测校验
    "backtest": {
        "step": "⑦ 回测校验",
        "files": {
            "equity_curve.csv": {"is_csv": True},
            "metrics.json": {
                "required_fields": [],  # 回测指标字段不固定，只校验JSON合法性
            },
            "trade_log.csv": {"is_csv": True},
        },
    },
    # 环节⑧ 风险检查
    "risk-check": {
        "step": "⑧ 风险检查",
        "files": {
            "risk_report.json": {
                "required_fields": ["timestamp", "overall_verdict", "passed", "checks"],
            },
        },
    },
    # 环节⑨ 调仓执行
    "rebalance-execution": {
        "step": "⑨ 调仓执行",
        "files": {
            "orders.json": {
                "required_fields": ["timestamp", "total_orders", "orders"],
            },
            "alerts.json": {
                "required_fields": [],  # 可能为空列表
            },
        },
    },
    # 环节⑩ 归因复盘
    "attribution-review": {
        "step": "⑩ 归因复盘",
        "files": {
            "review_log.md": {"is_markdown": True},
        },
    },
}

# 旧目录（历史遗留，允许存在但不强制要求）
LEGACY_DIRS = ["screening", "trend", "kelly", "monitor"]

# 信仰手册风险红线（用于验证 portfolio.json 仓位约束）
RISK_LIMITS = {
    "single_max": 0.10,      # 单票最大仓位 10%
    "industry_max": 0.30,    # 单行业最大仓位 30%
    "total_max": 0.80,       # 总仓位上限 80%
    "max_holding_days": 3,   # 最大持仓天数 3天
}


# ============================================================
# Mock 数据生成器（模拟8步工作流输出）
# ============================================================
def _mock_stock(code, name, industry, price, score, **extra):
    """生成单只股票的 mock 数据"""
    base = {
        "code": code,
        "name": name,
        "industry_level1": industry.split(".")[0],
        "industry_level2": industry,
        "price": price,
        "score": score,
    }
    base.update(extra)
    return base


def gen_info_collection():
    """③ 信息收集 mock 输出"""
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "data_source": "akshare_stock_zh_a_spot",
        "degraded": False,
        "degrade_reason": None,
        "total_stocks": 5538,
        "data_completeness": {
            "quotes_coverage": 0.98,
            "fundamental_coverage": 0.85,
            "northbound_coverage": 0.36,
            "dragon_tiger_coverage": 0.05,
        },
        "sector_heat": {
            "半导体设备": {"total_score": 89, "decision": "首选介入"},
            "食品饮料（白酒）": {"total_score": 78, "decision": "首选介入"},
            "有色金属（黄金）": {"total_score": 73, "decision": "观察参与"},
        },
        "stocks": [
            _mock_stock("600519", "贵州茅台", "消费.白酒", 1685.50, 85.2,
                        pe=28.5, pb=8.2, turnover_rate=0.8, ma_alignment="bullish"),
            _mock_stock("300750", "宁德时代", "新能源.锂电", 218.30, 82.1,
                        pe=35.2, pb=4.1, turnover_rate=2.1, ma_alignment="bullish"),
            _mock_stock("601398", "工商银行", "金融.国有大行", 5.42, 72.5,
                        pe=5.8, pb=0.65, turnover_rate=0.3, ma_alignment="neutral"),
        ],
    }


def gen_company_research():
    """④ 公司研究 mock 输出"""
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total_researched": 3,
        "sector_focus": ["半导体设备", "食品饮料（白酒）", "有色金属（黄金）"],
        "reports": [
            {
                "code": "600519", "name": "贵州茅台",
                "industry_level2": "消费.白酒",
                "sector_heat_score": 78, "sector_decision": "首选介入",
                "fundamental": {"roe": 30.5, "revenue_growth": 18.2,
                                "free_cash_flow_positive": True, "debt_ratio": 22.5},
                "competitive_position": {"market_share": "高端白酒60%+",
                                         "core_moat": "品牌壁垒+渠道控制力", "industry_rank": 1},
                "catalyst": {"short_term": "中秋旺季预期", "capital_signal": "北向连续3日净买入",
                             "technical": "均线多头排列", "leader_type": "空间龙头"},
                "risks": {"valuation": "PE 28.5倍偏高", "unlock": "无", "goodwill": "低", "sentiment": "正常"},
                "research_conclusion": "推荐进入打分环节",
                "core_barrier": "高端白酒品牌壁垒+渠道定价权",
            },
        ],
    }


def gen_factor_scoring():
    """⑤ 因子打分 mock 输出"""
    return {
        "success": True,
        "data": {
            "last_update": datetime.now().isoformat(timespec="seconds"),
            "total_results": 3,
            "top_stocks": [
                {
                    "rank": 1, "code": "600519", "name": "贵州茅台", "price": 1685.50,
                    "total_score": 85.2, "fundamental_score": 35.2, "trend_score": 18.2,
                    "volume_price_score": 11.8, "capital_score": 21.5,
                    "grade": "⭐⭐⭐⭐⭐ 优秀",
                    "advice": "✅ 积极建仓：消费.白酒行业，四流派均衡得分",
                    "industry_level2": "消费.白酒",
                },
                {
                    "rank": 2, "code": "300750", "name": "宁德时代", "price": 218.30,
                    "total_score": 82.1, "fundamental_score": 33.5, "trend_score": 17.0,
                    "volume_price_score": 10.5, "capital_score": 21.1,
                    "grade": "⭐⭐⭐⭐ 良好",
                    "advice": "✅ 积极建仓：新能源.锂电行业，基本面优秀",
                    "industry_level2": "新能源.锂电",
                },
                {
                    "rank": 3, "code": "601398", "name": "工商银行", "price": 5.42,
                    "total_score": 72.5, "fundamental_score": 30.0, "trend_score": 14.5,
                    "volume_price_score": 9.0, "capital_score": 19.0,
                    "grade": "⭐⭐⭐ 中性",
                    "advice": "⚠️ 谨慎关注：金融.国有大行行业，基本面良好",
                    "industry_level2": "金融.国有大行",
                },
            ],
        },
    }


def gen_portfolio():
    """⑥ 组合构建 mock 输出（严格遵守信仰手册风险红线）"""
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_position": 25.0,   # ≤ 80%
        "cash_reserve": 75.0,
        "positions": [
            {
                "code": "600519", "name": "贵州茅台", "industry": "消费.白酒",
                "score": 85.2, "kelly_position": 10.0, "adjusted_position": 8.5,  # ≤ 10%
                "buy_price_range": [1680, 1720], "holding_days_max": 3,           # ≤ 3天
            },
            {
                "code": "300750", "name": "宁德时代", "industry": "新能源.锂电",
                "score": 82.1, "kelly_position": 10.0, "adjusted_position": 8.5,
                "buy_price_range": [210, 225], "holding_days_max": 3,
            },
            {
                "code": "601398", "name": "工商银行", "industry": "金融.国有大行",
                "score": 72.5, "kelly_position": 8.0, "adjusted_position": 8.0,
                "buy_price_range": [5.38, 5.48], "holding_days_max": 3,
            },
        ],
        "industry_distribution": {"消费": 8.5, "新能源": 8.5, "金融": 8.0},  # 每个行业 ≤ 30%
    }


def gen_backtest_metrics():
    """⑦ 回测校验 mock 输出"""
    return {
        "start_date": "2024-01-01", "end_date": "2024-06-30",
        "initial_capital": 1000000, "final_equity": 1122500,
        "total_return": 0.1225, "annual_return": 0.252,
        "max_drawdown": 0.083, "sharpe_ratio": 1.85,
        "win_rate": 0.62, "profit_loss_ratio": 1.8,
        "total_trades": 24, "benchmark_csi500": 0.068,
    }


def gen_risk_report():
    """⑧ 风险检查 mock 输出"""
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "overall_verdict": "放行",
        "passed": True,
        "checks": {
            "core_redlines": {
                "R1_single_max_10pct": {"passed": True, "value": "max=8.5%"},
                "R2_max_drawdown_5pct": {"passed": True, "value": "4.2%"},
                "R3_industry_max_30pct": {"passed": True, "value": "max=8.5%"},
                "R4_daily_loss_2pct": {"passed": True, "value": "max=-1.2%"},
                "R5_max_holding_3days": {"passed": True, "value": "max=3天"},
            },
            "structure": {
                "R6_min_5_stocks": {"passed": False, "value": "3只", "action": "从观察池补入"},
                "R7_min_3_industries": {"passed": True, "value": "3个行业"},
            },
            "market_timing": {"status": "牛市", "position_adjustment": "正常仓位"},
        },
        "failed_items": [
            {"check_id": "R6", "issue": "持仓数量不足5只", "action": "从观察池补入", "retry_suggested": False},
        ],
        "retry_suggestion": None,
    }


def gen_orders():
    """⑨ 调仓执行 mock 输出"""
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total_orders": 3,
        "orders": [
            {
                "order_id": f"ORD-{datetime.now().strftime('%Y%m%d')}-001",
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "code": "600519", "name": "贵州茅台", "action": "buy",
                "price": 1685.50, "shares": 5, "amount": 8427.50,
                "position_pct": 8.5, "reason": "因子打分85.2分+风控放行",
                "score": 85.2, "risk_check_passed": True,
            },
        ],
        "sell_plans": [
            {
                "code": "600519", "buy_price": 1685.50,
                "stop_loss_price": 1651.79, "stop_loss_pct": -2.0,
                "target_sell_prices": [
                    {"level": 1, "profit_pct": 3, "price": 1736.07, "position_to_sell": 0.3},
                    {"level": 2, "profit_pct": 5, "price": 1769.78, "position_to_sell": 0.3},
                ],
                "t3_force_close_date": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
            },
        ],
    }


def gen_alerts():
    """⑨ 调仓执行 - 预警信号 mock 输出"""
    return {"alerts": [], "last_check": datetime.now().isoformat(timespec="seconds")}


def gen_review_log():
    """⑩ 归因复盘 mock 输出（Markdown）"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return f"""# 投资复盘日志 {date_str}

## 1. 本期组合表现
- 总收益率：12.25%
- 基准（沪深300）：6.80%
- 超额收益：5.45%
- 最大回撤：8.3%
- 胜率：62%
- 盈亏比：1.8

## 2. 收益归因
| 来源 | 贡献 | 类型 | 说明 |
|------|------|------|------|
| 赛道贡献 | 4.2% | 运气 | 消费板块普涨 |
| 个股 Alpha | 6.8% | 方法论 | 茅台超额收益 |
| 择时收益 | 1.25% | 方法论 | MA20择时有效 |
| 随机误差 | 0% | 不可解释 | |

## 3. 规则遵守检查
| 规则 | 是否遵守 | 违规情况 | 改进措施 |
|------|----------|----------|----------|
| 单票≤10% | ✅ | 无 | - |
| 单行业≤30% | ✅ | 无 | - |
| T+3强制平仓 | ✅ | 无 | - |
| 止损-2% | ✅ | 无 | - |

## 4. 方法论更新建议
- 打分规则：无调整
- 风控规则：无调整
- 信仰手册：无调整
- 赛道打分表：消费板块权重维持
"""


# ============================================================
# 文件写入器
# ============================================================
def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, data: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def write_csv(path: Path, header: str, rows: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


# ============================================================
# Mock 生成主函数
# ============================================================
def generate_mock_outputs():
    """模拟运行8步工作流，生成各环节mock输出文件"""
    print("=" * 70)
    print("🔄 模拟运行 8 步工作流（③~⑩），生成 mock 输出文件...")
    print("=" * 70)

    # ③ 信息收集
    print("  ③ 信息收集 → output/info-collection/market_data.json")
    write_json(OUTPUT_DIR / "info-collection" / "market_data.json", gen_info_collection())

    # ④ 公司研究
    print("  ④ 公司研究 → output/company-research/research_reports.json")
    write_json(OUTPUT_DIR / "company-research" / "research_reports.json", gen_company_research())

    # ⑤ 因子打分
    print("  ⑤ 因子打分 → output/factor-scoring/top10_stocks.json")
    write_json(OUTPUT_DIR / "factor-scoring" / "top10_stocks.json", gen_factor_scoring())

    # ⑥ 组合构建
    print("  ⑥ 组合构建 → output/portfolio-construction/portfolio.json")
    write_json(OUTPUT_DIR / "portfolio-construction" / "portfolio.json", gen_portfolio())

    # ⑦ 回测校验
    print("  ⑦ 回测校验 → output/backtest/")
    write_csv(OUTPUT_DIR / "backtest" / "equity_curve.csv",
              "date,equity,equity_norm,ret,csi500,hs300",
              ["2024-01-01,1000000,1.0,0,0,0", "2024-06-30,1122500,1.1225,0.005,0.003,0.002"])
    write_json(OUTPUT_DIR / "backtest" / "metrics.json", gen_backtest_metrics())
    write_csv(OUTPUT_DIR / "backtest" / "trade_log.csv",
              "date,code,action,price,shares,amount,profit",
              ["2024-01-05,600519,buy,1685.5,5,8427.5,0",
               "2024-02-10,600519,sell,1736.0,5,8680.0,252.5"])

    # ⑧ 风险检查
    print("  ⑧ 风险检查 → output/risk-check/risk_report.json")
    write_json(OUTPUT_DIR / "risk-check" / "risk_report.json", gen_risk_report())

    # ⑨ 调仓执行
    print("  ⑨ 调仓执行 → output/rebalance-execution/")
    write_json(OUTPUT_DIR / "rebalance-execution" / "orders.json", gen_orders())
    write_json(OUTPUT_DIR / "rebalance-execution" / "alerts.json", gen_alerts())

    # ⑩ 归因复盘
    print("  ⑩ 归因复盘 → output/attribution-review/review_log.md")
    write_text(OUTPUT_DIR / "attribution-review" / "review_log.md", gen_review_log())

    print(f"\n✅ Mock 输出生成完成，共 {len(EXPECTED_STRUCTURE)} 个环节\n")


# ============================================================
# 验证器
# ============================================================
class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.details = []

    def pass_(self, msg):
        self.passed += 1
        self.details.append(("✅ PASS", msg))

    def fail(self, msg):
        self.failed += 1
        self.details.append(("❌ FAIL", msg))

    # fail_ 别名（兼容调用）
    fail_ = fail

    def warn(self, msg):
        self.warnings += 1
        self.details.append(("⚠️  WARN", msg))

    # warn_ 别名（兼容调用）
    warn_ = warn

    def summary(self):
        total = self.passed + self.failed
        rate = (self.passed / total * 100) if total > 0 else 0
        return f"通过 {self.passed}/{total}（{rate:.0f}%），失败 {self.failed}，警告 {self.warnings}"


def validate_directory_structure(result: TestResult):
    """验证1：8个输出目录是否全部存在"""
    print("\n[验证1] 输出目录结构（8个环节）")
    print("-" * 50)
    for dirname, config in EXPECTED_STRUCTURE.items():
        dirpath = OUTPUT_DIR / dirname
        if dirpath.exists() and dirpath.is_dir():
            result.pass_(f"{config['step']} → output/{dirname}/ 目录存在")
        else:
            result.fail_(f"{config['step']} → output/{dirname}/ 目录不存在")


def validate_files_exist(result: TestResult):
    """验证2：每个目录的期望文件是否存在"""
    print("\n[验证2] 各环节期望文件是否存在")
    print("-" * 50)
    for dirname, config in EXPECTED_STRUCTURE.items():
        for filename in config["files"]:
            filepath = OUTPUT_DIR / dirname / filename
            if filepath.exists():
                size = filepath.stat().st_size
                result.pass_(f"output/{dirname}/{filename}（{size} bytes）")
            else:
                result.fail_(f"output/{dirname}/{filename} 文件缺失")


def validate_json_format(result: TestResult):
    """验证3：JSON 文件格式是否合法"""
    print("\n[验证3] JSON 文件格式合法性")
    print("-" * 50)
    for dirname, config in EXPECTED_STRUCTURE.items():
        for filename, spec in config["files"].items():
            if spec.get("is_csv") or spec.get("is_markdown"):
                continue
            filepath = OUTPUT_DIR / dirname / filename
            if not filepath.exists():
                continue
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                result.pass_(f"output/{dirname}/{filename} JSON 解析成功")
            except json.JSONDecodeError as e:
                result.fail_(f"output/{dirname}/{filename} JSON 解析失败：{e}")


def validate_required_fields(result: TestResult):
    """验证4：JSON 文件是否包含文档定义的必需字段"""
    print("\n[验证4] 必需字段完整性")
    print("-" * 50)
    for dirname, config in EXPECTED_STRUCTURE.items():
        for filename, spec in config["files"].items():
            required = spec.get("required_fields", [])
            if not required or spec.get("is_csv") or spec.get("is_markdown"):
                continue
            filepath = OUTPUT_DIR / dirname / filename
            if not filepath.exists():
                continue
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                missing = [f for f in required if f not in data]
                if missing:
                    result.fail_(f"output/{dirname}/{filename} 缺少字段：{missing}")
                else:
                    result.pass_(f"output/{dirname}/{filename} 必需字段完整：{required}")
            except Exception as e:
                result.fail_(f"output/{dirname}/{filename} 字段检查异常：{e}")


def validate_risk_limits(result: TestResult):
    """验证5：portfolio.json 是否符合信仰手册风险红线"""
    print("\n[验证5] 信仰手册风险红线（portfolio.json）")
    print("-" * 50)
    filepath = OUTPUT_DIR / "portfolio-construction" / "portfolio.json"
    if not filepath.exists():
        result.fail_("portfolio.json 不存在，跳过风险红线检查")
        return
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        positions = data.get("positions", [])

        # 检查单票仓位 ≤ 10%
        for pos in positions:
            pct = pos.get("adjusted_position", 0) / 100
            code = pos.get("code", "?")
            if pct > RISK_LIMITS["single_max"]:
                result.fail_(f"{code} 单票仓位 {pct:.1%} > {RISK_LIMITS['single_max']:.0%} 红线")
            else:
                result.pass_(f"{code} 单票仓位 {pct:.1%} ≤ {RISK_LIMITS['single_max']:.0%} ✓")

        # 检查单行业仓位 ≤ 30%
        industry_dist = data.get("industry_distribution", {})
        for ind, pct in industry_dist.items():
            pct_ratio = pct / 100
            if pct_ratio > RISK_LIMITS["industry_max"]:
                result.fail_(f"{ind} 行业仓位 {pct_ratio:.1%} > {RISK_LIMITS['industry_max']:.0%} 红线")
            else:
                result.pass_(f"{ind} 行业仓位 {pct_ratio:.1%} ≤ {RISK_LIMITS['industry_max']:.0%} ✓")

        # 检查总仓位 ≤ 80%
        total = data.get("total_position", 0) / 100
        if total > RISK_LIMITS["total_max"]:
            result.fail_(f"总仓位 {total:.1%} > {RISK_LIMITS['total_max']:.0%} 红线")
        else:
            result.pass_(f"总仓位 {total:.1%} ≤ {RISK_LIMITS['total_max']:.0%} ✓")

        # 检查最大持仓天数 ≤ 3
        for pos in positions:
            max_days = pos.get("holding_days_max", 999)
            code = pos.get("code", "?")
            if max_days > RISK_LIMITS["max_holding_days"]:
                result.fail_(f"{code} 持仓天数上限 {max_days} > {RISK_LIMITS['max_holding_days']} 红线")
            else:
                result.pass_(f"{code} 持仓天数上限 {max_days} ≤ {RISK_LIMITS['max_holding_days']} ✓")

    except Exception as e:
        result.fail_(f"风险红线检查异常：{e}")


def validate_pipeline_flow(result: TestResult):
    """验证6：工作流数据流连贯性（上下游字段对接）"""
    print("\n[验证6] 工作流数据流连贯性（上下游对接）")
    print("-" * 50)

    # ③→④：信息收集的 stocks 应包含公司研究的 reports 中的 code
    ic_path = OUTPUT_DIR / "info-collection" / "market_data.json"
    cr_path = OUTPUT_DIR / "company-research" / "research_reports.json"
    if ic_path.exists() and cr_path.exists():
        ic = json.loads(ic_path.read_text(encoding="utf-8"))
        cr = json.loads(cr_path.read_text(encoding="utf-8"))
        ic_codes = {s["code"] for s in ic.get("stocks", [])}
        cr_codes = {r["code"] for r in cr.get("reports", [])}
        if cr_codes.issubset(ic_codes):
            result.pass_(f"③→④ 公司研究的股票 {cr_codes} 均在信息收集台账中")
        else:
            result.fail_(f"③→④ 公司研究包含信息收集台账中不存在的股票：{cr_codes - ic_codes}")

    # ④→⑤：公司研究结论 "推荐进入打分" 的股票应在因子打分 Top10 中
    fs_path = OUTPUT_DIR / "factor-scoring" / "top10_stocks.json"
    if cr_path.exists() and fs_path.exists():
        cr = json.loads(cr_path.read_text(encoding="utf-8"))
        fs = json.loads(fs_path.read_text(encoding="utf-8"))
        recommended = {r["code"] for r in cr.get("reports", []) if "推荐" in r.get("research_conclusion", "")}
        scored = {s["code"] for s in fs.get("data", {}).get("top_stocks", [])}
        if recommended.issubset(scored):
            result.pass_(f"④→⑤ 推荐股票 {recommended} 均进入因子打分")
        else:
            result.fail(f"④→⑤ 推荐股票未全部进入打分：{recommended - scored}")

    # ⑤→⑥：因子打分 Top10 应在组合构建 positions 中
    pf_path = OUTPUT_DIR / "portfolio-construction" / "portfolio.json"
    if fs_path.exists() and pf_path.exists():
        fs = json.loads(fs_path.read_text(encoding="utf-8"))
        pf = json.loads(pf_path.read_text(encoding="utf-8"))
        scored = {s["code"] for s in fs.get("data", {}).get("top_stocks", [])}
        held = {p["code"] for p in pf.get("positions", [])}
        if held.issubset(scored):
            result.pass_(f"⑤→⑥ 组合构建持仓 {held} 均来自因子打分榜单")
        else:
            result.fail(f"⑤→⑥ 持仓包含非打分榜单股票：{held - scored}")

    # ⑥→⑧：组合构建 positions 应通过风险检查
    rc_path = OUTPUT_DIR / "risk-check" / "risk_report.json"
    if pf_path.exists() and rc_path.exists():
        pf = json.loads(pf_path.read_text(encoding="utf-8"))
        rc = json.loads(rc_path.read_text(encoding="utf-8"))
        if rc.get("passed") and len(pf.get("positions", [])) > 0:
            result.pass_("⑥→⑧ 风险检查通过，组合方案可进入调仓执行")
        else:
            result.warn_("⑥→⑧ 风险检查未通过或组合为空，需退回调整")

    # ⑧→⑨：风险检查放行后才有调仓委托
    od_path = OUTPUT_DIR / "rebalance-execution" / "orders.json"
    if rc_path.exists() and od_path.exists():
        rc = json.loads(rc_path.read_text(encoding="utf-8"))
        od = json.loads(od_path.read_text(encoding="utf-8"))
        if rc.get("passed") and od.get("total_orders", 0) > 0:
            result.pass_("⑧→⑨ 风控放行，已生成调仓委托")
        elif not rc.get("passed") and od.get("total_orders", 0) == 0:
            result.pass_("⑧→⑨ 风控未放行，无调仓委托（正确）")
        else:
            result.warn_("⑧→⑨ 风控状态与委托数量不一致")


def validate_legacy_dirs(result: TestResult):
    """验证7：旧目录处理（允许存在但提示迁移）"""
    print("\n[验证7] 旧目录迁移提示")
    print("-" * 50)
    for dirname in LEGACY_DIRS:
        dirpath = OUTPUT_DIR / dirname
        if dirpath.exists() and any(dirpath.iterdir()):
            result.warn_(f"output/{dirname}/ 存在历史文件，建议迁移到新目录结构后清理")
        elif dirpath.exists():
            result.pass_(f"output/{dirname}/ 空目录（可删除）")
        else:
            result.pass_(f"output/{dirname}/ 不存在（已迁移）")


# ============================================================
# 清理函数
# ============================================================
def clean_mock_files():
    """清理生成的 mock 文件"""
    print("🧹 清理 mock 文件...")
    cleaned = 0
    for dirname, config in EXPECTED_STRUCTURE.items():
        dirpath = OUTPUT_DIR / dirname
        if dirname == "backtest":
            continue  # backtest 可能有真实数据，不清理
        for filename in config["files"]:
            filepath = dirpath / filename
            if filepath.exists():
                filepath.unlink()
                print(f"  删除 output/{dirname}/{filename}")
                cleaned += 1
    print(f"✅ 清理完成，共删除 {cleaned} 个文件")


# ============================================================
# 主函数
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="TransAlpha 工作流结构验证测试")
    parser.add_argument("--validate", action="store_true", help="仅验证（不生成mock）")
    parser.add_argument("--clean", action="store_true", help="清理mock文件")
    args = parser.parse_args()

    if args.clean:
        clean_mock_files()
        return

    if not args.validate:
        generate_mock_outputs()

    print("\n" + "=" * 70)
    print("🔍 开始验证输出目录结构...")
    print("=" * 70)

    result = TestResult()

    validate_directory_structure(result)
    validate_files_exist(result)
    validate_json_format(result)
    validate_required_fields(result)
    validate_risk_limits(result)
    validate_pipeline_flow(result)
    validate_legacy_dirs(result)

    # 打印详细结果
    print("\n" + "=" * 70)
    print("📋 验证明细")
    print("=" * 70)
    for status, msg in result.details:
        print(f"  {status}  {msg}")

    # 打印汇总
    print("\n" + "=" * 70)
    print(f"📊 汇总：{result.summary()}")
    print("=" * 70)

    if result.failed > 0:
        print(f"\n❌ 有 {result.failed} 项检查未通过，请修复后重试")
        sys.exit(1)
    else:
        print("\n✅ 所有检查项通过！工作流目录结构正确")
        sys.exit(0)


if __name__ == "__main__":
    main()
