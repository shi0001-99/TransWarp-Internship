# TransAlpha 量化投资系统

> 本文档是项目入口，做任何任务前先读本文档，再按需读对应子流程文档。

***

## 1. 这是什么项目

TransAlpha 小组的 AI 量化投资系统，覆盖"数据收集 → 选股筛选 → 仓位计算 → 风险监控 → 回测校验"全流程，目标是实现"人工决策主导、AI辅助执行"的量化研究范式。

### 流水线全流程

| 成员      | 环节   | 交付物              |
| ------- | ---- | ---------------- |
| 师文池+夏可欣 | 信息收集 | 标准化数据（行情/财报/资金流） |
| 师文池     | 量化打分 | Top10股票 + 各项小分明细 |
| 薛辉      | 组合构建 | 持仓占比（凯利仓位）       |
| 施夏迪+夏可欣 | 确定卖点 | 卖点计划（目标价/止损价）    |
| 李俊森     | 回测校验 | 合理性验证（夏普/回撤）     |

### 各环节核心功能

| 环节     | 工具/模块                             | 核心功能              | 输入     | 输出               |
| ------ | --------------------------------- | ----------------- | ------ | ---------------- |
| ① 选股筛选 | `stock_screener/  +stock_trend印证` | 多维度评分、行业自适应阈值     | 全A股列表  | Top10候选股票 + 明细评分 |
| ② 仓位计算 | `股票凯利分析器/`                        | 五维评分 + 凯利公式计算最优仓位 | 候选股票代码 | 持仓占比建议（单票仓位%）    |
| ③ 风险监控 | `stock_monitor/+stock_trend印证`    | 七大预警规则、动态止盈止损     | 持仓方案   | 预警信号（买入/卖出提醒）    |
| ④ 回测校验 | `backtest/` \[待开发]                | 策略验证、夏普比率计算       | 买卖记录   | 合理性验证报告          |

<br />

<br />

**技术栈**：Python 3.13 / Pandas / Requests / Flask / akshare / baostock

**运行命令**：

```
# ① 选股筛选
python stock_screener/screener.py              # CLI 全市场选股
python stock_screener/app.py                   # Web 选股界面

# ② 仓位计算（凯利分析器）
cd stock_kelly
python start_server.py                         # 启动 Web 服务 → http://127.0.0.1:5000

# ③ 风险监控
cd stock-monitor-skill/scripts
python monitor_daemon.py                       # 后台常驻监控进程

# ④ 回测校验 [待开发]
python backtest/backtest_validator.py

# 安装依赖
pip install -r stock_screener/requirements.txt
pip install -r 股票凯利分析器/requirements.txt
```

***

## 2. 目录约定

```
第二周/
├── main_auto_workflow.md          ← 本文件（入口，薄）
├── docs/
│   ├── data-collection_auto_workflow.md         ← 数据收集规范
│   ├── stock-scoring_auto_workflow.md           ← 打分规则说明
│   ├── portfolio-construction_auto_workflow.md  ← 组合构建方法
│   ├── sell-point-determination_auto_workflow.md ← 卖点确定规则
│   └── review-backtest_auto_workflow.md         ← 回测校验流程
├── stock_screener/                ← ① 选股筛选模块
│   ├── screener.py                ← 全市场选股引擎
│   ├── data_fetcher.py            ← 数据获取层（含容错）
│   ├── app.py                     ← Flask Web 服务
│   └── stock_list_cache.json      ← 股票列表缓存（7天有效）
├── stock_kelly/                   ← ② 仓位计算模块
│   ├── stock_kelly_analyzer.py    ← 核心分析引擎（五维评分 + 凯利公式）
│   ├── app.py                     ← Flask Web 服务
│   ├── server_daemon.py           ← 后台守护进程
│   └── templates/index.html       ← 前端界面
├── stock_monitor/                 ← ③ 风险监控模块
│   ├── SKILL.md                   ← 使用说明
│   └── scripts/
│       ├── monitor.py             ← 核心监控（七大预警规则）
│       ├── monitor_daemon.py      ← 后台常驻进程
│       ├── analyser.py            ← 智能分析引擎
│       └── web_server.py          ← Web 服务
├── backtest/                      ← ④ 回测校验模块 [待开发]
│   └── backtest_validator.py      ← 策略合理性验证
├── stock_analyzer/                ← 单股分析代码（辅助）
│   └── ai_stock_analyzer.py       ← 单股深度分析
├── 投资知识/                       ← 方法论文档库
│   ├── AI量化投资流水线.md          ← 10步闭环总纲
│   ├── 数据收集关注指标.md          ← 指标速查表
│   └── 关于20日线的技巧/            ← 技术分析参考
└── 股票信息收集/                   ← 个股研报产出目录
```

**新文件落位规则**：

- 选股相关代码 → `stock_screener/`
- 仓位计算相关代码 → `stock_kelly/`
- 风险监控相关代码 → `stock-monitor/`
- 回测校验相关代码 → `backtest/`
- 新的投资方法论笔记 → `投资知识/`
- 个股研报 → `股票信息收集/股票投资报告{date}/`

***

## 3. 流水线交接规范

### 环节交接流程

