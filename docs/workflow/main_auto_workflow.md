# TransAlpha 量化投资系统 — 自动化流水线 (CLI 版)

> **入口文档**。当用户说"运行一下 main_auto_workflow.md"时，Agent 按本文档自动执行全流程，仅在关键节点暂停寻求人类建议。
>
> **设计依据**：`AI量化投资流水线(1).md` 的 10 步端到端人工投资体系。其中 ① 投资信仰、② 赛道选择 由 `TransAlpha小组投资信仰手册.md` 与 `TransAlpha赛道景气度打分表.md` 作为前置输入，不在本流水线内执行；本流水线从 ③ 信息收集 起跑，覆盖 8 个自动化环节 + 4 个人工审查暂停点。

---

## 1. 流水线总览

```
③ 信息收集      ⓪ 人工审查①    ④ 公司研究      ⓪ 人工审查②    ⑤ 因子打分      ⑥ 组合构建      ⓪ 人工审查③    ⑦ 回测校验      ⑧ 风险检查      ⓪ 人工审查④    ⑨ 调仓执行      ⑩ 归因复盘
DataFetcher   → ⏸ 数据质量    →  CompanyResearch → ⏸ 研究结论   →  StockScreener →  KellyAnalyzer → ⏸ 组合方案    →  BacktestRunner → RiskChecker  → ⏸ 风控放行    →  RebalanceExec → AttributionReview
(自动)          (暂停等待)      (自动)            (暂停等待)      (自动)          (自动)          (暂停等待)      (自动)           (自动)          (暂停等待)      (自动)          (自动)

全A股数据台账   抽查数据源      个股深度报告      确认候选池      Top10 打分榜单  持仓方案+凯利仓位 组合审查       资金曲线/绩效    风控报告        放行/退回      委托记录+监控    复盘日志
```

| 环节 | 工具/模块 | 自动/手动 | 输入 | 输出 | 输出目录 |
|------|----------|----------|------|------|----------|
| ③ 信息收集 | `src/screener/data_fetcher.py` | 自动 | 全A股代码+赛道景气度表 | 全市场数据台账 | `output/info-collection/market_data.json` |
| ⓪ 人工审查① | CLI 交互 | **手动暂停** | 数据台账 | 数据质量确认 | — |
| ④ 公司研究 | `src/trend/stock_analysis.py` | 自动 | 候选股代码 | 个股深度研究报告 | `output/company-research/research_reports.json` |
| ⓪ 人工审查② | CLI 交互 | **手动暂停** | 研究报告 | 候选池确认 | — |
| ⑤ 因子打分 | `src/screener/screener.py` | 自动 | 候选池+数据台账 | Top10 打分榜单 | `output/factor-scoring/top10_stocks.json` |
| ⑥ 组合构建 | `src/kelly/stock_kelly_analyzer.py` | 自动 | Top10 榜单 | 持仓方案+凯利仓位 | `output/portfolio-construction/portfolio.json` |
| ⓪ 人工审查③ | CLI 交互 | **手动暂停** | 持仓方案 | 组合方案确认 | — |
| ⑦ 回测校验 | `src/backtest/runner.py` | 自动 | 宽池（默认中证500） | 资金曲线/绩效指标/交易记录 | `output/backtest/equity_curve.csv`, `metrics.json`, `trade_log.csv` |
| ⑧ 风险检查 | `src/risk/checker.py`（待建） | 自动 | 持仓方案+回测结果 | 风控检查报告 | `output/risk-check/risk_report.json` |
| ⓪ 人工审查④ | CLI 交互 | **手动暂停** | 风控报告 | 风控放行/退回 | — |
| ⑨ 调仓执行 | `src/monitor/monitor.py` | 自动 | 最终持仓方案 | 委托记录+实时监控预警 | `output/rebalance-execution/orders.json`, `alerts.json` |
| ⑩ 归因复盘 | `src/attribution/review.py`（待建） | 自动 | 交易记录+绩效 | 复盘日志+方法论更新建议 | `output/attribution-review/review_log.md` |

