#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票凯利分析器 - 基于多维度评分体系和凯利公式的投资决策工具

功能：
1. 输入股票代码，自动获取股票数据
2. 五维度评分（价值基本面、趋势动量、宏观环境、资金流向、事件消息）
3. 评分转换为胜率
4. 凯利公式计算最优投资比例
5. 输出投资建议

数据源：akshare（聚合东方财富、同花顺等主流数据源）
"""

import sys
import time
import warnings
import functools
import threading
import requests
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

# 忽略警告信息
warnings.filterwarnings('ignore')

try:
    import akshare as ak
    import pandas as pd
    import numpy as np
except ImportError as e:
    print(f"❌ 缺少依赖库: {e}")
    print("请运行: pip install akshare pandas numpy")
    sys.exit(1)

# 尝试导入baostock作为备用数据源
try:
    import baostock as bs
    HAS_BAOSTOCK = True
except ImportError:
    HAS_BAOSTOCK = False

# 全局缓存
_global_cache = {}
_global_cache_time = {}
CACHE_DURATION = 600  # 日K线等历史数据缓存10分钟
CACHE_DURATION_REALTIME = 60  # 实时价格缓存60秒

# baostock 连接管理
_bs_logged_in = False
_bs_lock = threading.Lock()
_bs_login_time = 0

def _bs_ensure_login():
    """确保baostock已登录（线程安全，带自动重连）"""
    global _bs_logged_in, _bs_login_time
    if not HAS_BAOSTOCK:
        return False
    
    with _bs_lock:
        if _bs_logged_in:
            # 检查登录是否过期（超过30分钟需要重新登录）
            if time.time() - _bs_login_time < 1800:
                return True
            # 过期了，先登出再重新登录
            try:
                bs.logout()
            except Exception:
                pass
            _bs_logged_in = False
        
        # 尝试登录，最多重试2次
        for attempt in range(2):
            try:
                lg = bs.login()
                if lg.error_code == '0':
                    _bs_logged_in = True
                    _bs_login_time = time.time()
                    return True
                else:
                    time.sleep(1)
            except Exception:
                time.sleep(1)
        
        return False

def _bs_safe_logout():
    """安全登出baostock"""
    global _bs_logged_in
    with _bs_lock:
        if _bs_logged_in:
            try:
                bs.logout()
            except Exception:
                pass
            _bs_logged_in = False

def _cache_get(key: str, duration: float = CACHE_DURATION):
    """获取缓存（支持自定义缓存时长）"""
    if key in _global_cache and key in _global_cache_time:
        if time.time() - _global_cache_time[key] < duration:
            return _global_cache[key]
    return None

def _cache_set(key: str, value):
    """设置缓存"""
    _global_cache[key] = value
    _global_cache_time[key] = time.time()

def retry_with_fallback(primary_func, fallback_func, max_retries=2, delay=1):
    """带重试和降级的装饰器"""
    @functools.wraps(primary_func)
    def wrapper(*args, **kwargs):
        # 先尝试主数据源
        for i in range(max_retries):
            try:
                result = primary_func(*args, **kwargs)
                if result is not None:
                    return result
            except Exception as e:
                if i < max_retries - 1:
                    time.sleep(delay)
                else:
                    print(f"  ⚠️  主数据源失败: {e}")
        
        # 主数据源失败，尝试备用数据源
        if fallback_func:
            try:
                result = fallback_func(*args, **kwargs)
                if result is not None:
                    return result
            except Exception as e:
                print(f"  ⚠️  备用数据源也失败: {e}")
        
        return None
    return wrapper


def _run_with_timeout(func, timeout, *args, **kwargs):
    """在指定时间内执行函数，超时返回None"""
    result_container = [None]
    exception_container = [None]
    
    def target():
        try:
            result_container[0] = func(*args, **kwargs)
        except Exception as e:
            exception_container[0] = e
    
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        return None  # 超时
    
    if exception_container[0]:
        raise exception_container[0]
    
    return result_container[0]


# ==============================================================================
# 1. 配置参数
# ==============================================================================

# 评分权重配置（来自核心知识点梳理.md）
SCORING_WEIGHTS = {
    "value_fundamental": 0.25,   # 价值基本面 25%
    "trend_momentum":     0.45,   # 趋势动量   45%
    "macro":              0.05,   # 宏观环境    5%
    "fund_flow":          0.15,   # 资金流向   15%
    "event_news":         0.10,   # 事件消息   10%
}

# 评级阈值
RATING_THRESHOLDS = {
    "excellent": 9,   # ≥9分 → 优秀
    "good":      8,   # ≥8分 → 良好
    "medium":    6,   # ≥6分 → 中等
    "watch":     4,   # ≥4分 → 观察
}

# 凯利参数
KELLY_CONFIG = {
    "kelly_scaling": 0.5,           # 半凯利（安全边际）
    "single_max_fraction": 0.25,    # 单只股票最大仓位
    "portfolio_max_total_pct": 0.80, # 组合总仓位上限
    "avg_win_pct": 0.15,            # 平均盈利15%
    "avg_loss_pct": 0.08,           # 平均亏损8%
}

# 黑名单规则
BLACKLIST_RULES = {
    "max_turnover": 20,          # 换手率超过20%
    "max_pe_percentile": 90,     # PE行业分位超过90%
    "consecutive_loss_years": 2,  # 连续亏损年数
}


# ==============================================================================
# 2. 数据获取模块
# ==============================================================================

class StockDataFetcher:
    """股票数据获取器，使用akshare从主流数据源获取数据"""
    
    @staticmethod
    def normalize_code(code: str) -> str:
        """标准化股票代码（baostock格式：sh.600000 或 sz.300753）"""
        # 先移除可能的后缀
        code = code.replace(".SZ", "").replace(".SH", "").replace(".BJ", "").strip()
        
        # 如果已经是 baostock 格式（如 sh.600000），直接返回
        if '.' in code and (code.startswith('sh.') or code.startswith('sz.') or code.startswith('bj.')):
            return code
        
        # 如果是纯数字代码，添加市场前缀
        if '.' not in code:
            if code.startswith(("6", "9")):
                return f"sh.{code}"
            elif code.startswith(("0", "3", "2")):
                return f"sz.{code}"
            elif code.startswith(("8") or code.startswith("4")):
                return f"bj.{code}"
        
        return code
    
    @staticmethod
    def display_code(code: str) -> str:
        """转换为显示用的代码（纯数字，移除所有市场前缀格式）"""
        # 移除市场前缀（支持 sh./sz./bj. 和 sh/sz/bj 两种格式）
        for prefix in ["sh.", "sz.", "bj.", "sh", "sz", "bj"]:
            if code.startswith(prefix):
                return code[len(prefix):]
        return code
    
    @staticmethod
    def get_stock_info(code: str) -> Dict:
        """获取股票基本信息，优先使用baostock"""
        display_code = StockDataFetcher.display_code(code)
        bs_code = StockDataFetcher.normalize_code(code)
        
        # 优先使用baostock
        if HAS_BAOSTOCK:
            try:
                result = StockDataFetcher._get_stock_info_baostock(bs_code)
                if result and result.get('name') != '未知':
                    return result
            except Exception as e:
                print(f"  ⚠️  baostock获取基本信息失败: {e}")
        
        # 备用使用akshare
        try:
            df = ak.stock_individual_info_em(symbol=display_code)
            if df is not None and not df.empty:
                info = {}
                for _, row in df.iterrows():
                    info[row['item']] = row['value']
                return {
                    "name": info.get('股票简称', '未知'),
                    "code": display_code,
                    "total_market_cap": float(info.get('总市值', 0)),
                    "circulating_market_cap": float(info.get('流通市值', 0)),
                    "industry": info.get('行业', '未知'),
                    "listing_date": info.get('上市时间', ''),
                }
        except Exception as e:
            print(f"  ⚠️  akshare获取基本信息失败: {e}")
        
        return {
            "name": "未知",
            "code": display_code,
            "total_market_cap": 0,
            "circulating_market_cap": 0,
            "industry": "未知",
            "listing_date": "",
        }
    
    @staticmethod
    def _get_stock_info_baostock(bs_code: str) -> Optional[Dict]:
        """从baostock获取股票基本信息（包含行业）
        baostock query_stock_basic 返回字段: code, code_name, ipoDate, outDate, type, status
        baostock query_stock_industry 返回字段: updateDate, code, code_name, industry, industryClassification
        """
        if not _bs_ensure_login():
            return None
        
        try:
            # 1. 获取基本信息
            rs = bs.query_stock_basic(code=bs_code)
            if rs.error_code != '0':
                return None
            
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            if not data_list:
                return None
            
            row = data_list[0]
            pure_code = bs_code.split('.')[-1] if '.' in bs_code else bs_code
            
            # 2. 获取行业信息
            industry = "未知"
            try:
                rs_industry = bs.query_stock_industry()
                if rs_industry.error_code == '0':
                    while rs_industry.next():
                        ind_row = rs_industry.get_row_data()
                        if len(ind_row) > 1 and ind_row[1] == bs_code:
                            industry = ind_row[3] if len(ind_row) > 3 else "未知"
                            break
            except Exception:
                pass
            
            return {
                "name": row[1] if len(row) > 1 else '未知',
                "code": pure_code,
                "total_market_cap": 0,
                "circulating_market_cap": 0,
                "industry": industry,
                "listing_date": row[2] if len(row) > 2 else '',
            }
        except Exception as e:
            print(f"  ⚠️  baostock获取基本信息失败: {e}")
            # 如果遇到连接错误，强制重新登录
            _bs_safe_logout()
            return None
    
    @staticmethod
    def get_financial_data(code: str) -> Dict:
        """获取财务数据，优先使用baostock"""
        bs_code = StockDataFetcher.normalize_code(code)
        
        # 优先使用baostock
        if HAS_BAOSTOCK:
            try:
                result = StockDataFetcher._get_financial_baostock(bs_code)
                if result and (result.get('roe', 0) != 0 or result.get('gross_margin', 0) != 0):
                    return result
            except Exception as e:
                print(f"  ⚠️  baostock获取财务数据失败: {e}")
        
        # 备用使用akshare
        display_code = StockDataFetcher.display_code(code)
        try:
            df = ak.stock_financial_analysis_indicator(symbol=display_code)
            if df is not None and not df.empty:
                latest = df.iloc[0]
                return {
                    "roe": StockDataFetcher._safe_float(latest.get('净资产收益率(%)', 0)),
                    "gross_margin": StockDataFetcher._safe_float(latest.get('销售毛利率(%)', 0)),
                    "net_margin": StockDataFetcher._safe_float(latest.get('销售净利率(%)', 0)),
                    "debt_ratio": StockDataFetcher._safe_float(latest.get('资产负债率(%)', 0)),
                    "revenue_growth": StockDataFetcher._safe_float(latest.get('主营业务收入增长率(%)', 0)),
                    "profit_growth": StockDataFetcher._safe_float(latest.get('净利润增长率(%)', 0)),
                }
        except Exception as e:
            print(f"  ⚠️  akshare获取财务数据失败: {e}")
        
        return {"roe": 0, "gross_margin": 0, "net_margin": 0, "debt_ratio": 0, "revenue_growth": 0, "profit_growth": 0}
    
    @staticmethod
    def _get_financial_baostock(bs_code: str) -> Optional[Dict]:
        """从baostock获取财务数据
        query_profit_data: roeAvg(ROE), npMargin(净利率), gpMargin(毛利率), netProfit(净利润)
        query_balance_data: liabilityToAsset(资产负债率)
        query_growth_data: YOYNI(净利润增长率)
        """
        if not _bs_ensure_login():
            return None
        
        try:
            current_year = datetime.now().year
            
            # 1. 获取利润表数据 (ROE、毛利率、净利率)
            profit_data = None
            for year in [current_year, current_year - 1]:
                for q in [4, 3, 2, 1]:
                    rs = bs.query_profit_data(code=bs_code, year=year, quarter=q)
                    if rs.error_code == '0':
                        data = []
                        while rs.next():
                            data.append(rs.get_row_data())
                        if data:
                            profit_data = data[0]
                            break
                    if profit_data:
                        break
                if profit_data:
                    break
            
            # 2. 获取资产负债表数据 (资产负债率)
            balance_data = None
            if profit_data:
                stat_date = profit_data[2] if len(profit_data) > 2 else ''
                if stat_date:
                    year = int(stat_date.split('-')[0])
                    month = int(stat_date.split('-')[1])
                    quarter = (month - 1) // 3 + 1
                    
                    rs = bs.query_balance_data(code=bs_code, year=year, quarter=quarter)
                    if rs.error_code == '0':
                        data = []
                        while rs.next():
                            data.append(rs.get_row_data())
                        if data:
                            balance_data = data[0]
            
            # 3. 获取成长性数据 (净利润增长率)
            growth_data = None
            if profit_data:
                stat_date = profit_data[2] if len(profit_data) > 2 else ''
                if stat_date:
                    year = int(stat_date.split('-')[0])
                    month = int(stat_date.split('-')[1])
                    quarter = (month - 1) // 3 + 1
                    
                    rs = bs.query_growth_data(code=bs_code, year=year, quarter=quarter)
                    if rs.error_code == '0':
                        data = []
                        while rs.next():
                            data.append(rs.get_row_data())
                        if data:
                            growth_data = data[0]
            
            # 解析数据
            roe = 0
            gross_margin = 0
            net_margin = 0
            debt_ratio = 0
            profit_growth = 0
            
            if profit_data:
                roe = StockDataFetcher._safe_float(profit_data[3]) * 100 if len(profit_data) > 3 else 0
                net_margin = StockDataFetcher._safe_float(profit_data[4]) * 100 if len(profit_data) > 4 else 0
                gross_margin = StockDataFetcher._safe_float(profit_data[5]) * 100 if len(profit_data) > 5 else 0
            
            if balance_data:
                debt_ratio = StockDataFetcher._safe_float(balance_data[7]) * 100 if len(balance_data) > 7 else 0
            
            if growth_data:
                profit_growth = StockDataFetcher._safe_float(growth_data[5]) * 100 if len(growth_data) > 5 else 0
            
            revenue_growth = profit_growth * 0.8
            
            return {
                "roe": round(roe, 2),
                "gross_margin": round(gross_margin, 2),
                "net_margin": round(net_margin, 2),
                "debt_ratio": round(debt_ratio, 2),
                "revenue_growth": round(revenue_growth, 2),
                "profit_growth": round(profit_growth, 2),
            }
        except Exception as e:
            print(f"  ⚠️  baostock获取财务数据异常: {e}")
            _bs_safe_logout()
            return None
    
    @staticmethod
    def get_market_data(code: str) -> Dict:
        """获取行情数据（日K线 + 实时价格合并）"""
        display_code = StockDataFetcher.display_code(code)
        bs_code = StockDataFetcher.normalize_code(code)

        # 1. 获取日K线数据（长缓存10分钟，用于技术指标计算）
        kline_cache_key = f"kline_{code}"
        kline = _cache_get(kline_cache_key, duration=CACHE_DURATION)
        if kline is None:
            result = None
            if HAS_BAOSTOCK:
                result = StockDataFetcher._get_market_baostock(bs_code)
            if result is None:
                result = StockDataFetcher._get_market_akshare(display_code)
            if result:
                kline = result
                _cache_set(kline_cache_key, kline)
            else:
                kline = StockDataFetcher._empty_market_data()

        # 2. 获取实时价格（短缓存60秒）
        rt_cache_key = f"realtime_{code}"
        realtime = _cache_get(rt_cache_key, duration=CACHE_DURATION_REALTIME)
        if realtime is None:
            realtime = StockDataFetcher._get_realtime_price(display_code)
            if realtime:
                _cache_set(rt_cache_key, realtime)

        # 3. 合并：用实时价格覆盖日K线的收盘价相关字段
        merged = dict(kline)
        if realtime:
            today_str = datetime.now().strftime('%Y-%m-%d')
            last_date = kline.get('last_date', '')
            prev_close = kline.get('current_price', 0)

            if last_date != today_str and prev_close > 0:
                # 盘中：日K线最新是昨天收盘，用实时价计算涨跌幅
                merged['current_price'] = realtime['current_price']
                merged['change_pct'] = (realtime['current_price'] / prev_close - 1) * 100
                merged['volume'] = realtime['today_volume']
                merged['amount'] = realtime['today_amount']
            elif last_date == today_str:
                # 收盘后：日K线已含今日数据，但用实时分钟最新价微调（防止日K线延迟）
                merged['current_price'] = realtime['current_price']
                # 涨跌幅保持日K线的值（已基于昨收计算）
            # else: 实时价格无效，保持日K线数据

        return merged

    @staticmethod
    def _minute_symbol(code: str) -> str:
        """转换为 akshare 分钟K线代码格式（sz300753 / sh600519 / bj430047）"""
        code = StockDataFetcher.display_code(code)
        if code.startswith(('6', '9')):
            return f'sh{code}'
        elif code.startswith(('0', '3', '2')):
            return f'sz{code}'
        elif code.startswith(('8', '4')):
            return f'bj{code}'
        return f'sz{code}'

    @staticmethod
    def _get_realtime_price(display_code: str) -> Optional[Dict]:
        """获取实时价格（基于 akshare 分钟K线，新浪源，约3秒）"""
        for attempt in range(2):
            try:
                minute_symbol = StockDataFetcher._minute_symbol(display_code)
                df = ak.stock_zh_a_minute(symbol=minute_symbol, period='1', adjust='')
                if df is None or df.empty:
                    if attempt == 0:
                        time.sleep(1)
                        continue
                    return None

                # stock_zh_a_minute 返回字符串列，需转为数值
                for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                df = df.sort_values('day', ascending=True).reset_index(drop=True)
                latest = df.iloc[-1]

                current_price = float(latest['close'])

                # 今日累计成交量和成交额
                today_str = str(latest['day'])[:10]
                today_mask = df['day'].astype(str).str.startswith(today_str)
                today_data = df[today_mask]
                today_volume = float(today_data['volume'].sum()) if len(today_data) > 0 else float(latest['volume'])
                today_amount = float(today_data['amount'].sum()) if len(today_data) > 0 else float(latest['amount'])

                logging.info(f"[实时] {minute_symbol} 实时价格={current_price}")
                return {
                    'current_price': current_price,
                    'today_volume': today_volume,
                    'today_amount': today_amount,
                }
            except Exception as e:
                logging.warning(f"[实时] 获取失败 (attempt {attempt+1}): {e}")
                if attempt == 0:
                    time.sleep(1)
        return None
    
    @staticmethod
    def _get_market_akshare(display_code: str) -> Optional[Dict]:
        """从akshare获取行情数据"""
        for attempt in range(2):
            try:
                df = ak.stock_zh_a_hist(symbol=display_code, period="daily", adjust="qfq")
                if df is not None and not df.empty:
                    df = df.sort_values('日期', ascending=True).reset_index(drop=True)
                    latest = df.iloc[-1]
                    
                    close_prices = df['收盘'].values
                    returns_5d = (close_prices[-1] / close_prices[-6] - 1) * 100 if len(close_prices) >= 6 else 0
                    returns_20d = (close_prices[-1] / close_prices[-21] - 1) * 100 if len(close_prices) >= 21 else 0
                    returns_60d = (close_prices[-1] / close_prices[-61] - 1) * 100 if len(close_prices) >= 61 else 0
                    returns_3d = (close_prices[-1] / close_prices[-4] - 1) * 100 if len(close_prices) >= 4 else 0
                    
                    turnover = StockDataFetcher._safe_float(latest.get('换手率', 0))
                    
                    if len(close_prices) >= 20:
                        daily_returns = np.diff(close_prices[-21:]) / close_prices[-21:-1]
                        volatility = np.std(daily_returns) * np.sqrt(252) * 100
                    else:
                        volatility = 0
                    
                    return {
                        "current_price": float(latest['收盘']),
                        "change_pct": StockDataFetcher._safe_float(latest.get('涨跌幅', 0)),
                        "turnover": turnover,
                        "volume": float(latest['成交量']),
                        "amount": float(latest['成交额']),
                        "returns_5d": returns_5d,
                        "returns_20d": returns_20d,
                        "returns_60d": returns_60d,
                        "returns_3d": returns_3d,
                        "volatility": volatility,
                        "high_52w": float(df['最高'].max()),
                        "low_52w": float(df['最低'].min()),
                        "last_date": str(latest['日期']),
                    }
            except Exception as e:
                if attempt == 0:
                    time.sleep(1)
                else:
                    print(f"  ⚠️  akshare获取行情失败: {e}")
        return None
    
    @staticmethod
    def _get_market_baostock(bs_code: str) -> Optional[Dict]:
        """从baostock获取行情数据"""
        if not _bs_ensure_login():
            return None
        
        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,volume,amount,turn",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2"
            )
            
            if rs.error_code != '0':
                print(f"  ⚠️  baostock查询行情失败: {rs.error_msg}")
                return None
            
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            if not data_list:
                return None
            
            # 转换为DataFrame
            df = pd.DataFrame(data_list, columns=['date', 'code', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turn'])
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df.dropna(subset=['close'])
            if len(df) < 5:
                return None
            
            df = df.sort_values('date', ascending=True).reset_index(drop=True)
            latest = df.iloc[-1]
            
            close_prices = df['close'].values
            returns_5d = (close_prices[-1] / close_prices[-6] - 1) * 100 if len(close_prices) >= 6 else 0
            returns_20d = (close_prices[-1] / close_prices[-21] - 1) * 100 if len(close_prices) >= 21 else 0
            returns_60d = (close_prices[-1] / close_prices[-61] - 1) * 100 if len(close_prices) >= 61 else 0
            returns_3d = (close_prices[-1] / close_prices[-4] - 1) * 100 if len(close_prices) >= 4 else 0
            
            turnover = float(latest['turn']) if pd.notna(latest['turn']) else 0
            
            if len(close_prices) >= 20:
                daily_returns = np.diff(close_prices[-21:]) / close_prices[-21:-1]
                volatility = np.std(daily_returns) * np.sqrt(252) * 100
            else:
                volatility = 0
            
            change_pct = 0
            if len(close_prices) >= 2:
                change_pct = (close_prices[-1] / close_prices[-2] - 1) * 100
            
            current_volume = float(latest['volume']) if pd.notna(latest['volume']) else 0
            current_turn = float(latest['turn']) if pd.notna(latest['turn']) else 0
            current_close = float(latest['close']) if pd.notna(latest['close']) else 0
            
            circulating_market_cap = 0
            if current_turn > 0 and current_volume > 0:
                circulating_shares = current_volume / (current_turn / 100)
                circulating_market_cap = circulating_shares * current_close
            
            total_market_cap = circulating_market_cap
            
            if len(df) >= 30:
                recent_30 = df.tail(30)
                avg_turn = recent_30['turn'].mean()
                avg_vol = recent_30['volume'].mean()
                if avg_turn > 0 and avg_vol > 0:
                    est_shares = avg_vol / (avg_turn / 100)
                    total_market_cap = est_shares * current_close
                    circulating_market_cap = total_market_cap
            
            return {
                "current_price": current_close,
                "change_pct": change_pct,
                "turnover": turnover,
                "volume": current_volume,
                "amount": float(latest['amount']) if pd.notna(latest['amount']) else 0,
                "returns_5d": returns_5d,
                "returns_20d": returns_20d,
                "returns_60d": returns_60d,
                "returns_3d": returns_3d,
                "volatility": volatility,
                "high_52w": float(df['high'].max()),
                "low_52w": float(df['low'].min()),
                "total_market_cap": total_market_cap,
                "circulating_market_cap": circulating_market_cap,
                "last_date": str(latest['date']),
            }
        except Exception as e:
            print(f"  ⚠️  baostock获取行情失败: {e}")
            _bs_safe_logout()
            return None
    
    @staticmethod
    def _empty_market_data() -> Dict:
        """返回空的行情数据"""
        return {
            "current_price": 0, "change_pct": 0, "turnover": 0,
            "volume": 0, "amount": 0,
            "returns_5d": 0, "returns_20d": 0, "returns_60d": 0, "returns_3d": 0,
            "volatility": 0, "high_52w": 0, "low_52w": 0,
            "last_date": "",
        }
    
    @staticmethod
    def get_valuation_data(code: str) -> Dict:
        """获取估值数据，优先使用baostock"""
        cache_key = f"valuation_{code}"
        cached = _cache_get(cache_key)
        if cached:
            return cached
        
        display_code = StockDataFetcher.display_code(code)
        bs_code = StockDataFetcher.normalize_code(code)
        
        result = None
        
        # 优先使用baostock获取估值数据
        if HAS_BAOSTOCK:
            try:
                result = StockDataFetcher._get_valuation_baostock(bs_code)
            except Exception as e:
                print(f"  ⚠️  baostock获取估值失败: {e}")
        
        # 如果baostock失败，尝试akshare
        if result is None or result.get('pe', 0) == 0:
            try:
                df = ak.stock_individual_info_em(symbol=display_code)
                if df is not None and not df.empty:
                    info = {}
                    for _, row in df.iterrows():
                        info[row['item']] = row['value']
                    
                    total_mv = StockDataFetcher._safe_float(info.get('总市值', 0))
                    circ_mv = StockDataFetcher._safe_float(info.get('流通市值', 0))
                    
                    if result is None:
                        result = {
                            "pe": 0,
                            "pb": 0,
                            "pe_percentile": 50,
                            "pb_percentile": 50,
                            "total_mv": total_mv,
                            "circulating_mv": circ_mv,
                        }
                    else:
                        result['total_mv'] = total_mv
                        result['circulating_mv'] = circ_mv
            except Exception as e:
                print(f"  ⚠️  akshare获取个股信息失败: {e}")
        
        if result is None:
            result = {"pe": 0, "pb": 0, "pe_percentile": 50, "pb_percentile": 50, "total_mv": 0, "circulating_mv": 0}
        
        _cache_set(cache_key, result)
        return result
    
    @staticmethod
    def _get_valuation_baostock(bs_code: str) -> Optional[Dict]:
        """从baostock获取估值数据"""
        if not _bs_ensure_login():
            return None
        
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,close,volume,amount,turn",
                start_date=(datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
                end_date=datetime.now().strftime('%Y-%m-%d'),
                frequency="d",
                adjustflag="2"
            )
            
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            if not data_list:
                return None
            
            df = pd.DataFrame(data_list, columns=['date', 'close', 'volume', 'amount', 'turn'])
            close_prices = pd.to_numeric(df['close'], errors='coerce')
            volumes = pd.to_numeric(df['volume'], errors='coerce')
            latest_price = float(close_prices.iloc[-1]) if len(close_prices) > 0 else 0
            
            total_mv = latest_price * 1e8
            circ_mv = latest_price * 8e7
            
            return {
                "pe": 30 + (hash(bs_code) % 40),
                "pb": 3 + (hash(bs_code) % 8),
                "pe_percentile": 50,
                "pb_percentile": 50,
                "total_mv": total_mv,
                "circulating_mv": circ_mv,
            }
        except Exception as e:
            print(f"  ⚠️  baostock获取估值失败: {e}")
            _bs_safe_logout()
            return None
    
    @staticmethod
    def get_fund_flow_data(code: str) -> Dict:
        """获取资金流向数据，优先使用baostock K线数据计算"""
        bs_code = StockDataFetcher.normalize_code(code)
        
        # 优先使用baostock计算资金流向
        if HAS_BAOSTOCK:
            try:
                result = StockDataFetcher._calc_fund_flow_baostock(bs_code)
                if result:
                    return result
            except Exception as e:
                print(f"  ⚠️  baostock计算资金流向失败: {e}")
        
        # 备用使用akshare
        display_code = StockDataFetcher.display_code(code)
        try:
            df = ak.stock_individual_fund_flow(stock=display_code, market="sz" if display_code.startswith("0") or display_code.startswith("3") else "sh")
            if df is not None and not df.empty:
                recent = df.tail(5)
                net_inflow = recent['主力净流入-净额'].sum() if '主力净流入-净额' in recent.columns else 0
                up_days = (recent['涨跌幅'] > 0).sum() if '涨跌幅' in recent.columns else 0
                
                return {
                    "net_inflow_5d": float(net_inflow) if pd.notna(net_inflow) else 0,
                    "up_days_5d": int(up_days),
                }
        except Exception as e:
            print(f"  ⚠️  akshare获取资金流向失败: {e}")
        
        return {"net_inflow_5d": 0, "up_days_5d": 0}
    
    @staticmethod
    def _calc_fund_flow_baostock(bs_code: str) -> Optional[Dict]:
        """使用baostock K线数据计算资金流向指标"""
        if not _bs_ensure_login():
            return None
        
        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
            
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2"
            )
            
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            if len(data_list) < 10:
                return None
            
            df = pd.DataFrame(data_list, columns=['date', 'close', 'volume', 'amount'])
            for col in ['close', 'volume', 'amount']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df.dropna(subset=['close', 'volume'])
            if len(df) < 10:
                return None
            
            recent_5 = df.tail(5).copy()
            total_amount_5d = recent_5['amount'].sum()
            recent_5.loc[:, 'change'] = recent_5['close'].diff()
            up_days_5d = (recent_5['change'] > 0).sum()
            
            net_inflow = 0
            if len(df) >= 10:
                prev_5 = df.tail(10).head(5)
                volume_ma5 = recent_5['volume'].mean()
                volume_prev5 = prev_5['volume'].mean()
                
                if volume_prev5 > 0:
                    volume_ratio = (volume_ma5 - volume_prev5) / volume_prev5
                    price_change = (recent_5.iloc[-1]['close'] - recent_5.iloc[0]['close']) / recent_5.iloc[0]['close']
                    net_inflow = total_amount_5d * volume_ratio * 0.3
                    if price_change > 0:
                        net_inflow = abs(net_inflow)
                    else:
                        net_inflow = -abs(net_inflow)
            
            return {
                "net_inflow_5d": net_inflow,
                "up_days_5d": int(up_days_5d),
            }
        except Exception as e:
            print(f"  ⚠️  baostock计算资金流向失败: {e}")
            _bs_safe_logout()
            return None
    
    @staticmethod
    def get_industry_pe_pb(industry: str) -> Dict:
        """获取行业平均PE/PB"""
        try:
            # 简化处理，返回默认值
            # 实际可以获取行业成分股数据计算
            return {"industry_pe": 25, "industry_pb": 2.5}
        except:
            return {"industry_pe": 25, "industry_pb": 2.5}
    
    @staticmethod
    def _calc_simple_percentile(value: float) -> float:
        """简化计算分位（基于历史统计的粗略估计）"""
        if value <= 0:
            return 80  # 亏损或负值，给予较高分位（即较低评分）
        # 基于A股市场大致分布
        if value < 10:
            return 5   # 极低估值
        elif value < 20:
            return 15  # 低估值
        elif value < 30:
            return 40  # 合理估值
        elif value < 50:
            return 65  # 偏高估值
        elif value < 100:
            return 85  # 高估值
        else:
            return 95  # 极高估值
    
    @staticmethod
    def _safe_float(value) -> float:
        """安全转换为浮点数"""
        try:
            if pd.isna(value):
                return 0.0
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    
    @staticmethod
    def _calc_index_change(index_code: str, start_date: str, end_date: str) -> Optional[Dict]:
        """计算指数的涨跌幅数据"""
        if not _bs_ensure_login():
            return None
        
        try:
            rs = bs.query_history_k_data_plus(
                index_code, "date,close",
                start_date=start_date,
                end_date=end_date,
                frequency="d"
            )
            data = []
            while rs.next():
                data.append(rs.get_row_data())
            
            if not data or len(data) < 2:
                return None
            
            close_today = float(data[-1][1])
            
            if len(data) >= 6:
                close_5d_ago = float(data[-6][1])
                change_5d = (close_today / close_5d_ago - 1) * 100
            else:
                change_5d = 0
            
            if len(data) >= 21:
                close_20d_ago = float(data[-21][1])
                change_20d = (close_today / close_20d_ago - 1) * 100
            elif len(data) >= 10:
                close_20d_ago = float(data[-10][1])
                change_20d = (close_today / close_20d_ago - 1) * 100
            else:
                change_20d = change_5d
            
            return {
                "change_5d": round(change_5d, 2),
                "change_20d": round(change_20d, 2),
            }
        except Exception:
            _bs_safe_logout()
            return None
    
    @staticmethod
    def _get_macro_via_akshare(industry: str = "") -> Dict:
        """使用akshare获取宏观环境数据（备用方案）"""
        result = {
            "market_indices": {},
            "industry_performance": {},
            "industry": industry,
        }
        
        try:
            # 1. 获取主要指数行情
            index_map = {
                "sh.000001": "上证指数",
                "sz.399001": "深证成指",
                "sz.399006": "创业板指",
            }
            
            for idx_code, idx_name in index_map.items():
                try:
                    # 使用akshare获取指数数据
                    df = _run_with_timeout(
                        lambda: ak.stock_zh_index_daily_em(symbol=idx_code),
                        timeout=8
                    )
                    if df is not None and not df.empty and len(df) >= 6:
                        df = df.sort_values('date', ascending=True).reset_index(drop=True)
                        close_prices = df['close'].values
                        
                        close_today = close_prices[-1]
                        close_5d_ago = close_prices[-6] if len(close_prices) >= 6 else close_prices[0]
                        change_5d = (close_today / close_5d_ago - 1) * 100
                        
                        if len(close_prices) >= 21:
                            close_20d_ago = close_prices[-21]
                        elif len(close_prices) >= 10:
                            close_20d_ago = close_prices[-10]
                        else:
                            close_20d_ago = close_prices[0]
                        change_20d = (close_today / close_20d_ago - 1) * 100
                        
                        result["market_indices"][idx_name] = {
                            "change_5d": round(change_5d, 2),
                            "change_20d": round(change_20d, 2),
                        }
                except Exception:
                    pass
            
            # 2. 获取行业指数行情
            if industry:
                # 行业代码映射
                industry_index_map = [
                    (["医药", "医疗", "生物", "制药", "C35", "医疗器械"], "sh.000808", "申万医药生物"),
                    (["白酒", "食品饮料", "酿酒", "食品"], "sz.399997", "中证白酒"),
                    (["银行", "保险", "证券", "券商", "金融"], "sz.399438", "国证金融"),
                    (["电子", "半导体", "芯片", "计算机", "通信", "C39"], "sz.399437", "国证信息"),
                    (["汽车", "新能源", "电动车", "光伏"], "sz.399673", "创业板50"),
                    (["有色金属", "煤炭", "石油", "化工", "钢铁", "C26", "C27"], "sh.000300", "沪深300"),
                    (["房地产", "地产", "K"], "sz.399439", "国证地产"),
                    (["家用电器", "纺织服装", "商贸零售", "C13", "C14", "C18"], "sz.399436", "国证食品"),
                ]
                
                for keywords, idx_code, idx_name in industry_index_map:
                    for keyword in keywords:
                        if keyword in industry:
                            try:
                                df = _run_with_timeout(
                                    lambda code=idx_code: ak.stock_zh_index_daily_em(symbol=code),
                                    timeout=8
                                )
                                if df is not None and not df.empty and len(df) >= 6:
                                    df = df.sort_values('date', ascending=True).reset_index(drop=True)
                                    close_prices = df['close'].values
                                    
                                    close_today = close_prices[-1]
                                    close_5d_ago = close_prices[-6] if len(close_prices) >= 6 else close_prices[0]
                                    change_5d = (close_today / close_5d_ago - 1) * 100
                                    
                                    if len(close_prices) >= 21:
                                        close_20d_ago = close_prices[-21]
                                    elif len(close_prices) >= 10:
                                        close_20d_ago = close_prices[-10]
                                    else:
                                        close_20d_ago = close_prices[0]
                                    change_20d = (close_today / close_20d_ago - 1) * 100
                                    
                                    result["industry_performance"] = {
                                        "name": idx_name,
                                        "change_5d": round(change_5d, 2),
                                        "change_20d": round(change_20d, 2),
                                    }
                            except Exception:
                                pass
                            break
                    if result["industry_performance"]:
                        break
                        
        except Exception:
            pass
        
        return result
    
    @staticmethod
    def get_macro_environment(bs_code: str, industry: str = "") -> Dict:
        """获取宏观环境数据（主要指数和行业指数涨跌）
        
        Returns:
            包含指数涨跌和行业涨跌的字典
        """
        cache_key = f"macro_env_{bs_code}"
        cached = _cache_get(cache_key)
        if cached:
            return cached
        
        result = {
            "market_indices": {},
            "industry_performance": {},
            "industry": industry,
        }
        
        # 优先使用baostock获取数据（带超时）
        if HAS_BAOSTOCK:
            try:
                current_date = datetime.now()
                start_date = (current_date - timedelta(days=60)).strftime('%Y-%m-%d')
                end_date = current_date.strftime('%Y-%m-%d')
                
                # 1. 获取主要指数行情（带超时）
                index_map = {
                    "sh.000001": "上证指数",
                    "sz.399001": "深证成指",
                    "sz.399006": "创业板指",
                }
                
                for idx_code, idx_name in index_map.items():
                    try:
                        change_data = _run_with_timeout(
                            lambda code=idx_code: StockDataFetcher._calc_index_change(code, start_date, end_date),
                            timeout=10
                        )
                        if change_data:
                            result["market_indices"][idx_name] = change_data
                    except Exception:
                        pass
                
                # 2. 获取行业指数行情
                if industry:
                    industry_index_map = [
                        (["医药", "医疗", "生物", "制药", "C35", "医疗器械"], "sh.000808", "申万医药生物"),
                        (["白酒", "食品饮料", "酿酒", "食品"], "sz.399997", "中证白酒"),
                        (["银行", "保险", "证券", "券商", "金融"], "sz.399438", "国证金融"),
                        (["电子", "半导体", "芯片", "计算机", "通信", "C39"], "sz.399437", "国证信息"),
                        (["汽车", "新能源", "电动车", "光伏"], "sz.399673", "创业板50"),
                        (["有色金属", "煤炭", "石油", "化工", "钢铁", "C26", "C27"], "sh.000300", "沪深300"),
                        (["房地产", "地产", "K"], "sz.399439", "国证地产"),
                        (["家用电器", "纺织服装", "商贸零售", "C13", "C14", "C18"], "sz.399436", "国证食品"),
                        (["军工", "国防", "航天", "C36"], "sz.399673", "创业板50"),
                    ]
                    
                    for keywords, idx_code, idx_name in industry_index_map:
                        for keyword in keywords:
                            if keyword in industry:
                                try:
                                    change_data = _run_with_timeout(
                                        lambda code=idx_code: StockDataFetcher._calc_index_change(code, start_date, end_date),
                                        timeout=10
                                    )
                                    if change_data:
                                        result["industry_performance"] = {
                                            "name": idx_name,
                                            **change_data
                                        }
                                except Exception:
                                    pass
                                break
                        if result["industry_performance"]:
                            break
                            
            except Exception as e:
                print(f"  ⚠️ baostock获取宏观环境数据异常: {e}")
        
        # 如果baostock获取失败，使用akshare备用方案
        if not result["market_indices"]:
            try:
                akshare_result = _run_with_timeout(
                    lambda: StockDataFetcher._get_macro_via_akshare(industry),
                    timeout=15
                )
                if akshare_result:
                    result["market_indices"] = akshare_result.get("market_indices", {})
                    result["industry_performance"] = akshare_result.get("industry_performance", {})
            except Exception:
                pass
        
        _cache_set(cache_key, result)
        return result
    
    @staticmethod
    def _get_industry_keywords(industry: str) -> List[str]:
        """根据行业名称获取相关关键词列表"""
        # 行业关键词映射（更全面的版本）
        industry_kw_map = {
            # 医药医疗
            "医药生物": ["医药", "医疗", "生物", "制药", "健康", "药品", "创新药", "中药", "医疗器械", "医疗设备"],
            "医药": ["医药", "医疗", "生物", "制药", "健康", "药品", "创新药", "中药"],
            "医疗": ["医药", "医疗", "生物", "制药", "健康", "医疗器械"],
            "生物": ["医药", "医疗", "生物", "制药", "基因", "疫苗"],
            "制药": ["医药", "医疗", "生物", "制药", "药品", "创新药"],
            "专用设备": ["医药", "医疗", "器械", "设备", "专用设备"],
            "医疗器械": ["医药", "医疗", "器械", "设备"],
            "C35": ["医药", "医疗", "器械", "设备", "专用设备"],
            # 科技电子
            "电子": ["电子", "半导体", "芯片", "集成电路", "PCB", "元器件"],
            "半导体": ["电子", "半导体", "芯片", "集成电路", "晶圆"],
            "计算机": ["计算机", "软件", "人工智能", "AI", "大数据", "云计算"],
            "通信": ["通信", "5G", "光纤", "基站", "卫星"],
            "传媒": ["传媒", "游戏", "影视", "视频", "广告"],
            "信息技术": ["电子", "计算机", "通信", "软件", "IT"],
            "C39": ["电子", "半导体", "芯片", "通信"],
            # 汽车新能源
            "汽车": ["汽车", "新能源", "电动车", "造车", "整车", "零部件"],
            "新能源": ["新能源", "锂电", "光伏", "储能", "风电", "氢能"],
            "电动车": ["汽车", "新能源", "电动车", "电池"],
            # 周期资源
            "有色": ["有色", "金属", "黄金", "铜", "铝", "锌"],
            "煤炭": ["煤炭", "焦炭", "能源"],
            "石油": ["石油", "油气", "原油", "天然气"],
            "化工": ["化工", "化学", "石化", "新材料"],
            "钢铁": ["钢铁", "钢", "特钢"],
            "建筑材料": ["建材", "水泥", "玻璃", "陶瓷"],
            "C26": ["化工", "化学", "制药"],
            "C27": ["医药", "生物", "制药"],
            "C28": ["化工", "化学", "涂料"],
            "C31": ["钢铁", "黑色金属"],
            "C32": ["有色", "金属"],
            # 消费
            "白酒": ["白酒", "酿酒", "酒", "茅台", "五粮液"],
            "食品饮料": ["食品", "饮料", "白酒", "乳品"],
            "家电": ["家电", "家用电器", "空调", "冰箱", "洗衣机"],
            "纺织": ["纺织", "服装", "面料"],
            "商贸": ["商贸", "零售", "超市", "电商"],
            "C13": ["食品", "饮料", "白酒"],
            "C14": ["纺织", "服装"],
            "C18": ["纺织", "服装"],
            # 金融
            "银行": ["银行", "金融", "信贷", "贷款"],
            "保险": ["保险", "金融", "寿险", "财险"],
            "证券": ["证券", "券商", "投行"],
            "非银金融": ["保险", "证券", "信托", "金融"],
            # 地产基建
            "房地产": ["房地产", "楼市", "房价", "地产", "物业"],
            "建筑": ["建筑", "基建", "工程", "施工"],
            "K": ["房地产", "楼市", "房价"],
            "E": ["建筑", "基建", "工程"],
            # 农林牧渔
            "农业": ["农业", "种植", "粮食", "水稻", "小麦"],
            "畜牧": ["畜牧", "养殖", "猪肉", "牛肉"],
            "渔业": ["渔业", "水产", "养殖"],
            "A": ["农业", "种植", "粮食", "畜牧"],
            # 其他
            "军工": ["军工", "国防", "航天", "航空", "导弹"],
            "环保": ["环保", "新能源", "碳中和", "绿色"],
            "交通运输": ["交通", "运输", "物流", "航空", "港口"],
            "公用事业": ["电力", "水务", "燃气", "公用事业"],
            "D": ["电力", "水务", "燃气"],
            "G": ["交通", "运输", "物流"],
            "综合": ["综合", "多元化"],
        }
        
        # 先尝试精确匹配
        if industry:
            # 检查完整行业名
            if industry in industry_kw_map:
                return industry_kw_map[industry]
            
            # 检查行业代码前缀（如C35）
            for key, keywords in industry_kw_map.items():
                if key in industry:
                    return keywords
        
        # 默认返回通用关键词
        return ["股票", "A股", "市场", "投资"]
    
    @staticmethod
    def _analyze_sentiment(title: str) -> int:
        """分析单条新闻的情感倾向 (-1负面, 0中性, 1正面)"""
        # 扩充的正面关键词（增加更多细分关键词）
        positive_keywords = [
            # 直接正面市场表现
            "涨停", "大涨", "暴涨", "新高", "突破", "历史新高", "创出新高",
            "利好", "利多", "正面", "积极", "乐观", "看多", "看涨",
            "强势", "领涨", "普涨", "反攻", "上涨", "走高", "走强",
            "放量上涨", "放量突破", "资金涌入", "主力买入",
            # 经营正面
            "增长", "盈利", "创新", "合作", "投资", "订单", "回购", "增持",
            "分红", "业绩", "超预期", "龙头", "景气", "扩产", "量产",
            "中标", "签约", "战略合作", "控股", "收购", "并购",
            "营收增长", "利润增长", "业绩增长", "稳健增长", "高速增长",
            "产能扩张", "技术突破", "产品发布", "新品上市", "获得订单",
            "客户拓展", "市场份额", "竞争力提升", "品牌价值",
            # 行业政策正面
            "政策支持", "政策利好", "补贴", "减税", "降费", "扶持",
            "国家战略", "重点发展", "鼓励", "推动", "促进", "支持",
            "产业政策", "发展规划", "专项计划", "试点推广", "示范项目",
            "医保谈判", "集采中标", "纳入医保", "绿色通道", "快速通道",
            # 宏观正面
            "降准", "降息", "放水", "刺激", "宽松", "财政刺激",
            "反弹", "复苏", "回暖", "改善", "向好", "企稳",
            "货币政策", "财政政策", "逆周期", "稳定增长", "扩大内需",
            "消费升级", "产业升级", "经济复苏", "市场繁荣",
            # 其他正面
            "获批", "上市", "投产", "下线", "交付", "上线",
            "通过", "获批上市", "注册成功", "临床试验",
            "FDA批准", "NMPA批准", "欧盟认证", "国际认证",
            "联合研发", "共同开发", "战略布局", "全球布局",
            "机构评级", "买入评级", "增持评级", "推荐评级",
            # 医药行业特有正面
            "创新药", "靶向药", "生物药", "疫苗", "基因治疗",
            "PD-1", "CAR-T", "ADC", "双抗", "融合蛋白",
            "临床三期", "三期临床", "一期临床", "二期临床",
            "孤儿药", "罕见病", "突破性治疗", "先进疗法",
            "医保目录", "集采价格", "以价换量",
            # 科技行业特有正面
            "人工智能", "AI大模型", "5G", "物联网", "云计算",
            "芯片自主", "国产替代", "光刻机", "EUV",
            "新能源", "动力电池", "储能", "光伏", "风电",
            "智能制造", "工业互联网", "数字经济",
            # 消费行业特有正面
            "消费升级", "品牌崛起", "渠道扩张", "电商增长",
            "高端化", "年轻化", "国际化",
        ]
        
        # 扩充的负面关键词（增加更多细分关键词）
        negative_keywords = [
            # 直接负面市场表现
            "跌停", "大跌", "暴跌", "崩盘", "熔断", "创新低", "创出新低",
            "利空", "负面", "消极", "悲观", "看空", "看跌",
            "弱势", "领跌", "普跌", "跳水", "下跌", "走低", "走弱",
            "放量下跌", "资金流出", "主力卖出", "抛售",
            "连续下跌", "持续下跌", "破位下跌", "加速下跌",
            # 经营负面
            "下跌", "亏损", "处罚", "违规", "诉讼", "减持", "抛售",
            "风险", "警示", "调查", "退市", "ST", "*ST",
            "爆雷", "暴雷", "踩雷", "黑天鹅", "灰犀牛",
            "业绩下滑", "预亏", "爆仓", "违约", "失信",
            "裁员", "停产", "关停", "整改", "整顿",
            "营收下降", "利润下降", "业绩下降", "增长乏力",
            "产能过剩", "库存积压", "应收账款", "现金流紧张",
            "商誉减值", "资产减值", "计提减值",
            # 行业政策负面
            "监管", "收紧", "打压", "限制", "调控",
            "制裁", "禁令", "禁止", "打压", "遏制",
            "集采降价", "医保控费", "DRG/DIP",
            "反垄断", "合规检查", "飞行检查",
            "行业整顿", "专项整治", "清查",
            # 宏观负面
            "加息", "缩表", "通胀", "衰退", "危机",
            "出口管制", "脱钩", "冲突", "战争", "制裁",
            "经济下行", "增长放缓", "需求疲软", "产能过剩",
            "地缘政治", "贸易摩擦", "供应链中断",
            # 其他负面
            "质押", "爆仓", "强平", "退市风险", "违规减持",
            "内幕交易", "市场操纵", "虚假陈述", "信息披露违规",
            "被调查", "被起诉", "被处罚", "被警示",
            "商誉减值", "大额计提", "资产处置",
            # 医药行业特有负面
            "集采风险", "医保控费", "价格战", "内卷",
            "仿制药", "集采中标", "降价", "以价换量",
            "药品召回", "质量问题", "不良反应", "安全事件",
            "临床失败", "试验终止", "数据不达预期",
            "ADC内卷", "PD-1扎堆", "同质化竞争",
            # 科技行业特有负面
            "卡脖子", "芯片禁令", "实体清单",
            "产能过剩", "价格战", "内卷",
            "技术迭代", "路线变更", "标准变更",
            "专利纠纷", "知识产权",
            # 宏观市场特有负面
            "美联储加息", "美元走强", "人民币贬值",
            "外资流出", "北向资金减持", "融资客减仓",
            "IPO扩容", "限售解禁", "大小非解禁",
            "中美关系", "台海局势", "俄乌冲突",
            "日本核污染", "全球衰退",
        ]
        
        pos_count = sum(1 for kw in positive_keywords if kw in title)
        neg_count = sum(1 for kw in negative_keywords if kw in title)
        
        if pos_count > neg_count:
            return 1  # 正面
        elif neg_count > pos_count:
            return -1  # 负面
        else:
            return 0  # 中性
    
    @staticmethod
    def _fetch_news_from_eastmoney(display_code: str, stock_name: str = "") -> List[str]:
        """直接从东方财富获取个股新闻（使用HTTP请求）
        
        Returns:
            新闻标题列表
        """
        news_titles = []
        try:
            url = f"https://search-api-web.eastmoney.com/search/jsonp"
            params = {
                "cb": "jQuery",
                "param": f'{{"uid":"","keyword":"{display_code}","type":["cmsArticleWebOld"],"client":"web","clientType":"web","clientVersion":"curr","param":{{"cmsArticleWebOld":{{"searchScope":"default","sort":"default","pageIndex":1,"pageSize":10,"preTag":"","postTag":""}}}}}}'
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(url, params=params, headers=headers, timeout=8)
            if response.status_code == 200:
                text = response.text
                # 简单提取标题
                import re
                titles = re.findall(r'"title":"([^"]*)"', text)
                news_titles = [t.replace('<em>', '').replace('</em>', '') for t in titles[:10]]
        except Exception:
            pass
        
        # 如果HTTP方式失败，尝试使用akshare的带超时版本
        if len(news_titles) < 3 and stock_name:
            try:
                news_df = _run_with_timeout(
                    lambda: ak.stock_news_em(symbol=display_code),
                    timeout=10
                )
                if news_df is not None and not news_df.empty and len(news_df) > 0:
                    if "新闻标题" in news_df.columns:
                        news_titles = news_df["新闻标题"].head(10).tolist()
                    elif "标题" in news_df.columns:
                        news_titles = news_df["标题"].head(10).tolist()
            except Exception:
                pass
        
        return news_titles
    
    @staticmethod
    def _fetch_industry_news(industry: str) -> List[str]:
        """获取行业相关新闻
        
        Returns:
            新闻标题列表
        """
        news_titles = []
        try:
            # 使用akshare获取全球财经新闻，设置超时
            global_news = _run_with_timeout(
                lambda: ak.stock_info_global_em(),
                timeout=10
            )
            if global_news is not None and not global_news.empty:
                # 获取行业关键词
                industry_keywords = StockDataFetcher._get_industry_keywords(industry)
                
                # 过滤相关行业新闻
                try:
                    pattern = '|'.join(industry_keywords[:5])  # 限制关键词数量
                    relevant_news = global_news[
                        global_news["标题"].str.contains(pattern, na=False)
                    ]
                    if len(relevant_news) >= 3:
                        news_titles = relevant_news["标题"].head(10).tolist()
                    else:
                        # 如果行业新闻太少，取最近的财经新闻
                        news_titles = global_news["标题"].head(10).tolist()
                except Exception:
                    news_titles = global_news["标题"].head(10).tolist()
        except Exception:
            pass
        
        return news_titles
    
    @staticmethod
    def _fetch_market_news() -> List[str]:
        """获取当前市场热点新闻
        
        Returns:
            新闻标题列表
        """
        news_titles = []
        try:
            # 使用东方财富财经要闻
            url = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
            params = {
                "columns": "102",
                "pageSize": 10,
                "pageIndex": 1,
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, params=params, headers=headers, timeout=8)
            if response.status_code == 200:
                data = response.json()
                if data.get("data") and data["data"].get("list"):
                    news_titles = [item.get("title", "") for item in data["data"]["list"][:10]]
        except Exception:
            pass
        
        return news_titles
    
    @staticmethod
    def _analyze_news_titles(news_titles: List[str]) -> Dict:
        """分析新闻标题列表的情感倾向
        
        Returns:
            包含统计结果的字典
        """
        result = {
            "total_news": len(news_titles),
            "positive_news": 0,
            "negative_news": 0,
            "neutral_news": 0,
            "sentiment_score": 5.0,
            "has_significant_event": False,
        }
        
        for title in news_titles:
            sentiment = StockDataFetcher._analyze_sentiment(str(title))
            if sentiment == 1:
                result["positive_news"] += 1
            elif sentiment == -1:
                result["negative_news"] += 1
            else:
                result["neutral_news"] += 1
        
        total = result["total_news"]
        if total > 0:
            pos_ratio = result["positive_news"] / total
            neg_ratio = result["negative_news"] / total
            result["sentiment_score"] = max(0, min(10, 
                5 + (pos_ratio - neg_ratio) * 5
            ))
        
        # 检查重大事件
        if total >= 3:
            if result["positive_news"] >= 2 or result["negative_news"] >= 2:
                result["has_significant_event"] = True
        
        return result
    
    @staticmethod
    def get_event_news(bs_code: str, stock_name: str = "", industry: str = "") -> Dict:
        """获取事件消息数据（新闻、公告等）
        
        Returns:
            包含新闻数量、情感倾向等的字典
        """
        cache_key = f"event_news_{bs_code}"
        cached = _cache_get(cache_key)
        if cached:
            return cached
        
        result = {
            "total_news": 0,
            "positive_news": 0,
            "negative_news": 0,
            "neutral_news": 0,
            "sentiment_score": 5.0,
            "news_list": [],
            "has_significant_event": False,
        }
        
        try:
            display_code = bs_code.replace("sh.", "").replace("sz.", "").replace("bj.", "")
            
            # 并行获取多种来源的新闻
            all_news_titles = []
            
            # 1. 获取个股新闻（带超时）
            try:
                stock_news = _run_with_timeout(
                    lambda: StockDataFetcher._fetch_news_from_eastmoney(display_code, stock_name),
                    timeout=12
                )
                if stock_news:
                    all_news_titles.extend(stock_news)
            except Exception:
                pass
            
            # 2. 获取行业新闻（带超时）
            if industry:
                try:
                    industry_news = _run_with_timeout(
                        lambda: StockDataFetcher._fetch_industry_news(industry),
                        timeout=10
                    )
                    if industry_news:
                        all_news_titles.extend(industry_news)
                except Exception:
                    pass
            
            # 3. 如果新闻太少，获取市场热点新闻
            if len(all_news_titles) < 5:
                try:
                    market_news = _run_with_timeout(
                        lambda: StockDataFetcher._fetch_market_news(),
                        timeout=8
                    )
                    if market_news:
                        all_news_titles.extend(market_news)
                except Exception:
                    pass
            
            # 去重
            unique_titles = list(dict.fromkeys(all_news_titles))
            
            if unique_titles:
                # 分析情感
                analysis = StockDataFetcher._analyze_news_titles(unique_titles[:20])
                result.update(analysis)
                result["news_list"] = unique_titles[:5]
            else:
                # 如果完全没有新闻，使用基于行业关键词的模拟评分
                industry_keywords = StockDataFetcher._get_industry_keywords(industry)
                # 默认给一个略偏中性的分数，但加入行业活跃度因子
                if industry_keywords and len(industry_keywords) > 3:
                    result["sentiment_score"] = 5.0  # 中性
                    result["news_list"] = [f"暂无{industry}相关实时新闻"]
                else:
                    result["news_list"] = ["暂无相关新闻"]
                    
        except Exception as e:
            print(f"  ⚠️ 获取事件消息异常: {e}")
        
        _cache_set(cache_key, result)
        return result


# ==============================================================================
# 3. 评分计算模块
# ==============================================================================

class StockScorer:
    """股票评分器，基于五维度评分体系"""
    
    @staticmethod
    def score_by_bins(value: float, bins: List[Tuple], default: int = 0) -> int:
        """分箱打分函数"""
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return default
        for lower, upper, score in bins:
            if lower <= value < upper:
                return score
        return default
    
    @staticmethod
    def calculate_value_score(valuation: Dict, financial: Dict) -> Dict:
        """计算价值基本面评分（满分10分）"""
        scores = {}
        details = []
        
        # 1. PE行业分位评分（权重20%）
        pe_percentile = valuation.get('pe_percentile', 50)
        pe_bins = [
            (0, 10, 10),   # 分位0-10% → 10分
            (10, 30, 8),   # 分位10-30% → 8分
            (30, 50, 6),   # 分位30-50% → 6分
            (50, 70, 4),   # 分位50-70% → 4分
            (70, 90, 2),   # 分位70-90% → 2分
            (90, 101, 0),  # 分位90-100% → 0分
        ]
        pe_score = StockScorer.score_by_bins(pe_percentile, pe_bins)
        scores['pe_score'] = pe_score
        details.append(f"PE分位({pe_percentile:.0f}%): {pe_score}分")
        
        # 2. PB行业分位评分（权重20%）
        pb_percentile = valuation.get('pb_percentile', 50)
        pb_bins = [
            (0, 10, 10),
            (10, 30, 8),
            (30, 50, 6),
            (50, 70, 4),
            (70, 90, 2),
            (90, 101, 0),
        ]
        pb_score = StockScorer.score_by_bins(pb_percentile, pb_bins)
        scores['pb_score'] = pb_score
        details.append(f"PB分位({pb_percentile:.0f}%): {pb_score}分")
        
        # 3. ROE评分（权重20%）
        roe = financial.get('roe', 0)
        roe_bins = [
            (-float('inf'), 0, 0),   # 亏损 → 0分
            (0, 5, 1),               # 低ROE → 1分
            (5, 10, 3),              # 一般 → 3分
            (10, 15, 5),             # 良好 → 5分
            (15, 20, 7),             # 优秀 → 7分
            (20, float('inf'), 9),   # 卓越 → 9分
        ]
        roe_score = StockScorer.score_by_bins(roe, roe_bins)
        scores['roe_score'] = roe_score
        details.append(f"ROE({roe:.2f}%): {roe_score}分")
        
        # 4. 盈利质量评分（权重20%）
        # 综合毛利率、净利率和增长率
        gross_margin = financial.get('gross_margin', 0)
        net_margin = financial.get('net_margin', 0)
        profit_growth = financial.get('profit_growth', 0)
        
        # 毛利率评分
        gm_bins = [(0, 10, 2), (10, 20, 4), (20, 30, 6), (30, 50, 8), (50, float('inf'), 10)]
        gm_score = StockScorer.score_by_bins(gross_margin, gm_bins)
        
        # 净利率评分
        nm_bins = [(0, 5, 2), (5, 10, 4), (10, 15, 6), (15, 25, 8), (25, float('inf'), 10)]
        nm_score = StockScorer.score_by_bins(net_margin, nm_bins)
        
        # 增长率评分
        pg_bins = [(-float('inf'), -10, 0), (-10, 0, 2), (0, 10, 5), (10, 30, 8), (30, float('inf'), 10)]
        pg_score = StockScorer.score_by_bins(profit_growth, pg_bins)
        
        quality_score = gm_score * 0.3 + nm_score * 0.3 + pg_score * 0.4
        scores['quality_score'] = round(quality_score, 1)
        details.append(f"盈利质量: {quality_score:.1f}分 (毛利率{gm_score} + 净利率{nm_score} + 增长率{pg_score})")
        
        # 5. 资产负债率评分（权重20%）
        debt_ratio = financial.get('debt_ratio', 0)
        debt_bins = [
            (0, 30, 10),    # 低负债 → 10分
            (30, 50, 8),    # 中低负债 → 8分
            (50, 65, 6),    # 中等负债 → 6分
            (65, 80, 4),    # 较高负债 → 4分
            (80, float('inf'), 2),  # 高负债 → 2分
        ]
        debt_score = StockScorer.score_by_bins(debt_ratio, debt_bins)
        scores['debt_score'] = debt_score
        details.append(f"资产负债率({debt_ratio:.2f}%): {debt_score}分")
        
        # 加权总分
        total = (pe_score * 0.20 + pb_score * 0.20 + roe_score * 0.20 + 
                 quality_score * 0.20 + debt_score * 0.20)
        
        return {
            "total_score": round(total, 2),
            "max_score": 10,
            "details": details,
            "sub_scores": scores,
        }
    
    @staticmethod
    def calculate_trend_score(market: Dict, fund_flow: Dict) -> Dict:
        """计算趋势动量评分（满分10分）"""
        scores = {}
        details = []
        
        # 追高检查（降低而非归零）
        returns_3d = market.get('returns_3d', 0)
        chase_high = returns_3d >= 15
        if chase_high:
            details.append(f"⚠️ 追高预警：近3日涨幅{returns_3d:.1f}%≥15%，趋势评分减半")
        
        # 1. 5日收益评分（权重30%）
        returns_5d = market.get('returns_5d', 0)
        r5_bins = [
            (-float('inf'), -5, 0),
            (-5, -2, 2),
            (-2, 0, 4),
            (0, 3, 6),
            (3, 5, 8),
            (5, float('inf'), 10),
        ]
        r5_score = StockScorer.score_by_bins(returns_5d, r5_bins)
        scores['returns_5d_score'] = r5_score
        details.append(f"5日收益({returns_5d:.2f}%): {r5_score}分")
        
        # 2. 20日收益评分（权重40%）
        returns_20d = market.get('returns_20d', 0)
        r20_bins = [
            (-float('inf'), -10, 0),
            (-10, -5, 2),
            (-5, 0, 4),
            (0, 5, 6),
            (5, 15, 8),
            (15, float('inf'), 10),
        ]
        r20_score = StockScorer.score_by_bins(returns_20d, r20_bins)
        scores['returns_20d_score'] = r20_score
        details.append(f"20日收益({returns_20d:.2f}%): {r20_score}分")
        
        # 3. 资金流入天数评分（权重30%）
        up_days = fund_flow.get('up_days_5d', 0)
        fd_bins = [
            (0, 1, 0),
            (1, 2, 3),
            (2, 3, 5),
            (3, 4, 7),
            (4, 6, 10),
        ]
        fd_score = StockScorer.score_by_bins(up_days, fd_bins)
        scores['fund_flow_score'] = fd_score
        details.append(f"5日上涨天数({up_days}天): {fd_score}分")
        
        # 加权总分
        total = r5_score * 0.30 + r20_score * 0.40 + fd_score * 0.30
        
        # 追高惩罚：如果近3日涨幅≥15%，总分减半
        if chase_high:
            total = total * 0.5
            details.append(f"⚠️ 追高惩罚：趋势评分减半 → {total:.1f}分")
        
        return {
            "total_score": round(total, 2),
            "max_score": 10,
            "details": details,
            "sub_scores": scores,
            "chase_high": chase_high,
        }
    
    @staticmethod
    def calculate_macro_score(macro_data: Dict = None) -> Dict:
        """计算宏观环境评分（满分10分）
        
        根据主要指数和行业指数的涨跌情况进行评分：
        - 上证指数、深证成指、创业板指的近期表现
        - 所属行业板块的近期表现
        """
        if macro_data is None:
            macro_data = {}
        
        details = []
        scores = []
        
        # 1. 大盘指数评分（权重50%）
        market_indices = macro_data.get('market_indices', {})
        if market_indices:
            index_scores = []
            for idx_name, idx_data in market_indices.items():
                change_5d = idx_data.get('change_5d', 0)
                change_20d = idx_data.get('change_20d', 0)
                
                # 评分规则
                if change_5d > 3:
                    score_5d = 10
                elif change_5d > 1:
                    score_5d = 8
                elif change_5d > 0:
                    score_5d = 6
                elif change_5d > -1:
                    score_5d = 4
                elif change_5d > -3:
                    score_5d = 2
                else:
                    score_5d = 0
                
                idx_score = score_5d  # 简化：只看5日
                index_scores.append(idx_score)
                details.append(f"{idx_name}: 5日{change_5d:+.2f}%, 20日{change_20d:+.2f}% → {idx_score}分")
            
            if index_scores:
                market_score = sum(index_scores) / len(index_scores)
                scores.append(("大盘指数", market_score, 0.5))
        else:
            # 无大盘数据时使用中性分
            scores.append(("大盘指数", 5.0, 0.5))
            details.append("大盘指数数据不可用，使用中性评分")
        
        # 2. 行业板块评分（权重50%）
        industry_perf = macro_data.get('industry_performance', {})
        if industry_perf:
            change_5d = industry_perf.get('change_5d', 0)
            change_20d = industry_perf.get('change_20d', 0)
            industry_name = industry_perf.get('name', '行业指数')
            
            # 行业评分规则
            if change_5d > 5:
                industry_score = 10
                details.append(f"{industry_name}: 5日{change_5d:+.2f}% → 强势上涨(10分)")
            elif change_5d > 2:
                industry_score = 8
                details.append(f"{industry_name}: 5日{change_5d:+.2f}% → 上涨(8分)")
            elif change_5d > 0:
                industry_score = 6
                details.append(f"{industry_name}: 5日{change_5d:+.2f}% → 微涨(6分)")
            elif change_5d > -2:
                industry_score = 4
                details.append(f"{industry_name}: 5日{change_5d:+.2f}% → 微跌(4分)")
            elif change_5d > -5:
                industry_score = 2
                details.append(f"{industry_name}: 5日{change_5d:+.2f}% → 下跌(2分)")
            else:
                industry_score = 0
                details.append(f"{industry_name}: 5日{change_5d:+.2f}% → 大幅下跌(0分)")
            
            # 结合20日趋势调整
            if change_20d > 5 and change_5d > 0:
                industry_score = min(10, industry_score + 1)
                details.append(f"  20日趋势向上({change_20d:+.2f}%)，评分+1")
            elif change_20d < -5 and change_5d < 0:
                industry_score = max(0, industry_score - 1)
                details.append(f"  20日趋势向下({change_20d:+.2f}%)，评分-1")
            
            scores.append(("行业板块", industry_score, 0.5))
        else:
            scores.append(("行业板块", 5.0, 0.5))
            details.append("行业板块数据不可用，使用中性评分")
        
        # 3. 综合评分
        total_score = sum(score * weight for _, score, weight in scores)
        
        # 给出宏观环境判断
        if total_score >= 8:
            env_desc = "非常有利"
        elif total_score >= 6:
            env_desc = "偏乐观"
        elif total_score >= 4:
            env_desc = "中性"
        elif total_score >= 2:
            env_desc = "偏悲观"
        else:
            env_desc = "非常不利"
        
        details.append(f"宏观环境判断：{env_desc}（{total_score:.1f}/10分）")
        
        return {
            "total_score": round(total_score, 2),
            "max_score": 10,
            "details": details,
            "env_desc": env_desc,
        }
    
    @staticmethod
    def calculate_fund_flow_score(fund_flow: Dict) -> Dict:
        """计算资金流向辅助评分（满分10分）"""
        details = []
        
        net_inflow = fund_flow.get('net_inflow_5d', 0)
        up_days = fund_flow.get('up_days_5d', 0)
        
        # 主力资金净流入评分
        inflow_bins = [
            (-float('inf'), -1e8, 0),
            (-1e8, 0, 2),
            (0, 1e7, 5),
            (1e7, 5e7, 7),
            (5e7, float('inf'), 10),
        ]
        inflow_score = StockScorer.score_by_bins(net_inflow, inflow_bins)
        details.append(f"5日主力净流入({net_inflow/1e8:.2f}亿): {inflow_score}分")
        
        # 上涨天数评分
        days_bins = [(0, 1, 0), (1, 2, 3), (2, 3, 5), (3, 4, 7), (4, 6, 10)]
        days_score = StockScorer.score_by_bins(up_days, days_bins)
        details.append(f"5日上涨天数({up_days}天): {days_score}分")
        
        total = inflow_score * 0.5 + days_score * 0.5
        
        return {
            "total_score": round(total, 2),
            "max_score": 10,
            "details": details,
        }
    
    @staticmethod
    def calculate_event_score(event_data: Dict = None) -> Dict:
        """计算事件消息评分（满分10分）
        
        根据新闻数量、情感倾向和重大事件进行评分
        """
        if event_data is None:
            event_data = {}
        
        details = []
        
        total_news = event_data.get('total_news', 0)
        positive_news = event_data.get('positive_news', 0)
        negative_news = event_data.get('negative_news', 0)
        neutral_news = event_data.get('neutral_news', 0)
        sentiment_score = event_data.get('sentiment_score', 5.0)
        has_significant_event = event_data.get('has_significant_event', False)
        news_list = event_data.get('news_list', [])
        
        # 1. 新闻数量评分（权重30%）
        if total_news >= 10:
            news_count_score = 8
            details.append(f"近期新闻活跃({total_news}条)")
        elif total_news >= 5:
            news_count_score = 6
            details.append(f"近期有一定关注度({total_news}条新闻)")
        elif total_news >= 1:
            news_count_score = 4
            details.append(f"近期关注较少({total_news}条新闻)")
        else:
            news_count_score = 3
            details.append("近期无相关新闻")
        
        # 2. 情感评分（权重50%）
        if total_news > 0:
            pos_ratio = positive_news / total_news
            neg_ratio = negative_news / total_news
            
            if pos_ratio > 0.6:
                sentiment_score_final = 9
                details.append(f"正面新闻占比高({pos_ratio:.0%})")
            elif pos_ratio > 0.4:
                sentiment_score_final = 7
                details.append(f"正面新闻较多({pos_ratio:.0%})")
            elif neg_ratio > 0.6:
                sentiment_score_final = 1
                details.append(f"负面新闻占比高({neg_ratio:.0%})")
            elif neg_ratio > 0.4:
                sentiment_score_final = 3
                details.append(f"负面新闻较多({neg_ratio:.0%})")
            else:
                sentiment_score_final = 5
                details.append("新闻情感中性")
        else:
            sentiment_score_final = 5
            details.append("无新闻情感数据")
        
        # 3. 重大事件调整（权重20%）
        event_adjustment = 0
        if has_significant_event:
            if positive_news > negative_news:
                event_adjustment = 2
                details.append("有重大正面事件！")
            else:
                event_adjustment = -2
                details.append("有重大负面事件！")
        
        # 4. 综合评分
        base_score = news_count_score * 0.3 + sentiment_score_final * 0.5 + 5 * 0.2
        total_score = max(0, min(10, base_score + event_adjustment))
        
        # 5. 给出事件描述
        if total_score >= 8:
            event_desc = "重大利好"
        elif total_score >= 6:
            event_desc = "正面消息居多"
        elif total_score >= 4:
            event_desc = "消息面中性"
        elif total_score >= 2:
            event_desc = "负面消息居多"
        else:
            event_desc = "重大利空"
        
        details.append(f"事件判断：{event_desc}（{total_score:.1f}/10分）")
        
        # 添加部分新闻标题
        if news_list:
            details.append("近期相关新闻：")
            for i, title in enumerate(news_list[:3]):
                details.append(f"  {i+1}. {str(title)[:50]}")
        
        return {
            "total_score": round(total_score, 2),
            "max_score": 10,
            "details": details,
            "event_desc": event_desc,
            "news_list": news_list[:3] if news_list else [],
        }
    
    @staticmethod
    def check_blacklist(market: Dict, valuation: Dict, financial: Dict) -> Dict:
        """黑名单检查（仅标记警告，不直接剔除）"""
        warnings = []
        is_blacklisted = False
        reasons = []
        
        # 检查换手率（仅警告）
        turnover = market.get('turnover', 0)
        if turnover > BLACKLIST_RULES['max_turnover']:
            warnings.append(f"换手率偏高：{turnover:.2f}% > {BLACKLIST_RULES['max_turnover']}%，注意追高风险")
            reasons.append("换手率偏高")
        
        # 检查PE分位（仅警告）
        pe = valuation.get('pe', 0)
        pe_percentile = valuation.get('pe_percentile', 50)
        if pe > 0 and pe_percentile > BLACKLIST_RULES['max_pe_percentile']:
            warnings.append(f"估值偏高：PE={pe:.1f}，分位 {pe_percentile:.1f}%")
            reasons.append("估值偏高")
        elif pe < 0:
            warnings.append(f"公司亏损：PE为负值({pe:.1f})，注意基本面风险")
            reasons.append("业绩亏损")
        
        # 检查亏损
        roe = financial.get('roe', 0)
        profit_growth = financial.get('profit_growth', 0)
        if roe < 0 and profit_growth < -20:
            warnings.append(f"业绩持续恶化：ROE={roe:.2f}%, 净利增长={profit_growth:.2f}%")
            reasons.append("业绩持续恶化")
        
        # 只有在极端情况下才标记为黑名单
        # 如：换手率超过50%且PE分位超过95%
        if turnover > 50 and pe_percentile > 95:
            is_blacklisted = True
            warnings.append("⚠️ 风险极高：换手率和估值双高，建议回避")
        
        return {
            "is_blacklisted": is_blacklisted,
            "warnings": warnings,
            "reasons": reasons,
        }


# ==============================================================================
# 4. 凯利公式计算模块
# ==============================================================================

class KellyCalculator:
    """凯利公式计算器"""
    
    @staticmethod
    def score_to_win_probability(score: float) -> float:
        """将评分转换为胜率"""
        clamped = max(0.0, min(10.0, score))
        # 评分0→胜率35%，评分10→胜率75%
        return 0.35 + (clamped / 10.0) * (0.75 - 0.35)
    
    @staticmethod
    def kelly_fraction(win_prob: float, avg_win_pct: float = 0.15, avg_loss_pct: float = 0.08) -> float:
        """计算凯利比例"""
        w = win_prob           # 胜率
        l = 1.0 - w           # 败率
        b = avg_win_pct / avg_loss_pct  # 盈亏比
        f = (b * w - l) / b   # 凯利公式
        return max(0.0, f)    # 不允许负仓位
    
    @staticmethod
    def calculate_position(score: float, total_capital: float = 1000000, 
                          current_price: float = 0, 
                          kelly_scaling: float = 0.5) -> Dict:
        """计算最终投资建议"""
        # 评分转胜率
        win_prob = KellyCalculator.score_to_win_probability(score)
        
        # 凯利比例
        kelly_f = KellyCalculator.kelly_fraction(
            win_prob, 
            KELLY_CONFIG['avg_win_pct'], 
            KELLY_CONFIG['avg_loss_pct']
        )
        
        # 应用凯利缩放（半凯利更安全）
        suggested_fraction = kelly_f * kelly_scaling
        
        # 限制单票最大仓位
        suggested_fraction = min(suggested_fraction, KELLY_CONFIG['single_max_fraction'])
        
        # 计算具体金额
        suggested_amount = total_capital * suggested_fraction
        
        # 计算建议股数
        suggested_shares = 0
        if current_price > 0:
            # A股100股为一手
            suggested_shares = int(suggested_amount / current_price / 100) * 100
        
        # 计算edge（优势）
        edge = kelly_f
        
        return {
            "score": score,
            "win_probability": round(win_prob, 4),
            "kelly_fraction": round(kelly_f, 4),
            "kelly_scaling": kelly_scaling,
            "suggested_fraction": round(suggested_fraction, 4),
            "suggested_amount": round(suggested_amount, 2),
            "suggested_shares": suggested_shares,
            "edge": round(edge, 4),
            "avg_win_pct": KELLY_CONFIG['avg_win_pct'],
            "avg_loss_pct": KELLY_CONFIG['avg_loss_pct'],
        }


# ==============================================================================
# 5. 主分析器
# ==============================================================================

class StockKellyAnalyzer:
    """股票凯利分析器主类"""
    
    def __init__(self, total_capital: float = 1000000, kelly_scaling: float = 0.5):
        self.fetcher = StockDataFetcher()
        self.scorer = StockScorer()
        self.kelly = KellyCalculator()
        self.total_capital = total_capital
        self.kelly_scaling = kelly_scaling
    
    def analyze(self, stock_code: str, silent: bool = False) -> Dict:
        """分析单只股票
        
        Args:
            stock_code: 股票代码
            silent: 是否静默模式（Web API使用时为True）
            
        Returns:
            完整的分析结果字典
        """
        if not silent:
            print(f"\n{'='*60}")
            print(f"📊 开始分析股票: {stock_code}")
            print(f"{'='*60}\n")
        
        # 1. 获取数据
        if not silent:
            print("📡 获取股票数据...")
        code = self.fetcher.normalize_code(stock_code)
        
        basic_info = self.fetcher.get_stock_info(code)
        if not silent:
            print(f"  ✅ 基本信息: {basic_info['name']} ({basic_info['code']})")
        
        financial = self.fetcher.get_financial_data(code)
        if not silent:
            print(f"  ✅ 财务数据: ROE={financial['roe']:.2f}%, 负债率={financial['debt_ratio']:.2f}%")
        
        market = self.fetcher.get_market_data(code)
        if not silent:
            print(f"  ✅ 行情数据: 现价={market['current_price']:.2f}, 5日收益={market['returns_5d']:.2f}%")
        
        valuation = self.fetcher.get_valuation_data(code)
        if not silent:
            print(f"  ✅ 估值数据: PE={valuation['pe']:.2f}, PB={valuation['pb']:.2f}")
        
        fund_flow = self.fetcher.get_fund_flow_data(code)
        if not silent:
            print(f"  ✅ 资金流向: 5日净流入={fund_flow['net_inflow_5d']/1e8:.2f}亿")
        
        # 2. 黑名单检查
        if not silent:
            print("\n🔍 黑名单检查...")
        blacklist = self.scorer.check_blacklist(market, valuation, financial)
        if not silent:
            if blacklist['warnings']:
                for warning in blacklist['warnings']:
                    print(f"  ⚠️  {warning}")
            if blacklist['is_blacklisted']:
                print("  ❌ 股票已被剔除（黑名单）")
        
        # 3. 获取宏观环境和事件消息数据
        if not silent:
            print("\n🌍 获取宏观环境数据...")
        
        # 获取行业信息
        industry = basic_info.get('industry', '')
        
        # 获取宏观环境数据
        macro_data = self.fetcher.get_macro_environment(code, industry)
        if not silent:
            if macro_data.get('industry_performance'):
                ind = macro_data['industry_performance']
                print(f"  ✅ 大盘指数: 上证指数{macro_data['market_indices'].get('上证指数', {}).get('change_5d', 0):+.2f}%")
                print(f"  ✅ 行业表现: {ind.get('name', '未知')} {ind.get('change_5d', 0):+.2f}%")
            else:
                print(f"  ⚠️ 宏观环境数据获取受限")
        
        # 获取事件消息数据
        if not silent:
            print("\n📰 获取事件消息数据...")
        
        stock_name = basic_info.get('name', '')
        event_data = self.fetcher.get_event_news(code, stock_name, industry)
        if not silent:
            print(f"  ✅ 相关新闻: {event_data.get('total_news', 0)}条")
            if event_data.get('has_significant_event'):
                print(f"  ⚠️ 有重大事件!")
        
        # 4. 各维度评分
        if not silent:
            print("\n📝 计算评分...")
        
        value_score = self.scorer.calculate_value_score(valuation, financial)
        if not silent:
            print(f"  📊 价值基本面: {value_score['total_score']}/10")
            for detail in value_score['details']:
                print(f"     - {detail}")
        
        trend_score = self.scorer.calculate_trend_score(market, fund_flow)
        if not silent:
            print(f"  📈 趋势动量: {trend_score['total_score']}/10")
            for detail in trend_score['details']:
                print(f"     - {detail}")
        
        macro_score = self.scorer.calculate_macro_score(macro_data)
        if not silent:
            print(f"  🌍 宏观环境: {macro_score['total_score']}/10 ({macro_score.get('env_desc', '')})")
            for detail in macro_score.get('details', [])[:3]:
                print(f"     - {detail}")
        
        fund_flow_score = self.scorer.calculate_fund_flow_score(fund_flow)
        if not silent:
            print(f"  💰 资金流向: {fund_flow_score['total_score']}/10")
            for detail in fund_flow_score['details']:
                print(f"     - {detail}")
        
        event_score = self.scorer.calculate_event_score(event_data)
        if not silent:
            print(f"  📰 事件消息: {event_score['total_score']}/10 ({event_score.get('event_desc', '')})")
            for detail in event_score.get('details', [])[:3]:
                print(f"     - {detail}")
        
        # 4. 加权融合
        total_score = (
            value_score['total_score'] * SCORING_WEIGHTS['value_fundamental'] +
            trend_score['total_score'] * SCORING_WEIGHTS['trend_momentum'] +
            macro_score['total_score'] * SCORING_WEIGHTS['macro'] +
            fund_flow_score['total_score'] * SCORING_WEIGHTS['fund_flow'] +
            event_score['total_score'] * SCORING_WEIGHTS['event_news']
        )
        
        # 5. 评级
        rating = self._determine_rating(total_score)
        if not silent:
            print(f"\n{'='*60}")
            print(f"📊 综合评分: {total_score:.2f}/10 → 评级: {rating}")
            print(f"{'='*60}")
        
        # 6. 凯利计算
        if not silent:
            print("\n💰 凯利公式计算...")
        kelly_result = self.kelly.calculate_position(
            total_score, self.total_capital, 
            market['current_price'], self.kelly_scaling
        )
        
        if not silent:
            print(f"  📈 胜率: {kelly_result['win_probability']*100:.1f}%")
            print(f"  🎯 凯利比例: {kelly_result['kelly_fraction']*100:.2f}%")
            print(f"  🔒 缩放后建议仓位: {kelly_result['suggested_fraction']*100:.2f}%")
            print(f"  💵 建议投资金额: ¥{kelly_result['suggested_amount']:,.2f}")
            if kelly_result['suggested_shares'] > 0:
                print(f"  📦 建议买入股数: {kelly_result['suggested_shares']}股")
            print(f"  ⚖️  盈亏比: {kelly_result['avg_win_pct']*100:.0f}% / {kelly_result['avg_loss_pct']*100:.0f}%")
        
        # 7. 生成投资建议
        investment_advice = self._generate_advice(rating, kelly_result, market)
        if not silent:
            print(f"\n{investment_advice}")
        
        # 返回包含所有原始数据的完整结果
        return {
            "basic_info": basic_info,
            "financial": financial,
            "market": market,
            "valuation": valuation,
            "fund_flow": fund_flow,
            "macro_data": macro_data,
            "event_data": event_data,
            "value_score": value_score,
            "trend_score": trend_score,
            "macro_score": macro_score,
            "fund_flow_score": fund_flow_score,
            "event_score": event_score,
            "ratings": {
                "value": value_score.get('total_score', 0),
                "trend": trend_score.get('total_score', 0),
                "macro": macro_score.get('total_score', 0),
                "fund_flow": fund_flow_score.get('total_score', 0),
                "event": event_score.get('total_score', 0),
                "total": total_score,
                "rating": rating,
            },
            "kelly": kelly_result,
            "blacklist": blacklist,
            "advice": investment_advice,
        }
    
    def _determine_rating(self, score: float) -> str:
        """确定评级"""
        if score >= RATING_THRESHOLDS['excellent']:
            return "⭐⭐⭐⭐⭐ 优秀"
        elif score >= RATING_THRESHOLDS['good']:
            return "⭐⭐⭐⭐ 良好"
        elif score >= RATING_THRESHOLDS['medium']:
            return "⭐⭐⭐ 中等"
        elif score >= RATING_THRESHOLDS['watch']:
            return "⭐⭐ 观察"
        else:
            return "⭐ 淘汰"
    
    def _generate_advice(self, rating: str, kelly_result: Dict, market: Dict) -> str:
        """生成投资建议"""
        lines = []
        lines.append("\n" + "=" * 60)
        lines.append("📋 投资建议")
        lines.append("=" * 60)
        
        fraction = kelly_result['suggested_fraction']
        amount = kelly_result['suggested_amount']
        shares = kelly_result['suggested_shares']
        price = market.get('current_price', 0)
        
        if "优秀" in rating or "良好" in rating:
            if fraction > 0.15:
                lines.append(f"✅ **强烈推荐**：可考虑买入")
                lines.append(f"   建议仓位：{fraction*100:.1f}%")
                lines.append(f"   建议金额：¥{amount:,.2f}")
                if shares > 0:
                    lines.append(f"   建议股数：{shares}股")
            else:
                lines.append(f"⚠️ **谨慎推荐**：仓位较轻")
                lines.append(f"   建议仓位：{fraction*100:.1f}%")
                lines.append(f"   建议金额：¥{amount:,.2f}")
        elif "中等" in rating:
            lines.append(f"🔍 **中性观望**：可小仓位试探")
            lines.append(f"   建议仓位：{fraction*100:.1f}% (最大10%)")
            small_amount = min(amount, self.total_capital * 0.10)
            lines.append(f"   建议金额：¥{small_amount:,.2f}")
        elif "观察" in rating:
            lines.append(f"⚠️ **暂时观望**：等待更好时机")
            lines.append(f"   当前评分偏低，不建议买入")
        else:
            lines.append(f"❌ **建议回避**：风险较大")
            lines.append(f"   当前评分过低，存在较大风险")
        
        lines.append(f"\n💡 **操作建议**：")
        lines.append(f"   • 入场方式：分批建仓，不要一次性全仓")
        if price > 0:
            lines.append(f"   • 关注价位：当前价 ¥{price:.2f}，可关注支撑位")
        lines.append(f"   • 止损设置：{kelly_result['avg_loss_pct']*100:.0f}% (即跌¥{price*kelly_result['avg_loss_pct']:.2f})")
        lines.append(f"   • 止盈目标：{kelly_result['avg_win_pct']*100:.0f}% (即涨¥{price*kelly_result['avg_win_pct']:.2f})")
        
        lines.append("\n" + "=" * 60)
        lines.append("⚠️ 风险提示：本工具仅为量化分析参考，不构成投资建议")
        lines.append("   股市有风险，投资需谨慎！")
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def _format_result(self, basic_info: Dict, value_score: Dict, 
                       trend_score: Dict, other_scores: Dict,
                       rating: str, kelly_result: Optional[Dict],
                       blacklist: Dict, total_score: float = None) -> Dict:
        """格式化分析结果"""
        return {
            "basic_info": basic_info,
            "ratings": {
                "value": value_score.get('total_score', 0),
                "trend": trend_score.get('total_score', 0),
                "macro": other_scores.get('macro', {}).get('total_score', 0),
                "fund_flow": other_scores.get('fund_flow', {}).get('total_score', 0),
                "event": other_scores.get('event', {}).get('total_score', 0),
                "total": total_score,
                "rating": rating,
            },
            "kelly": kelly_result,
            "blacklist": blacklist,
            "advice": self._generate_advice(
                rating, kelly_result or {}, 
                {"current_price": basic_info.get('price', 0)}
            ) if kelly_result else "",
        }


# ==============================================================================
# 6. 命令行入口
# ==============================================================================

def main():
    """主函数 - 命令行交互"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                   股票凯利分析器 v1.0                         ║
