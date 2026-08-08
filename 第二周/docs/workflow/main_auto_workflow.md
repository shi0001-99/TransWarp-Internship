# TransAlpha 量化投资系统 — 自动化流水线 (CLI 版)

> **入口文档**。当用户说"运行一下 main_auto_workflow.md"时，Agent 按本文档自动执行全流程，仅在关键节点暂停寻求人类建议。

***

## 1. 流水线总览

```
① 选股筛选     ② 人工抽查      ③ 趋势分析     ④ 人工确认      ⑤ 凯利仓位     ⑥ 人工审查持仓    ⑦ 实时监控
StockScreener → ⏸ 随机抽查  →  StockAnalyzer → ⏸ 确认买入  →  KellyAnalyzer → ⏸ 审查+改金额 →  StockMonitor
(自动)          (暂停等待)      (自动)          (暂停等待)      (自动)          (暂停等待)       (自动)

Top10 候选股   抽查1只全数据    看涨股票列表    确认买入列表    半凯利持仓建议   最终持仓方案     预警信号
```

| 阶段 | 工具/模块 | 自动/手动 | 输入 | 输出 | 输出目录 |
|------|----------|----------|------|------|----------|
| ① 选股筛选 | `src/screener/screener.py` | 自动 | 热门500只股票（按成交额排序） | Top10 候选股票 | `output/screening/top10_stocks.json` |
| ② 人工抽查 | CLI 交互 | **手动暂停** | Top10 候选股票 | 确认通过的股票列表 | — |
| ③ 趋势分析 | `src/screener/data_fetcher.py` | 自动 | 通过审核的股票代码 | 趋势看涨股票列表 | `output/trend/analysis_results.json` |
| ④ 人工确认 | CLI 交互 | **手动暂停** | 趋势分析结果 | 确认买入的股票列表 | — |
| ⑤ 凯利仓位 | `src/kelly/stock_kelly_analyzer.py` | 自动 | 确认的股票列表 | 半凯利持仓建议 | `output/kelly/kelly_suggestions.json` |
| ⑥ 人工审查持仓 | CLI 交互 | **手动暂停** | 凯利持仓建议 | 最终持仓方案 | — |
| ⑦ 实时监控 | `src/monitor/monitor.py` | 自动 | 最终持仓方案 | 七大预警规则实时监控 | `output/monitor/watchlist.json`, `output/monitor/alerts.json` |

> **回测校验暂未接入**，后续在 ⑦ 之后增加 `backtest/` 模块。

***

## 2. 运行方式

### 一键启动 (CLI)

```bash
cd <项目根目录>
python run.py
```

### 子命令

```bash
python run.py              # 运行完整流水线 (7阶段)
python run.py --screen     # 仅运行选股筛选
python run.py --analyze    # 仅运行趋势分析
python run.py --kelly      # 仅运行凯利仓位
python run.py --monitor    # 仅运行实时监控
python run.py --status     # 查看当前流水线状态
python run.py --reset      # 重置流水线 (清空输出)
```

### Python API 调用

```python
from src.pipeline import (
    run_screening_stage,
    run_manual_review,
    run_analysis_stage,
    run_manual_confirmation,
    run_kelly_stage,
    run_position_review,
    run_monitor_stage,
    run_pipeline,
)

# 完整流水线
run_pipeline()

# 或单独运行某阶段
run_screening_stage(mode="hot", top_n=10)
```

### Agent 执行指令

当用户说"运行一下 main_auto_workflow.md"时，Agent 应：

1. 读取本文档（`docs/workflow/main_auto_workflow.md`）获取全流程规范
2. 执行 `python run.py` 启动流水线
3. 阶段①自动完成（选股筛选 Top10），结果保存到 `output/screening/top10_stocks.json`
4. **阶段②暂停**，从 `output/screening/top10_stocks.json` 读取结果，随机抽取1只股票展示，等待用户确认
5. 用户确认后，自动执行阶段③（趋势分析），结果保存到 `output/trend/analysis_results.json`
6. **阶段④暂停**，展示趋势分析结果，等待用户确认买入列表
7. 用户确认后，自动执行阶段⑤（凯利仓位计算），结果保存到 `output/kelly/kelly_suggestions.json`
8. **阶段⑥暂停**，展示凯利建议，等待用户审查持仓方案
9. 用户确认后，自动执行阶段⑦（实时监控），结果保存到 `output/monitor/`
10. 最终展示监控预警状态

**代码路径对照表**:

