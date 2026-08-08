#!/usr/bin/env python3
"""
自选股监控预警工具 - OpenClaw集成版
支持 A股、ETF 及 国际现货黄金 (伦敦金)
"""

import requests
import json
import time
import os
import sys
import logging
import atexit
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler

sys.path.insert(0, str(Path(__file__).parent))
from db_lock import file_lock, atomic_write_json, safe_read_json

# ============ 日志配置 ============

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "output" / "monitor"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "monitor.log"
ALERT_LOG_FILE = LOG_DIR / "alerts.log"
PID_FILE = LOG_DIR / "monitor.pid"
WATCHLIST_FILE = LOG_DIR / 'watchlist.json'
WATCHLIST_LOCK_FILE = LOG_DIR / 'watchlist.lock'


def save_watchlist(watchlist):
    """Persist watchlist to JSON file (并发安全，跨进程互斥)

    使用文件锁 + 原子写入，确保 web_server 和 daemon 同时写入时不会冲突。
    """
    with file_lock(WATCHLIST_LOCK_FILE):
        WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(WATCHLIST_FILE, watchlist)

def setup_logging(log_to_file=True, log_to_console=True):
    """配置日志系统"""
    logger = logging.getLogger("stock_monitor")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if log_to_file:
        file_handler = RotatingFileHandler(
            str(LOG_FILE),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

def setup_alert_logging():
    """配置预警专用日志（独立文件，方便查看历史预警）"""
    alert_logger = logging.getLogger("stock_monitor.alerts")
    alert_logger.setLevel(logging.INFO)
    alert_logger.handlers.clear()

    formatter = logging.Formatter(
        '%(asctime)s [ALERT] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    file_handler = RotatingFileHandler(
        str(ALERT_LOG_FILE),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    alert_logger.addHandler(file_handler)

    return alert_logger

# ============ 配置区 ============

# 监控列表 - 长期挂机通用配置
# 注意: 伦敦金使用新浪hf_XAU接口，价格为 人民币/克 (约4800元/克 = $2740/盎司)
# 
# 预警规则设计原则 (适合长期挂机):
# 1. 成本百分比预警: 基于持仓成本设置 ±10%/±15% 预警，比固定价格更合理
# 2. 单日涨跌幅预警: 
#    - 个股 ±3%~5% (波动大)
#    - ETF ±1.5%~2.5% (波动小)
#    - 黄金 ±2%~3% (24H特殊)
# 3. 防骚扰: 同类预警30分钟内只发一次

# 标的类型定义
STOCK_TYPE = {
    "INDIVIDUAL": "individual",  # 个股
    "ETF": "etf",                # ETF
    "GOLD": "gold"               # 黄金/贵金属
}

WATCHLIST = [
    # ===== 个股: 波动较大，设置较宽的涨跌预警 =====
    {
        "code": "600362", 
        "name": "江西铜业", 
        "market": "sh",
        "type": "individual",
        "cost": 57.00,
        "alerts": {
            "cost_pct_above": 15.0,    # 盈利15%
            "cost_pct_below": -12.0,   # 止损12%
            "change_pct_above": 4.0,   # 日内异动 ±4%
            "change_pct_below": -4.0,
            "volume_surge": 2.0        # 成交量是5日均量2倍
        }
    },
    {
        "code": "601318", 
        "name": "中国平安", 
        "market": "sh",
        "type": "individual",
        "cost": 66.00,
        "alerts": {
            "cost_pct_above": 12.0,
            "cost_pct_below": -10.0,
            "change_pct_above": 3.5,   # 日内异动 ±3.5%
            "change_pct_below": -3.5,
            "volume_surge": 2.0
        }
    },
    # ===== ETF: 波动相对较小，设置更敏感的预警 =====
    {
        "code": "159892", 
        "name": "恒生医疗", 
        "market": "sz",
        "type": "etf",
        "cost": 0.80,
        "alerts": {
            "cost_pct_above": 15.0,
            "cost_pct_below": -15.0,
            "change_pct_above": 2.0,   # ETF日内异动 ±2%
            "change_pct_below": -2.0,
            "volume_surge": 1.8        # ETF放量阈值更低
        }
    },
    {
        "code": "513180", 
        "name": "恒生科技", 
        "market": "sh",
        "type": "etf",
        "cost": 0.72,
        "alerts": {
            "cost_pct_above": 15.0,
            "cost_pct_below": -15.0,
            "change_pct_above": 2.0,   # ETF日内异动 ±2%
            "change_pct_below": -2.0,
            "volume_surge": 1.8
        }
    },
    {
        "code": "159681", 
        "name": "创50ETF", 
        "market": "sz",
        "type": "etf",
        "cost": 1.50,
        "alerts": {
            "cost_pct_above": 12.0,
            "cost_pct_below": -12.0,
            "change_pct_above": 2.0,   # ETF日内异动 ±2%
            "change_pct_below": -2.0,
            "volume_surge": 1.8
        }
    },
    {
        "code": "516020", 
        "name": "化工50ETF", 
        "market": "sh",
        "type": "etf",
        "cost": 0.90,
        "alerts": {
            "cost_pct_above": 12.0,
            "cost_pct_below": -12.0,
            "change_pct_above": 2.0,   # ETF日内异动 ±2%
            "change_pct_below": -2.0,
            "volume_surge": 1.8
        }
    },
    # ===== 伦敦金: 24H特殊标的 =====
    {
        "code": "XAU", 
        "name": "伦敦金(人民币/克)", 
        "market": "fx",
        "type": "gold",
        "cost": 4650.0,
        "alerts": {
            "cost_pct_above": 10.0,    # 盈利10%
            "cost_pct_below": -8.0,    # 止损8%
            "change_pct_above": 2.5,   # 黄金日内异动 ±2.5%
            "change_pct_below": -2.5
            # 黄金不监控成交量 (外汇市场无成交量概念)
        }
    }
]

# Load persisted watchlist if exists
WATCHLIST_FILE = LOG_DIR / 'watchlist.json'
if WATCHLIST_FILE.exists():
    try:
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            _persisted = json.load(f)
        if isinstance(_persisted, list) and len(_persisted) > 0:
            WATCHLIST = _persisted
    except (json.JSONDecodeError, IOError):
        pass

# 智能频率配置
SMART_SCHEDULE = {
    "market_open": {"hours": [(9, 30), (11, 30), (13, 0), (15, 0)], "interval": 300},  # 交易时间: 5分钟
    "after_hours": {"interval": 1800},  # 收盘后: 30分钟
    "night": {"hours": [(0, 0), (8, 0)], "interval": 3600},  # 凌晨: 1小时(仅伦敦金)
}

# ============ 核心代码 ============

class StockAlert:
    def __init__(self, log_to_file=True, log_to_console=True, watchlist=None):
        self.prev_data = {}
        self.alert_log = []
        self.session = requests.Session()
        self.logger = setup_logging(log_to_file=log_to_file, log_to_console=log_to_console)
        self.alert_logger = setup_alert_logging()
        self._shutdown = False
        self.watchlist = watchlist or WATCHLIST
        self._watchlist_file_mtime = 0  # 记录watchlist.json的修改时间
        # 设置完整的浏览器请求头，避免被识别为爬虫
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://quote.eastmoney.com/"
        })
        # 清除可能的代理设置，避免代理连接问题
        self.session.trust_env = False
        self.session.proxies = {}
        # 请求间隔计数器，避免请求过快
        self._request_count = 0
        # 昨日K线数据缓存 (symbol -> ohlc dict)
        self._yesterday_ohlc_cache = {}

    def reload_watchlist(self):
        """从文件重新加载watchlist配置 (支持前端修改立即生效)

        并发安全说明：
        - 使用 safe_read_json 读取，即使 web_server 正在写入也不会读到半写状态
          (atomic_write_json 保证文件要么是旧版本要么是新版本)
        - mtime 检查避免无谓的重复加载
        """
        try:
            if WATCHLIST_FILE.exists():
                file_mtime = WATCHLIST_FILE.stat().st_mtime
                if file_mtime > self._watchlist_file_mtime:
                    # 使用 safe_read_json 防止读到写入一半的损坏数据
                    new_watchlist = safe_read_json(WATCHLIST_FILE, default=None)
                    if isinstance(new_watchlist, list):
                        for i, new_stock in enumerate(new_watchlist):
                            code = new_stock.get('code')
                            old_stock = next((s for s in self.watchlist if s.get('code') == code), None)
                            if old_stock:
                                if 'max_high' in old_stock:
                                    new_stock['max_high'] = old_stock['max_high']
                                if '_alerted' in old_stock:
                                    new_stock['_alerted'] = old_stock['_alerted']
                        self.watchlist = new_watchlist
                        self._watchlist_file_mtime = file_mtime
                        self.logger.info(f"配置已从文件重新加载 ({len(self.watchlist)} 只标的)")
        except Exception as e:
            self.logger.warning(f"重新加载watchlist失败: {e}")

    def _api_request(self, url, params, max_retries=3):
        """统一的API请求方法，包含重试和请求间隔控制"""
        import time
        self._request_count += 1
        # 每5个请求增加短暂延迟，避免请求过快被限制
        if self._request_count % 5 == 0:
            time.sleep(0.5)

        for retry in range(max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=15)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code in [429, 503]:  # 请求过多或服务不可用
                    time.sleep(2 * (retry + 1))  # 指数退避
                    continue
            except Exception as e:
                if retry < max_retries - 1:
                    time.sleep(1)
                    continue
                raise e
        return None
        
    def should_run_now(self):
        """智能频率控制: 判断当前是否应该执行监控 (基于北京时间)"""
        # 自动检测本地时区，如果是北京时间则直接使用，否则转换为北京时间
        import time
        from datetime import timedelta, timezone

        local_now = datetime.now()
        # 检查本地时区是否为 UTC+8 (北京时间)
        local_tz_offset = time.localtime().tm_gmtoff / 3600 if hasattr(time.localtime(), 'tm_gmtoff') else 8

        # 如果本地时区不是 UTC+8，则转换为北京时间
        if local_tz_offset != 8:
            # 计算与北京时间的时差
            beijing_offset = 8 - local_tz_offset
            now = local_now + timedelta(hours=beijing_offset)
        else:
            now = local_now

        hour, minute = now.hour, now.minute
        time_val = hour * 100 + minute
        weekday = now.weekday()
        
        # 周末只监控伦敦金
        if weekday >= 5:  # 周六日
            return {"run": True, "mode": "weekend", "stocks": [s for s in self.watchlist if s['market'] == 'fx']}
        
        # 交易时间 (9:30-11:30, 13:00-15:00)
        morning_session = 930 <= time_val <= 1130
        afternoon_session = 1300 <= time_val <= 1500
        
        if morning_session or afternoon_session:
            return {"run": True, "mode": "market", "stocks": self.watchlist, "interval": 300}
        
        # 午休 (11:30-13:00)
        if 1130 < time_val < 1300:
            return {"run": True, "mode": "lunch", "stocks": self.watchlist, "interval": 600}  # 10分钟
        
        # 收盘后 (15:00-24:00)
        if 1500 <= time_val <= 2359:
            return {"run": True, "mode": "after_hours", "stocks": self.watchlist, "interval": 1800}  # 30分钟
        
        # 凌晨 (0:00-9:30)
        if 0 <= time_val < 930:
            return {"run": True, "mode": "night", "stocks": [s for s in self.watchlist if s['market'] == 'fx'], "interval": 3600}  # 1小时
        
        return {"run": False}

    def fetch_sina_kline(self, symbol, market, datalen=30):
        """从新浪财经获取日K线数据 (更宽松的反爬策略)"""
        # 新浪代码格式: sh600519 或 sz000001
        sina_symbol = f"{market}{symbol}"
        url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            'symbol': sina_symbol,
            'scale': '240',  # 日线
            'ma': 'no',      # 不返回均线
            'datalen': str(datalen)
        }
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.encoding = 'utf-8'
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                # 返回格式: [{day, open, close, high, low, volume}, ...]
                # 注意: 新浪返回的是正序(从早到晚)
                result = []
                for item in data:
                    result.append({
                        'date': item.get('day', ''),
                        'open': float(item.get('open', 0)),
                        'close': float(item.get('close', 0)),
                        'high': float(item.get('high', 0)),
                        'low': float(item.get('low', 0)),
                        'volume': int(float(item.get('volume', 0)))
                    })
                return result
        except Exception as e:
            print(f"新浪K线获取失败 {symbol}: {e}")
        return None

    def fetch_eastmoney_kline(self, symbol, market):
        """获取最新日K线数据 (备用数据源)"""
        secid = f"{market}.{symbol}"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',
            'fqt': '0',
            'end': '20500101',
            'lmt': '2'
        }
        try:
            resp = self.session.get(url, params=params, timeout=10)
            data = resp.json()
            klines = data.get('data', {}).get('klines', [])
            if len(klines) >= 1:
                today = klines[-1].split(',')
                prev_close = float(today[2])
                if len(klines) >= 2:
                    prev_close = float(klines[-2].split(',')[2])
                return {
                    'name': data.get('data', {}).get('name', symbol),
                    'price': float(today[2]),
                    'prev_close': prev_close,
                    'volume': int(float(today[5])),
                    'amount': float(today[6]),
                    'date': today[0],
                    'time': '15:00:00'
                }
        except Exception as e:
            print(f"东财K线获取失败 {symbol}: {e}")
        return None

    def fetch_yesterday_ohlc(self, symbol, market):
        """获取昨日K线的真实高低价（用于跳空缺口检测），带缓存"""
        cache_key = f"{market}.{symbol}"
        if cache_key in self._yesterday_ohlc_cache:
            return self._yesterday_ohlc_cache[cache_key]

        # 优先使用新浪接口
        klines = self.fetch_sina_kline(symbol, market, datalen=2)
        if klines and len(klines) >= 2:
            # klines[-1] = 今天, klines[-2] = 昨天 (新浪返回正序)
            yesterday = klines[-2]
            result = {
                'prev_open': yesterday['open'],
                'prev_close': yesterday['close'],
                'prev_high': yesterday['high'],
                'prev_low': yesterday['low']
            }
            self._yesterday_ohlc_cache[cache_key] = result
            return result

        # 备用: 东方财富
        secid = f"{market}.{symbol}"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',
            'fqt': '0',
            'end': '20500101',
            'lmt': '2'
        }
        try:
            data = self._api_request(url, params)
            if data:
                em_klines = data.get('data', {}).get('klines', [])
                if len(em_klines) >= 2:
                    yesterday = em_klines[-2].split(',')
                    result = {
                        'prev_open': float(yesterday[1]),
                        'prev_close': float(yesterday[2]),
                        'prev_high': float(yesterday[3]),
                        'prev_low': float(yesterday[4])
                    }
                    self._yesterday_ohlc_cache[cache_key] = result
                    return result
        except Exception as e:
            print(f"获取昨日K线失败 {symbol}: {e}")
        return None

    def fetch_volume_ma5(self, symbol, market):
        """获取5日平均成交量 (优先新浪，备用东财)"""
        # 优先使用新浪接口
        klines = self.fetch_sina_kline(symbol, market, datalen=6)
        if klines and len(klines) >= 2:
            # 排除最后一天(今天)，计算前5日平均
            volumes = [k['volume'] for k in klines[:-1]]
            if volumes:
                return sum(volumes) / len(volumes)

        # 备用: 东方财富
        secid = f"{market}.{symbol}"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',
            'fqt': '0',
            'end': '20500101',
            'lmt': '6'
        }
        try:
            data = self._api_request(url, params)
            if data:
                em_klines = data.get('data', {}).get('klines', [])
                if len(em_klines) >= 2:
                    volumes = []
                    for k in em_klines[:-1]:
                        p = k.split(',')
                        volumes.append(float(p[5]))
                    return sum(volumes) / len(volumes) if volumes else 0
        except Exception as e:
            print(f"获取均量失败 {symbol}: {e}")
        return 0

    def fetch_ma_data(self, symbol, market):
        """获取均线数据 (MA5, MA10, MA20) 和 RSI (优先新浪)"""
        # 优先使用新浪接口
        klines = self.fetch_sina_kline(symbol, market, datalen=30)
        if klines and len(klines) >= 20:
            closes = [k['close'] for k in klines]

            # 计算均线
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20

            # 判断均线趋势
            prev_ma5 = sum(closes[-6:-1]) / 5
            prev_ma10 = sum(closes[-11:-1]) / 10

            # 计算RSI(14)
            rsi = self._calculate_rsi(closes, 14)

            return {
                'MA5': ma5,
                'MA10': ma10,
                'MA20': ma20,
                'MA5_trend': 'up' if ma5 > prev_ma5 else 'down',
                'MA10_trend': 'up' if ma10 > prev_ma10 else 'down',
                'golden_cross': prev_ma5 <= prev_ma10 and ma5 > ma10,
                'death_cross': prev_ma5 >= prev_ma10 and ma5 < ma10,
                'RSI': rsi,
                'RSI_overbought': rsi > 70 if rsi else False,
                'RSI_oversold': rsi < 30 if rsi else False
            }

        # 备用: 东方财富
        secid = f"{market}.{symbol}"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',
            'fqt': '0',
            'end': '20500101',
            'lmt': '30'
        }
        try:
            data = self._api_request(url, params)
            if data:
                em_klines = data.get('data', {}).get('klines', [])
                if len(em_klines) >= 20:
                    closes = []
                    for k in em_klines:
                        p = k.split(',')
                        closes.append(float(p[2]))

                    ma5 = sum(closes[-5:]) / 5
                    ma10 = sum(closes[-10:]) / 10
                    ma20 = sum(closes[-20:]) / 20

                    prev_ma5 = sum(closes[-6:-1]) / 5
                    prev_ma10 = sum(closes[-11:-1]) / 10

                    rsi = self._calculate_rsi(closes, 14)

                    return {
                        'MA5': ma5,
                        'MA10': ma10,
                        'MA20': ma20,
                        'MA5_trend': 'up' if ma5 > prev_ma5 else 'down',
                        'MA10_trend': 'up' if ma10 > prev_ma10 else 'down',
                        'golden_cross': prev_ma5 <= prev_ma10 and ma5 > ma10,
                        'death_cross': prev_ma5 >= prev_ma10 and ma5 < ma10,
                        'RSI': rsi,
                        'RSI_overbought': rsi > 70 if rsi else False,
                        'RSI_oversold': rsi < 30 if rsi else False
                    }
        except Exception as e:
            print(f"获取均线失败 {symbol}: {e}")
        return None
    
    def _calculate_rsi(self, closes, period=14):
        """计算RSI指标"""
        if len(closes) < period + 1:
            return None
        
        gains = []
        losses = []
        
        for i in range(1, period + 1):
            change = closes[-i] - closes[-i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 2)

    def fetch_sina_realtime(self, stocks):
        """获取实时行情 (优先实时，收盘后用日K)"""
        stock_list = [s for s in stocks if s['market'] != 'fx']
        fx_list = [s for s in stocks if s['market'] == 'fx']
        results = {}
        
        # 1. A股/ETF - 尝试实时接口
        if stock_list:
            codes = [f"{s['market']}{s['code']}" for s in stock_list]
            url = f"https://hq.sinajs.cn/list={','.join(codes)}"
            try:
                resp = self.session.get(url, headers={'Referer': 'https://finance.sina.com.cn'}, timeout=10)
                resp.encoding = 'gb18030'
                for line in resp.text.strip().split(';'):
                    if 'hq_str_' not in line or '=' not in line: continue
                    key = line.split('=')[0].split('_')[-1]
                    if len(key) < 8: continue
                    data_str = line[line.index('"')+1 : line.rindex('"')]
                    p = data_str.split(',')
                    if len(p) > 30 and float(p[3]) > 0:
                        # 新浪数据格式: 名称,今日开盘,昨日收盘,当前价,今日最高,今日最低,竞买价,竞卖价,成交量,成交额...
                        # 保存昨日最高最低价用于跳空检测 (用昨日收盘近似，或用均线数据补充)
                        results[key[2:]] = {
                            'name': p[0],
                            'price': float(p[3]),
                            'prev_close': float(p[2]),
                            'open': float(p[1]),      # 今日开盘
                            'high': float(p[4]),      # 今日最高
                            'low': float(p[5]),       # 今日最低
                            'volume': int(p[8]),
                            'amount': float(p[9]),
                            'date': p[30],
                            'time': p[31]
                        }
            except Exception as e: 
                print(f"实时行情获取失败: {e}")
            
            # 2. 如果实时接口返回空或0，用日K线补数据
            for stock in stock_list:
                code = stock['code']
                if code not in results or results[code]['price'] <= 0:
                    kline_data = self.fetch_eastmoney_kline(code, 1 if stock['market'] == 'sh' else 0)
                    if kline_data:
                        results[code] = kline_data
                        print(f"  {stock['name']}: 使用日K收盘价 {kline_data['price']}")

        # 3. 伦敦金 (新浪hf_XAU接口，人民币/克)
        if fx_list:
            url = "https://hq.sinajs.cn/list=hf_XAU"
            try:
                resp = self.session.get(url, headers={'Referer': 'https://finance.sina.com.cn'}, timeout=10)
                line = resp.text.strip()
                if '"' in line:
                    data_str = line[line.index('"')+1 : line.rindex('"')]
                    p = data_str.split(',')
                    if len(p) >= 13:
                        # 新浪hf_XAU: 人民币/克 (约4800=2740美元/盎司)
                        price = float(p[0])
                        results['XAU'] = {
                            'name': '伦敦金', 
                            'price': price, 
                            'prev_close': float(p[7]),
                            'volume': 0, 'amount': 0, 
                            'date': p[11] if len(p) > 11 else datetime.now().strftime('%Y-%m-%d'), 
                            'time': p[6]
                        }
            except Exception as e: 
                print(f"伦敦金获取失败: {e}")
            
        return results
    
    def check_alerts(self, stock_config, data):
        """检查预警条件 (支持成本百分比、单日涨跌幅、分级预警)"""
        alerts = []
        alert_weights = []  # 用于计算预警级别
        code = stock_config['code']
        cfg = stock_config.get('alerts', {})
        cost = stock_config.get('cost', 0)
        stock_type = stock_config.get('type', 'individual')
        price, prev_close = data['price'], data['prev_close']
        change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
        
        # 1. 基于成本的百分比预警 (权重: 高)
        if cost > 0:
            cost_change_pct = (price - cost) / cost * 100
            
            if 'cost_pct_above' in cfg and cost_change_pct >= cfg['cost_pct_above']:
                target_price = cost * (1 + cfg['cost_pct_above']/100)
                if not self._alerted_recently(code, 'cost_above'):
                    alerts.append(('cost_above', f"🎯 盈利 {cfg['cost_pct_above']:.0f}% (目标价 ¥{target_price:.2f})"))
                    alert_weights.append(3)  # 高权重
            
            if 'cost_pct_below' in cfg and cost_change_pct <= cfg['cost_pct_below']:
                target_price = cost * (1 + cfg['cost_pct_below']/100)
                if not self._alerted_recently(code, 'cost_below'):
                    alerts.append(('cost_below', f"🛑 亏损 {abs(cfg['cost_pct_below']):.0f}% (止损价 ¥{target_price:.2f})"))
                    alert_weights.append(3)  # 高权重
        
        # 2. 基于固定价格的预警 (权重: 中)
        if 'price_above' in cfg and price >= cfg['price_above'] and not self._alerted_recently(code, 'above'):
            alerts.append(('above', f"🚀 价格突破 ¥{cfg['price_above']}"))
            alert_weights.append(2)
        if 'price_below' in cfg and price <= cfg['price_below'] and not self._alerted_recently(code, 'below'):
            alerts.append(('below', f"📉 价格跌破 ¥{cfg['price_below']}"))
            alert_weights.append(2)
        
        # 3. 单日涨跌幅预警 (权重: 根据幅度)
        if 'change_pct_above' in cfg and change_pct >= cfg['change_pct_above'] and not self._alerted_recently(code, 'pct_up'):
            alerts.append(('pct_up', f"📈 日内大涨 {change_pct:+.2f}%"))
            # 异动越大权重越高
            if change_pct >= 7:
                alert_weights.append(3)  # 涨停附近
            elif change_pct >= 5:
                alert_weights.append(2)  # 大涨
            else:
                alert_weights.append(1)  # 一般异动
                
        if 'change_pct_below' in cfg and change_pct <= cfg['change_pct_below'] and not self._alerted_recently(code, 'pct_down'):
            alerts.append(('pct_down', f"📉 日内大跌 {change_pct:+.2f}%"))
            if change_pct <= -7:
                alert_weights.append(3)  # 跌停附近
            elif change_pct <= -5:
                alert_weights.append(2)  # 大跌
            else:
                alert_weights.append(1)  # 一般异动
        
        # 4. 成交量异动检测 (仅股票和ETF)
        if stock_type != 'gold' and 'volume_surge' in cfg:
            current_volume = data.get('volume', 0)
            if current_volume > 0:
                # 尝试获取5日均量
                ma5_volume = self.fetch_volume_ma5(code, stock_config['market'])
                if ma5_volume > 0:
                    volume_ratio = current_volume / ma5_volume
                    threshold = cfg['volume_surge']

                    # 数据合理性检查：成交量倍数超过20倍通常是数据异常，跳过
                    if volume_ratio > 20:
                        # 不触发异常预警，避免虚假信号
                        pass
                    elif volume_ratio >= threshold and not self._alerted_recently(code, 'volume_surge'):
                        alerts.append(('volume_surge', f"📊 放量 {volume_ratio:.1f}倍 (5日均量)"))
                        alert_weights.append(2)  # 中等权重
                    elif volume_ratio <= 0.5 and not self._alerted_recently(code, 'volume_shrink'):
                        alerts.append(('volume_shrink', f"📉 缩量 {volume_ratio:.1f}倍 (5日均量)"))
                        alert_weights.append(1)  # 低权重
        
        # 5. 均线系统 (MA金叉死叉)
        if stock_type != 'gold' and cfg.get('ma_monitor', True):
            ma_data = self.fetch_ma_data(code, stock_config['market'])
            if ma_data:
                # 金叉: MA5上穿MA10 (短期转强)
                if ma_data.get('golden_cross') and not self._alerted_recently(code, 'ma_golden'):
                    alerts.append(('ma_golden', f"🌟 均线金叉 (MA5¥{ma_data['MA5']:.2f}上穿MA10¥{ma_data['MA10']:.2f})"))
                    alert_weights.append(3)  # 高权重
                
                # 死叉: MA5下穿MA10 (短期转弱)
                if ma_data.get('death_cross') and not self._alerted_recently(code, 'ma_death'):
                    alerts.append(('ma_death', f"⚠️ 均线死叉 (MA5¥{ma_data['MA5']:.2f}下穿MA10¥{ma_data['MA10']:.2f})"))
                    alert_weights.append(3)  # 高权重
                
                # RSI超买超卖检测
                rsi = ma_data.get('RSI')
                if rsi:
                    if ma_data.get('RSI_overbought') and not self._alerted_recently(code, 'rsi_high'):
                        alerts.append(('rsi_high', f"🔥 RSI超买 ({rsi})，可能回调"))
                        alert_weights.append(2)
                    elif ma_data.get('RSI_oversold') and not self._alerted_recently(code, 'rsi_low'):
                        alerts.append(('rsi_low', f"❄️ RSI超卖 ({rsi})，可能反弹"))
                        alert_weights.append(2)
        
        # 5. 跳空缺口检测 (使用真实昨日K线数据)
        if stock_type != 'gold':
            current_open = data.get('open', price)

            if current_open > 0:
                yesterday_ohlc = self.fetch_yesterday_ohlc(code, stock_config['market'])

                if yesterday_ohlc:
                    prev_high = yesterday_ohlc['prev_high']
                    prev_low = yesterday_ohlc['prev_low']

                    # 向上跳空: 今日开盘 > 昨日最高
                    if prev_high > 0 and current_open > prev_high:
                        gap_pct = (current_open - prev_high) / prev_high * 100
                        if gap_pct >= 0.5 and not self._alerted_recently(code, 'gap_up'):  # 跳空幅度 ≥ 0.5%
                            alerts.append(('gap_up', f"⬆️ 向上跳空 {gap_pct:.1f}% (突破昨日最高¥{prev_high:.2f})"))
                            alert_weights.append(2)

                    # 向下跳空: 今日开盘 < 昨日最低
                    elif prev_low > 0 and current_open < prev_low:
                        gap_pct = (prev_low - current_open) / prev_low * 100
                        if gap_pct >= 0.5 and not self._alerted_recently(code, 'gap_down'):  # 跳空幅度 ≥ 0.5%
                            alerts.append(('gap_down', f"⬇️ 向下跳空 {gap_pct:.1f}% (跌破昨日最低¥{prev_low:.2f})"))
                            alert_weights.append(2)
        
        # 6. 动态止盈/移动止损 (跟踪持仓以来的历史最高价)
        if cost > 0:
            profit_pct = (price - cost) / cost * 100

            if profit_pct >= 10:
                max_high = stock_config.get('max_high', cost)
                if price > max_high:
                    max_high = price
                    stock_config['max_high'] = max_high

                drawdown = (max_high - price) / max_high * 100 if max_high > cost else 0

                if drawdown >= 5 and not self._alerted_recently(code, 'trailing_stop_5'):
                    alerts.append(('trailing_stop_5', f"📉 利润回撤 {drawdown:.1f}% (历史最高 ¥{max_high:.2f})，建议减仓"))
                    alert_weights.append(2)

                elif drawdown >= 10 and not self._alerted_recently(code, 'trailing_stop_10'):
                    alerts.append(('trailing_stop_10', f"🚨 利润回撤 {drawdown:.1f}% (历史最高 ¥{max_high:.2f})，建议清仓"))
                    alert_weights.append(3)
        
        # 7. 计算预警级别
        level = self._calculate_alert_level(alerts, alert_weights, stock_type)
        
        return alerts, level
    
    def _calculate_alert_level(self, alerts, weights, stock_type):
        """计算预警级别: info(提醒) / warning(警告) / critical(紧急)"""
        if not alerts:
            return None
        
        total_weight = sum(weights)
        alert_count = len(alerts)
        
        # 紧急: 多条件共振 或 高权重单一条件
        if total_weight >= 5 or alert_count >= 3:
            return "critical"
        
        # 警告: 中等权重 或 2个条件
        if total_weight >= 3 or alert_count >= 2:
            return "warning"
        
        # 提醒: 单一低权重条件
        return "info"
    
    def _alerted_recently(self, code, atype):
        now = time.time()
        self.alert_log = [l for l in self.alert_log if now - l['t'] < 1800] # 30分钟有效期
        for l in self.alert_log:
            if l['c'] == code and l['a'] == atype: return True
        return False
    
    def record_alert(self, code, atype):
        self.alert_log.append({'c': code, 'a': atype, 't': time.time()})
        self.alert_logger.info(f"{code} | {atype}")
    
    def fetch_news(self, symbol):
        """抓取个股最近新闻 (新浪/东财聚合) - 简化版"""
        try:
            # 使用东财个股新闻API
            url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax"
            params = {"code": symbol}
            resp = self.session.get(url, params=params, timeout=5)
            return ["新闻模块已就绪 (市场收盘中)"]
        except:
            return []

    def run_once(self, smart_mode=True):
        """执行监控 (支持智能频率)"""
        self.reload_watchlist()
        
        if smart_mode:
            schedule = self.should_run_now()
            if not schedule.get("run"):
                return []
            
            stocks_to_check = schedule.get("stocks", self.watchlist)
            mode = schedule.get("mode", "normal")
            
            if mode in ["market", "weekend"]:
                self.logger.info(f"[{datetime.now().strftime('%H:%M')}] {mode}模式扫描 {len(stocks_to_check)} 只标的...")
        else:
            stocks_to_check = self.watchlist
        
        data_map = self.fetch_sina_realtime(stocks_to_check)
        triggered = []
        
        for stock in stocks_to_check:
            code = stock['code']
            if code not in data_map: continue
            
            data = data_map[code]
            
            # 数据有效性检查
            if data['price'] <= 0 or data['prev_close'] <= 0:
                continue
            
            alerts, level = self.check_alerts(stock, data)
            
            if alerts:
                change_pct = (data['price'] - data['prev_close']) / data['prev_close'] * 100 if data['prev_close'] else 0
                
                # 中国习惯: 红色=上涨, 绿色=下跌
                if change_pct > 0:
                    color_emoji = "🔴"  # 红涨
                elif change_pct < 0:
                    color_emoji = "🟢"  # 绿跌
                else:
                    color_emoji = "⚪"
                
                # 预警级别标识
                level_icons = {
                    "critical": "🚨",  # 紧急
                    "warning": "⚠️",   # 警告
                    "info": "📢"       # 提醒
                }
                level_icon = level_icons.get(level, "📢")
                level_text = {"critical": "【紧急】", "warning": "【警告】", "info": "【提醒】"}.get(level, "")
                
                msg = f"<b>{level_icon} {level_text}{color_emoji} {stock['name']} ({code})</b>\n"
                msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                msg += f"💰 当前价格: <b>{data['price']:.2f}</b> ({change_pct:+.2f}%)\n"
                
                # 显示持仓盈亏
                cost = stock.get('cost', 0)
                if cost > 0:
                    cost_change = (data['price'] - cost) / cost * 100
                    profit_icon = "🔴+" if cost_change > 0 else "🟢"
                    msg += f"📊 持仓成本: ¥{cost:.2f} | 盈亏: {profit_icon}{cost_change:.2f}%\n"
                
                msg += f"\n🎯 触发预警 ({len(alerts)}项):\n"
                for _, text in alerts: 
                    msg += f"  • {text}\n"
                    self.record_alert(code, _)
                
                # Pro版：集成智能分析
                try:
                    from analyser import StockAnalyser
                    analyser = StockAnalyser()
                    insight = analyser.generate_insight(stock, {
                        'price': data['price'],
                        'change_pct': change_pct
                    }, alerts)
                    msg += f"\n{insight}"
                except Exception:
                    pass
                
                triggered.append(msg)
                self.logger.info(f"ALERT [{level}] {stock['name']}({code}): {'; '.join(t for _, t in alerts)}")
        
        if not triggered and stocks_to_check:
            self.logger.info(f"扫描完成: {len(stocks_to_check)} 只标的，无预警触发")

        self._persist_watchlist_max_high()

        return triggered

    def _persist_watchlist_max_high(self):
        """Persist max_high updates back to watchlist.json (并发安全)

        采用"读-改-写"模式，避免覆盖 web_server 进程的最新修改：
        1. 加文件锁
        2. 读取最新的 watchlist (可能被 web_server 修改过)
        3. 仅更新 max_high 字段，保留其他字段的最新值
        4. 原子写回
        这样即使多人同时在网页上编辑，daemon 的 max_high 更新也不会覆盖他们的修改。
        """
        try:
            with file_lock(WATCHLIST_LOCK_FILE):
                # 读取最新 watchlist (可能是 web_server 刚写过的)
                latest = safe_read_json(WATCHLIST_FILE, default=None)
                if not isinstance(latest, list):
                    latest = self.watchlist

                # 仅同步 max_high 字段，不覆盖其他字段
                for stock in self.watchlist:
                    code = stock.get('code')
                    if 'max_high' not in stock:
                        continue
                    target = next((s for s in latest if s.get('code') == code), None)
                    if target is not None:
                        target['max_high'] = stock['max_high']

                # 原子写回
                WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(WATCHLIST_FILE, latest)
        except Exception as e:
            self.logger.warning(f"Failed to persist watchlist max_high: {e}")