> **闭环规则**：⑩ 归因复盘的结论回流至 ① 投资信仰手册与 ② 赛道景气度打分表，形成"信仰 → 赛道 → 信息 → 研究 → 打分 → 组合 → 回测 → 风控 → 执行 → 复盘 → 信仰"的完整迭代闭环。

---

## 2. 运行方式

### 一键启动 (CLI)

```bash
cd <项目根目录>
python run.py
```

### 子命令

```bash
python run.py              # 运行完整流水线 (8环节)
python run.py --collect    # 仅运行 ③ 信息收集
python run.py --research   # 仅运行 ④ 公司研究
python run.py --score      # 仅运行 ⑤ 因子打分
python run.py --portfolio  # 仅运行 ⑥ 组合构建
python run.py --backtest   # 仅运行 ⑦ 回测校验
python run.py --risk       # 仅运行 ⑧ 风险检查
python run.py --rebalance  # 仅运行 ⑨ 调仓执行
python run.py --review     # 仅运行 ⑩ 归因复盘
python run.py --status     # 查看当前流水线状态
python run.py --reset      # 重置流水线 (清空输出)
```

### Python API 调用

```python
from src.pipeline import (
    run_info_collection_stage,    # ③
    run_manual_review_data,       # ⓪ 人工审查①
    run_company_research_stage,   # ④
    run_manual_review_research,   # ⓪ 人工审查②
    run_factor_scoring_stage,     # ⑤
    run_portfolio_stage,          # ⑥
    run_manual_review_portfolio,  # ⓪ 人工审查③
    run_backtest_stage,           # ⑦
    run_risk_check_stage,         # ⑧
    run_manual_review_risk,       # ⓪ 人工审查④
    run_rebalance_stage,          # ⑨
    run_attribution_stage,        # ⑩
    run_pipeline,
)

# 完整流水线
run_pipeline()
```

### Agent 执行指令

当用户说"运行一下 main_auto_workflow.md"时，Agent 应：

1. 读取本文档获取全流程规范
2. 读取前置文档 `TransAlpha小组投资信仰手册.md`（风险红线 + AI Agent 行为准则）和 `TransAlpha赛道景气度打分表.md`（六维热度打分 + 短线三层信息源）
3. 执行 ③ 信息收集（自动），结果保存到 `output/info-collection/`
4. **暂停①**：展示数据台账摘要，等待用户抽查数据质量
5. 用户确认后，执行 ④ 公司研究（自动），结果保存到 `output/company-research/`
6. **暂停②**：展示个股研究报告，等待用户确认候选池
7. 用户确认后，执行 ⑤ 因子打分（自动），结果保存到 `output/factor-scoring/`
8. 自动执行 ⑥ 组合构建，结果保存到 `output/portfolio-construction/`
9. **暂停③**：展示持仓方案+凯利仓位，等待用户审查
10. 用户确认后，执行 ⑦ 回测校验，结果保存到 `output/backtest/`
11. 自动执行 ⑧ 风险检查，结果保存到 `output/risk-check/`
12. **暂停④**：展示风控报告，等待用户放行或退回
13. 用户放行后，执行 ⑨ 调仓执行，结果保存到 `output/rebalance-execution/`
14. 自动执行 ⑩ 归因复盘，结果保存到 `output/attribution-review/`
15. 最终展示监控预警状态 + 回测绩效 + 复盘结论

**代码路径对照表**:

| 环节 | 源文件位置 | 导入方式 |
|------|----------|----------|
| 流水线主入口 | `src/pipeline.py` | `from src.pipeline import run_pipeline` |
| ③ 信息收集 | `src/screener/data_fetcher.py` | `from src.screener.data_fetcher import StockDataFetcher` |
| ④ 公司研究 | `src/trend/stock_analysis.py` | `from src.trend.stock_analysis import StockAnalyzer` |
| ⑤ 因子打分 | `src/screener/screener.py` | `from src.screener.screener import StockScreener` |
| ⑥ 组合构建 | `src/kelly/stock_kelly_analyzer.py` | `from src.kelly.stock_kelly_analyzer import StockKellyAnalyzer` |
| ⑦ 回测校验 | `src/backtest/runner.py` | `from src.backtest.runner import BacktestRunner` |
| ⑧ 风险检查 | `src/risk/checker.py`（待建） | `from src.risk.checker import RiskChecker` |
| ⑨ 调仓执行 | `src/monitor/monitor.py` | `from src.monitor.monitor import StockAlert` |
| ⑩ 归因复盘 | `src/attribution/review.py`（待建） | `from src.attribution.review import AttributionReview` |