| 阶段 | 源文件位置 | 导入方式 |
|------|----------|----------|
| 流水线主入口 | `src/pipeline.py` | `from src.pipeline import run_pipeline` |
| ① 选股筛选 | `src/screener/screener.py` | `from src.screener.screener import StockScreener` |
| ③ 趋势分析 | `src/screener/data_fetcher.py` | `from src.screener.data_fetcher import StockAnalyzer` |
| ⑤ 凯利仓位 | `src/kelly/stock_kelly_analyzer.py` | `from src.kelly.stock_kelly_analyzer import StockKellyAnalyzer` |
| ⑦ 实时监控 | `src/monitor/monitor.py` | `from src.monitor.monitor import StockMonitor` |

***

## 3. 各阶段详解

### 阶段① 选股筛选（自动）

**工具**: `src/screener/screener.py`

**股票池来源**: 东方财富API按成交额排序的热门500只股票（`_fetch_hot_stocks_api`），API不可用时降级到硬编码龙头股池（`_get_hardcoded_hot_stocks`，59只）

**调用方式**:
```python
from src.screener.screener import StockScreener
screener = StockScreener()
results = screener.run_screening(top_n=10, mode="hot")
```

**输出**: `output/screening/top10_stocks.json`
```json
{
  "mode": "hot",
  "results": [
    {
      "symbol": "600519",
      "name": "贵州茅台",
      "price": 1680.00,
      "score": 85.2,
      "industry": "消费.白酒"
    }
  ]
}
```

**评分体系**: 基本面(40) + 技术面(40) + 资金面(20) = 满分100

### 阶段② 人工抽查（暂停）

**触发条件**: 阶段①筛选出 Top10 后自动暂停

**操作方式**: CLI 交互 — 展示候选列表，用户输入通过的序号

**设计意图**: 防止筛选系统静默失效——抽查发现数据异常时应立即中止。

### 阶段③ 趋势分析（自动）

**工具**: `src/screener/data_fetcher.py`

**调用方式**:
```python
from src.screener.data_fetcher import StockAnalyzer
analyzer = StockAnalyzer()
result = analyzer.get_stock_analysis("600519")
```

**筛选条件**: `signal_direction == "看多"` 且 `score >= 55`

**输出**: `output/trend/analysis_results.json`

### 阶段④ 人工确认（暂停）

**触发条件**: 阶段③趋势分析完成后自动暂停

**操作方式**: CLI 交互 — 展示分析结果，用户输入确认的股票序号

### 阶段⑤ 凯利仓位计算（自动）

**工具**: `src/kelly/stock_kelly_analyzer.py`

**调用方式**:
```python
from src.kelly.stock_kelly_analyzer import StockKellyAnalyzer
analyzer = StockKellyAnalyzer(total_capital=1000000, kelly_scaling=0.5)
result = analyzer.analyze_stock("600519")
```

**关键参数**:
- `kelly_scaling=0.5` → **半凯利**（安全边际）
- `single_max_fraction=0.25` → 单票最大仓位 25%
- `portfolio_max_total_pct=0.80` → 组合总仓位上限 80%

**输出**: `output/kelly/kelly_suggestions.json`

### 阶段⑥ 人工审查持仓（暂停）

**触发条件**: 阶段⑤凯利计算完成后自动暂停

**操作方式**: CLI 交互 — 展示凯利建议，用户审查确认

### 阶段⑦ 实时监控（自动）

**工具**: `src/monitor/monitor.py`

**调用方式**:
```python
from src.monitor.monitor import StockMonitor
monitor = StockMonitor()
monitor.set_watchlist(["600519", "000001"])
alerts = monitor.fetch_realtime_data()
```

**七大预警规则**:
1. 成本百分比：盈利 +15% / 亏损 -12%
2. 日内涨跌幅：个股 ±4%
3. 成交量异动：放量 > 2倍均量
4. 均线金叉/死叉：MA5 上穿/下穿 MA10
5. RSI 超买超卖：RSI > 70 / RSI < 30
6. 跳空缺口：向上/向下跳空 > 0.5%
7. 动态止盈：盈利 10%+ 后回撤 5%/10%

**输出**: `output/monitor/watchlist.json`, `output/monitor/alerts.json`

***

## 4. HABP协议人机边界

| 任务类型 | 人机边界 | 机器内部边界性质 | 判定理由 | 示例 |
| --- | --- | --- | --- | --- |
| 财务指标计算 | AI主导，人类抽查 | 刚性 | 确定性程序化计算 | 市盈率、资产负债率计算 |
| 因子打分 | AI主导，人类抽查 | 刚性 | 基于既定公式的量化输出 | 因子暴露度计算 |
| 策略适用性评分 | 人机协作，AI建议须经人类确认 | 柔性 | 依赖主观研判 | 价值策略适用度评分 |
| 管理层质量判断 | 人类主导，AI提供参考信息 | 柔性 | 涉及综合判断 | 管理层是否值得信任 |
| 风控规则校验 | AI主导，禁止人类临时豁免 | 刚性 | 防止系统性风险 | 单一标的仓位上限校验 |
| 尾部情景构建 | 人类主导，AI提供历史案例参考 | 柔性 | 需要创造性推演 | 黑天鹅情景设想 |

