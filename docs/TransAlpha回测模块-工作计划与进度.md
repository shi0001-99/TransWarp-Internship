# TransAlpha ⑧ 回测校验模块 — 工作计划与进度比对

> **目标**：在 TransAlpha 主工作流中新增「第 8 阶段 · 回测校验」，用**历史可回放的 proxy 数据**强对齐主选股逻辑（六维打分），在**宽池**（默认中证 500）上做**周度再平衡**策略回测，输出
> `output/backtest/equity_curve.csv`、`metrics.json`、`trade_log.csv`，并与 **中证 500 + 沪深 300 双基准**对照。
>
> **定位**：TransAlpha 自治（方案 B）+ 内核移植 QuantBacktest。数据四块能力（资金流 / 财报 PIT / 指数历史 / 情绪 proxy）全部落地。
> **更新日期**：2026-08-07

---

## 一、总体架构与阶段划分

回测模块拆分为 **6 个阶段**，从「数据」到「闭环验证」逐段推进，每段有明确交付物与校验方式，可与后面「完成度比对表」一一对应。

```
阶段A 数据口   ──  data_loader.py   （baostock 四类数据：K线/财报PIT/指数/资金流proxy）
阶段B 打分口   ──  proxy_metrics.py （六维打分画像 TransAlpha）
阶段C 引擎口   ──  costs.py + rules.py + runner.py（撮合：成本/T+1/涨跌停/停牌/止损）
阶段D 输出口   ──  导出 equity_curve.csv / metrics.json / trade_log.csv
阶段E 编排口   ──  pipeline.py 阶段8 + run.py --backtest + CLI（python -m backtest）
阶段F 验证口   ──  tests/test_backtest.py + 烟测跑通
```

---

## 二、阶段里程碑与验收

### 阶段 A：数据口（data_loader.py）
| 子项 | 状态 | 验收标准 |
|------|------|----------|
| baostock 登录/生命周期 | 完成 | login/logout 封装，重试机制 |
| 历史K线（前复权 adjustflag=2） | 完成 | 实盘验证 `sh.600519` 返回真实 OHLCV |
| 财报 + pubDate（天然 PIT） | 完成 | `query_profit_data` 自带公告日 |
| 指数历史（中证500/沪深300） | 完成 | `sh.000905` / `sh.000300` K线实测通过 |
| 资金流（东财主源 + 换手兜底降级） | 完成 | 成交额/换手 proxy 兜底已内置 |
| 中证500 成分股（宽池） | 完成 | `query_zz500_stocks` |
| logger 字段渲染 / PIT 时间线 | 部分 | `pub_timeline` 在 runner 层简化 |

### 阶段 B：六维打分（proxy_metrics.py）
| 交付物 | 状态 | 验收标准 |
|------|------|----------|
| 技术面（均线/量能/换手/动量） | 完成 | MA 多头排列、3 日量能信号移植 |
| 基本面 40（ROE/增速/现金流/负债） | 完成 | PIT 对齐 |
| 资金/量能 20（净流入/换手） | 完成 | 无净流入时换手兜底 |
| 综合买入门槛 + 选 Top N | 完成 | `buy` 判定 + `select_top_n` |

### 阶段 C：回测引擎（costs.py + rules.py + runner.py）
| 交付物 | 状态 | 验收标准 |
|------|------|----------|
| 交易成本（佣金/印花税/过户/滑点） | 完成 | 公式移植 QuantBacktest |
| 涨跌停/停牌/T+1 | 完成 | rules 已建库 |
| 宽池周度再平衡主循环 | **有 bug 待修** | 修复类型注解/方法名/现金流传递 |
| 止损（MA20 跌破减半） | **有 bug 待修** | 现金流累计逻辑修正 |
| 双基准归一化 | 待验收 | 等权、单票≤25% |

### 阶段 D：输出口（report.py / 导出三文件）
| 交付物 | 状态 | 验收标准 |
|------|------|----------|
| `output/backtest/equity_curve.csv` | **未完成** | 含 date/equity/nav/基准列 |
| `output/backtest/metrics.json` | **未完成** | 全套绩效指标 |
| `output/backtest/trade_log.csv` | **未完成** | 每笔买卖记录 |

### 阶段 E：编排口（pipeline.py + run.py）
| 交付物 | 状态 | 验收标准 |
|------|------|----------|
| STAGE_MAP 增加阶段 8 | **未完成** | `1..8` 含回测 |
| run_pipeline 循环扩到 9 | **未完成** | `range(1,8)` → `range(1,9)` |
| CLI `--backtest` 直跑 | **未完成** | `python run.py --backtest` |
| `python -m backtest` 独立入口 | **未完成** | 需 `__main__.py` |