---

## 3. 各环节详解

### 环节③ 信息收集（自动）

**工具**: `src/screener/data_fetcher.py`

**数据源依据**: `TransAlpha赛道景气度打分表.md` 的"短线三层信息源"（盘前层/盘中层/盘后层）+ `TransAlpha小组投资信仰手册.md` 的"全行业覆盖"定位。

**调用方式**:
```python
from src.screener.data_fetcher import StockDataFetcher
fetcher = StockDataFetcher()
# 获取全A股列表（优先 akshare，回退到东方财富直连）
stocks = fetcher.get_all_a_stocks(max_count=0, use_cache=True)
# 批量获取实时行情
quotes = fetcher.fetch_batch_quotes(stocks)
# 构建数据台账
market_data = {"stocks": stocks, "quotes": quotes, "timestamp": ...}
```

**输出**: `output/info-collection/market_data.json`

详见：`docs/workflow/steps/info-collection_auto_workflow.md`

### ⓪ 人工审查①（暂停）

**触发条件**: ③ 信息收集完成后自动暂停

**操作方式**: CLI 交互 — 展示数据台账摘要（股票数量、数据源、缺失率），用户抽查数据质量

**设计意图**: 防止数据源静默降级（如 59 只硬编码清单冒充全市场），抽查发现异常应立即中止。

### 环节④ 公司研究（自动）

**工具**: `src/trend/stock_analysis.py`

**数据源依据**: `TransAlpha小组投资信仰手册.md` 的"选股逻辑：资金驱动 + 技术形态 + 短线催化" + `TransAlpha赛道景气度打分表.md` 的"六维热度打分模型"。

**调用方式**:
```python
from src.trend.stock_analysis import StockAnalyzer
analyzer = StockAnalyzer()
result = analyzer.analyze("600519", show_progress=False)
```

**输出**: `output/company-research/research_reports.json`

详见：`docs/workflow/steps/company-research_auto_workflow.md`

### ⓪ 人工审查②（暂停）

**触发条件**: ④ 公司研究完成后自动暂停

**操作方式**: CLI 交互 — 展示研究报告，用户确认候选池（哪些股票进入打分环节）

### 环节⑤ 因子打分（自动）

**工具**: `src/screener/screener.py`

**调用方式**:
```python
from src.screener.screener import StockScreener
screener = StockScreener()
results = screener.run_screening(top_n=10, mode="all")
```

**评分体系**: 基本面(40) + 趋势动量(20) + 量价筹码(15) + 资金面行为(25) = 满分100（方案A四流派权重）

**输出**: `output/factor-scoring/top10_stocks.json`

详见：`docs/workflow/steps/stock-scoring_auto_workflow.md`

### 环节⑥ 组合构建（自动）

**工具**: `src/kelly/stock_kelly_analyzer.py`

**调用方式**:
```python
from src.kelly.stock_kelly_analyzer import StockKellyAnalyzer
analyzer = StockKellyAnalyzer(total_capital=1000000, kelly_scaling=0.5)
result = analyzer.analyze("600519", silent=True)
```

**关键参数**:
- `kelly_scaling=0.5` → **半凯利**（安全边际，对应信仰手册"风险承受上限"）
- `single_max_fraction=0.10` → 单票最大仓位 10%（信仰手册红线）
- `portfolio_max_total_pct=0.80` → 组合总仓位上限 80%

**输出**: `output/portfolio-construction/portfolio.json`

详见：`docs/workflow/steps/portfolio-construction_auto_workflow.md`

### ⓪ 人工审查③（暂停）

