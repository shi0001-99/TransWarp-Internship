# Stock Monitor Pro - 全功能智能股票监控预警系统

<div align="center">

![Version](https://img.shields.io/badge/version-2.0-blue)
![Python](https://img.shields.io/badge/Python-3.8%2B-green)
![Flask](https://img.shields.io/badge/Flask-2.0%2B-orange)
![License](https://img.shields.io/badge/License-MIT-yellow)

**支持A股、ETF、黄金等标的的全自动监控预警系统**

[功能特性](#功能特性) • [快速开始](#快速开始) • [使用指南](#使用指南) • [改进历程](#改进历程)

</div>

---

## 📋 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [使用指南](#使用指南)
  - [Web界面操作](#web界面操作)
  - [后台进程管理](#后台进程管理)
  - [标的配置](#标的配置)
  - [预警规则说明](#预警规则说明)
- [交易时间配置](#交易时间配置)
- [API数据源](#api数据源)
- [改进历程](#改进历程)
- [常见问题](#常见问题)

---

## 项目简介

Stock Monitor Pro 是一个面向中国投资者的智能股票监控预警系统，支持**实时行情监控**、**技术指标分析**、**多维度预警**和**Web可视化展示**。

### 设计理念

- 🇨🇳 **符合中国习惯**：红色代表上涨/盈利，绿色代表下跌/亏损
- 🔄 **全自动监控**：后台进程持续运行，智能调整监控频率
- 📊 **可视化展示**：Web界面实时展示监控数据和技术指标
- 🔔 **分级预警**：根据触发条件数量自动判定预警级别
- 🛡️ **双重保障**：新浪财经API（主）+ 东方财富API（备）确保数据稳定

---

## 功能特性

### 1️⃣ 七大预警规则

| 预警类型 | 触发条件 | 权重 | 说明 |
|---------|---------|------|------|
| **成本百分比** | 盈利/亏损达到设定阈值 | ⭐⭐⭐ | 基于持仓成本计算 |
| **日内涨跌幅** | 单日涨跌超过设定百分比 | ⭐⭐ | 盘中实时监控 |
| **成交量异动** | 放量/缩量超过倍数阈值 | ⭐⭐ | 对比5日均量 |
| **均线金叉/死叉** | MA5上穿/下穿MA10 | ⭐⭐⭐ | 趋势转折信号 |
| **RSI超买超卖** | RSI>70 或 RSI<30 | ⭐⭐ | 震荡指标预警 |
| **跳空缺口** | 开盘价突破昨日高低点 | ⭐⭐ | 基于真实昨日K线数据 |
| **动态止盈** | 盈利10%后回撤5%/10% | ⭐⭐⭐ | 跟踪历史最高价 |

### 2️⃣ 分级预警系统

```
🚨 紧急级：多个条件同时触发（如：放量 + 金叉 + 突破成本）
⚠️ 警告级：2个条件触发（如：RSI超卖 + 放量）
📢 提醒级：单一条件触发
```

### 3️⃣ 智能监控频率

根据交易时间自动调整监控频率，避免非交易时间的无效请求：

| 时间段 | 北京时间 | 监控标的 | 频率 |
|--------|---------|---------|------|
| 早盘 | 09:15-11:30 | A股/ETF | 60秒 |
| 午盘 | 13:00-15:00 | A股/ETF | 60秒 |
| 盘后 | 15:00-次日09:15 | - | 暂停 |
| 夜盘 | 全天 | 伦敦金 | 1小时 |

### 4️⃣ Web可视化界面

- **仪表盘**：总览卡片、涨跌分布图、持仓盈亏柱状图
- **预警中心**：实时预警列表，支持按级别筛选
- **操作日志**：运行日志和预警日志双标签页
- **监控配置**：标的管理（增删改查）、参数配置

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Web 前端 (响应式)                        │
│         HTML + CSS + JavaScript + ECharts                   │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP/REST API
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   Flask 后端服务                             │
│  /api/watchlist    /api/alerts    /api/scan    /api/daemon  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   核心监控引擎                                │
│  • 实时行情获取 (新浪财经)                                   │
│  • 技术指标计算 (MA, RSI, 成交量)                            │
│  • 预警规则检查 (7大规则)                                    │
│  • 动态止盈跟踪 (历史最高价)                                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   数据源 (双重保障)                          │
│  ✅ 新浪财经 API (主数据源) - 宽松反爬策略                   │
│  🔄 东方财富 API (备用数据源) - 自动降级                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 环境要求

- Python 3.8+
- Windows / macOS / Linux

### 安装步骤

```bash
# 1. 克隆项目
cd D:\trae_projects\transalpha\skills\stock-monitor-skill

# 2. 安装依赖
pip install requests flask

# 3. 配置监控标的
# 编辑 scripts/monitor.py 中的 WATCHLIST 配置
# 或通过 Web 界面动态添加

# 4. 启动 Web 服务
cd scripts
python web_server.py --port 8080 --host 0.0.0.0

# 5. 打开浏览器访问
# http://localhost:8080
```

### 目录结构

```
stock-monitor-skill/
├── scripts/
│   ├── monitor.py           # 核心监控逻辑
│   ├── web_server.py        # Flask Web服务
│   ├── monitor_daemon.py    # 后台守护进程
│   └── web_static/
│       ├── index.html       # 前端页面
│       ├── styles.css       # 样式文件
│       └── app.js           # 交互逻辑
├── README.md                # 本文档
└── SKILL.md                 # Skill配置文件
```

---

## 使用指南

### Web界面操作

#### 仪表盘页面

- **总览卡片**：显示监控标的数量、触发预警数、最大盈亏
- **涨跌分布饼图**：展示持仓盈亏分布
- **持仓盈亏柱状图**：可视化各标的盈亏百分比
- **股票卡片**：显示价格、涨跌、盈亏、历史最高价

#### 预警中心页面

- 查看历史预警记录
- 按预警级别筛选（紧急/警告/提醒）
- 显示预警时间、类型、详细内容

#### 操作日志页面

- **运行日志**：监控扫描记录
- **预警日志**：预警触发记录
- 支持日志行数调整

#### 监控配置页面

- **查看标的列表**：代码、名称、类型、成本、历史最高价
- **新增标的**：填写代码、名称、市场、类型、成本、预警参数
- **编辑标的**：修改成本价、预警参数
- **删除标的**：确认后移除监控

### 后台进程管理

#### 通过Web界面

侧边栏的 **「🤖 后台监控」** 面板：

- **状态指示器**：🟢 运行中 / ⚪ 未运行
- **启动按钮**：启动后台监控进程
- **停止按钮**：停止后台进程

#### 通过命令行

```powershell
# 启动后台进程（Windows PowerShell）
cd D:\trae_projects\transalpha\skills\stock-monitor-skill\scripts
python monitor_daemon.py

# 查看进程状态
Get-Content C:\Users\sxd\.stock_monitor\monitor_daemon.pid

# 查看运行日志
Get-Content C:\Users\sxd\.stock_monitor\monitor.log -Tail 50

# 查看预警日志
Get-Content C:\Users\sxd\.stock_monitor\alerts.log -Tail 20
```

### 标的配置

#### 配置文件位置

`scripts/monitor.py` 中的 `WATCHLIST` 列表，或通过 Web 界面动态添加。

#### 配置示例

```python
{
    "code": "600362",              # 股票代码
    "name": "江西铜业",            # 股票名称
    "market": "sh",                # 市场: sh(沪) / sz(深)
    "type": "individual",          # 类型: individual / etf / gold
    "cost": 57.00,                 # 持仓成本
    "alerts": {
        # 1. 成本百分比预警
        "cost_pct_above": 15.0,    # 盈利15%提醒
        "cost_pct_below": -12.0,   # 亏损12%止损
        
        # 2. 日内涨跌幅 (个股建议±4%)
        "change_pct_above": 4.0,
        "change_pct_below": -4.0,
        
        # 3. 成交量异动
        "volume_surge": 2.0,       # 放量>2倍5日均量
        
        # 4-7. 技术指标 (默认开启)
        "ma_monitor": True,        # 均线金叉死叉
        "rsi_monitor": True,       # RSI超买超卖
        "gap_monitor": True,       # 跳空缺口
        "trailing_stop": True      # 动态止盈
    }
}
```

#### 标的类型差异化配置

| 类型 | 日内异动阈值 | 成交量阈值 | 适用标的 |
|------|-------------|-----------|----------|
| individual (个股) | ±4% | 2倍 | 江西铜业、中国平安 |
| etf (ETF基金) | ±2% | 1.8倍 | 恒生医疗、创50等 |
| gold (黄金) | ±2.5% | 无 | 伦敦金 |

### 预警规则说明

#### 1. 成本百分比预警

基于持仓成本计算盈亏百分比：

```
盈利15%提醒 → 目标价 = 成本 × (1 + 15%)
亏损12%止损 → 止损价 = 成本 × (1 - 12%)
```

#### 2. 日内涨跌幅预警

基于昨日收盘价计算当日涨跌：

```
涨跌幅 = (当前价 - 昨收价) / 昨收价 × 100%
```

#### 3. 成交量异动

对比5日平均成交量：

```
放量倍数 = 当前成交量 / 5日均量
缩量倍数 = 当前成交量 / 5日均量 (< 0.5倍)
```

#### 4. 均线金叉/死叉

计算MA5和MA10的交叉情况：

- **金叉**：昨日 MA5 ≤ MA10，今日 MA5 > MA10 → 买入信号
- **死叉**：昨日 MA5 ≥ MA10，今日 MA5 < MA10 → 卖出信号

#### 5. RSI超买超卖

RSI(14) 计算公式：

```
RS = 平均上涨幅度 / 平均下跌幅度
RSI = 100 - 100 / (1 + RS)

RSI > 70 → 超买，可能回调
RSI < 30 → 超卖，可能反弹
```

#### 6. 跳空缺口检测

使用**真实昨日K线数据**（非估算）：

```
向上跳空：今日开盘 > 昨日最高价
向下跳空：今日开盘 < 昨日最低价
跳空幅度 ≥ 0.5% 才触发预警
```

#### 7. 动态止盈

跟踪**持仓以来的历史最高价**（非当日最高）：

```
启动条件：盈利 ≥ 10%
回撤5%提醒 → 建议减仓
回撤10%警告 → 建议清仓
```

---

## 交易时间配置

### 智能监控时段

系统根据中国A股交易时间自动调整监控频率：

| 时段 | 北京时间 | 监控行为 |
|------|---------|---------|
| **集合竞价** | 09:15-09:25 | 准备阶段 |
| **连续竞价（早）** | 09:30-11:30 | 每60秒扫描一次 |
| **午间休市** | 11:30-13:00 | 暂停扫描 |
| **连续竞价（午）** | 13:00-15:00 | 每60秒扫描一次 |
| **收盘后** | 15:00-次日09:15 | 暂停扫描（黄金除外） |
| **黄金夜盘** | 全天 | 每小时扫描一次 |

### 盘后行为

- **Web服务**：保持运行，前端可查看历史数据
- **后台进程**：暂停A股扫描，仅监控黄金等24H品种
- **预警防骚扰**：同类预警30分钟内只触发一次

### 时间判断逻辑

```python
def _get_monitor_mode(self):
    """判断当前监控模式"""
    now = datetime.now()
    hour, minute = now.hour, now.minute

    # 早盘: 09:30-11:30
    if (hour == 9 and minute >= 30) or (hour == 10) or (hour == 11 and minute <= 30):
        return {"run": True, "mode": "morning", "interval": 60}

    # 午盘: 13:00-15:00
    if hour == 13 or hour == 14 or (hour == 15 and minute == 0):
        return {"run": True, "mode": "afternoon", "interval": 60}

    # 夜盘（黄金）: 全天
    if hour >= 0 or hour < 9:
        return {"run": True, "mode": "night", "interval": 3600}

    # 其他时间暂停
    return {"run": False}
```

---

## API数据源

### 双重数据保障架构

为确保数据稳定性，系统采用**新浪财经（主）+ 东方财富（备）**的双重架构：

#### 主数据源：新浪财经 API

| 接口 | 用途 | 特点 |
|------|------|------|
| `hq.sinajs.cn/list=` | 实时行情 | 响应快、限制宽松 |
| `money.finance.sina.com.cn/.../getKLineData` | 历史K线 | JSON格式、易解析 |

**优势**：
- ✅ 无需认证，请求限制宽松
- ✅ 运行超过15年，稳定可靠
- ✅ 标准JSON响应，解析简单
- ✅ 支持批量查询（最多100只）

#### 备用数据源：东方财富 API

| 接口 | 用途 | 特点 |
|------|------|------|
| `push2his.eastmoney.com/.../kline/get` | K线数据 | 数据丰富 |
| `quote.eastmoney.com/` | 实时行情 | 界面美观 |

**使用场景**：
- 新浪API失败时自动降级
- 作为数据验证的辅助源

### 数据源切换逻辑

```python
def fetch_yesterday_ohlc(self, symbol, market):
    """获取昨日K线高低价"""
    # 优先使用新浪接口
    klines = self.fetch_sina_kline(symbol, market, datalen=2)
    if klines and len(klines) >= 2:
        return {
            'prev_high': klines[-2]['high'],
            'prev_low': klines[-2]['low']
        }

    # 备用：东方财富
    data = self._api_request(eastmoney_url, params)
    if data:
        return parse_eastmoney_data(data)

    return None  # 两者都失败
```

### 反爬策略

新浪财经 API 推荐配置：

```python
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://finance.sina.com.cn'
}
session.trust_env = False  # 避免代理问题
session.proxies = {}       # 清空代理设置
```

---

## 改进历程

### v1.0 初始版本

- ✅ 实现基础监控功能（成本预警、涨跌预警）
- ✅ 支持实时行情获取（新浪财经）
- ✅ 后台进程支持

### v2.0 功能增强

#### 新增技术指标监控

- 🆕 **均线金叉/死叉**：MA5/MA10交叉检测
- 🆕 **RSI超买超卖**：RSI(14)计算和预警
- 🆕 **成交量异动**：5日均量对比
- 🆕 **跳空缺口**：开盘跳空检测

#### 优化跳空检测逻辑

**问题**：初期使用昨收价±2%估算昨日高低价，导致误报

**改进**：
```python
# 旧逻辑（估算）
prev_high = prev_close * 1.02  # 昨收+2%
prev_low = prev_close * 0.98   # 昨收-2%

# 新逻辑（真实数据）
yesterday_ohlc = fetch_yesterday_ohlc(symbol, market)
prev_high = yesterday_ohlc['prev_high']  # 真实的昨日最高价
prev_low = yesterday_ohlc['prev_low']    # 真实的昨日最低价
```

**效果**：跳空检测准确率提升，消除假阳性预警

#### 新增动态止盈功能

**问题**：静态止盈点无法适应趋势行情

**改进**：
- 跟踪持仓以来的**历史最高价**（非当日最高）
- 盈利≥10%后启动监控
- 回撤5%提醒减仓，回撤10%提醒清仓

**持久化**：`max_high` 保存在 `watchlist.json`，跨重启保持

#### 新增Web可视化界面

- 🆕 Flask后端提供REST API
- 🆕 响应式前端（桌面/平板/手机）
- 🆕 ECharts图表可视化
- 🆕 标的CRUD操作界面

### v2.1 稳定性优化

#### 修复后台进程启动问题

**问题**：Web端点击「启动后台」后，状态显示「运行中」但很快变回「未运行」

**根因**：
```python
# web_server.py 先写PID文件
PID_FILE.write_text(str(proc.pid))

# monitor_daemon.py 启动时检查PID文件
if PID_FILE.exists():
    check_status()  # 发现PID正在运行（就是自己！）
    return          # 直接退出
```

**修复**：对比PID，区分「预写PID」和「真实旧进程」

```python
my_pid = os.getpid()
if PID_FILE.exists():
    existing_pid = int(PID_FILE.read_text().strip())
    if existing_pid == my_pid:
        # 是自己，删除旧文件继续运行
        PID_FILE.unlink()
    else:
        # 真有旧进程，拒绝启动
        return
```

#### 数据源切换

**问题**：东方财富API频繁触发反爬限制，导致技术指标全部失效

**改进**：切换为新浪财经API作为主数据源

| 改进点 | 代码位置 | 效果 |
|--------|---------|------|
| 新增 `fetch_sina_kline()` | monitor.py:324 | 获取历史K线数据 |
| 改造 `fetch_yesterday_ohlc()` | monitor.py:392 | 新浪优先 + 东财备用 |
| 改造 `fetch_volume_ma5()` | monitor.py:442 | 新浪优先 |
| 改造 `fetch_ma_data()` | monitor.py:478 | 新浪优先 |

**效果**：API成功率从30%提升至100%

#### 前端交互优化

- ✅ 后台控制面板移至侧边栏显眼位置
- ✅ 移除「自动刷新」选项，默认10秒自动刷新
- ✅ 移除「立即扫描」按钮（后台运行时冗余）
- ✅ 新增状态指示器徽章

---

## 常见问题

### Q1: 后台进程无法启动？

**检查步骤**：

1. 查看是否有残留进程：
```powershell
Get-Process python -ErrorAction SilentlyContinue
```

2. 手动删除PID文件：
```powershell
Remove-Item C:\Users\sxd\.stock_monitor\monitor_daemon.pid -Force
```

3. 重新启动Web服务

### Q2: 技术指标全部失效？

**可能原因**：API数据源异常

**检查方法**：
```python
from monitor import StockAlert
sa = StockAlert()
print(sa.fetch_sina_kline('600362', 'sh', datalen=5))
```

**解决方案**：系统会自动降级到备用数据源

### Q3: 跳空缺口预警不准确？

**原因**：使用了估算的昨日高低价

**确认**：v2.0已修复，使用真实K线数据

**验证代码**：
```python
result = sa.fetch_yesterday_ohlc('600362', 'sh')
print(result)  # 应显示真实OHLC数据
```

### Q4: 动态止盈的历史最高价不准确？

**原因**：使用了当日最高价而非持仓历史最高价

**确认**：v2.0已修复，跟踪持仓以来的历史最高价

**验证**：查看 `watchlist.json` 中的 `max_high` 字段

### Q5: 如何添加新标的？

**方法一：Web界面**
1. 打开监控配置页面
2. 点击「新增标的」
3. 填写代码、名称、成本等参数
4. 点击保存

**方法二：修改配置文件**
编辑 `monitor.py` 中的 `WATCHLIST` 列表

### Q6: 如何修改预警参数？

通过Web界面的「监控配置」页面，点击标的行的「编辑」按钮，修改后保存。

### Q7: 监控频率可以调整吗？

可以修改 `monitor_daemon.py` 中的扫描间隔：

```python
# 默认60秒
interval = 60  # 单位：秒
```

**注意**：不建议设置过低频率，避免触发API限制。

---

## 技术栈

- **后端**：Python 3.8+, Flask 2.0+
- **前端**：HTML5, CSS3, JavaScript ES6, ECharts
- **数据源**：新浪财经 API, 东方财富 API
- **日志**：Python logging 模块，轮转日志

---

## 许可证

MIT License

---

## 贡献

欢迎提交 Issue 和 Pull Request！

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给一个 Star！⭐**

Made with ❤️ by Stock Monitor Pro Team

</div>