### 本系统的暂停环节与边界映射

| 暂停环节 | 对应任务类型 | 边界性质 | 暂停目的 |
|---------|------------|---------|---------|
| 阶段② 人工抽查 | 财务指标计算 + 因子打分 | 刚性 | 抽查AI计算的财务指标和评分是否准确 |
| 阶段④ 人工确认 | 策略适用性评分 | 柔性 | 人类决定最终买入列表 |
| 阶段⑥ 人工审查持仓 | 策略适用性评分 + 尾部情景构建 | 柔性 | 人类调整仓位，覆盖凯利最优解 |

***

## 5. 目录结构

```
第二周/
├── run.py                                ← 启动入口 (CLI)
├── requirements.txt                      ← 统一依赖清单
│
├── src/                                  ← 源代码根目录
│   ├── __init__.py
│   ├── pipeline.py                       ← ⭐ 核心流水线 (CLI 编排 + 状态管理)
│   │
│   ├── screener/                         ← ① 选股模块 (自包含)
│   │   ├── __init__.py
│   │   ├── screener.py                   ←   选股引擎 (StockScreener)
│   │   └── data_fetcher.py              ←   数据爬取 (StockDataFetcher + StockAnalyzer)
│   │
│   ├── trend/                            ← ③ 趋势分析模块
│   │   ├── __init__.py
│   │   └── stock_analysis.py             ←   技术指标 + 形态识别
│   │
│   ├── kelly/                            ← ⑤ 凯利仓位计算模块
│   │   ├── __init__.py
│   │   └── stock_kelly_analyzer.py       ←   多维度评分 + 凯利公式
│   │
│   └── monitor/                          ← ⑦ 实时监控模块
│       ├── __init__.py
│       ├── monitor.py                    ←   核心引擎 (七大预警)
│       ├── analyser.py                   ←   智能分析
│       └── db_lock.py                    ←   跨进程文件锁 + 原子写入
│
├── output/                               ← ⭐ 运行时输出 (自动生成)
│   ├── screening/                        ←   ① 选股结果
│   │   └── top10_stocks.json
│   ├── trend/                            ←   ③ 趋势分析结果
│   │   └── analysis_results.json
│   ├── kelly/                            ←   ⑤ 凯利建议
│   │   └── kelly_suggestions.json
│   ├── monitor/                          ←   ⑦ 监控数据
│   │   ├── watchlist.json
│   │   ├── alerts.json
│   │   └── monitor.log
│   └── pipeline_state.json              ←   流水线状态
│
├── tests/                                ← 测试套件
│   ├── __init__.py
│   ├── run_tests.py                      ←   一键运行所有测试
│   ├── test_kelly.py
│   ├── test_monitor.py
│   ├── test_trend.py
│   └── test_integration.py
│
└── docs/                                 ← 文档库
    └── workflow/
        └── main_auto_workflow.md          ←   本文件
```

***

## 6. 硬约束

| # | 约束 | 理由 |
|---|------|------|
| H1 | 禁止用统一财务阈值筛选所有行业 | 银行高负债、半导体周期底部ROE可能为负 |
| H2 | API请求必须走 `data_fetcher.py` 容错层 | 第三方接口不稳定，需3备份域名+指数退避 |
| H3 | 股票列表缓存有效期7天 | 保证数据时效性 |
| H4 | API不可用时降级到硬编码热门龙头股池（59只） | 保证系统不空跑 |
| H5 | 买入/卖出判断必须依赖MA20 | 基本面解决"买什么"，技术面解决"何时买卖" |
| H6 | 凯利仓位必须使用半凯利（kelly_scaling=0.5） | 全凯利波动太大，半凯利提供安全边际 |
| H7 | 阶段②④⑥必须暂停等待人类确认 | 人工决策主导，AI辅助执行 |
| H8 | 阶段②抽查如发现数据异常，必须回退重跑 | 防止错误数据污染下游所有环节 |
| H9 | 阶段⑥用户修改金额后，系统必须重新校验风控规则 | 单票上限25%、组合上限80%不得被人工突破 |

***

## 7. 代码规范

- **命名**：模块文件 `snake_case.py`，类名 `PascalCase`，函数 `snake_case`
- **错误处理**：API调用层必须 `try-except` + 重试
- **日志**：关键操作用 `print` 带时间戳前缀
- **输出格式**：JSON 格式（存入 `output/` 对应子目录）
- **路径**：全部使用相对路径（`Path(__file__).parent` 等），禁止硬编码绝对路径
- **依赖**：新增第三方库写入 `requirements.txt`