**触发条件**: ⑥ 组合构建完成后自动暂停

**操作方式**: CLI 交互 — 展示持仓方案+凯利仓位，用户审查确认（可调整仓位，但不得突破信仰手册红线）

### 环节⑦ 回测校验（自动）

**工具**: `src/backtest/runner.py` + `src/backtest/data_loader.py` + `src/backtest/proxy_metrics.py` + `src/backtest/report.py`

**调用方式**:
```python
from src.backtest.runner import BacktestConfig, BacktestRunner
from src.backtest.report import export_backtest_result

cfg = BacktestConfig(
    initial_capital=1_000_000.0,
    start_date="2023-01-01", end_date="2024-06-30",
    rebalance="monthly", top_n=5, max_single_fund=0.10, stop_loss_ma20=True,
)
runner = BacktestRunner(cfg=cfg)
result = runner.run(stock_pool=None)
paths = export_backtest_result(result)
```

**输出**: `output/backtest/`（equity_curve.csv / metrics.json / trade_log.csv）

详见：`docs/workflow/steps/review-backtest_auto_workflow.md`

### 环节⑧ 风险检查（自动）

**工具**: `src/risk/checker.py`（待建，当前由 `review-backtest` 中的风险检查清单临时承接）

**检查依据**: `TransAlpha小组投资信仰手册.md` 第 1.2 节"风险承受上限（核心红线）"。

**输出**: `output/risk-check/risk_report.json`

详见：`docs/workflow/steps/risk-check_auto_workflow.md`

### ⓪ 人工审查④（暂停）

**触发条件**: ⑧ 风险检查完成后自动暂停

**操作方式**: CLI 交互 — 展示风控报告，用户决定放行（进入调仓执行）或退回（回到 ⑥ 组合构建调整）

### 环节⑨ 调仓执行（自动）

**工具**: `src/monitor/monitor.py`（含原卖点确定逻辑 + 实时监控）

**调用方式**:
```python
from src.monitor.monitor import StockAlert
alert_system = StockAlert(log_to_file=True, log_to_console=False)
result = alert_system.run_once(smart_mode=True)
```

**输出**: `output/rebalance-execution/orders.json`, `alerts.json`

详见：`docs/workflow/steps/rebalance-execution_auto_workflow.md`

### 环节⑩ 归因复盘（自动）

**工具**: `src/attribution/review.py`（待建，当前由 `review-backtest` 中的归因复盘模板临时承接）

**输出**: `output/attribution-review/review_log.md`

详见：`docs/workflow/steps/attribution-review_auto_workflow.md`

---

## 4. HABP协议人机边界

| 任务类型 | 人机边界 | 机器内部边界性质 | 判定理由 | 示例 |
| --- | --- | --- | --- | --- |
| 数据质量核查 | AI主导，人类抽查 | 刚性 | 确定性程序化采集 | 全A股列表完整性、行情数据缺失率 |
| 公司研究结论 | 人机协作，AI建议须经人类确认 | 柔性 | 依赖主观研判 | 企业核心壁垒判断、管理层质量 |
| 财务指标计算 | AI主导，人类抽查 | 刚性 | 确定性程序化计算 | 市盈率、资产负债率计算 |
| 因子打分 | AI主导，人类抽查 | 刚性 | 基于既定公式的量化输出 | 因子暴露度计算 |
| 组合仓位分配 | 人机协作，AI建议须经人类确认 | 柔性 | 依赖主观研判 | 行业分散度、现金储备比例 |
| 风控规则校验 | AI主导，禁止人类临时豁免 | 刚性 | 防止系统性风险 | 单一标的仓位上限、回撤熔断 |
| 尾部情景构建 | 人类主导，AI提供历史案例参考 | 柔性 | 需要创造性推演 | 黑天鹅情景设想 |

### 本系统的暂停环节与边界映射

