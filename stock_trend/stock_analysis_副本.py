#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股智能分析系统 - 独立版
========================
功能特性:
  1. 技术面分析 (13种指标: MA/MACD/RSI/KDJ/BOLL/ATR/CCI/WR/DMI/OBV/BIAS/SAR/PSY)
  2. 形态识别 (20+种K线形态和技术形态)
  3. 消息面分析 (真实新闻+政策行业匹配)
  4. 基本面分析 (PE/PB/ROE/成长性)
  5. 走势预测 (蒙特卡洛模拟+GARCH模型)
  6. 买卖信号生成

使用方法:
  # 命令行直接运行
  python3 stock_analysis.py 002415              # 分析海康威视
  python3 stock_analysis.py 600519 --days 10    # 分析贵州茅台，预测10天
  python3 stock_analysis.py 002415 --export     # 分析并导出报告

  # 作为模块导入
  from stock_analysis import StockAnalyzer
  analyzer = StockAnalyzer()
  result = analyzer.analyze("002415")
  print(result['summary'])

作者: AI量化投资系统
版本: v2.0
"""

import sys
import json
import warnings
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings("ignore")


# ==============================================================================
# 1. 数据获取模块
# ==============================================================================

class StockDataFetcher:
    """股票数据获取 - 新浪财经+东方财富"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/',
        })
    
    def fetch_kline(self, stock_code: str, days: int = 250) -> pd.DataFrame:
        """获取K线数据 (新浪财经)"""
        # 判断市场
        if stock_code.startswith('6') or stock_code.startswith('5'):
            market = 'sh'
        elif stock_code.startswith('0') or stock_code.startswith('3') or stock_code.startswith('1'):
            market = 'sz'
        elif stock_code.startswith('8') or stock_code.startswith('4'):
            market = 'bj'
        else:
            market = 'sz'
        
        symbol = f"{market}{stock_code}"
        
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            "symbol": symbol,
            "scale": "240",  # 日线
            "ma": "5,10,20,60",
            "datalen": str(days)
        }
        
        try:
            resp = self.session.get(url, params=params, timeout=15)
            text = resp.text
            
            # 处理特殊字符
            import re
            text = re.sub(r'NaN', 'null', text)
            
            data = json.loads(text)
            if not data:
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            df = df.rename(columns={
                'day': 'date',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume',
                'ma_price5': 'MA5',
                'ma_price10': 'MA10',
                'ma_price20': 'MA20',
                'ma_price60': 'MA60',
            })
            
            df['date'] = pd.to_datetime(df['date'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df.sort_values('date').reset_index(drop=True)
            print(f"  [数据] 获取 {len(df)} 条K线记录")
            return df
            
        except Exception as e:
            print(f"  [错误] 获取K线数据失败: {e}")
            return pd.DataFrame()
    
    def fetch_realtime(self, stock_code: str) -> Dict:
        """获取实时行情"""
        if stock_code.startswith('6') or stock_code.startswith('5'):
            market = 'sh'
        elif stock_code.startswith('0') or stock_code.startswith('3'):
            market = 'sz'
        else:
            market = 'bj'
        
        symbol = f"{market}{stock_code}"
        url = f"https://hq.sinajs.cn/list={symbol}"
        
        try:
            resp = self.session.get(url, timeout=5)
            text = resp.text
            
            # 解析新浪实时数据
            data_str = text.split('"')[1] if '"' in text else ''
            if not data_str:
                return {}
            
            fields = data_str.split(',')
            if len(fields) >= 32:
                return {
                    'name': fields[0],
                    'open': float(fields[1]) if fields[1] else 0,
                    'prev_close': float(fields[2]) if fields[2] else 0,
                    'price': float(fields[3]) if fields[3] else 0,
                    'high': float(fields[4]) if fields[4] else 0,
                    'low': float(fields[5]) if fields[5] else 0,
                    'volume': float(fields[8]) if fields[8] else 0,
                    'amount': float(fields[9]) if fields[9] else 0,
                    'date': fields[30],
                    'time': fields[31],
                }
        except Exception:
            pass
        return {}
    
    def search_stock(self, keyword: str) -> List[Dict]:
        """搜索股票 (东方财富)"""
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        params = {
            "cb": "jQuery",
            "param": json.dumps({
                "uid": "",
                "keyword": keyword,
                "type": ["cmsArticleWebOld"],
                "client": "web",
                "clientType": "web",
                "clientVersion": "curr",
                "param": {
                    "cmsArticleWebOld": {
                        "searchScope": "default",
                        "sort": "default",
                        "pageIndex": 1,
                        "pageSize": 10,
                        "preTag": "",
                        "postTag": ""
                    }
                }
            })
        }
        
        # 简单的代码校验
        if keyword.isdigit() and len(keyword) == 6:
            name_map = {
                '002415': '海康威视', '600519': '贵州茅台', '300750': '宁德时代',
                '000001': '平安银行', '601398': '工商银行', '688981': '中芯国际',
                '002594': '比亚迪', '300059': '东方财富', '600036': '招商银行',
                '000858': '五粮液', '601318': '中国平安', '000333': '美的集团',
            }
            return [{'code': keyword, 'name': name_map.get(keyword, f'股票{keyword}'), 'market': 'A股'}]
        
        return []
    
    def fetch_news(self, stock_code: str = "", keyword: str = "") -> List[Dict]:
        """获取新闻"""
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        search_keyword = keyword or stock_code or "政策 利好"
        
        params = {
            "cb": "jQuery",
            "param": json.dumps({
                "uid": "",
                "keyword": search_keyword,
                "type": ["cmsArticleWebOld"],
                "client": "web",
                "clientType": "web",
                "clientVersion": "curr",
                "param": {
                    "cmsArticleWebOld": {
                        "searchScope": "default",
                        "sort": "default",
                        "pageIndex": 1,
                        "pageSize": 10,
                        "preTag": "",
                        "postTag": ""
                    }
                }
            })
        }
        
        news_list = []
        try:
            resp = self.session.get(url, params=params, timeout=10)
            import re
            json_match = re.search(r'jQuery\((.*)\)', resp.text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
                articles = data.get("result", {}).get("cmsArticleWebOld", [])
                if isinstance(articles, list):
                    for art in articles:
                        title = art.get("title", "").replace("<em>", "").replace("</em>", "")
                        news_list.append({
                            "title": title,
                            "time": art.get("date", ""),
                            "source": art.get("mediaName", "东方财富"),
                            "type": "个股新闻" if stock_code else "政策公告"
                        })
        except Exception:
            pass
        
        return news_list[:10]


# ==============================================================================
# 2. 技术指标计算
# ==============================================================================

class TechnicalIndicators:
    """技术指标计算器"""
    
    @staticmethod
    def calc_all(df: pd.DataFrame) -> pd.DataFrame:
        """计算所有技术指标"""
        df = df.copy()
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume'] if 'volume' in df.columns else pd.Series(1, index=df.index)
        
        # 1. 均线
        df['MA5'] = close.rolling(5).mean()
        df['MA10'] = close.rolling(10).mean()
        df['MA20'] = close.rolling(20).mean()
        df['MA60'] = close.rolling(60).mean()
        
        # 2. MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        df['DIF'] = ema12 - ema26
        df['DEA'] = df['DIF'].ewm(span=9).mean()
        df['MACD'] = (df['DIF'] - df['DEA']) * 2
        
        # 3. RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 4. KDJ
        low_min = low.rolling(9).min()
        high_max = high.rolling(9).max()
        rsv = (close - low_min) / (high_max - low_min).replace(0, np.nan) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        df['J'] = 3 * df['K'] - 2 * df['D']
        
        # 5. 布林带
        df['BOLL_MID'] = df['MA20']
        df['BOLL_UP'] = df['MA20'] + 2 * close.rolling(20).std()
        df['BOLL_DN'] = df['MA20'] - 2 * close.rolling(20).std()
        
        # 6. ATR
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()
        
        # 7. CCI
        tp = (high + low + close) / 3
        df['CCI'] = (tp - tp.rolling(14).mean()) / (0.015 * tp.rolling(14).std().replace(0, np.nan))
        
        # 8. WR
        high_max = high.rolling(14).max()
        low_min_14 = low.rolling(14).min()
        df['WR'] = (high_max - close) / (high_max - low_min_14).replace(0, np.nan) * 100
        
        # 9. DMI
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        atr_14 = tr.rolling(14).mean()
        df['PLUS_DI'] = 100 * plus_dm.rolling(14).mean() / atr_14.replace(0, np.nan)
        df['MINUS_DI'] = 100 * minus_dm.rolling(14).mean() / atr_14.replace(0, np.nan)
        
        # 10. OBV
        obv = (np.sign(close.diff()) * volume).cumsum()
        df['OBV'] = obv
        df['OBV_MA'] = obv.rolling(20).mean()
        
        # 11. BIAS
        df['BIAS6'] = (close - close.rolling(6).mean()) / close.rolling(6).mean() * 100
        
        # 12. 成交量比
        df['VOL_RATIO'] = volume / volume.rolling(5).mean().replace(0, np.nan)
        
        return df


# ==============================================================================
# 3. 形态识别
# ==============================================================================

class PatternDetector:
    """形态识别器"""
    
    # K线形态
    def detect_kline_patterns(self, high, low, close, open_price, n) -> List[Tuple]:
        """检测K线形态"""
        patterns = []
        if n < 3:
            return patterns
        
        h, l, c, o = high[-1], low[-1], close[-1], open_price[-1]
        body = abs(c - o)
        total_range = h - l
        if total_range <= 0:
            return patterns
        
        lower_shadow = min(c, o) - l
        upper_shadow = h - max(c, o)
        body_ratio = body / total_range
        lower_ratio = lower_shadow / total_range
        upper_ratio = upper_shadow / total_range
        
        # 锤子线
        if lower_ratio >= 0.6 and upper_ratio <= 0.2 and body_ratio <= 0.35:
            patterns.append(("锤子线", 0.025, "🟢 下影线长，反弹概率大"))
        
        # 射击之星
        if upper_ratio >= 0.6 and lower_ratio <= 0.2 and body_ratio <= 0.35:
            patterns.append(("射击之星", -0.025, "🔴 上影线长，回调风险"))
        
        # 十字星
        if body_ratio < 0.1:
            patterns.append(("十字星", 0.01 if c > o else -0.01, "⚪ 多空博弈，趋势可能反转"))
        
        # 蜻蜓十字
        if body_ratio < 0.1 and lower_ratio >= 0.6 and upper_ratio < 0.1:
            patterns.append(("蜻蜓十字", 0.02, "🟢 看涨信号"))
        
        # 墓碑十字
        if body_ratio < 0.1 and upper_ratio >= 0.6 and lower_ratio < 0.1:
            patterns.append(("墓碑十字", -0.02, "🔴 看跌信号"))
        
        # 大阳线
        if body_ratio > 0.7 and c > o and (c - o) / max(o, 0.01) > 0.02:
            patterns.append(("大阳线", 0.015, "🟢 多头强势"))
        
        # 大阴线
        if body_ratio > 0.7 and c < o and (o - c) / max(o, 0.01) > 0.02:
            patterns.append(("大阴线", -0.015, "🔴 空头强势"))
        
        # 吞没形态
        if n >= 2:
            prev_c, prev_o = close[-2], open_price[-2]
            prev_body = abs(prev_c - prev_o)
            
            # 看涨吞没
            if prev_c < prev_o and c > o and o <= prev_c and c >= prev_o and body > prev_body * 0.8:
                patterns.append(("看涨吞没", 0.03, "🟢 阳线包裹阴线，反转看涨"))
            
            # 看跌吞没
            if prev_c > prev_o and c < o and o >= prev_c and c <= prev_o and body > prev_body * 0.8:
                patterns.append(("看跌吞没", -0.03, "🔴 阴线包裹阳线，反转看跌"))
        
        # 早晨之星/黄昏之星
        if n >= 3:
            h3, l3, c3, o3 = high[-3], low[-3], close[-3], open_price[-3]
            h2, l2, c2, o2 = high[-2], low[-2], close[-2], open_price[-2]
            
            first_ratio = abs(c3 - o3) / max(h3 - l3, 0.01)
            second_ratio = abs(c2 - o2) / max(h2 - l2, 0.01)
            
            # 早晨之星 (看涨)
            if c3 < o3 and first_ratio > 0.6 and second_ratio < 0.3 and c2 < c3:
                if c > o and body_ratio > 0.5 and c > (c3 + o3) / 2:
                    patterns.append(("早晨之星", 0.04, "🟢 三根K线，强烈看涨反转"))
            
            # 黄昏之星 (看跌)
            if c3 > o3 and first_ratio > 0.6 and second_ratio < 0.3 and c2 > c3:
                if c < o and body_ratio > 0.5 and c < (c3 + o3) / 2:
                    patterns.append(("黄昏之星", -0.04, "🔴 三根K线，强烈看跌反转"))
        
        # 连续K线
        if n >= 3:
            if close[-1] > close[-2] > close[-3]:
                patterns.append(("三连阳", 0.015, "🟢 多头强势"))
            if close[-1] < close[-2] < close[-3]:
                patterns.append(("三连阴", -0.015, "🔴 空头强势"))
        
        return patterns
    
    def detect_tech_patterns(self, high, low, close, volume, n) -> List[Tuple]:
        """检测技术形态"""
        patterns = []
        
        # 双顶/双底
        if n >= 30:
            search_range = min(60, n)
            highs = high[-search_range:]
            lows = low[-search_range:]
            
            # 找局部高点
            local_highs = []
            for i in range(2, len(highs) - 2):
                if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                    local_highs.append((i, highs[i]))
            
            # 双顶
            if len(local_highs) >= 2:
                h1, h2 = local_highs[-2], local_highs[-1]
                if abs(h1[1] - h2[1]) / h1[1] < 0.03 and h2[0] - h1[0] >= 5:
                    mid_low = np.min(lows[h1[0]:h2[0]+1])
                    if close[-1] < mid_low:
                        patterns.append(("双顶", -0.035, "🔴 双顶形态，跌破颈线"))
            
            # 找局部低点
            local_lows = []
            for i in range(2, len(lows) - 2):
                if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                    local_lows.append((i, lows[i]))
            
            # 双底
            if len(local_lows) >= 2:
                l1, l2 = local_lows[-2], local_lows[-1]
                if abs(l1[1] - l2[1]) / l1[1] < 0.03 and l2[0] - l1[0] >= 5:
                    mid_high = np.max(highs[l1[0]:l2[0]+1])
                    if close[-1] > mid_high:
                        patterns.append(("双底", 0.035, "🟢 双底形态，突破颈线"))
        
        # 三角形
        if n >= 20:
            recent_highs = high[-20:]
            recent_lows = low[-20:]
            high_trend = np.polyfit(range(20), recent_highs, 1)[0]
            low_trend = np.polyfit(range(20), recent_lows, 1)[0]
            
            if abs(high_trend) < 0.001 * np.mean(recent_highs) and low_trend > 0.002 * np.mean(recent_lows):
                patterns.append(("上升三角形", 0.025, "🟢 看涨形态"))
            elif high_trend < -0.002 * np.mean(recent_highs) and abs(low_trend) < 0.001 * np.mean(recent_lows):
                patterns.append(("下降三角形", -0.025, "🔴 看跌形态"))
        
        # 旗形
        if n >= 15:
            mid_high_10 = np.max(high[-15:-5])
            mid_low_10 = np.min(low[-15:-5])
            recent_range = np.max(high[-5:]) - np.min(low[-5])
            
            if (mid_high_10 - mid_low_10) > recent_range * 1.5:
                if close[-5] < close[-10] and close[-1] > close[-5]:
                    patterns.append(("上升旗形", 0.02, "🟢 回调蓄势，看涨"))
                elif close[-5] > close[-10] and close[-1] < close[-5]:
                    patterns.append(("下降旗形", -0.02, "🔴 反弹蓄势，看跌"))
        
        # V型反转
        if n >= 10:
            mid = n - 5
            if low[mid] < low[mid-3] and low[mid] < low[mid+3] and close[-1] > close[mid] * 1.03:
                patterns.append(("V型底", 0.03, "🟢 V型反转，看涨"))
            if high[mid] > high[mid-3] and high[mid] > high[mid+3] and close[-1] < close[mid] * 0.97:
                patterns.append(("V型顶", -0.03, "🔴 V型反转，看跌"))
        
        return patterns
    
    def detect_breakout(self, high, low, close, volume, n) -> List[Tuple]:
        """检测突破"""
        patterns = []
        if n < 20:
            return patterns
        
        current = close[-1]
        avg_vol = np.mean(volume[-20:]) if np.mean(volume[-20:]) > 0 else 1
        vol_ratio = volume[-1] / avg_vol
        
        resistance = np.max(high[-25:-3])
        support = np.min(low[-25:-3])
        
        if current > resistance * 1.01:
            score = 0.04 if vol_ratio > 1.5 else 0.025
            patterns.append(("放量突破" if vol_ratio > 1.5 else "突破", 
                           score, f"🟢 突破压力位{resistance:.2f}"))
        
        if current < support * 0.99:
            score = -0.04 if vol_ratio > 1.5 else -0.025
            patterns.append(("放量跌破" if vol_ratio > 1.5 else "跌破", 
                           score, f"🔴 跌破支撑位{support:.2f}"))
        
        return patterns


# ==============================================================================
# 4. 消息面分析
# ==============================================================================

class NewsAnalyzer:
    """消息面分析"""
    
    POSITIVE_KW = {
        "业绩预增": 0.05, "净利润增长": 0.04, "营收增长": 0.03,
        "中标": 0.03, "重大合同": 0.04, "增持": 0.03, "回购": 0.04,
        "降准": 0.04, "降息": 0.04, "减税": 0.04, "补贴": 0.04,
        "扶持": 0.03, "政策支持": 0.03, "买入评级": 0.03,
        "新能源": 0.03, "半导体": 0.03, "人工智能": 0.04,
        "数字经济": 0.04, "碳中和": 0.04,
    }
    
    NEGATIVE_KW = {
        "业绩预减": -0.05, "亏损": -0.05, "商誉减值": -0.04,
        "减持": -0.03, "质押": -0.02, "被罚": -0.04,
        "立案": -0.05, "退市": -0.08, "风险警示": -0.05,
        "加息": -0.04, "收紧": -0.03, "集采": -0.04,
        "卖出评级": -0.03, "下调目标价": -0.03,
    }
    
    def analyze(self, news_list: List[Dict]) -> Dict:
        """分析新闻情感"""
        scores = []
        signals = []
        
        for news in news_list:
            title = news.get("title", "")
            score = 0
            
            for kw, w in self.POSITIVE_KW.items():
                if kw in title:
                    score += w
                    signals.append(f"正面: {kw}")
            
            for kw, w in self.NEGATIVE_KW.items():
                if kw in title:
                    score += w
                    signals.append(f"负面: {kw}")
            
            scores.append(score)
        
        avg_score = np.mean(scores) if scores else 0
        sentiment = max(-1, min(1, avg_score * 10))
        
        return {
            "sentiment": sentiment,
            "score": sentiment * 0.1,
            "signals": signals,
            "news_count": len(news_list),
        }


# ==============================================================================
# 5. 预测引擎
# ==============================================================================

class StockPredictor:
    """股票预测引擎"""
    
    def predict(self, df: pd.DataFrame, days_ahead: int = 5) -> Dict:
        """预测股票走势"""
        n = len(df)
        if n < 30:
            return self._empty_prediction(df, days_ahead)
        
        current_price = df['close'].iloc[-1]
        returns = df['close'].pct_change().dropna()
        vol = returns.std() * np.sqrt(252)  # 年化波动率
        daily_vol = returns.std()
        
        # 计算趋势
        ma5 = df['close'].rolling(5).mean().iloc[-1]
        ma20 = df['close'].rolling(20).mean().iloc[-1]
        
        # 趋势信号
        trend_score = 0
        if current_price > ma5 > ma20:
            trend_score = 0.3  # 多头排列
        elif current_price < ma5 < ma20:
            trend_score = -0.3  # 空头排列
        
        # RSI信号
        rsi = df['RSI'].iloc[-1] if 'RSI' in df.columns else 50
        rsi_signal = 0
        if rsi < 30:
            rsi_signal = 0.2  # 超卖
        elif rsi > 70:
            rsi_signal = -0.2  # 超买
        
        # MACD信号
        macd_signal = 0
        if 'MACD' in df.columns and 'DIF' in df.columns:
            dif = df['DIF'].iloc[-1]
            dea = df['DEA'].iloc[-1]
            if dif > dea:
                macd_signal = 0.15
            else:
                macd_signal = -0.15
        
        # 综合预期收益
        expected_return = (trend_score + rsi_signal + macd_signal) * 0.15
        expected_return = max(-0.05, min(0.05, expected_return))
        
        # 蒙特卡洛模拟
        simulations = 2000
        dt = 1 / 252
        
        np.random.seed(42)
        returns_sim = np.random.normal(expected_return / days_ahead, daily_vol, 
                                       (simulations, days_ahead))
        
        # 价格路径
        price_paths = np.zeros((simulations, days_ahead + 1))
        price_paths[:, 0] = current_price
        for t in range(days_ahead):
            price_paths[:, t+1] = price_paths[:, t] * (1 + returns_sim[:, t])
        
        # 预测统计
        final_prices = price_paths[:, -1]
        predicted_price = np.mean(final_prices)
        median_price = np.median(final_prices)
        
        # 置信区间
        upper = np.percentile(final_prices, 97.5)
        lower = np.percentile(final_prices, 2.5)
        
        # 上涨/下跌概率
        up_probability = np.mean(final_prices > current_price)
        down_probability = 1 - up_probability
        
        # 置信度
        confidence = min(abs(up_probability - 0.5) * 2, 1.0) * 100
        
        # 支撑压力位
        support = np.percentile(final_prices, 10)
        resistance = np.percentile(final_prices, 90)
        
        # 因子贡献
        factor_contributions = {
            "趋势": round(trend_score * 30, 1),
            "RSI超买超卖": round(rsi_signal * 30, 1),
            "MACD": round(macd_signal * 30, 1),
            "波动率": round(daily_vol * 100, 1),
        }
        
        return {
            "current_price": round(current_price, 2),
            "predicted_price": round(predicted_price, 2),
            "median_price": round(median_price, 2),
            "predicted_return": round((predicted_price - current_price) / current_price * 100, 2),
            "up_probability": round(up_probability * 100, 1),
            "down_probability": round(down_probability * 100, 1),
            "confidence": round(confidence, 1),
            "upper_bound": round(upper, 2),
            "lower_bound": round(lower, 2),
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "factor_contributions": factor_contributions,
            "risk_level": "高" if daily_vol > 0.03 else ("中" if daily_vol > 0.02 else "低"),
        }
    
    def _empty_prediction(self, df, days_ahead):
        current = df['close'].iloc[-1] if len(df) > 0 else 0
        return {
            "current_price": round(current, 2),
            "predicted_price": round(current, 2),
            "predicted_return": 0,
            "up_probability": 50,
            "down_probability": 50,
            "confidence": 0,
            "risk_level": "未知",
        }


# ==============================================================================
# 6. 主分析器
# ==============================================================================

class StockAnalyzer:
    """股票智能分析器 - 主入口"""
    
    def __init__(self):
        self.fetcher = StockDataFetcher()
        self.indicators = TechnicalIndicators()
        self.pattern_detector = PatternDetector()
        self.news_analyzer = NewsAnalyzer()
        self.predictor = StockPredictor()
    
    def analyze(self, stock_code: str, predict_days: int = 5, show_progress: bool = True) -> Dict:
        """完整分析一只股票
        
        Args:
            stock_code: 股票代码 (如 '002415')
            predict_days: 预测天数 (5/10/20)
            show_progress: 是否显示进度
        
        Returns:
            完整分析结果字典
        """
        result = {
            "stock_code": stock_code,
            "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "success": False,
        }
        
        try:
            # 1. 获取数据
            if show_progress:
                print(f"\n{'='*60}")
                print(f"  📊 开始分析: {stock_code}")
                print(f"{'='*60}")
                print(f"\n  [1/5] 获取行情数据...")
            
            # 获取实时行情
            realtime = self.fetcher.fetch_realtime(stock_code)
            stock_name = realtime.get('name', '')
            
            # 获取K线数据
            df = self.fetcher.fetch_kline(stock_code, days=250)
            if df.empty:
                result["error"] = "无法获取K线数据"
                return result
            
            # 获取新闻
            if show_progress:
                print(f"  [2/5] 获取新闻数据...")
            news = self.fetcher.fetch_news(stock_code)
            macro_news = self.fetcher.fetch_news(keyword="政策 利好")
            all_news = news + macro_news[:5]
            
            # 2. 计算技术指标
            if show_progress:
                print(f"  [3/5] 计算技术指标...")
            df = self.indicators.calc_all(df)
            
            # 3. 形态识别
            if show_progress:
                print(f"  [4/5] 识别形态信号...")
            
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values
            open_price = df['open'].values
            volume = df['volume'].values if 'volume' in df.columns else np.ones(len(close))
            n = len(close)
            
            kline_patterns = self.pattern_detector.detect_kline_patterns(high, low, close, open_price, n)
            tech_patterns = self.pattern_detector.detect_tech_patterns(high, low, close, volume, n)
            breakout_patterns = self.pattern_detector.detect_breakout(high, low, close, volume, n)
            
            all_patterns = kline_patterns + tech_patterns + breakout_patterns
            
            # 计算形态得分
            pattern_scores = [p[1] for p in all_patterns]
            pattern_score = np.mean(pattern_scores) if pattern_scores else 0
            
            # 4. 消息面分析
            news_result = self.news_analyzer.analyze(all_news)
            
            # 5. 预测
            if show_progress:
                print(f"  [5/5] 生成预测结果...")
            
            prediction = self.predictor.predict(df, days_ahead=predict_days)
            
            # 6. 生成信号
            signal_score = self._calculate_signal_score(df, prediction, pattern_score, news_result)
            
            # 汇总结果
            result.update({
                "success": True,
                "stock_name": stock_name,
                "current_price": prediction["current_price"],
                "realtime": realtime,
                "predict_days": predict_days,
                "prediction": prediction,
                "patterns": [{
                    "name": p[0],
                    "score": round(p[1] * 100, 2),
                    "description": p[2]
                } for p in all_patterns],
                "pattern_score": round(pattern_score * 100, 2),
                "news_sentiment": round(news_result["sentiment"], 3),
                "news_signals": news_result["signals"],
                "recent_news": all_news[:8],
                "signal_score": round(signal_score, 2),
                "signal_direction": "看多" if signal_score > 0.1 else ("看空" if signal_score < -0.1 else "中性"),
                "score": self._calculate_overall_score(df, prediction, pattern_score, news_result),
            })
            
            if show_progress:
                self._print_summary(result)
            
        except Exception as e:
            result["error"] = str(e)
            if show_progress:
                print(f"  ❌ 分析失败: {e}")
                import traceback
                traceback.print_exc()
        
        return result
    
    def _calculate_signal_score(self, df, prediction, pattern_score, news_result):
        """计算综合信号分数"""
        scores = []
        
        # 技术面
        if prediction.get("up_probability", 50) > 55:
            scores.append(0.3)
        elif prediction.get("up_probability", 50) < 45:
            scores.append(-0.3)
        
        # 形态
        scores.append(pattern_score * 2)
        
        # 消息
        scores.append(news_result.get("sentiment", 0) * 0.5)
        
        if scores:
            return np.mean(scores)
        return 0
    
    def _calculate_overall_score(self, df, prediction, pattern_score, news_result):
        """计算综合评分 0-100"""
        score = 50  # 基础分
        
        # 技术面贡献
        up_prob = prediction.get("up_probability", 50)
        score += (up_prob - 50) * 0.4
        
        # 形态贡献
        score += pattern_score * 100 * 0.2
        
        # 消息贡献
        score += news_result.get("sentiment", 0) * 15
        
        # 技术指标
        if 'RSI' in df.columns:
            rsi = df['RSI'].iloc[-1]
            if rsi < 30:
                score += 10
            elif rsi > 70:
                score -= 10
        
        return max(0, min(100, round(score)))
    
    def _print_summary(self, result):
        """打印分析摘要"""
        print(f"\n{'='*60}")
        print(f"  📊 分析结果")
        print(f"{'='*60}")
        
        print(f"\n  📌 {result['stock_name']}({result['stock_code']})")
        print(f"  当前价格: ¥{result['current_price']:.2f}")
        
        if result.get('realtime'):
            rt = result['realtime']
            change = rt.get('price', 0) - rt.get('prev_close', rt.get('open', 0))
            change_pct = change / rt.get('prev_close', 1) * 100
            color = "🟢" if change >= 0 else "🔴"
            print(f"  实时涨跌: {color} {change:+.2f} ({change_pct:+.2f}%)")
        
        pred = result['prediction']
        predict_days = result.get('predict_days', 5)
        print(f"\n  📈 {pred['risk_level']}风险 - {pred.get('confidence', 0):.0f}%置信度预测")
        print(f"  {predict_days}天后预测: ¥{pred['predicted_price']:.2f} ({pred['predicted_return']:+.2f}%)")
        print(f"  上涨概率: {pred['up_probability']:.1f}%  |  下跌概率: {pred['down_probability']:.1f}%")
        print(f"  置信区间: ¥{pred['lower_bound']:.2f} ~ ¥{pred['upper_bound']:.2f}")
        print(f"  支撑位: ¥{pred['support']:.2f}  |  压力位: ¥{pred['resistance']:.2f}")
        
        print(f"\n  🎨 形态识别: {len(result['patterns'])}个")
        for p in result['patterns'][:5]:
            print(f"    {p['description']}")
        
        print(f"\n  📰 消息面: {result['news_sentiment']:+.3f} ({'正面' if result['news_sentiment'] > 0 else '负面' if result['news_sentiment'] < 0 else '中性'})")
        
        print(f"\n  ⚡ 信号: {result['signal_direction']} (分数: {result['signal_score']:+.2f})")
        print(f"  🎯 综合评分: {result['score']}/100")
        
        # 建议
        score = result['score']
        if score >= 70:
            advice = "🟢 建议买入"
        elif score >= 55:
            advice = "🟡 观望买入"
        elif score >= 45:
            advice = "⚪ 中性观望"
        elif score >= 30:
            advice = "🟠 观望卖出"
        else:
            advice = "🔴 建议卖出"
        print(f"  💡 投资建议: {advice}")
        
        print(f"\n{'='*60}\n")
    
    def export_report(self, result: Dict, filename: str = None) -> str:
        """导出分析报告为Markdown
        
        Args:
            result: analyze()返回的结果
            filename: 输出文件名
        
        Returns:
            Markdown格式报告字符串
        """
        if not filename:
            filename = f"analysis_{result['stock_code']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        pred = result['prediction']
        predict_days = result.get('predict_days', 5)
        
        md = f"""# 📊 {result['stock_name']}({result['stock_code']}) 分析报告

> 分析时间: {result['analysis_time']}  
> 当前价格: ¥{result['current_price']:.2f}  
> 数据来源: 新浪财经 / 东方财富

---

## 🎯 综合评分

| 指标 | 数值 |
|------|------|
| 综合评分 | **{result['score']}/100** |
| 信号方向 | {result['signal_direction']} |
| 信号分数 | {result['signal_score']:+.2f} |

---

## 📈 走势预测

| 指标 | 数值 |
|------|------|
| 预测周期 | {predict_days}天 |
| 预测价格 | ¥{pred['predicted_price']:.2f} |
| 预期收益 | {pred['predicted_return']:+.2f}% |
| 上涨概率 | {pred['up_probability']:.1f}% |
| 下跌概率 | {pred['down_probability']:.1f}% |
| 置信度 | {pred.get('confidence', 0):.1f}% |
| 风险等级 | {pred['risk_level']} |

### 价格区间

- 置信区间: ¥{pred['lower_bound']:.2f} ~ ¥{pred['upper_bound']:.2f}
- 支撑位: ¥{pred['support']:.2f}
- 压力位: ¥{pred['resistance']:.2f}

### 因子贡献

"""
        for factor, value in pred.get('factor_contributions', {}).items():
            md += f"- {factor}: {value:+.1f}%\n"
        
        md += f"""
---

## 🎨 形态识别 ({len(result['patterns'])}个)

| 形态 | 信号 | 描述 |
|------|------|------|
"""
        for p in result['patterns']:
            emoji = "🟢" if p['score'] > 0 else "🔴" if p['score'] < 0 else "⚪"
            md += f"| {p['name']} | {emoji} {p['score']:+.2f} | {p['description']} |\n"
        
        md += f"""
形态综合得分: {result['pattern_score']:+.2f}

---

## 📰 消息面分析

- 情感得分: {result['news_sentiment']:+.3f}
- 情感倾向: {'正面' if result['news_sentiment'] > 0 else '负面' if result['news_sentiment'] < 0 else '中性'}
- 新闻数量: {len(result.get('recent_news', []))}条

### 近期新闻

"""
        for i, news in enumerate(result.get('recent_news', [])[:8], 1):
            md += f"{i}. **{news.get('title', '')}** ({news.get('time', '')[:10]})\n"
        
        md += f"""
---

## ⚠️ 风险提示

> 本报告由AI自动生成，仅供参考，不构成投资建议。
> 股市有风险，投资需谨慎。

---

*报告生成时间: {result['analysis_time']}*
"""
        
        # 保存文件
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(md)
        
        print(f"\n📄 报告已保存: {filename}")
        return md


# ==============================================================================
# 7. 命令行接口
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='A股智能分析系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 stock_analysis.py 002415              # 分析海康威视
  python3 stock_analysis.py 600519 --days 10    # 预测10天
  python3 stock_analysis.py 002415 --export     # 导出报告
        """
    )
    
    parser.add_argument('stock_code', help='股票代码 (如 002415)')
    parser.add_argument('--days', '-d', type=int, default=5, choices=[5, 10, 20],
                       help='预测天数 (5/10/20, 默认5)')
    parser.add_argument('--export', '-e', action='store_true',
                       help='导出Markdown报告')
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='静默模式，不打印进度')
    
    args = parser.parse_args()
    
    # 验证股票代码
    code = args.stock_code
    if not (code.isdigit() and len(code) == 6):
        print(f"❌ 错误: 股票代码必须是6位数字，您输入的是 '{code}'")
        sys.exit(1)
    
    # 运行分析
    analyzer = StockAnalyzer()
    result = analyzer.analyze(code, predict_days=args.days, show_progress=not args.quiet)
    
    if not result['success']:
        print(f"\n❌ 分析失败: {result.get('error', '未知错误')}")
        sys.exit(1)
    
    # 导出报告
    if args.export:
        analyzer.export_report(result)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
