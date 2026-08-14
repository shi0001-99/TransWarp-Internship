# 跨域迁移法优化 TransAlpha 工作流方案

> **文档定位**：基于 `跨域迁移法_全概念实战手册.md` 的 15 个跨域概念，对 TransAlpha 量化投资流水线（8 自动环节 + 4 人工审查点）进行系统性优化的落地蓝图。
>
> **核心原则**：不搞"为迁移而迁移"，而是抓住 TransAlpha 已有的**刚性风控红线（H1–H13）+ 4 个 HABP 人机边界暂停点**，把跨域概念变成可自动触发的**审查清单 / 决策触发器 / 权重修正器**。
>
> **设计依据**：
> - `跨域迁移法_全概念实战手册.md`（15 概念 × 五环节闭环）
> - `docs/workflow/main_auto_workflow.md`（8 环节 + 4 审查点 + H1–H13 硬约束）
> - `TransAlpha小组投资信仰手册.md`（风险红线 + AI Agent 行为准则）
> - `src/pipeline.py`（流水线核心编排逻辑）

---

## 目录

- [一、总体架构：跨域概念 → 流水线环节 映射图](#一总体架构跨域概念--流水线环节-映射图)
- [二、15 个概念分学科落地详解](#二15-个概念分学科落地详解)
  - [2.1 行为心理学（概念①②③）](#21-行为心理学概念)
  - [2.2 博弈论（概念④⑤⑥）](#22-博弈论概念)
  - [2.3 认知科学（概念⑦⑧⑨）](#23-认知科学概念)
  - [2.4 社会科学（概念⑩⑪⑫）](#24-社会科学概念)
  - [2.5 行为经济学（概念⑬⑭⑮）](#25-行为经济学概念)
- [三、五个最高优先级落地项（可直接改代码）](#三五個最高优先级落地项可直接改代码)
- [四、工程层面落地建议](#四工程层面落地建议)
- [五、落地优先级路线图](#五落地优先级路线图)
- [六、HABP 协议人机边界提醒](#六habp-协议人机边界提醒)
- [七、与现有硬约束（H1–H13）的协同关系](#七与现有硬约束h1h13的协同关系)
- [八、下一步行动建议](#八下一步行动建议)

---

## 一、总体架构：跨域概念 → 流水线环节 映射图

```
③ 信息收集      ⓪ 审查①    ④ 公司研究      ⓪ 审查②    ⑤ 因子打分      ⑥ 组合构建      ⓪ 审查③    ⑦ 回测校验      ⑧ 风险检查      ⓪ 审查④    ⑨ 调仓执行      ⑩ 归因复盘
DataFetcher   → ⏸ 数据质量  → CompanyResearch → ⏸ 研究结论 → StockScreener → KellyAnalyzer → ⏸ 组合方案  → BacktestRunner → RiskChecker  → ⏸ 风控放行  → RebalanceExec → AttributionReview
(自动)          (暂停等待)    (自动)            (暂停等待)    (自动)          (自动)          (暂停等待)    (自动)           (自动)          (暂停等待)    (自动)          (自动)

嵌入概念：
[⑫弱连接]      [⑦双系统]   [⑧确认偏误]      [③过度自信]   [⑪幂律分布]    [⑪幂律分布]    [①锚定效应]   [⑬前景理论]     [②损失厌恶]    [④纳什均衡]   [②损失厌恶]    [⑦双系统]
                            [⑨心智模型]      [⑮现状偏见]                   [⑭心理账户]    [⑮现状偏见]   [⑪幂律分布]     [⑬前景理论]    [⑥囚徒困境]   [③过度自信]    [⑩网络效应]
                                                            [⑬前景理论]    [⑩网络效应]                                  [⑤信号传递]                  [⑭心理账户]
                                                                                                                                                        [⑮现状偏见]
```

### 映射表

| 环节 | 工具/模块 | 可嵌入概念 | 嵌入形式 | 影响等级 |
|---|---|---|---|---|
| ③ 信息收集 | `src/screener/data_fetcher.py` | ⑫ 弱连接理论 | 新增"非传统信息源采集"子流程 | ★★★ |
| ⓪ 审查① | CLI 交互 | ⑦ 双系统理论 | 强制"系统二"抽查覆盖率 ≥70% | ★★ |
| ④ 公司研究 | `src/trend/stock_analysis.py` | ⑧ 确认偏误、⑨ 心智模型 | 生成"反面证据专章"+"心智模型版本号" | ★★★★ |
| ⓪ 审查② | CLI 交互 | ③ 过度自信、⑮ 现状偏见 | 连续3笔盈利→强制冷静期；持仓时钟提示 | ★★★ |
| ⑤ 因子打分 | `src/screener/screener.py` | ⑪ 幂律分布 | 打分权重向 Top3 倾斜（核心集中型） | ★★★★ |
| ⑥ 组合构建 | `src/kelly/stock_kelly_analyzer.py` | ⑪ 幂律分布、⑭ 心理账户、⑬ 前景理论、⑩ 网络效应 | 核心+卫星架构、心理账户中性校验、对称止损线、网络效应护城河打分 | ★★★★★ |
| ⓪ 审查③ | CLI 交互 | ① 锚定效应、⑮ 现状偏见 | "去锚定检查清单"、"替代方案优先"提示 | ★★★★ |
| ⑦ 回测校验 | `src/backtest/runner.py` | ⑬ 前景理论、⑪ 幂律分布 | 报告增加"心理回撤"与"幂律贡献度" | ★★★ |
| ⑧ 风险检查 | `src/risk/checker.py` | ② 损失厌恶、⑬ 前景理论 | 对称止损/止盈校验、心理阈值 vs 数学阈值双报告 | ★★★★★ |
| ⓪ 审查④ | CLI 交互 | ④ 纳什均衡、⑥ 囚徒困境、⑤ 信号传递 | 行业博弈状态识别 + 信号可信度打分 | ★★★★ |
| ⑨ 调仓执行 | `src/monitor/monitor.py` | ② 损失厌恶、③ 过度自信 | 硬止损/止盈 + 连续盈利冷静期自动触发 | ★★★★★ |
| ⑩ 归因复盘 | `src/attribution/review.py` | ⑦ 双系统理论、⑩ 网络效应、⑭ 心理账户、⑮ 现状偏见 | 系统一/二决策占比、幂律贡献度分析、心理账户痕迹检查、持仓时钟复盘 | ★★★ |

> 注：★★★★★ = 直接影响交易纪律，优先级最高。

---

## 二、15 个概念分学科落地详解

### 2.1 行为心理学（概念①②③）

#### 概念① 锚定效应 → 嵌入 ⓪ 审查③ + ④ 公司研究

**理论核心**：决策时过度依赖最先获得的信息（锚点），后续判断围绕锚点小幅调整，即使该参考信息可能已过时或不相关。

**TransAlpha 对应场景**：
- ④ 公司研究阶段，`StockAnalyzer` 输出的研究报告可能隐含"历史高点/低点"作为估值参照
- ⓪ 审查③ 阶段，用户审查持仓方案时可能以"买入成本价"或"近期高点"为锚点判断是否调仓

**落地策略：去锚定检查清单**

```python
# src/behavioral/deanchoring.py

DEANCHORING_CHECKLIST = {
    "price_anchor_stripped": {
        "description": "是否已剥离历史股价锚点（如'原价80'、'高点回撤50%'）",
        "required": True,
        "check_method": "研究报告不得出现'相比历史高点'类表述作为核心估值依据",
    },
    "valuation_independent": {
        "description": "是否基于当前基本面独立构建估值区间",
        "required": True,
        "check_method": "DCF估值 + 行业PE/PB分位数 + 未来三年现金流折现",
    },
    "deviation_threshold": {
        "description": "独立估值与历史锚定价的偏离度",
        "threshold_pct": 30.0,
        "action_on_exceed": "触发深度复盘，排查是否被锚定效应误导",
    },
    "target_price_basis": {
        "description": "目标价是否建立在估值模型之上（而非历史高点的打折幅度）",
        "required": True,
    },
}

def run_deanchoring_check(research_report: dict, historical_anchor_price: float) -> dict:
    """去锚定检查 — 在 ④ 公司研究输出后自动执行

    Args:
        research_report: StockAnalyzer.analyze() 的输出
        historical_anchor_price: 历史锚定价（如近一年高点）

    Returns:
        {
            "passed": bool,
            "deviation_pct": float,
            "trigger_deep_review": bool,
            "details": {...}
        }
    """
    independent_valuation = research_report.get("valuation", {}).get("fair_value", 0)
    if independent_valuation <= 0 or historical_anchor_price <= 0:
        return {"passed": True, "deviation_pct": 0, "trigger_deep_review": False}

    deviation = abs(independent_valuation - historical_anchor_price) / historical_anchor_price * 100
    trigger = deviation > DEANCHORING_CHECKLIST["deviation_threshold"]["threshold_pct"]

    return {
        "passed": not trigger,
        "deviation_pct": round(deviation, 2),
        "trigger_deep_review": trigger,
        "independent_valuation": independent_valuation,
        "anchor_price": historical_anchor_price,
        "message": f"独立估值({independent_valuation:.2f})与锚定价({historical_anchor_price:.2f})"
                   f"偏离{deviation:.1f}%，{'触发深度复盘' if trigger else '在安全范围内'}",
    }
```

**模拟盘验证**（对齐手册）：选取3只"大幅回调后横盘"标的，分别以"去锚定估值法"和"传统技术面支撑法"给出买卖决策，对比4周内收益率差异与最大回撤。

---

#### 概念② 损失厌恶 → 嵌入 ⑨ 调仓执行 + ⑧ 风险检查

**理论核心**：人们对损失的痛苦感受约为同等收益愉悦感受的 2.0–2.5 倍，导致亏损时"持亏不卖"、盈利时"过早止盈"，是交易纪律的最大敌人。

**TransAlpha 对应场景**：
- ⑨ 调仓执行阶段，`StockAlert` 的 `cost_pct_below: -12.0` 是单线止损，缺少对称止盈
- 当前 monitor.py 的告警阈值不对称：亏损 -12% 触发但盈利 +15% 才触发，没有强制止盈

**落地策略：对称风控规则 + 亏损日记**

```python
# src/behavioral/loss_aversion.py

BEHAVIORAL_RISK_CONFIG = {
    "loss_aversion": {
        "hard_stop_loss": -15.0,        # 硬止损线（对抗"持亏不卖"）
        "symmetric_take_profit": 30.0,  # 对称止盈线（+30% vs -15%，2:1 盈亏比）
        "psychological_stop": -8.0,     # 心理止损线（前景理论，-8%触发预警）
        "psychological_take_profit": 15.0,  # 心理止盈线
        "journal_on_trigger": True,     # 触发后自动写"亏损日记"
        "rebuy_test": True,             # 浮亏复核：若不愿以当前价重新买入则立即止损
    },
    "overconfidence": {
        "cooling_trigger": 3,           # 连续3笔盈利触发冷静期
        "cooling_days": 3,             # 冷静期天数（期间仅允许减仓）
        "max_consecutive_wins_before_alert": 3,
    },
}

def check_symmetric_risk_rules(position: dict, current_price: float) -> dict:
    """对称风控规则校验 — 在 ⑨ 调仓执行 + ⑧ 风险检查中调用

    对抗损失厌恶：亏损时倾向"持亏不卖"，盈利时倾向"过早止盈"
    解决方案：硬止损/止盈对称触发，无条件执行
    """
    cost_price = position.get("cost_price", 0)
    if cost_price <= 0:
        return {"action": "hold", "reason": "无成本价数据"}

    pnl_pct = (current_price - cost_price) / cost_price * 100
    config = BEHAVIORAL_RISK_CONFIG["loss_aversion"]

    # 硬止损/止盈：触及任一阈值无条件执行
    if pnl_pct <= config["hard_stop_loss"]:
        return {
            "action": "force_sell",
            "reason": f"触发硬止损线({config['hard_stop_loss']}%)，当前盈亏{pnl_pct:.1f}%",
            "pnl_pct": round(pnl_pct, 2),
            "journal_required": config["journal_on_trigger"],
            "journal_entry": f"止损卖出{position.get('symbol')}，盈亏{pnl_pct:.1f}%，"
                           f"决策逻辑：触及硬止损线，无条件执行",
        }

    if pnl_pct >= config["symmetric_take_profit"]:
        return {
            "action": "force_sell",
            "reason": f"触发对称止盈线({config['symmetric_take_profit']}%)，当前盈亏{pnl_pct:.1f}%",
            "pnl_pct": round(pnl_pct, 2),
            "journal_required": config["journal_on_trigger"],
            "journal_entry": f"止盈卖出{position.get('symbol')}，盈亏{pnl_pct:.1f}%，"
                           f"决策逻辑：触及对称止盈线，无条件执行",
        }

    # 心理预警线（不强制执行，但触发提醒）
    if pnl_pct <= config["psychological_stop"]:
        return {
            "action": "alert",
            "reason": f"触发心理止损预警({config['psychological_stop']}%)，当前盈亏{pnl_pct:.1f}%",
            "pnl_pct": round(pnl_pct, 2),
            "rebuy_test_required": config["rebuy_test"],
            "rebuy_test_prompt": "请回答：若现在不持有此标的，会以当前价重新买入吗？"
                               "若答案为否，应立即止损",
        }

    return {"action": "hold", "pnl_pct": round(pnl_pct, 2)}


def write_loss_journal(symbol: str, action: str, pnl_pct: float, reason: str) -> None:
    """亏损日记机制 — 每笔止损/止盈后记录决策逻辑，定期复盘强化纪律"""
    from pathlib import Path
    from datetime import datetime

    journal_path = Path("output/rebalance-execution/loss_journal.md")
    journal_path.parent.mkdir(parents=True, exist_ok=True)

    entry = f"\n## {datetime.now().strftime('%Y-%m-%d %H:%M')} | {symbol} | {action}\n"
    entry += f"- 盈亏: {pnl_pct:.1f}%\n"
    entry += f"- 原因: {reason}\n"
    entry += f"- 复盘要点: 是否遵守了对称风控规则？是否存在人为豁免？\n"

    with open(journal_path, "a", encoding="utf-8") as f:
        f.write(entry)
```

**模拟盘验证**（对齐手册第55行）：以"对称止盈止损法"替代原有"宽松止损法"运行3个月，对比两组策略的年化收益率、最大回撤、胜率、夏普比，量化验证克服损失厌恶对长期绩效的边际贡献。

**与 H1–H13 协同**：
- H11（持仓≤3日）：概念②补强执行纪律，避免"超T+3仍持亏不卖"
- H12（日亏≤2%）：概念②确保单日亏损触及阈值时无条件止损
- H13（回撤≤5%）：概念②的对称止盈防止"盈利回吐变亏损"

---

#### 概念③ 过度自信 → 嵌入 ⓪ 审查② + ⑩ 归因复盘

**理论核心**：系统性高估自身判断准确性，表现为低估风险、高估胜率、过度交易。

**TransAlpha 对应场景**：
- ⓪ 审查② 阶段，用户确认候选池时可能因连续盈利而过度自信
- ⑩ 归因复盘阶段，需要检测过度自信的早期信号

**落地策略：过度自信预警体系**

```python
# src/behavioral/overconfidence.py

OVERCONFIDENCE_CONFIG = {
    "consecutive_win_cooling_trigger": 3,   # 连续3笔盈利触发冷静期
    "cooling_period_days": 3,               # 冷静期天数
    "cooling_period_actions": "仅允许减仓，不允许加仓",
    "high_confidence_threshold": 0.80,      # 胜率>80%视为高置信度
    "self_proof_required": True,            # 高置信度判断需写"错误3原因"
    "trading_freq_increase_threshold": 0.80, # 交易频次环比增加80%触发预警
}

def check_overconfidence_signals(recent_trades: list, trading_freq_ratio: float) -> dict:
    """过度自信预警检查

    Args:
        recent_trades: 最近交易记录列表
        trading_freq_ratio: 本月交易频次/上月交易频次

    Returns:
        {
            "cooling_triggered": bool,
            "cooling_days": int,
            "warnings": list[str],
        }
    """
    warnings = []
    config = OVERCONFIDENCE_CONFIG

    # 检查连续盈利笔数
    consecutive_wins = 0
    for trade in reversed(recent_trades):
        if trade.get("pnl", 0) > 0:
            consecutive_wins += 1
        else:
            break

    cooling_triggered = consecutive_wins >= config["consecutive_win_cooling_trigger"]
    if cooling_triggered:
        warnings.append(
            f"连续{consecutive_wins}笔盈利，触发冷静期({config['cooling_period_days']}天)，"
            f"期间{config['cooling_period_actions']}"
        )

    # 检查交易频次
    if trading_freq_ratio > 1 + config["trading_freq_increase_threshold"]:
        warnings.append(
            f"交易频次环比增加{(trading_freq_ratio-1)*100:.0f}%，"
            f"超过阈值{config['trading_freq_increase_threshold']*100}%，警惕过度交易"
        )

    return {
        "cooling_triggered": cooling_triggered,
        "cooling_days": config["cooling_period_days"] if cooling_triggered else 0,
        "consecutive_wins": consecutive_wins,
        "trading_freq_ratio": round(trading_freq_ratio, 2),
        "warnings": warnings,
    }


def self_proof_check(confidence_level: float, decision: str) -> dict:
    """自证预言检查：高置信度判断必须同步写出"若判断错误，最可能的3个原因"

    对抗过度自信：强制高置信度决策者写出反面可能性
    """
    if confidence_level >= OVERCONFIDENCE_CONFIG["high_confidence_threshold"]:
        return {
            "required": True,
            "prompt": f"您对'{decision}'的置信度为{confidence_level*100:.0f}%（高置信度），"
                     f"请写出若判断错误，最可能的3个原因：",
            "template": [
                "原因1: ____",
                "原因2: ____",
                "原因3: ____",
            ],
            "blocking": True,  # 未填写则阻断决策
        }
    return {"required": False}
```

---

### 2.2 博弈论（概念④⑤⑥）

#### 概念④ 纳什均衡 → 嵌入 ⓪ 审查④ + ④ 公司研究

**理论核心**：给定其他参与者策略不变，没有人有动机单方面改变自己策略的状态。

**TransAlpha 对应场景**：
- ⓪ 审查④ 阶段，用户需要判断持仓中周期股是否处于价格战末期的纳什均衡区间
- ④ 公司研究阶段，行业分析需要识别博弈状态

**落地策略：均衡识别三步法**

```python
# src/behavioral/nash_equilibrium.py

def identify_nash_equilibrium(industry_data: dict) -> dict:
    """均衡识别三步法 — 在 ⓪ 审查④ 风控报告中附表A展示

    Args:
        industry_data: {
            "players": [
                {"name": "A公司", "strategy": "降价", "market_share": 0.35, "profit_margin": 0.05},
                {"name": "B公司", "strategy": "降价", "market_share": 0.30, "profit_margin": 0.04},
                {"name": "C公司", "strategy": "维持", "market_share": 0.20, "profit_margin": 0.08},
            ],
            "industry_profit_history": [...],
        }

    Returns:
        {
            "is_equilibrium": bool,
            "equilibrium_type": "stable" | "unstable" | "not_reached",
            "deviation_cost_analysis": [...],
            "investment_implication": str,
        }
    """
    players = industry_data.get("players", [])
    if len(players) < 2:
        return {"is_equilibrium": False, "equilibrium_type": "not_reached",
                "message": "参与者不足，无法分析"}

    # Step 1: 梳理策略矩阵
    strategy_matrix = []
    for p in players:
        strategy_matrix.append({
            "player": p["name"],
            "current_strategy": p["strategy"],
            "market_share": p["market_share"],
            "profit_margin": p["profit_margin"],
        })

    # Step 2: 计算偏离成本（若单独改变策略会否引发报复）
    deviation_costs = []
    for p in players:
        # 简化模型：若单独提价，市场份额损失 ≈ 其他玩家不跟进的差额
        deviation_cost = p["market_share"] * 0.15  # 假设提价导致15%份额流失
        gain_from_deviation = p["profit_margin"] * 0.03  # 假设提价带来3%利润率提升
        net_cost = deviation_cost - gain_from_deviation
        deviation_costs.append({
            "player": p["name"],
            "deviation_cost": round(net_cost, 4),
            "would_deviate": net_cost < 0,
        })

    # Step 3: 判定均衡
    any_would_deviate = any(d["would_deviate"] for d in deviation_costs)
    if not any_would_deviate:
        return {
            "is_equilibrium": True,
            "equilibrium_type": "stable",
            "strategy_matrix": strategy_matrix,
            "deviation_cost_analysis": deviation_costs,
            "investment_implication": "行业处于纳什均衡区间，可考虑逆向建仓策略",
        }
    else:
        return {
            "is_equilibrium": False,
            "equilibrium_type": "unstable",
            "strategy_matrix": strategy_matrix,
            "deviation_cost_analysis": deviation_costs,
            "investment_implication": "行业尚未达到均衡，保持观望，等待龙头率先发出限产/提价信号",
        }
```

---

#### 概念⑤ 信号传递 → 嵌入 ⓪ 审查④ + ③ 信息收集

**理论核心**：在信息不对称情境下，拥有私有信息的一方通过"发送成本高、伪造成本更高"的行动传递可信信号。

**TransAlpha 对应场景**：
- ⓪ 审查④ 阶段，需要评估持仓标的大股东增持/回购等信号的可信度
- ③ 信息收集阶段，可采集公告信号并自动评分

**落地策略：信号可信度评估框架**

```python
# src/behavioral/signaling.py

SIGNAL_CREDIBILITY_FRAMEWORK = {
    "high_cost_signals": {
        "locked_in_purchase": {"weight": 30, "description": "有锁定期的增持（6个月+）"},
        "large_repurchase": {"weight": 25, "description": "回购金额占总市值>2%"},
        "management_purchase": {"weight": 20, "description": "管理层集体增持"},
    },
    "low_cost_signals": {
        "verbal_commitment": {"weight": 5, "description": "口头承诺（无约束力）"},
        "small_repurchase": {"weight": 10, "description": "回购金额占总市值<0.5%"},
    },
    "negative_signals": {
        "pledge_pressure_purchase": {"weight": -30, "description": "股权质押平仓线附近的被动增持"},
        "insider_selling": {"weight": -40, "description": "大股东同期有减持记录"},
    },
}

def evaluate_signal_credibility(announcement: dict) -> dict:
    """信号可信度评估 — 在 ⓪ 审查④ 风控报告中附表C展示

    Args:
        announcement: {
            "type": "增持" | "回购" | "定增",
            "amount": float,           # 金额（万元）
            "lockup_period_months": int, # 锁定期（月）
            "price_vs_market": float,    # 增持价 vs 当前市价
            "has_pledge_pressure": bool,  # 是否存在股权质押压力
            "has_insider_selling": bool,  # 同期是否有减持
        }

    Returns:
        {
            "credibility_score": float,  # 0-100
            "credibility_level": "high" | "medium" | "low",
            "signal_type": "active_positive" | "passive" | "negative",
            "details": [...],
        }
    """
    score = 50  # 基准分
    details = []
    framework = SIGNAL_CREDIBILITY_FRAMEWORK

    # 高成本信号加分
    if announcement.get("lockup_period_months", 0) >= 6:
        score += framework["high_cost_signals"]["locked_in_purchase"]["weight"]
        details.append(f"有锁定期增持({announcement['lockup_period_months']}个月)，高成本信号 +30")

    if announcement.get("amount", 0) > 0:
        # 假设总市值100亿，amount单位万元
        repurchase_ratio = announcement["amount"] / 1_000_000  # 简化计算
        if repurchase_ratio > 0.02:
            score += framework["high_cost_signals"]["large_repurchase"]["weight"]
            details.append(f"大额回购(占比{repurchase_ratio*100:.1f}%)，高成本信号 +25")

    # 负面信号减分
    if announcement.get("has_pledge_pressure"):
        score -= abs(framework["negative_signals"]["pledge_pressure_purchase"]["weight"])
        details.append("存在股权质押压力，可能是被动增持 -30")

    if announcement.get("has_insider_selling"):
        score -= abs(framework["negative_signals"]["insider_selling"]["weight"])
        details.append("同期有大股东减持记录 -40")

    # 分级
    if score >= 75:
        level = "high"
        signal_type = "active_positive"
    elif score >= 50:
        level = "medium"
        signal_type = "active_positive" if score >= 60 else "passive"
    else:
        level = "low"
        signal_type = "negative"

    return {
        "credibility_score": min(100, max(0, score)),
        "credibility_level": level,
        "signal_type": signal_type,
        "details": details,
        "recommendation": "可作为加仓参考" if level == "high" else
                         "需进一步核实" if level == "medium" else
                         "警告：信号可信度低，不建议作为投资依据",
    }
```

---

#### 概念⑥ 囚徒困境 → 嵌入 ⓪ 审查④ + ③ 信息收集

**理论核心**：个体理性选择导致集体非理性结果，每个参与者独立最优策略组合后集体结果反而更差。

**TransAlpha 对应场景**：
- ⓪ 审查④ 阶段，判断持仓行业是否陷入产能过剩的囚徒困境
- ③ 信息收集阶段，可监控行业扩产公告密度

**落地策略：囚徒困境预警框架**

```python
# src/behavioral/prisoner_dilemma.py

PRISONER_DILEMMA_CONFIG = {
    "expansion_announcement_window_months": 6,  # 监控窗口
    "expansion_alert_multiplier": 2.0,          # 扩产公告数超历史均值2倍触发预警
    "price_decline_threshold_pct": 50,          # 产品价格跌幅超50%触发预警
    "industry_profit_decline_threshold_pct": 30, # 行业利润率下降超30%触发预警
}

def detect_prisoner_dilemma(industry_expansion_data: dict) -> dict:
    """囚徒困境预警框架 — 在 ⓪ 审查④ 风控报告中附表B展示

    Args:
        industry_expansion_data: {
            "industry_name": str,
            "expansion_announcements_6m": int,    # 近6个月扩产公告数
            "historical_avg_announcements_6m": int, # 历史均值
            "product_price_current": float,
            "product_price_peak": float,
            "industry_profit_margin_current": float,
            "industry_profit_margin_peak": float,
        }

    Returns:
        {
            "in_prisoner_dilemma": bool,
            "alert_level": "red" | "yellow" | "green",
            "alerts": list[str],
            "action": str,
        }
    """
    config = PRISONER_DILEMMA_CONFIG
    alerts = []

    # 检查1: 扩产公告密度
    expansion_ratio = (industry_expansion_data.get("expansion_announcements_6m", 0) /
                       max(1, industry_expansion_data.get("historical_avg_announcements_6m", 1)))
    if expansion_ratio >= config["expansion_alert_multiplier"]:
        alerts.append(
            f"扩产公告密度预警：近6个月{industry_expansion_data['expansion_announcements_6m']}个公告，"
            f"为历史均值的{expansion_ratio:.1f}倍（阈值{config['expansion_alert_multiplier']}倍）"
        )

    # 检查2: 产品价格暴跌
    price_decline = ((industry_expansion_data.get("product_price_peak", 0) -
                      industry_expansion_data.get("product_price_current", 0)) /
                     max(0.01, industry_expansion_data.get("product_price_peak", 1)) * 100)
    if price_decline >= config["price_decline_threshold_pct"]:
        alerts.append(
            f"产品价格暴跌：从{industry_expansion_data['product_price_peak']}跌至"
            f"{industry_expansion_data['product_price_current']}，跌幅{price_decline:.1f}%"
        )

    # 检查3: 行业利润率大幅下降
    profit_decline = ((industry_expansion_data.get("industry_profit_margin_peak", 0) -
                       industry_expansion_data.get("industry_profit_margin_current", 0)) /
                      max(0.01, abs(industry_expansion_data.get("industry_profit_margin_peak", 1))) * 100)
    if profit_decline >= config["industry_profit_decline_threshold_pct"]:
        alerts.append(
            f"行业利润率骤降：从{industry_expansion_data['industry_profit_margin_peak']*100:.1f}%降至"
            f"{industry_expansion_data['industry_profit_margin_current']*100:.1f}%，降幅{profit_decline:.1f}%"
        )

    # 判定
    if len(alerts) >= 2:
        return {
            "in_prisoner_dilemma": True,
            "alert_level": "red",
            "alerts": alerts,
            "action": "立即减仓或做空行业ETF，等待产能出清信号（落后产能出清、龙头率先限产）",
        }
    elif len(alerts) == 1:
        return {
            "in_prisoner_dilemma": False,
            "alert_level": "yellow",
            "alerts": alerts,
            "action": "密切关注，准备减仓预案",
        }
    else:
        return {
            "in_prisoner_dilemma": False,
            "alert_level": "green",
            "alerts": [],
            "action": "行业状态正常",
        }
```

---

### 2.3 认知科学（概念⑦⑧⑨）

#### 概念⑦ 双系统理论 → 嵌入 ⓪ 审查① + ⑩ 归因复盘

**理论核心**：系统一（快速直觉）vs 系统二（慢速审慎），二者协同但常产生冲突。

**TransAlpha 对应场景**：
- ⓪ 审查① 阶段，需要确保数据质量抽查经过"系统二"审慎分析
- ⑩ 归因复盘阶段，需要统计系统一/二决策占比

**落地策略：强制系统二介入检查点**

```python
# src/behavioral/dual_system.py

DUAL_SYSTEM_CONFIG = {
    "system_two_min_ratio": 0.70,          # 系统二决策占比目标 ≥70%
    "large_position_threshold": 0.05,      # 单笔仓位>5%必须系统二介入
    "system_two_required_analysis_pages": 3, # 系统二决策需完成3页以上量化分析
    "post_win_streak_cooling": True,        # 连续盈利后强制系统二审核
}

def classify_decision_system(decision: dict) -> str:
    """判定决策属于系统一还是系统二

    系统一标志：直觉判断、无量化分析、快速决策、小仓位
    系统二标志：DCF估值、行业对标、情景分析、大仓位、审慎分析
    """
    has_quantitative_analysis = bool(decision.get("dcf_valuation") or
                                     decision.get("industry_benchmark") or
                                     decision.get("scenario_analysis"))
    position_size = decision.get("position_fraction", 0)
    analysis_depth = decision.get("analysis_pages", 0)

    if (has_quantitative_analysis and
        position_size >= DUAL_SYSTEM_CONFIG["large_position_threshold"] and
        analysis_depth >= DUAL_SYSTEM_CONFIG["system_two_required_analysis_pages"]):
        return "system_2"
    else:
        return "system_1"

def check_system_two_ratio(decisions: list) -> dict:
    """系统二决策占比检查 — 在 ⑩ 归因复盘中展示

    Returns:
        {
            "system_2_ratio": float,
            "target_ratio": float,
            "passed": bool,
            "system_1_count": int,
            "system_2_count": int,
            "message": str,
        }
    """
    if not decisions:
        return {"system_2_ratio": 0, "passed": False, "message": "无决策记录"}

    classifications = [classify_decision_system(d) for d in decisions]
    s2_count = sum(1 for c in classifications if c == "system_2")
    s1_count = sum(1 for c in classifications if c == "system_1")
    s2_ratio = s2_count / len(decisions)
    target = DUAL_SYSTEM_CONFIG["system_two_min_ratio"]

    return {
        "system_2_ratio": round(s2_ratio, 2),
        "target_ratio": target,
        "passed": s2_ratio >= target,
        "system_1_count": s1_count,
        "system_2_count": s2_count,
        "message": (f"系统二决策占比{s2_ratio*100:.0f}%（目标≥{target*100:.0f}%），"
                   f"{'达标' if s2_ratio >= target else '⚠️ 低于目标，需设置强制系统二介入检查点'}"),
    }
```

---

#### 概念⑧ 确认偏误 → 嵌入 ④ 公司研究

**理论核心**：倾向于寻找、采信支持自己已有观点的信息，忽视或贬低反面证据。

**TransAlpha 对应场景**：
- ④ 公司研究阶段，`StockAnalyzer` 输出的研究报告可能只呈现正面信息

**落地策略：反面证据专章 + 红队机制**

```python
# src/behavioral/confirmation_bias.py

CONFIRMATION_BIAS_CONFIG = {
    "min_counter_evidence_count": 3,        # 每份报告至少3条反面证据
    "red_team_required": True,               # 投决会前必须有红队报告
    "condition_change_trigger_required": True, # 必须写出"什么情况下会改变判断"
}

def generate_counter_evidence_section(research_report: dict) -> dict:
    """反面证据专章生成器 — 嵌入 ④ 公司研究报告输出

    强制每份研究报告包含反面证据，对抗确认偏误
    """
    main_conclusion = research_report.get("conclusion", "")
    positive_factors = research_report.get("positive_factors", [])

    # 自动生成反面证据提示框架
    counter_evidence_template = {
        "section_name": "反面证据专章（确认偏误防护）",
        "required_count": CONFIRMATION_BIAS_CONFIG["min_counter_evidence_count"],
        "counter_evidence_items": [
            "证据1: ____（与核心结论相反的证据及分析）",
            "证据2: ____",
            "证据3: ____",
        ],
        "red_team_report": {
            "required": CONFIRMATION_BIAS_CONFIG["red_team_required"],
            "author": "指定团队中一人专职撰写反驳报告",
            "focus": f"针对'{main_conclusion}'提出最强反驳论证",
        },
        "condition_change_trigger": {
            "required": CONFIRMATION_BIAS_CONFIG["condition_change_trigger_required"],
            "prompt": "请写出：什么情况下你会改变这个判断？",
            "template": "若以下条件发生，我将改变对{symbol}的判断：____",
        },
        "info_diversity_check": {
            "positive_vs_negative_ratio": "目标：正面:反面 ≤ 2:1",
            "info_source_diversity": "目标：至少引用3个不同来源的数据",
        },
    }

    return counter_evidence_template


def check_report_objectivity(research_report: dict) -> dict:
    """检查研究报告的客观性 — 在 ④ 公司研究输出后自动执行

    Returns:
        {
            "passed": bool,
            "positive_count": int,
            "negative_count": int,
            "ratio": str,
            "missing_sections": list[str],
        }
    """
    required = CONFIRMATION_BIAS_CONFIG["min_counter_evidence_count"]
    positive = research_report.get("positive_factors", [])
    negative = research_report.get("counter_evidence", [])
    has_trigger = bool(research_report.get("condition_change_trigger"))

    missing = []
    if len(negative) < required:
        missing.append(f"反面证据不足（{len(negative)}/{required}）")
    if not has_trigger:
        missing.append("缺少'判断改变触发条件'")

    return {
        "passed": len(missing) == 0,
        "positive_count": len(positive),
        "negative_count": len(negative),
        "ratio": f"{len(positive)}:{len(negative)}",
        "missing_sections": missing,
        "message": "报告客观性检查通过" if len(missing) == 0 else
                  f"⚠️ 报告存在确认偏误风险：{'; '.join(missing)}",
    }
```

---

#### 概念⑨ 心智模型 → 嵌入 ④ 公司研究

**理论核心**：人们用于理解复杂世界的简化认知框架，一旦形成不易更新。

**TransAlpha 对应场景**：
- ④ 公司研究阶段，分析新行业时可能套用过时的心智模型

**落地策略：心智模型更新清单**

```python
# src/behavioral/mental_model.py

MENTAL_MODEL_CONFIG = {
    "review_cycle_quarterly": True,    # 每季度审视一次
    "max_model_age_months": 12,        # 心智模型最长有效期12个月
    "key_variables_to_check": [
        "technology_driver",    # 技术驱动是否变化
        "regulatory_change",    # 监管是否变化
        "competition_pattern",  # 竞争模式是否变化
    ],
}

def generate_mental_model_checklist(industry: str, current_model: dict) -> dict:
    """心智模型更新清单 — 在 ④ 公司研究前执行

    Args:
        industry: 行业名称
        current_model: 当前使用的心智模型

    Returns:
        {
            "model_version": str,
            "model_age_months": int,
            "needs_update": bool,
            "key_variables_check": [...],
        }
    """
    from datetime import datetime

    model_date = current_model.get("created_date", "")
    model_age = 0
    if model_date:
        try:
            model_age = (datetime.now() - datetime.fromisoformat(model_date)).days / 30
        except Exception:
            pass

    key_vars = []
    for var in MENTAL_MODEL_CONFIG["key_variables_to_check"]:
        key_vars.append({
            "variable": var,
            "current_assumption": current_model.get(var, "未记录"),
            "has_changed": "待人工确认",
            "new_variable": "____",
        })

    needs_update = model_age > MENTAL_MODEL_CONFIG["max_model_age_months"]

    return {
        "industry": industry,
        "model_version": current_model.get("version", "v1.0"),
        "model_age_months": round(model_age, 1),
        "max_age_months": MENTAL_MODEL_CONFIG["max_model_age_months"],
        "needs_update": needs_update,
        "key_variables_check": key_vars,
        "message": (f"心智模型已使用{model_age:.0f}个月，"
                   f"{'⚠️ 超过有效期，需组织专题研讨更新分析框架' if needs_update else '在有效期内'}"),
    }
```

---

### 2.4 社会科学（概念⑩⑪⑫）

#### 概念⑩ 网络效应 → 嵌入 ⑥ 组合构建 + ④ 公司研究

**理论核心**：产品或服务的价值随使用者数量增加而增加，是平台型公司最重要的护城河。

**TransAlpha 对应场景**：
- ⑥ 组合构建阶段，对平台型公司需要评估网络效应护城河强度
- ④ 公司研究阶段，需要判断平台是否已跨越临界规模

**落地策略：网络效应护城河评估框架**

```python
# src/behavioral/network_effect.py

NETWORK_EFFECT_CONFIG = {
    "critical_mass_threshold": 0.3,     # 临界市场份额30%
    "user_churn_warning_threshold": 0.05, # 用户流失率>5%触发预警
    "multi_homing_cost_threshold": 0.5,   # 多归属成本低于50%视为护城河弱
}

def evaluate_network_effect_moat(company_data: dict) -> dict:
    """网络效应护城河评估 — 在 ⑥ 组合构建中作为因子打分补充

    Args:
        company_data: {
            "platform_type": "single" | "double" | "multi",
            "market_share": float,
            "user_growth_rate": float,
            "user_churn_rate": float,
            "multi_homing_cost": float,  # 用户切换成本（0-1）
            "competitor_subsidy_intensity": float, # 竞争对手补贴力度
        }

    Returns:
        {
            "moat_score": float,  # 0-100
            "moat_level": "strong" | "moderate" | "weak",
            "crossed_critical_mass": bool,
            "reverse_network_risk": float,
            "investment_implication": str,
        }
    """
    config = NETWORK_EFFECT_CONFIG
    score = 50  # 基准分
    details = []

    # 1. 平台类型
    platform_type = company_data.get("platform_type", "single")
    if platform_type == "double":
        score += 15
        details.append("双边网络效应，护城河更强 +15")
    elif platform_type == "multi":
        score += 20
        details.append("多边网络效应，护城河最强 +20")

    # 2. 临界规模
    market_share = company_data.get("market_share", 0)
    crossed = market_share >= config["critical_mass_threshold"]
    if crossed:
        score += 20
        details.append(f"已跨越临界规模(份额{market_share*100:.0f}%≥{config['critical_mass_threshold']*100:.0f}%) +20")
    else:
        score -= 15
        details.append(f"未跨越临界规模(份额{market_share*100:.0f}%<{config['critical_mass_threshold']*100:.0f}%) -15")

    # 3. 用户流失率
    churn = company_data.get("user_churn_rate", 0)
    if churn > config["user_churn_warning_threshold"]:
        score -= 20
        details.append(f"用户流失率{churn*100:.1f}%超预警({config['user_churn_warning_threshold']*100:.0f}%) -20")

    # 4. 多归属成本
    multi_homing = company_data.get("multi_homing_cost", 0)
    if multi_homing >= 0.7:
        score += 15
        details.append(f"多归属成本高({multi_homing*100:.0f}%)，用户粘性强 +15")
    elif multi_homing < config["multi_homing_cost_threshold"]:
        score -= 10
        details.append(f"多归属成本低({multi_homing*100:.0f}%)，护城河弱 -10")

    # 5. 反向网络效应压力测试
    competitor_subsidy = company_data.get("competitor_subsidy_intensity", 0)
    reverse_risk = churn * 10 + competitor_subsidy * 5 + (0.3 if not crossed else 0)

    score = max(0, min(100, score))
    if score >= 75:
        level = "strong"
    elif score >= 50:
        level = "moderate"
    else:
        level = "weak"

    return {
        "moat_score": round(score, 1),
        "moat_level": level,
        "crossed_critical_mass": crossed,
        "reverse_network_risk": round(reverse_risk, 2),
        "details": details,
        "investment_implication": (
            "护城河强，可给予高估值溢价" if level == "strong" else
            "护城河中等，正常估值" if level == "moderate" else
            "⚠️ 护城河弱，谨慎配置，监测用户流失率变化"
        ),
    }
```

---

#### 概念⑪ 幂律分布 → 嵌入 ⑤ 因子打分 + ⑥ 组合构建

**理论核心**：少数因素贡献了大部分结果。投资中表现为少数重仓标的贡献大部分收益。

**TransAlpha 对应场景**：
- ⑤ 因子打分阶段，当前"均匀打分"模式可能过度分散
- ⑥ 组合构建阶段，凯利仓位 `single_max_fraction=10%` 限制了集中度

**落地策略：核心+卫星架构 + 幂律贡献度追踪**

```python
# src/behavioral/power_law.py

CORE_SATELLITE_CONFIG = {
    "core_count": 3,           # 核心仓位数
    "core_weight": 0.60,       # 核心仓位总占比60%
    "satellite_weight": 0.40,  # 卫星仓位总占比40%
    "core_max_single": 0.15,   # 核心单票上限15%（突破10%限制，但总仓位仍受H9约束）
    "satellite_max_single": 0.05,  # 卫星单票上限5%
    "monthly_rebalance": True,      # 每月评估幂律贡献度
}

def apply_core_satellite(kelly_results: list, core_count: int = None,
                         core_weight: float = None) -> list:
    """核心+卫星架构 — 在 ⑥ 组合构建中调整凯利仓位输出

    对齐手册概念⑪：将仓位分为"核心仓位"（2-3只高确定性标的，占50-60%）
    和"卫星仓位"（分散化标的，占40-50%）

    Args:
        kelly_results: 凯利分析器输出列表（已按评分排序）
        core_count: 核心仓位数量
        core_weight: 核心仓位总权重

    Returns:
        调整后的持仓方案，标注core/satellite
    """
    config = CORE_SATELLITE_CONFIG
    core_count = core_count or config["core_count"]
    core_weight = core_weight or config["core_weight"]

    if len(kelly_results) <= core_count:
        # 标的数不足以分层，全部按核心处理
        for r in kelly_results:
            r["position_type"] = "core"
        return kelly_results

    # 按凯利分数排序，Top N 为核心
    sorted_results = sorted(kelly_results, key=lambda x: x.get("kelly_fraction", 0), reverse=True)

    core_total = 0
    for i, r in enumerate(sorted_results):
        if i < core_count:
            r["position_type"] = "core"
            # 核心仓位：在凯利建议基础上提升，但不超过core_max_single
            suggested = min(r.get("kelly_fraction", 0) * 1.5, config["core_max_single"])
            r["adjusted_fraction"] = round(suggested, 4)
            core_total += suggested
        else:
            r["position_type"] = "satellite"
            # 卫星仓位：在凯利建议基础上降低
            suggested = min(r.get("kelly_fraction", 0) * 0.5, config["satellite_max_single"])
            r["adjusted_fraction"] = round(suggested, 4)

    # 归一化：确保核心总权重 = core_weight
    if core_total > 0:
        scale = core_weight / core_total
        for r in sorted_results:
            if r["position_type"] == "core":
                r["adjusted_fraction"] = round(r["adjusted_fraction"] * scale, 4)

    # 卫星仓位归一化
    satellite_total = sum(r["adjusted_fraction"] for r in sorted_results if r["position_type"] == "satellite")
    if satellite_total > 0:
        sat_scale = (1 - core_weight) / satellite_total
        for r in sorted_results:
            if r["position_type"] == "satellite":
                r["adjusted_fraction"] = round(r["adjusted_fraction"] * sat_scale, 4)

    return sorted_results


def calculate_power_law_contribution(historical_returns: dict) -> dict:
    """幂律贡献度分析 — 在 ⑩ 归因复盘中展示

    分析哪些标的贡献了大部分收益

    Args:
        historical_returns: {"symbol_A": 0.15, "symbol_B": 0.30, ...}

    Returns:
        {
            "top3_contribution_pct": float,
            "is_power_law_distributed": bool,
            "core_satellite_effectiveness": str,
        }
    """
    if not historical_returns:
        return {"top3_contribution_pct": 0, "is_power_law_distributed": False}

    sorted_returns = sorted(historical_returns.items(), key=lambda x: x[1], reverse=True)
    total_return = sum(v for _, v in sorted_returns if v > 0)

    if total_return <= 0:
        return {"top3_contribution_pct": 0, "is_power_law_distributed": False,
                "message": "总收益为负，无法分析幂律分布"}

    top3_return = sum(v for _, v in sorted_returns[:3] if v > 0)
    top3_pct = top3_return / total_return * 100

    return {
        "top3_contribution_pct": round(top3_pct, 1),
        "is_power_law_distributed": top3_pct >= 70,
        "top3_symbols": [s for s, _ in sorted_returns[:3]],
        "total_positive_return": round(total_return, 4),
        "core_satellite_effectiveness": (
            "核心仓位有效贡献了大部分收益，架构合理" if top3_pct >= 70 else
            "收益分布过于均匀，核心仓位优势不明显，考虑调整配置"
        ),
    }
```

**与 H6/H9 协同**：H9 单票≤10%，但核心仓位可通过 `core_max_single=0.15` 适度突破（需在 ⓪ 审查③ 中人工确认），总仓位仍受 80% 上限约束。

---

#### 概念⑫ 弱连接理论 → 嵌入 ③ 信息收集

**理论核心**：弱关系网络传递新信息的效率往往高于强关系网络。

**TransAlpha 对应场景**：
- ③ 信息收集阶段，当前数据源以 akshare/东方财富为主（强关系），信息同质化

**落地策略：弱连接信息采集机制**

```python
# src/behavioral/weak_ties.py

WEAK_TIES_CONFIG = {
    "min_non_traditional_sources_per_week": 2,  # 每人每周至少2个非传统信息源
    "biweekly_sharing_session": True,            # 每两周召开弱连接信息交流会
    "non_consensus_info_tracking": True,         # 追踪非共识信息比例
    "non_traditional_sources": [
        "行业社群/论坛",
        "学术论文/专利数据库",
        "跨行业媒体",
        "产业链调研",
        "海关进出口数据",
        "企业招投标数据",
    ],
}

def generate_weak_ties_collection_prompt() -> dict:
    """弱连接信息采集提示 — 在 ③ 信息收集输出后展示

    Returns:
        弱连接信息采集任务清单
    """
    return {
        "section_name": "弱连接信息采集（概念⑫）",
        "objective": "突破信息同质化，获取非共识投资线索",
        "weekly_tasks": [
            {
                "task": f"每位成员从至少{WEAK_TIES_CONFIG['min_non_traditional_sources_per_week']}个"
                       f"非传统信息源获取信息并做简要汇报",
                "sources": WEAK_TIES_CONFIG["non_traditional_sources"],
            },
            {
                "task": "每两周召开一次弱连接信息交流会，分享非共识信息",
                "format": "成员分享 → 交叉验证 → 筛选投资线索",
            },
        ],
        "tracking_metrics": {
            "non_consensus_ratio": "团队发现的投资线索中'非共识'比例（目标≥30%）",
            "weak_ties_alpha": "基于弱连接信息的后续超额收益表现",
        },
        "cross_validation_rule": "弱连接信息必须与强连接信息（主流媒体/卖方研报）交叉验证后方可纳入投资决策",
    }
```

---

### 2.5 行为经济学（概念⑬⑭⑮）

#### 概念⑬ 前景理论 → 嵌入 ⑥ 组合构建 + ⑧ 风险检查 + ⑦ 回测校验

**理论核心**：人们面对收益和损失时风险态度不对称，价值感知呈S形曲线，损失的痛苦感约为收益快乐感的2–2.5倍。

**TransAlpha 对应场景**：
- ⑥ 组合构建阶段，风险评估以标准差/贝塔等"理性"指标为主
- ⑧ 风险检查阶段，止损线基于数学最优而非心理承受力

**落地策略：行为化风险评估框架**

```python
# src/behavioral/prospect_theory.py

PROSPECT_THEORY_CONFIG = {
    "loss_aversion_coefficient": 2.25,   # 损失厌恶系数（损失端斜率/收益端斜率）
    "psychological_stop_loss": -8.0,     # 心理止损线（基于团队真实心理承受力）
    "psychological_take_profit": 15.0,   # 心理止盈线
    "s_curve_reference_point": "cost_price",  # 参考点：成本价
    "dual_report": True,                 # 同时输出"数学阈值"和"心理阈值"双报告
}

def calculate_psychological_value(pnl_pct: float, config: dict = None) -> float:
    """基于前景理论的价值函数（S形曲线）

    V(x) = x^α           if x >= 0  (收益端)
    V(x) = -λ * (-x)^β   if x < 0   (损失端，λ为损失厌恶系数)

    其中 α=β=0.88（典型值），λ=2.25
    """
    config = config or PROSPECT_THEORY_CONFIG
    alpha = 0.88  # 收益端曲率
    beta = 0.88   # 损失端曲率
    lam = config["loss_aversion_coefficient"]

    if pnl_pct >= 0:
        return pnl_pct ** alpha
    else:
        return -lam * ((-pnl_pct) ** beta)


def generate_dual_risk_report(position: dict, math_metrics: dict) -> dict:
    """双维度风险报告：数学阈值 vs 心理阈值

    在 ⑧ 风险检查中同时展示传统风控指标和行为化风控指标

    Args:
        position: 持仓信息
        math_metrics: 传统风控指标（标准差、贝塔、最大回撤等）

    Returns:
        {
            "math_report": {...},
            "psychological_report": {...},
            "divergence_alerts": [...],
        }
    """
    config = PROSPECT_THEORY_CONFIG
    pnl_pct = position.get("pnl_pct", 0)

    # 数学阈值报告
    math_report = {
        "std_dev": math_metrics.get("std_dev", 0),
        "beta": math_metrics.get("beta", 0),
        "max_drawdown": math_metrics.get("max_drawdown", 0),
        "var_95": math_metrics.get("var_95", 0),
        "stop_loss_math": -15.0,  # 数学最优止损
        "take_profit_math": 30.0,
    }

    # 心理阈值报告
    psych_value = calculate_psychological_value(pnl_pct, config)
    psychological_report = {
        "psychological_value": round(psych_value, 4),
        "loss_aversion_coefficient": config["loss_aversion_coefficient"],
        "psychological_stop_loss": config["psychological_stop_loss"],
        "psychological_take_profit": config["psychological_take_profit"],
        "reference_point": config["s_curve_reference_point"],
        "current_pnl_pct": pnl_pct,
        "psychological_status": (
            "心理痛苦区" if pnl_pct <= config["psychological_stop_loss"] else
            "心理满足区" if pnl_pct >= config["psychological_take_profit"] else
            "心理中性区"
        ),
    }

    # 分歧预警
    alerts = []
    if abs(config["psychological_stop_loss"] - math_report["stop_loss_math"]) > 5:
        alerts.append(
            f"心理止损线({config['psychological_stop_loss']}%)与数学止损线"
            f"({math_report['stop_loss_math']}%)存在分歧，"
            f"建议以更严格者为准"
        )

    return {
        "math_report": math_report,
        "psychological_report": psychological_report,
        "divergence_alerts": alerts,
        "recommendation": "同时参考数学和心理阈值，取更严格者作为执行标准",
    }
```

---

#### 概念⑭ 心理账户 → 嵌入 ⑥ 组合构建 + ⑩ 归因复盘

**理论核心**：人们将资金心理上划分到不同"账户"并区别对待，导致非理性的资金调配。

**TransAlpha 对应场景**：
- ⑥ 组合构建阶段，可能对"盈利资金"和"本金资金"采取不同风险偏好
- ⑩ 归因复盘阶段，需要检测心理账户效应痕迹

**落地策略：心理账户中性化**

```python
# src/behavioral/mental_accounting.py

MENTAL_ACCOUNTING_CONFIG = {
    "unified_risk_budget": True,       # 统一风险预算
    "check_cycle": "monthly",          # 每月检查
    "risk_divergence_threshold": 0.3,  # 风险偏好分歧阈值
}

def detect_mental_accounting_effect(portfolio: dict, historical_pnl: dict) -> dict:
    """心理账户效应检测 — 在 ⑥ 组合构建 + ⑩ 归因复盘中执行

    检测"盈利资金"与"本金资金"是否被区别对待

    Args:
        portfolio: 当前持仓方案
        historical_pnl: {"principal_risk": 0.15, "profit_risk": 0.35, ...}
            principal_risk: 本金部分配置的平均风险（波动率）
            profit_risk: 盈利部分配置的平均风险

    Returns:
        {
            "neutral": bool,
            "divergence": float,
            "alerts": list[str],
        }
    """
    config = MENTAL_ACCOUNTING_CONFIG
    principal_risk = historical_pnl.get("principal_risk", 0)
    profit_risk = historical_pnl.get("profit_risk", 0)

    if principal_risk <= 0:
        return {"neutral": True, "divergence": 0, "alerts": []}

    divergence = (profit_risk - principal_risk) / principal_risk
    alerts = []

    if divergence > config["risk_divergence_threshold"]:
        alerts.append(
            f"⚠️ 检测到心理账户效应：盈利资金风险({profit_risk*100:.1f}%)显著高于"
            f"本金资金风险({principal_risk*100:.1f}%)，分歧{divergence*100:.0f}%"
        )
        alerts.append("建议：强制将所有资金视为统一整体，禁止以'本金/盈利'为标准做风险区分")

    return {
        "neutral": divergence <= config["risk_divergence_threshold"],
        "divergence": round(divergence, 2),
        "principal_risk": round(principal_risk, 4),
        "profit_risk": round(profit_risk, 4),
        "alerts": alerts,
        "unified_risk_budget_required": config["unified_risk_budget"],
    }


def enforce_unified_risk_budget(portfolio: list) -> dict:
    """统一风险预算框架

    所有资金共用同一套风险指标和仓位限制
    """
    return {
        "rule": "所有资金（本金+盈利）共用同一套风险指标和仓位限制",
        "position_limits": {
            "single_max": 0.10,       # 单票上限10%（H9）
            "portfolio_max": 0.80,    # 组合上限80%（H9）
            "sector_max": 0.30,       # 单行业上限30%（H9）
        },
        "risk_metrics": "所有仓位使用统一的波动率/夏普比/最大回撤评估",
        "monthly_check": "每月复盘检查是否存在心理账户效应痕迹",
    }
```

---

#### 概念⑮ 现状偏见 → 嵌入 ⓪ 审查②③ + ⑩ 归因复盘

**理论核心**：倾向于维持当前状态，即使改变明显更优。默认选项的"粘性"尤其强大。

**TransAlpha 对应场景**：
- ⓪ 审查②③ 阶段，用户可能因惰性维持现有持仓
- ⑩ 归因复盘阶段，需要检测"拖延式持仓"

**落地策略：现状偏见突破机制**

```python
# src/behavioral/status_quo.py

STATUS_QUO_CONFIG = {
    "quarterly_renewal_check": True,     # 每季度续持检查
    "max_holding_period_months": 3,      # 最大持仓周期3个月（对齐H11短线交易）
    "performance_miss_threshold_pct": 20, # 业绩低于预期20%触发强制换仓
    "industry_rank_decline_threshold": 3, # 行业排名下滑3位触发强制换仓
    "alternative_first_principle": True,   # "替代方案优先"原则
}

def check_status_quo_bias(holding: dict, current_quarter: int) -> dict:
    """现状偏见突破检查 — 在 ⓪ 审查②③ + ⑩ 归因复盘中执行

    Args:
        holding: {
            "symbol": str,
            "holding_months": int,
            "performance_vs_expectation_pct": float, # 业绩vs预期偏差
            "industry_rank_change": int,  # 行业排名变化（负数=下滑）
            "last_review_quarter": int,
        }

    Returns:
        {
            "force_rebalance": bool,
            "reasons": list[str],
            "alternative_prompt": str,
        }
    """
    config = STATUS_QUO_CONFIG
    reasons = []

    # 检查1: 持仓时钟
    holding_months = holding.get("holding_months", 0)
    if holding_months > config["max_holding_period_months"]:
        reasons.append(
            f"持仓时钟触发：已持有{holding_months}个月，"
            f"超过最大周期{config['max_holding_period_months']}个月，需重新评估"
        )

    # 检查2: 业绩不达标
    perf_miss = holding.get("performance_vs_expectation_pct", 0)
    if perf_miss < -config["performance_miss_threshold_pct"]:
        reasons.append(
            f"业绩不达标：低于预期{abs(perf_miss):.0f}%，"
            f"超过阈值{config['performance_miss_threshold_pct']}%，建议强制换仓"
        )

    # 检查3: 行业排名下滑
    rank_decline = holding.get("industry_rank_change", 0)
    if rank_decline < -config["industry_rank_decline_threshold"]:
        reasons.append(
            f"行业排名下滑{abs(rank_decline)}位，"
            f"超过阈值{config['industry_rank_decline_threshold']}位"
        )

    # 检查4: 是否错过续持检查
    last_review = holding.get("last_review_quarter", 0)
    if current_quarter - last_review >= 1:
        reasons.append(f"已超过1个季度未进行续持检查（上次检查：Q{last_review}）")

    force_rebalance = len(reasons) > 0

    # 替代方案优先原则
    alternative_prompt = ""
    if force_rebalance:
        alternative_prompt = (
            "【替代方案优先原则】在讨论是否继续持有前，"
            "请先回答：若现在不持有此标的，会买什么？"
            "对比当前持仓是否仍是最优选择"
        )

    return {
        "force_rebalance": force_rebalance,
        "reasons": reasons,
        "alternative_prompt": alternative_prompt,
        "holding_months": holding_months,
        "message": "需强制换仓" if force_rebalance else "续持检查通过",
    }
```

---

## 三、五个最高优先级落地项（可直接改代码）

### ① 把"损失厌恶"嵌入 `src/monitor/monitor.py` ⑨ 调仓执行

**当前问题**：monitor.py 里 `cost_pct_below: -12.0` 是硬编码单线阈值，缺少"对称止盈"（概念②）和"心理止损"（概念⑬）。

**改动点**：
- `src/monitor/monitor.py`：增加 `BEHAVIORAL_RISK_CONFIG` 配置，在 `run_once()` 中调用 `check_symmetric_risk_rules()`
- 新增 `src/behavioral/loss_aversion.py`：对称风控规则 + 亏损日记

**验证方式**（对齐手册概念②模拟盘验证）：以"对称止盈止损法"替代原有"宽松止损法"运行3个月，对比年化收益率、最大回撤、胜率、夏普比。

---

### ② 把"幂律分布 + 心理账户"嵌入 `src/kelly/stock_kelly_analyzer.py` ⑥ 组合构建

**当前问题**：凯利仓位虽然 `single_max_fraction=10%`，但没有显式的"核心+卫星"架构，也没有心理账户中性校验。

**改动点**：
- `src/kelly/stock_kelly_analyzer.py`：在 `analyze()` 输出后调用 `apply_core_satellite()` 调整仓位
- 新增 `src/behavioral/power_law.py`：核心+卫星架构 + 幂律贡献度追踪
- 新增 `src/behavioral/mental_accounting.py`：心理账户中性化检测

---

### ③ 把"锚定效应 + 确认偏误"嵌入 ④ 公司研究

**当前问题**：`src/trend/stock_analysis.py` 仅输出正面研究结论，没有反面证据专章。

**改动点**：
- `src/trend/stock_analysis.py`：在 `analyze()` 输出中增加 `counter_evidence` 和 `deanchoring_checklist` 字段
- 新增 `src/behavioral/confirmation_bias.py`：反面证据专章生成器
- 新增 `src/behavioral/deanchoring.py`：去锚定检查清单

---

### ④ 把"双系统理论 + 过度自信"嵌入 ⑩ 归因复盘

**当前问题**：`src/attribution/review.py` 尚未实现。

**改动点**：
- 新建 `src/attribution/review.py`：归因报告强制包含系统一/二决策占比与过度自信预警指标
- 新增 `src/behavioral/dual_system.py`：系统二介入检查点
- 新增 `src/behavioral/overconfidence.py`：过度自信预警体系

---

### ⑤ 把"纳什均衡 + 囚徒困境 + 信号传递"嵌入 ⓪ 审查④

**当前问题**：风控报告只看硬红线，不看行业博弈状态与信号可信度。

**改动点**：
- `src/risk/checker.py`（待建）：风控报告增加三张附表（博弈状态/产能预警/信号评分）
- 新增 `src/behavioral/nash_equilibrium.py`：均衡识别三步法
- 新增 `src/behavioral/prisoner_dilemma.py`：囚徒困境预警框架
- 新增 `src/behavioral/signaling.py`：信号可信度评估框架

---

## 四、工程层面落地建议

### 建议新增 `src/behavioral/` 子包（跨域概念执行器）

```
src/behavioral/
├── __init__.py
├── deanchoring.py         ← 概念① 去锚定检查清单
├── loss_aversion.py       ← 概念② 对称风控规则
├── overconfidence.py      ← 概念③ 过度自信预警
├── nash_equilibrium.py    ← 概念④ 均衡识别三步法
├── signaling.py           ← 概念⑤ 信号可信度评估
├── prisoner_dilemma.py    ← 概念⑥ 囚徒困境预警
├── dual_system.py         ← 概念⑦ 系统二介入检查点
├── confirmation_bias.py   ← 概念⑧ 反面证据专章
├── mental_model.py        ← 概念⑨ 心智模型更新清单
├── network_effect.py      ← 概念⑩ 网络效应护城河评估
├── power_law.py           ← 概念⑪ 核心+卫星架构
├── weak_ties.py           ← 概念⑫ 弱连接信息采集
├── prospect_theory.py     ← 概念⑬ 行为化风险评估
├── mental_accounting.py   ← 概念⑭ 心理账户中性化
└── status_quo.py          ← 概念⑮ 现状偏见突破机制
```

### 在 `src/pipeline.py` 中挂接调用

```python
# 环节⑥ 组合构建结束后
from src.behavioral.power_law import apply_core_satellite
from src.behavioral.mental_accounting import check_neutrality

portfolio = apply_core_satellite(kelly_results, core_count=3, core_weight=0.60)
mental_ok = check_neutrality(portfolio, historical_pnl)
if not mental_ok:
    log("⚠️ 心理账户效应检测到，需人工复核")

# 环节④ 公司研究输出后
from src.behavioral.confirmation_bias import check_report_objectivity
from src.behavioral.deanchoring import run_deanchoring_check

objectivity = check_report_objectivity(research_report)
if not objectivity["passed"]:
    log(f"⚠️ 研究报告客观性检查未通过：{objectivity['missing_sections']}")

# 环节⑨ 调仓执行中
from src.behavioral.loss_aversion import check_symmetric_risk_rules

for position in current_positions:
    risk_check = check_symmetric_risk_rules(position, current_price)
    if risk_check["action"] == "force_sell":
        log(f"⚠️ {risk_check['reason']}")
        if risk_check.get("journal_required"):
            write_loss_journal(position["symbol"], "force_sell",
                             risk_check["pnl_pct"], risk_check["reason"])
```

---

## 五、落地优先级路线图

| 阶段 | 时间 | 目标 | 交付物 | 验证方式 |
|---|---|---|---|---|
| **Phase 1** | 1–2 周 | **纪律层面**：损失厌恶 + 前景理论 + 幂律分布 | `loss_aversion.py`、`prospect_theory.py`、`power_law.py` 接入 monitor/kelly | 对称止盈止损 vs 宽松止损 3个月回测对比 |
| **Phase 2** | 3–4 周 | **认知层面**：确认偏误 + 锚定效应 + 双系统理论 | `confirmation_bias.py`、`deanchoring.py`、`dual_system.py` 接入 research/review | 研究报告客观性评分 + 系统二决策占比 ≥70% |
| **Phase 3** | 5–6 周 | **结构层面**：纳什均衡 + 囚徒困境 + 信号传递 | `nash_equilibrium.py`、`prisoner_dilemma.py`、`signaling.py` 接入 risk-check | 风控报告附表A/B/C完整输出 |
| **Phase 4** | 7–8 周 | **复盘层面**：剩余 5 个概念全覆盖 | 完整 behavioral 子包 + 迁移笔记自动生成器 | 15概念全部接入流水线 |

---

## 六、HABP 协议人机边界提醒

根据 `main_auto_workflow.md` 第 4 节 HABP 协议的**刚性/柔性划分**：

| 边界类型 | 对应跨域概念 | 执行方式 | 审查点 |
|---|---|---|---|
| **刚性边界（禁止豁免）** | ② 损失厌恶的硬止损、⑪ 幂律分布的凯利缩放 | AI 主导，人类仅抽查 | ⓪ 审查④ |
| **柔性边界（可人工覆盖）** | ⑨ 心智模型更新、⑫ 弱连接信息解读 | 人类主导，AI 提供辅助 | ⓪ 审查②③ |
| **混合边界** | ⑧ 确认偏误的反面证据（AI生成+人类审核） | AI 生成框架，人类确认内容 | ⓪ 审查② |

**关键提醒**：避免过度自动化。跨域迁移的精髓是"**用理论倒逼决策者写清楚自己的逻辑**"，如果全部自动化反而会变成新的认知陷阱（形成"算法确认偏误"）。

---

## 七、与现有硬约束（H1–H13）的协同关系

| 跨域概念 | 协同的硬约束 | 协同方式 | 冲突风险与处理 |
|---|---|---|---|
| ② 损失厌恶 | H11（持仓≤3日）、H12（日亏≤2%）、H13（回撤≤5%） | 概念补强 H11–H13 的执行纪律，避免人为豁免 | 无冲突，概念强化硬约束执行 |
| ⑪ 幂律分布 | H6（半凯利）、H9（单票≤10%、组合≤80%、单行业≤30%） | 概念调整"均匀分散"为"核心+卫星" | ⚠️ 核心仓位 `core_max_single=15%` 突破 H9 的 10% 限制，需在 ⓪ 审查③ 中人工确认 |
| ⑬ 前景理论 | H12、H13 | 概念增加"心理回撤"维度，与数学回撤双报告 | 无冲突，概念增加维度不替换硬约束 |
| ⑧ 确认偏误 | H1（禁统一阈值筛行业） | 概念强制引入反面证据，避免行业偏见固化 | 无冲突 |
| ④ 纳什均衡 | H1 | 概念提供行业差异化判断框架，支撑 H1 的全行业覆盖 | 无冲突 |
| ⑮ 现状偏见 | H11（持仓≤3日） | 概念的"持仓时钟"与 H11 的 T+3 限制对齐 | ⚠️ 概念的 `max_holding_period_months=3` 远大于 H11 的 3 日，需区分短线/中线场景 |

---

## 八、下一步行动建议

可选择以下任一方向推进：

- **A）Phase 1 落地**：直接写 `src/behavioral/loss_aversion.py`（最高优先级，直接影响交易纪律）
- **B）审查点增强**：在 `src/pipeline.py` 的 4 个审查点加跨域概念的提示逻辑
- **C）CLI 原型**：先做一个"跨域审查清单"CLI 命令原型（`python run.py --behavioral-check`）
- **D）回测验证**：在 `src/backtest/runner.py` 中增加"对称止盈止损 vs 宽松止损"对比模式，量化验证损失厌恶防控效果

---

*文档生成时间：2026-08-12*
*依据文件：`跨域迁移法_全概念实战手册.md` + `docs/workflow/main_auto_workflow.md`*
*适用项目：TransAlpha 量化投资工作流 v4*