| 暂停环节 | 对应任务类型 | 边界性质 | 暂停目的 |
|---------|------------|---------|---------|
| ⓪ 人工审查①（信息收集后） | 数据质量核查 + 财务指标计算 | 刚性 | 抽查数据源是否降级、行情数据是否异常 |
| ⓪ 人工审查②（公司研究后） | 公司研究结论 | 柔性 | 人类确认候选池，决定哪些股票进入打分 |
| ⓪ 人工审查③（组合构建后） | 组合仓位分配 + 尾部情景构建 | 柔性 | 人类调整仓位，覆盖凯利最优解（但不突破信仰手册红线） |
| ⓪ 人工审查④（风险检查后） | 风控规则校验 | 刚性 | 人类决定放行或退回，但风控红线不得临时豁免 |

---

## 5. 目录结构

```
TransAlpha工作流_v2/
├── run.py                                ← 启动入口 (CLI)
├── requirements.txt                      ← 统一依赖清单
│
├── TransAlpha小组投资信仰手册.md           ← ① 投资信仰（前置输入，不在流水线内执行）
├── TransAlpha赛道景气度打分表.md           ← ② 赛道选择（前置输入，不在流水线内执行）
├── AI量化投资流水线(1).md                  ← 10步端到端设计文档（本流水线的设计依据）
│
├── src/                                  ← 源代码根目录
│   ├── __init__.py
│   ├── pipeline.py                       ← ⭐ 核心流水线 (CLI 编排 + 状态管理)
│   │
│   ├── screener/                         ← ③⑤ 信息收集 + 因子打分
│   │   ├── __init__.py
│   │   ├── screener.py                   ←   ⑤ 选股引擎 (StockScreener v6.0 四流派打分)
│   │   ├── data_fetcher.py              ←   ③ 数据爬取 (StockDataFetcher)
│   │   ├── volume_price_analyzer.py     ←   ⑤ 量价筹码分析 (流派2)
│   │   ├── capital_flow_analyzer.py     ←   ⑤ 资金面行为分析 (流派4)
│   │   └── factor_model.py              ←   ⑤ CH-4 因子模型
│   │
│   ├── trend/                            ← ④ 公司研究
│   │   ├── __init__.py
│   │   └── stock_analysis.py             ←   技术指标 + 形态识别 + 个股深度分析
│   │
│   ├── kelly/                            ← ⑥ 组合构建
│   │   ├── __init__.py
│   │   └── stock_kelly_analyzer.py       ←   多维度评分 + 凯利公式
│   │
│   ├── backtest/                         ← ⑦ 回测校验
│   │   ├── __init__.py
│   │   ├── data_loader.py                ←   baostock 历史数据
│   │   ├── proxy_metrics.py              ←   六维打分
│   │   ├── costs.py                      ←   A股交易成本
│   │   ├── rules.py                      ←   A股交易规则
│   │   ├── metrics.py                    ←   绩效指标
│   │   ├── runner.py                     ←   回测主循环
│   │   └── report.py                     ←   三文件导出
│   │
│   ├── risk/                             ← ⑧ 风险检查（待建）
│   │   ├── __init__.py
│   │   └── checker.py                    ←   风控规则校验
│   │
│   ├── monitor/                          ← ⑨ 调仓执行
│   │   ├── __init__.py
│   │   ├── monitor.py                    ←   核心引擎 (七大预警 + 卖点监控)
│   │   ├── analyser.py                   ←   智能分析
│   │   └── db_lock.py                    ←   跨进程文件锁
│   │
│   └── attribution/                      ← ⑩ 归因复盘（待建）
│       ├── __init__.py
│       └── review.py                     ←   收益归因 + 方法论更新建议
│
├── output/                               ← ⭐ 运行时输出 (8个环节各一个目录)
│   ├── info-collection/                  ←   ③ 信息收集输出
│   │   └── market_data.json
│   ├── company-research/                 ←   ④ 公司研究输出
│   │   └── research_reports.json
│   ├── factor-scoring/                   ←   ⑤ 因子打分输出
│   │   └── top10_stocks.json
│   ├── portfolio-construction/           ←   ⑥ 组合构建输出
│   │   └── portfolio.json
│   ├── backtest/                         ←   ⑦ 回测校验输出
│   │   ├── equity_curve.csv
│   │   ├── metrics.json
│   │   └── trade_log.csv
│   ├── risk-check/                       ←   ⑧ 风险检查输出
│   │   └── risk_report.json
│   ├── rebalance-execution/              ←   ⑨ 调仓执行输出
│   │   ├── orders.json
│   │   └── alerts.json
│   ├── attribution-review/               ←   ⑩ 归因复盘输出
│   │   └── review_log.md
│   └── pipeline_state.json              ←   流水线状态
│
├── tests/                                ← 测试套件
│
└── docs/                                 ← 文档库
    └── workflow/
        ├── main_auto_workflow.md          ←   本文件 (入口文档)
        └── steps/
            ├── info-collection_auto_workflow.md       ← ③ 信息收集
            ├── company-research_auto_workflow.md      ← ④ 公司研究
            ├── stock-scoring_auto_workflow.md         ← ⑤ 因子打分
            ├── portfolio-construction_auto_workflow.md← ⑥ 组合构建
            ├── review-backtest_auto_workflow.md       ← ⑦ 回测校验
            ├── risk-check_auto_workflow.md            ← ⑧ 风险检查
            ├── rebalance-execution_auto_workflow.md   ← ⑨ 调仓执行
            └── attribution-review_auto_workflow.md    ← ⑩ 归因复盘
```