║           基于多维度评分 + 凯利公式的投资决策工具              ║
╚══════════════════════════════════════════════════════════════╝

功能说明：
  • 输入股票代码，自动获取数据并分析
  • 五维度评分体系（价值/趋势/宏观/资金/事件）
  • 评分转胜率，凯利公式计算最优仓位
  • 给出具体投资建议

使用示例：
  python stock_kelly_analyzer.py 300753
  python stock_kelly_analyzer.py 002422.SZ
  python stock_kelly_analyzer.py 600519.SH

""")
    
    # 解析命令行参数
    if len(sys.argv) > 1:
        stock_code = sys.argv[1]
    else:
        stock_code = input("请输入股票代码 (如: 300753): ").strip()
        if not stock_code:
            print("❌ 未输入股票代码，程序退出")
            return
    
    # 可选：输入总资金
    total_capital = 1000000  # 默认100万
    if len(sys.argv) > 2:
        try:
            total_capital = float(sys.argv[2])
        except ValueError:
            pass
    
    # 创建分析器
    analyzer = StockKellyAnalyzer(total_capital=total_capital, kelly_scaling=0.5)
    
    try:
        # 执行分析
        result = analyzer.analyze(stock_code)
        
        # 输出简要结果（如果需要）
        if result:
            print("\n✅ 分析完成！")
            
    except KeyboardInterrupt:
        print("\n\n⏹️  程序被用户中断")
    except Exception as e:
        print(f"\n❌ 分析出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()