```
① Screener → ② Kelly
  [输入] Top10候选股票列表（代码 + 名称 + 综合得分 + 各项小分）
  [输出] 每只股票的凯利仓位建议

② Kelly → ③ Monitor
  [输入] 持仓方案（股票代码 + 仓位占比 + 买入价）
  [输出] 预警信号（止盈/止损/趋势破坏提醒）

③ Monitor → ④ Backtest
  [输入] 买卖记录（买入日 + 卖出日 + 收益 + 持仓天数）
  [输出] 策略合理性验证报告（年化收益、最大回撤、夏普比率）
```

### 交接数据格式

每个环节输出必须为 JSON 格式，包含以下字段：

```json
{
  "date": "2026-08-03",
  "stage": "screener",  // 或 "kelly" 或 "monitor" 或 "backtest"
  "output": { ... },
  "summary": {
    "total_count": 10,
    "time_range": "2026-07-01 ~ 2026-08-03",
    "key_metrics": { ... }
  }
}
```

**交接要求**：

- 每个环节输出必须为 JSON 格式，包含完整字段
- 交接时附带数据摘要（样本数、时间范围、关键字段统计）
- 下一环节需校验上游数据完整性，异常时回退到上一环节

***

## 4. 硬约束（必须遵守）

| #  | 约束                                                                        | 理由                                                |
| -- | ------------------------------------------------------------------------- | ------------------------------------------------- |
| H1 | **禁止用统一财务阈值筛选所有行业**。必须走 `data_fetcher.py` 的行业识别逻辑，按行业动态调整 ROE/负债率/现金流阈值。  | 银行天生高负债、半导体周期底部 ROE 可能为负，统一阈值会误杀优质标的。             |
| H2 | **API 请求必须走** **`data_fetcher.py`** **的容错层**，禁止直接 `requests.get` 裸调第三方接口。 | 第三方接口不稳定，容错层内置 3 个备份域名 + 指数退避重试 + 智能降级，裸调会导致程序中断。 |
| H3 | **股票列表缓存有效期 7 天**，过期后必须重新拉取，禁止手动篡改缓存时间戳。                                  | 保证数据时效性，避免用过期股票列表做决策。                             |
| H4 | **API 不可用时自动降级到热门龙头股池（Top 50）**，不得返回空结果。                                  | 保证选股系统每日有输出，不间断运行。                                |
| H5 | **买入/卖出判断必须依赖 20 日均线（MA20）**，不得仅凭基本面得分直接给出操作建议。                           | 基本面解决"买什么"，技术面解决"何时买卖"，两者不可混用。                    |
| H6 | **所有交易操作必须可追溯**，记录委托时间、价格、操作理由。                                           | 禁止无依据临时交易，复盘时需要归因分析。                              |

***

## 5. 代码规范

- **命名**：模块文件用 `snake_case.py`，类名用 `PascalCase`，函数名用 `snake_case`
- **错误处理**：API 调用层必须有 `try-except` + 重试，不得向上层抛裸异常
- **日志**：关键操作（API 切换、缓存命中/过期、选股结果）用 `print` 带时间戳前缀
- **输出格式**：分析报告输出为 Markdown，选股结果输出为 JSON + Markdown 双格式
- **依赖**：新增第三方库必须写入 `requirements.txt`

***

## 6. 子流程入口（重要！）

做具体任务前，先读对应子流程文档：

| 做什么          | 使用工具               | 说明文档                                    |
| ------------ | ------------------ | --------------------------------------- |
| ① 选股筛选、多维度评分 | `stock_screener/`  | `docs/stock-scoring_auto_workflow.md`   |
| ② 仓位计算、凯利公式  | `stock_kelly/`     | `股票凯利分析器/使用说明.md`                       |
| ③ 风险监控、预警信号  | `stock_monitor/`   | `stock-monitor-skill/SKILL.md`          |
| ④ 回测校验、策略验证  | `backtest/` \[待开发] | `docs/review-backtest_auto_workflow.md` |

### 各模块使用指南

#### ① 选股筛选 (Screener)

```bash
# CLI 模式
python stock_screener/screener.py

# Web 模式
python stock_screener/app.py
# 访问 http://127.0.0.1:5001
```

**输出**：Top10 候选股票 + 各项小分明细（均线/成交/估值/动量）

#### ② 仓位计算 (凯利分析器)

```bash
cd stock_kelly
python start_server.py
# 访问 http://127.0.0.1:5000
```

**输入**：股票代码（如 600519）+ 总资金金额
**输出**：五维评分 + 凯利仓位建议（单票仓位%）

**评分体系**：

- 价值基本面 (25%)
- 趋势动量 (45%)
- 宏观环境 (5%)
- 资金流向 (15%)
- 事件消息 (10%)

#### ③ 风险监控 (Monitor)

```bash
cd stock_monitor/scripts
python monitor_daemon.py
```

**七大预警规则**：

1. 成本百分比：盈利 +15% / 亏损 -12%
2. 日内涨跌幅：个股 ±4% / ETF ±2%
3. 成交量异动：放量 > 2倍均量
4. 均线金叉/死叉：MA5 上穿/下穿 MA10
5. RSI 超买超卖：RSI > 70 / RSI < 30
6. 跳空缺口：向上/向下跳空 > 1%
7. 动态止盈：盈利 10%+ 后回撤 5%/10%

**输出**：分级预警信号（紧急/警告/提醒）

#### ④ 回测校验 \[待开发]

```bash
python backtest/backtest_validator.py
```

**输出**：年化收益、最大回撤、夏普比率

> 子流程文档包含完整的步骤清单、输入输出规范、注意事项。入口文档保持薄，细节在子文档里按需引用。