---

## 6. 硬约束

| # | 约束 | 理由 | 来源 |
|---|------|------|------|
| H1 | 禁止用统一财务阈值筛选所有行业 | 银行高负债、半导体周期底部ROE可能为负 | 信仰手册"全行业覆盖" |
| H2 | API请求必须走 `data_fetcher.py` 容器层 | 第三方接口不稳定，需多源备份+指数退避 | 工程规范 |
| H3 | 股票列表缓存有效期7天 | 保证数据时效性 | 工程规范 |
| H4 | API不可用时降级到热门龙头股池，但必须在⓪人工审查①中明示 | 保证系统不空跑，但不得静默降级 | 信仰手册"禁止模拟数据" |
| H5 | 买入/卖出判断必须依赖MA20/均线排列 | 基本面解决"买什么"，技术面解决"何时买卖" | 工程规范 |
| H6 | 凯利仓位必须使用半凯利（kelly_scaling=0.5） | 全凯利波动太大，半凯利提供安全边际 | 信仰手册"风险承受上限" |
| H7 | 4个人工审查环节必须暂停等待人类确认 | 人工决策主导，AI辅助执行 | 信仰手册"AI Agent行为准则" |
| H8 | ⓪人工审查①如发现数据降级，必须回退重跑 | 防止错误数据污染下游所有环节 | 信仰手册"禁止模拟数据" |
| H9 | ⓪人工审查③用户修改仓位后，系统必须重新校验风控规则 | 单票上限10%、组合上限80%、单行业30%不得被人工突破 | 信仰手册"风险承受上限" |
| H10 | ⓪人工审查④风控红线不得临时豁免 | 风控一票否决，没有例外 | 信仰手册"AI Agent行为准则" |
| H11 | 最大持仓天数 ≤ 3 个交易日 | 短线交易，超T+3系统自动标记强制平仓 | 信仰手册"风险承受上限" |
| H12 | 日最大亏损容忍 2% | 单日亏损超2%暂停当日所有交易 | 信仰手册"风险承受上限" |
| H13 | 组合最大允许回撤 5% | 回撤达3%预警减半，达5%熔断停止买入 | 信仰手册"风险承受上限" |

---

## 7. 代码规范

- **命名**：模块文件 `snake_case.py`，类名 `PascalCase`，函数 `snake_case`
- **错误处理**：API调用层必须 `try-except` + 重试
- **日志**：关键操作用 `print` 带时间戳前缀
- **输出格式**：JSON 格式（存入 `output/` 对应子目录）
- **路径**：全部使用相对路径（`Path(__file__).parent` 等），禁止硬编码绝对路径
- **依赖**：新增第三方库写入 `requirements.txt`
- **数据源降级透明**：任何降级行为必须在输出中标注 `degraded: true` 并说明原因，供⓪人工审查①检查