### 阶段 F：验证口（tests）
| 交付物 | 状态 | 验收标准 |
|------|------|----------|
| 回测单元测试 | ✅ 完成 | `test_backtest.py`，禁网络（mock）13 用例全过 |
| 集成/烟测跑通 | ✅ 完成 | 真实 baostock 拉数 pool=4，三文件闭环 |

---

## 三、完成度比对总表

> ✅=已完成 /⚠️=部分完成/有缺陷待修 / ❌=未完成

| # | 交付物 | 阶段 | 完成度 | 备注 |
|---|--------|------|--------|------|
| 1 | data_loader.py（四类数据能力） | A | ✅ 完成 | baostock 实测四类通过 |
| 2 | proxy_metrics.py（六维打分） | B | ✅ 完成 | 强对齐主逻辑 |
| 3 | costs.py（交易成本） | B/C | ✅ 完成 | 移植 QuantBack |
| 4 | rules.py（A股规则） | C | ✅ 完成 | |
| 5 | metrics.py（绩效指标） | C | ✅ 完成 | 双基准alpha/beta |
| 6 | runner.py 主循环 | C | ✅ 完成 | 已修复类型注解/方法名/现金流传递 |
| 7 | 输出三文件（csv/json/trade） | D | ✅ 完成 | report.py + 实测出三文件 |
| 8 | pipeline.py 第8阶段接入 | E | ✅ 完成 | STAGE_MAP[8] + range(1,9) |
| 9 | run.py `--backtest` | E | ✅ 完成 | CLI action 已加 |
| 10 | `__main__.py` 独立入口 | E | ✅ 完成 | `python -m src.backtest` 实测 |
| 11 | tests/test_backtest.py | F | ✅ 完成 | 13 用例全通过（禁网络 mock） |
| 12 | 烟测跑通出三文件 | F | ✅ 完成 | 真实 baostock 拉数 pool=4 闭环 |

---

## 四、待确认参数（决策点）

下表为默认参数，如需调整请直接答复对应编号：

| # | 参数 | 当前默认 | 说明 |
|---|------|----------|------|
| P1 | 候选池 | **中证 500 成分**（约120只采样） | 宽池版，真实区分策略有效性 |
| P2 | 再平衡频率 | **月度**（default 稳妥） | 备选 `weekly`（已有代码） |
| P3 | 单票仓位上限 | **25%**（对齐 TransAlpha） | |
| P4 | 资金流降级 | **成交额/换手 proxy 兜底** | 东财限流时可接受 |
| P5 | 止损 | **默认开启**（MA20 跌破减半） | |
| P6 | 初始资金 | **100 万** | runner 默认 `initial_capital` |

> 若无需调整，直接按默认推进实现。

---

## 五、变更记录

| 日期 | 内容 |
|------|------|
| 2026-08-07 | 新建本计划：建立 6 阶段划分 + 完成度比对表，标记 6 项待补 |
| 2026-08-07 | 补全全部缺口：修复 runner.py 致命 bug、新增 report.py 三文件导出、pipeline 阶段8 + run.py --backtest + `__main__.py`，新增 13 例单测并通过，真实 baostock 烟测 pool=4 闭环 |

---

## 六、使用方式

```bash
# 方式一：pipeline 全链路（在第 7 阶段后自动进入第 8 阶段回测）
python run.py                    # 或 python run.py --stage 1

# 方式二：只跑回测校验（第 8 阶段）
python run.py --backtest
python run.py --backtest --bt-start=2023-01-01 --bt-end=2024-06-30

# 方式三：独立回测 CLI
python -m src.backtest --start 2023-01-01 --end 2024-06-30               # 默认中证500宽池
python -m src.backtest --start 2023-01-01 --end 2024-06-30 --pool "600519,000858,000001" --rebalance weekly --top 5 --capital 1000000

# 查看输出
python run.py --status
```

**输出文件**（`output/backtest/`）：
| 文件 | 内容 |
|------|------|
| `equity_curve.csv` | 资金曲线：date / equity / equity_norm / ret + csi500 / hs300 基准 |
| `metrics.json` | 全套绩效指标（收益/风险/Sharpe/Sortino/Calmar/回撤 + 双基准 alpha/beta/IR + 交易统计） |
| `trade_log.csv` | 逐笔交易记录（买/卖、价格、股数、金额、费用、盈亏） |

> ⚠️ 注意：CLI 传 `--pool` 时多个代码请用**字符串引号包裹**（如 `--pool "600519,000858"`），避免 PowerShell 拆分导致候选池被截断。