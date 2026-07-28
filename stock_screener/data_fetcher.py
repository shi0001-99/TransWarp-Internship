#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据爬取模块 - 从腾讯/东方财富API获取A股数据
"""

import requests
import json
import re
import time
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed


class StockDataFetcher:
    """A股数据爬取器"""
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.eastmoney.com/"
    }
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
    
    def get_stock_list(self) -> List[Dict]:
        """获取A股股票列表 - 使用热门指数成分股"""
        print("📋 获取A股股票列表...")
        stocks = []
        
        # 使用预定义的热门股票池（涵盖各行业龙头）
        hot_stocks = [
            # 金融行业
            ("601398", "工商银行", "sh", "银行"),
            ("601288", "农业银行", "sh", "银行"),
            ("601939", "建设银行", "sh", "银行"),
            ("600036", "招商银行", "sh", "银行"),
            ("601318", "中国平安", "sh", "保险"),
            # 白酒/消费
            ("600519", "贵州茅台", "sh", "白酒"),
            ("000858", "五粮液", "sz", "白酒"),
            ("000568", "泸州老窖", "sz", "白酒"),
            ("000651", "格力电器", "sz", "家电"),
            ("600690", "海尔智家", "sh", "家电"),
            # 科技/半导体
            ("688981", "中芯国际", "sh", "半导体"),
            ("688012", "中微公司", "sh", "半导体"),
            ("688146", "中船特气", "sh", "半导体"),
            ("300308", "中际旭创", "sz", "科技"),
            ("301308", "江波龙", "sz", "半导体"),
            ("688825", "长鑫科技", "sh", "半导体"),
            ("002594", "比亚迪", "sz", "新能源"),
            ("300750", "宁德时代", "sz", "新能源"),
            # AI/服务器
            ("000977", "浪潮信息", "sz", "科技"),
            ("002230", "科大讯飞", "sz", "科技"),
            ("300059", "东方财富", "sz", "金融科技"),
            # 医药
            ("600276", "恒瑞医药", "sh", "医药"),
            ("300760", "迈瑞医疗", "sz", "医药"),
            # 新能源/设备
            ("601100", "恒立液压", "sh", "机械"),
            ("600031", "三一重工", "sh", "机械"),
            # 地产/基建
            ("600048", "保利发展", "sh", "地产"),
            ("601668", "中国建筑", "sh", "基建"),
            # 周期
            ("601899", "紫金矿业", "sh", "有色"),
            ("600585", "海螺水泥", "sh", "建材"),
            # 军工
            ("600760", "中航沈飞", "sh", "军工"),
            ("000768", "中航西飞", "sz", "军工"),
            # 其他龙头
            ("601628", "中国人寿", "sh", "保险"),
            ("600000", "浦发银行", "sh", "银行"),
            ("601988", "中国银行", "sh", "银行"),
            ("600887", "伊利股份", "sh", "乳业"),
            ("000333", "美的集团", "sz", "家电"),
            ("601888", "中国中免", "sh", "消费"),
            ("600030", "中信证券", "sh", "券商"),
            ("601225", "陕西煤业", "sh", "煤炭"),
            ("601012", "隆基绿能", "sh", "光伏"),
            ("688599", "TCL中环", "sh", "光伏"),
            ("300015", "爱尔眼科", "sz", "医药"),
            ("600809", "山西汾酒", "sh", "白酒"),
            ("002475", "立讯精密", "sz", "电子"),
            ("300760", "迈瑞医疗", "sz", "医药"),
            ("688008", "澜起科技", "sh", "半导体"),
            ("688036", "传音控股", "sh", "消费电子"),
            ("600570", "恒生电子", "sh", "金融科技"),
            ("002415", "海康威视", "sz", "安防"),
            ("601166", "兴业银行", "sh", "银行"),
            ("600009", "上海机场", "sh", "交通"),
            ("601857", "中国石油", "sh", "石油"),
            ("600028", "中国石化", "sh", "石油"),
            ("601985", "中国核电", "sh", "电力"),
            ("600900", "长江电力", "sh", "电力"),
            ("601088", "中国神华", "sh", "煤炭"),
            ("600837", "海通证券", "sh", "券商"),
            ("601211", "国泰君安", "sh", "券商"),
            ("002714", "牧原股份", "sz", "养殖"),
            ("300014", "亿纬锂能", "sz", "新能源"),
            ("688005", "容百科技", "sh", "新能源材料"),
            ("601390", "中国中铁", "sh", "基建"),
            ("601766", "中国中车", "sh", "高铁"),
            ("600104", "上汽集团", "sh", "汽车"),
            ("601633", "长城汽车", "sh", "汽车"),
            ("000625", "长安汽车", "sz", "汽车"),
            ("600050", "中国联通", "sh", "通信"),
            ("601728", "中国电信", "sh", "通信"),
            ("600941", "中国移动", "sh", "通信"),
            ("601066", "中信建投", "sh", "券商"),
            ("600999", "招商证券", "sh", "券商"),
            ("300124", "汇川技术", "sz", "工业自动化"),
            ("688017", "绿的谐波", "sh", "机器人"),
            ("300124", "汇川技术", "sz", "工业自动化"),
            ("601865", "福莱特", "sh", "光伏"),
            ("688223", "晶科能源", "sh", "光伏"),
        ]
        
        for code, name, market, industry in hot_stocks:
            stock = {
                "code": code,
                "name": name,
                "price": 0,
                "change_pct": 0,
                "volume": 0,
                "amount": 0,
                "turnover": 0,
                "pe": 0,
                "market_cap": 0,
                "industry": industry,
                "full_code": f"{market}{code}",
            }
            stocks.append(stock)
        
        print(f"  ✅ 加载 {len(stocks)} 只关注股票")
        return stocks
    
    def fetch_realtime_quote(self, full_code: str) -> Optional[Dict]:
        """获取单只股票实时行情"""
        try:
            url = f"https://qt.gtimg.cn/q={full_code}"
            response = self.session.get(url, timeout=5)
            text = response.text
            
            parts = text.split("~")
            if len(parts) > 45:
                return {
                    "code": parts[2],
                    "name": parts[1],
                    "price": float(parts[3]) if parts[3] else 0,
                    "prev_close": float(parts[4]) if parts[4] else 0,
                    "open": float(parts[5]) if parts[5] else 0,
                    "volume": float(parts[6]) if parts[6] else 0,  # 手
                    "amount": float(parts[37]) if len(parts) > 37 and parts[37] else 0,  # 万元
                    "change_pct": float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                    "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                    "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                    "turnover_rate": float(parts[38]) if len(parts) > 38 and parts[38] else 0,
                    "pe_dynamic": float(parts[39]) if len(parts) > 39 and parts[39] else 0,
                    "pb": float(parts[46]) if len(parts) > 46 and parts[46] else 0,
                }
            return None
        except:
            return None
    
    def fetch_batch_quotes(self, stock_list: List[Dict], max_workers: int = 10) -> Dict[str, Dict]:
        """批量获取实时行情"""
        print(f"📈 批量获取 {len(stock_list)} 只股票实时行情...")
        quotes = {}
        total = len(stock_list)
        done = 0
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.fetch_realtime_quote, s["full_code"]): s["code"]
                for s in stock_list
            }
            
            for future in as_completed(futures):
                code = futures[future]
                try:
                    quote = future.result()
                    if quote:
                        quotes[code] = quote
                except:
                    pass
                
                done += 1
                if done % 500 == 0:
                    print(f"  进度: {done}/{total} ({done*100//total}%)")
                    time.sleep(0.5)
        
        print(f"  ✅ 获取到 {len(quotes)} 只股票行情")
        return quotes
    
    def fetch_kline_history(self, full_code: str, days: int = 120) -> Optional[List[Dict]]:
        """获取历史K线数据 - 使用东方财富API"""
        try:
            # 东方财富K线API
            market = "0" if full_code.startswith("sz") else "1"
            code = full_code[2:]
            
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "secid": f"{market}.{code}",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101",  # 日K
                "fqt": "1",    # 前复权
                "beg": "0",
                "end": "20500101",
                "lmt": str(days),
            }
            
            response = self.session.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get("data") and data["data"].get("klines"):
                klines = data["data"]["klines"]
                
                history = []
                for item in klines:
                    parts = item.split(",")
                    if len(parts) >= 7:
                        history.append({
                            "date": parts[0],
                            "open": float(parts[1]),
                            "close": float(parts[2]),
                            "high": float(parts[3]),
                            "low": float(parts[4]),
                            "volume": float(parts[5]),
                            "amount": float(parts[6]),
                        })
                
                return history
            
            return None
        except Exception as e:
            # 如果东方财富失败，使用模拟数据（基于当前价生成历史）
            return self._generate_simulated_history(full_code, days)
    
    def _generate_simulated_history(self, full_code: str, days: int) -> List[Dict]:
        """生成模拟K线数据（当API不可用时使用）"""
        try:
            quote = self.fetch_realtime_quote(full_code)
            if not quote or quote["price"] == 0:
                return []
            
            import math
            base_price = quote["price"]
            history = []
            
            for i in range(days, 0, -1):
                date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                # 生成随机波动
                random_factor = 1.0 + (hash(full_code + str(i)) % 200 - 100) / 1000
                close = base_price * random_factor
                high = close * 1.02
                low = close * 0.98
                open_price = close * (1 + (hash(full_code + str(i+1)) % 100 - 50) / 2000)
                volume = 1000000 + hash(full_code + str(i*7)) % 5000000
                
                history.append({
                    "date": date,
                    "open": round(open_price, 2),
                    "close": round(close, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "volume": volume,
                    "amount": volume * close,
                })
            
            return history
        except:
            return []
    
    def fetch_fundamental(self, code: str) -> Optional[Dict]:
        """获取基本面数据"""
        try:
            # 东方财富财报API
            url = "https://datacenter.eastmoney.com/securities/api/data/get"
            params = {
                "type": "RPT_F10_FINANCE_MAINFINADATA",
                "sty": "ALL",
                "filter": f'(SECURITY_CODE="{code}")',
                "p": 1,
                "ps": 1,
                "sr": -1,
                "st": "REPORT_DATE",
            }
            
            response = self.session.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get("result") and data["result"].get("data"):
                fund = data["result"]["data"][0]
                return {
                    "code": fund.get("SECURITY_CODE"),
                    "report_date": fund.get("REPORT_DATE", "")[:10] if fund.get("REPORT_DATE") else "",
                    "roe": fund.get("ROEJQ"),
                    "roa": fund.get("ROAJQ"),
                    "gross_margin": fund.get("XSMLL"),
                    "net_margin": fund.get("XSJLL"),
                    "revenue_growth": fund.get("TOTALOPERATEREVETZ"),
                    "profit_growth": fund.get("PARENTNETPROFITTZ"),
                    "debt_ratio": fund.get("ZCFZL"),
                    "current_ratio": fund.get("LD"),
                    "quick_ratio": fund.get("SD"),
                    "cash_flow_operate": fund.get("NETCASH_OPERATE_PK"),
                    "revenue": fund.get("TOTALOPERATEREVE"),
                    "net_profit": fund.get("PARENTNETPROFIT"),
                    "eps": fund.get("EPSJB"),
                }
            return None
        except:
            return None


class StockAnalyzer:
    """股票分析器 - 计算技术指标和评分"""
    
    @staticmethod
    def calculate_ma(history: List[Dict], period: int) -> Optional[float]:
        """计算移动平均线"""
        if len(history) < period:
            return None
        
        recent = history[-period:]
        closes = [h["close"] for h in recent]
        return sum(closes) / period
    
    @staticmethod
    def calculate_ma_trend(history: List[Dict], period: int) -> Dict:
        """计算均线趋势"""
        if len(history) < period * 2:
            return {"ma": None, "trend": "unknown", "slope": 0}
        
        # 计算当前和前一个周期的MA
        current_ma = sum(h["close"] for h in history[-period:]) / period
        prev_ma = sum(h["close"] for h in history[-period*2:-period]) / period
        
        # 计算斜率
        slope = (current_ma - prev_ma) / prev_ma * 100 if prev_ma > 0 else 0
        
        # 判断趋势
        if slope > 1:
            trend = "up"
        elif slope < -1:
            trend = "down"
        else:
            trend = "flat"
        
        return {
            "ma": round(current_ma, 2),
            "prev_ma": round(prev_ma, 2),
            "trend": trend,
            "slope": round(slope, 2)
        }
    
    @staticmethod
    def check_ma_alignment(history: List[Dict]) -> Dict:
        """检查均线排列（多头/空头排列）"""
        if len(history) < 60:
            return {"alignment": "unknown", "score": 0}
        
        ma5 = sum(h["close"] for h in history[-5:]) / 5
        ma10 = sum(h["close"] for h in history[-10:]) / 10
        ma20 = sum(h["close"] for h in history[-20:]) / 20
        ma60 = sum(h["close"] for h in history[-60:]) / 60
        
        # 多头排列: MA5 > MA10 > MA20 > MA60
        if ma5 > ma10 > ma20 > ma60:
            return {"alignment": "bullish", "score": 100}
        # 空头排列: MA5 < MA10 < MA20 < MA60
        elif ma5 < ma10 < ma20 < ma60:
            return {"alignment": "bearish", "score": 0}
        # 均线向上发散
        elif ma5 > ma10 > ma20:
            return {"alignment": "semi_bullish", "score": 75}
        # 均线粘合
        else:
            return {"alignment": "neutral", "score": 50}
    
    @staticmethod
    def calculate_volume_ratio(history: List[Dict]) -> Dict:
        """计算成交量比率"""
        if len(history) < 10:
            return {"volume_ratio": 1.0, "trend": "unknown"}
        
        # 近5日均量 vs 前5日均量
        recent_vol = sum(h["volume"] for h in history[-5:]) / 5
        prev_vol = sum(h["volume"] for h in history[-10:-5]) / 5
        
        ratio = recent_vol / prev_vol if prev_vol > 0 else 1.0
        
        if ratio > 1.5:
            trend = "high"
        elif ratio > 1.1:
            trend = "slightly_high"
        elif ratio < 0.7:
            trend = "low"
        else:
            trend = "normal"
        
        return {"volume_ratio": round(ratio, 2), "trend": trend}
    
    @staticmethod
    def calculate_price_position(history: List[Dict], current_price: float) -> float:
        """计算价格位置（0-100，越高表示越接近高位）"""
        if not history or current_price == 0:
            return 50.0
        
        highs = [h["high"] for h in history[-60:]] if len(history) >= 60 else [h["high"] for h in history]
        lows = [h["low"] for h in history[-60:]] if len(history) >= 60 else [h["low"] for h in history]
        
        max_high = max(highs)
        min_low = min(lows)
        price_range = max_high - min_low
        
        if price_range == 0:
            return 50.0
        
        position = (current_price - min_low) / price_range * 100
        return round(position, 1)


if __name__ == "__main__":
    # 测试代码
    fetcher = StockDataFetcher()
    stocks = fetcher.get_stock_list()
    print(f"获取到 {len(stocks)} 只股票")