def _check_and_write_pid():
    """检查是否已有实例运行，写入PID文件"""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            # 检查进程是否存在
            if sys.platform == 'win32':
                import subprocess
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {old_pid}'],
                    capture_output=True, text=True
                )
                if str(old_pid) in result.stdout:
                    return False  # 进程仍在运行
            else:
                os.kill(old_pid, 0)
            return False
        except (ValueError, OSError, ProcessLookupError):
            pass  # 进程不存在，可以继续
    
    PID_FILE.write_text(str(os.getpid()))
    return True

def _remove_pid():
    """移除PID文件"""
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='股票监控预警系统')
    parser.add_argument('--daemon', '-d', action='store_true', help='后台常驻模式')
    parser.add_argument('--stop', '-s', action='store_true', help='停止后台进程')
    parser.add_argument('--status', help='查看后台进程状态', action='store_true')
    parser.add_argument('--once', '-o', action='store_true', help='单次运行（不使用智能调度）')
    parser.add_argument('--logs', '-l', action='store_true', help='查看最近日志')
    parser.add_argument('--alerts', '-a', action='store_true', help='查看最近预警')
    args = parser.parse_args()

    if args.status:
        if PID_FILE.exists():
            pid = PID_FILE.read_text().strip()
            print(f"监控进程运行中 (PID: {pid})")
        else:
            print("监控进程未运行")
        sys.exit(0)

    if args.stop:
        if PID_FILE.exists():
            pid = PID_FILE.read_text().strip()
            if sys.platform == 'win32':
                os.system(f'taskkill /PID {pid} /F')
            else:
                os.kill(int(pid), 15)
            _remove_pid()
            print(f"已停止进程 PID: {pid}")
        else:
            print("监控进程未运行")
        sys.exit(0)

    if args.logs:
        if LOG_FILE.exists():
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            print(''.join(lines[-50:]))
        else:
            print("暂无日志")
        sys.exit(0)

    if args.alerts:
        if ALERT_LOG_FILE.exists():
            with open(ALERT_LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            print(''.join(lines[-50:]))
        else:
            print("暂无预警记录")
        sys.exit(0)

    if args.daemon:
        if not _check_and_write_pid():
            print("监控进程已在运行中，使用 --stop 停止旧进程")
            sys.exit(1)
        
        monitor = StockAlert(log_to_file=True, log_to_console=True)
        monitor.logger.info("=== 股票监控后台进程启动 ===")
        monitor.logger.info(f"PID: {os.getpid()}")
        monitor.logger.info(f"监控标的: {len(WATCHLIST)} 只")
        
        atexit.register(_remove_pid)
        
        try:
            while not monitor._shutdown:
                alerts = monitor.run_once(smart_mode=True)
                if alerts:
                    for alert in alerts:
                        print(alert)
                time.sleep(30)  # 基础轮询间隔，智能调度会自行判断
        except KeyboardInterrupt:
            monitor.logger.info("收到中断信号，正在停止...")
        except Exception as e:
            monitor.logger.error(f"异常: {e}", exc_info=True)
        finally:
            _remove_pid()
            monitor.logger.info("=== 股票监控后台进程已停止 ===")
    else:
        monitor = StockAlert(log_to_file=True, log_to_console=True)
        smart = not args.once
        for alert in monitor.run_once(smart_mode=smart):
            print(alert)
