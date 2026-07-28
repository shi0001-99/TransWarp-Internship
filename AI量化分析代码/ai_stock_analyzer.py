#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 股票分析系统 - 基于基本面过滤 + 多维度打分 + 凯利公式
数据来源: 腾讯行情API + 东方财富财报API
"""

import requests
import json
import math
import re
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

# ============================================================
# 配置常量
# ============================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 行业分类映射 (股票代码前缀 + 名称关键词)
INDUSTRY_MAP = {
    "银行": {
        "code_prefix": ["601", "600"],  # 上交所主板
        "keywords": ["银行", "bank", "建设", "农业", "工商", "招商", "交通", "浦发", "民生", "兴业", "光大", "华夏", "中信", "平安"],
        "full_code_keywords": ["sh601", "sh600"],
        "note": "银行业: 高杠杆、高资产负债率(90%+)是正常业务模式",
    },
    "保险": {
        "code_prefix": ["601", "600"],
        "keywords": ["保险", "人保", "平安", "太平洋", "人寿"],
        "full_code_keywords": ["sh601", "sh600"],
        "note": "保险业: 高负债模式，投资驱动",
    },
    "白酒": {
        "code_prefix": ["000", "600"],
        "keywords": ["白酒", "酒", "五粮", "茅台", "泸州", "汾酒", "古井", "洋河", "舍得", "水井坊"],
        "full_code_keywords": ["sz000", "sh600"],
        "note": "白酒行业: 高毛利、强品牌、现金流季节性波动",
    },
    "消费": {
        "code_prefix": ["000", "600", "300"],
        "keywords": ["消费", "食品", "饮料", "家电", "零售", "伊利", "蒙牛", "格力", "美的", "海尔", "康师傅"],
        "full_code_keywords": ["sz000", "sh600", "sz300"],
        "note": "消费行业: 现金流稳定，品牌壁垒重要",
    },
    "半导体": {
        "code_prefix": ["688", "300", "002"],
        "keywords": ["半导体", "芯片", "存储", "DRAM", "光刻", "中芯", "长鑫", "北方华创", "中船", "特气", "韦尔", "兆易", "紫光"],
        "full_code_keywords": ["sh688", "sz300", "sz002"],
        "note": "半导体行业: 高资本支出、周期性强、现金流波动大",
    },
    "科技": {
        "code_prefix": ["688", "300", "002", "600"],
        "keywords": ["科技", "AI", "人工智能", "软件", "云计算", "大数据", "宁德", "比亚迪", "光伏", "新能源"],
        "full_code_keywords": ["sh688", "sz300", "sz002"],
        "note": "科技行业: 高成长性、高研发投入、估值波动大",
    },
    "医药": {
        "code_prefix": ["600", "000", "300", "688"],
        "keywords": ["医药", "生物", "医疗", "恒瑞", "药明", "智飞", "迈瑞", "复星", "片仔"],
        "full_code_keywords": ["sh600", "sz000", "sz300", "sh688"],
        "note": "医药行业: 高研发投入、产品周期长",
    },
}

# 行业特定阈值 (覆盖默认值)
INDUSTRY_THRESHOLDS = {
    "银行": {
        "roe_min": 2.0,           # 银行ROE偏低(2-5%)是正常的
        "gross_margin_min": None,  # 银行无毛利率概念
        "net_margin_min": None,    # 银行净利率计算方式不同
        "debt_ratio_max": 95.0,   # 银行资产负债率通常90%+
        "current_ratio_min": None, # 银行流动比率参考意义不大
        "allow_negative_cashflow": True,  # 银行Q1现金流为负常见
        "pe_max": 30,             # 银行PE通常较低
    },
    "保险": {
        "roe_min": 3.0,
        "gross_margin_min": None,
        "net_margin_min": None,
        "debt_ratio_max": 90.0,   # 保险业负债高
        "current_ratio_min": None,
        "allow_negative_cashflow": True,
        "pe_max": 35,
    },
    "白酒": {
        "roe_min": 10.0,          # 白酒ROE应较高
        "gross_margin_min": 40.0, # 白酒毛利率应>40%
        "net_margin_min": 20.0,   # 白酒净利率应>20%
        "debt_ratio_max": 60.0,
        "current_ratio_min": 1.5,
        "allow_negative_cashflow": False,
        "pe_max": 40,
    },
    "消费": {
        "roe_min": 8.0,
        "gross_margin_min": 15.0,
        "net_margin_min": 5.0,
        "debt_ratio_max": 65.0,
        "current_ratio_min": 1.2,
        "allow_negative_cashflow": False,
        "pe_max": 50,
    },
    "半导体": {
        "roe_min": -5.0,          # 半导体允许ROE为负(研发期)
        "gross_margin_min": 0.0,  # 亏损期毛利率可能为负
        "net_margin_min": None,
        "debt_ratio_max": 60.0,
        "current_ratio_min": 1.0,
        "allow_negative_cashflow": True,  # 半导体Q1现金流为负常见(资本支出)
        "pe_max": 300,
    },
    "科技": {
        "roe_min": -2.0,
        "gross_margin_min": 5.0,
        "net_margin_min": None,
        "debt_ratio_max": 60.0,
        "current_ratio_min": 1.0,
        "allow_negative_cashflow": True,
        "pe_max": 200,
    },
    "医药": {
        "roe_min": 3.0,
        "gross_margin_min": 30.0,
        "net_margin_min": 5.0,
        "debt_ratio_max": 65.0,
        "current_ratio_min": 1.2,
        "allow_negative_cashflow": False,
        "pe_max": 80,
    },
}

# 基本面过滤默认阈值 (适用于大多数行业)
DEFAULT_FILTERS = {
    "roe_min": 5.0,           # ROE 最低要求 (%)
    "revenue_growth_min": -20,  # 营收同比最低 (%)
    "profit_growth_min": -30,   # 净利润同比最低 (%)
    "gross_margin_min": 10.0,   # 销售毛利率最低 (%)
    "net_margin_min": 3.0,      # 销售净利率最低 (%)
    "debt_ratio_max": 70.0,     # 资产负债率最高 (%)
    "current_ratio_min": 0.8,    # 流动比率最低
    "pe_min": 0.1,              # PE 最低 (排除负值)
    "pe_max": 500,              # PE 最高 (排除极端值)
    "allow_negative_cashflow": False,
}

# 保留向后兼容
FUNDAMENTAL_FILTERS = DEFAULT_FILTERS

# 打分权重
SCORE_WEIGHTS = {
    "valuation": 0.35,    # 估值分 (PE, PB)
    "price": 0.35,        # 价格分 (距52周高低点)
    "market": 0.30,       # 市场热度分 (换手率, 成交量)
}

# 凯利公式参数
KELLY_WIN_RATE_BASE = 0.50    # 基准胜率
KELLY_MAX_POSITION = 0.70     # 最高仓位 (70%)
KELLY_HALF_Kelly = True       # 使用半凯利 (更稳健)


# ============================================================
# 数据获取层
# ============================================================

class StockDataFetcher:
    """股票数据获取器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def search_stock(self, keyword: str) -> List[Dict]:
        """搜索股票 (按名称或代码)"""
        results = []

        # 尝试用代码直接查
        if re.match(r'^\d{6}$', keyword):
            market = "sh" if keyword.startswith(("6", "5")) else "sz"
            code = f"{market}{keyword}"
            try:
                data = self._fetch_tencent_quote(code)
                if data:
                    results.append({
                        "code": keyword,
                        "name": data["name"],
                        "market": market,
                        "full_code": code,
                    })
                    return results
            except Exception:
                pass

        # 用名称/拼音搜索
        try:
            url = f"https://smartbox.gtimg.cn/s3/?v=2&q={keyword}&t=all"
            resp = self.session.get(url, timeout=10)
            resp.encoding = "utf-8"
            text = resp.text

            # 解析 v_hint 格式
            matches = re.findall(
                r'([shsz])~(\d{6})~([^~]+?)~[a-zA-Z]+~(GP|ZS|HK)',
                text,
            )
            for m in matches:
                market, code, name, stype = m
                results.append({
                    "code": code,
                    "name": name.strip(),
                    "market": market,
                    "full_code": f"{market}{code}",
                    "type": stype,
                })
        except Exception as e:
            print(f"  [搜索异常] {e}")

        return results[:10]

    def _fetch_tencent_quote(self, full_code: str) -> Optional[Dict]:
        """获取腾讯实时行情"""
        try:
            url = f"https://qt.gtimg.cn/q={full_code}"
            resp = self.session.get(url, timeout=10)
            resp.encoding = "gbk"
            text = resp.text

            match = re.search(r'"([^"]+)"', text)
            if not match:
                return None

            parts = match.group(1).split("~")
            if len(parts) < 50:
                return None

            return {
                "name": parts[1].strip(),
                "code": parts[2],
                "price": self._to_float(parts[3]),
                "prev_close": self._to_float(parts[4]),
                "open": self._to_float(parts[5]),
                "volume": self._to_float(parts[6]),         # 手
                "turnover": self._to_float(parts[37]),      # 万元
                "turnover_rate": self._to_float(parts[38]), # %
                "pe_dynamic": self._to_float(parts[39]),
                "high": self._to_float(parts[33]),
                "low": self._to_float(parts[34]),
                "pb": self._to_float(parts[46]) if len(parts) > 46 else None,
                "change_pct": self._to_float(parts[32]) if len(parts) > 32 else None,
                "amount_wan": self._to_float(parts[37]),
                "timestamp": parts[30] if len(parts) > 30 else "",
            }
        except Exception as e:
            print(f"  [行情获取异常] {e}")
            return None

    def fetch_realtime_quote(self, full_code: str) -> Optional[Dict]:
        """获取实时行情 (公开接口)"""
        return self._fetch_tencent_quote(full_code)

    def fetch_fundamental(self, code: str) -> Optional[Dict]:
        """获取东方财富基本面数据"""
        # 确定市场代码
        if code.startswith(("6", "5")):
            secucode = f"{code}.SH"
        else:
            secucode = f"{code}.SZ"

        url = (
            "https://datacenter.eastmoney.com/securities/api/data/get"
            f"?type=RPT_F10_FINANCE_MAINFINADATA&sty=ALL"
            f"&filter=(SECUCODE%3D%22{secucode}%22)"
            "&p=1&ps=5&sr=-1&st=REPORT_DATE"
        )
        headers = {
            **HEADERS,
            "Referer": "https://emweb.securities.eastmoney.com/",
        }
        try:
            resp = self.session.get(url, headers=headers, timeout=15)
            data = resp.json()

            if not data.get("result") or not data["result"].get("data"):
                return None

            records = data["result"]["data"]
            if not records:
                return None

            # 最新一期数据
            latest = records[0]
            # 上一期数据 (用于同比计算验证)
            previous = records[1] if len(records) > 1 else {}

            return {
                "report_date": latest.get("REPORT_DATE", "")[:10],
                "report_type": latest.get("REPORT_DATE_NAME", ""),
                "eps": latest.get("EPSJB"),
                "bps": latest.get("BPS"),
                "roe": latest.get("ROEJQ"),
                "roa": latest.get("ZZCJLL"),
                "gross_margin": latest.get("XSMLL"),
                "net_margin": latest.get("XSJLL"),
                "revenue": latest.get("TOTALOPERATEREVE"),
                "net_profit": latest.get("PARENTNETPROFIT"),
                "revenue_growth": latest.get("TOTALOPERATEREVETZ"),
                "profit_growth": latest.get("PARENTNETPROFITTZ"),
                "net_profit_deducted": latest.get("KCFJCXSYJLR"),
                "cash_flow_ps": latest.get("MGJYXJJE"),
                "cash_flow_operate": latest.get("NETCASH_OPERATE_PK"),
                "total_assets": latest.get("TOTAL_ASSETS_PK"),
                "total_equity": latest.get("TOTAL_EQUITY_PK"),
                "debt_ratio": latest.get("ZCFZL"),
                "current_ratio": latest.get("LD"),
                "quick_ratio": latest.get("SD"),
                "inventory_turn": latest.get("ZZCZZTS"),
                "account_receivable_turn": latest.get("YSZKZZTS"),
                "previous_profit": previous.get("PARENTNETPROFIT") if previous else None,
            }
        except Exception as e:
            print(f"  [基本面获取异常] {e}")
            return None

    def fetch_history(self, full_code: str, days: int = 60) -> List[Dict]:
        """获取历史K线数据"""
        try:
            url = (
                f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                f"?param={full_code},day,,,{days},qfq"
            )
            resp = self.session.get(url, timeout=10)
            data = resp.json()

            stock_data = data.get("data", {}).get(full_code, {})
            days_data = stock_data.get("qfqday") or stock_data.get("day", [])

            history = []
            for d in days_data:
                history.append({
                    "date": d[0],
                    "open": self._to_float(d[1]),
                    "close": self._to_float(d[2]),
                    "high": self._to_float(d[3]),
                    "low": self._to_float(d[4]),
                    "volume": self._to_float(d[5]),
                })
            return history
        except Exception as e:
            print(f"  [历史数据获取异常] {e}")
            return []

    @staticmethod
    def _to_float(val) -> Optional[float]:
        """安全转换为浮点数"""
        if val is None or val == "" or val == "--":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None


# ============================================================
# 分析引擎
# ============================================================

class IndustryClassifier:
    """行业分类器 - 根据股票代码和名称识别行业类型"""

    @staticmethod
    def classify(code: str, name: str = "", full_code: str = "") -> Dict:
        """
        识别股票所属行业
        
        Args:
            code: 股票代码 (如 '601939')
            name: 股票名称 (如 '建设银行')
            full_code: 完整代码 (如 'sh601939')
            
        Returns:
            dict: {
                'industry': 行业名称,
                'confidence': 置信度 (0-1),
                'reason': 识别原因,
                'note': 行业说明,
                'thresholds': 适用的阈值配置
            }
        """
        # 1. 先通过名称关键词匹配 (最准确)
        if name:
            for industry, config in INDUSTRY_MAP.items():
                for keyword in config["keywords"]:
                    if keyword in name:
                        return {
                            "industry": industry,
                            "confidence": 0.95,
                            "reason": f"名称'{name}'匹配关键词'{keyword}'",
                            "note": config.get("note", ""),
                            "thresholds": INDUSTRY_THRESHOLDS.get(industry, DEFAULT_FILTERS),
                        }

        # 2. 通过完整代码前缀匹配
        if full_code:
            for industry, config in INDUSTRY_MAP.items():
                for prefix in config["full_code_keywords"]:
                    if full_code.startswith(prefix):
                        return {
                            "industry": industry,
                            "confidence": 0.6,
                            "reason": f"代码'{full_code}'匹配前缀'{prefix}'",
                            "note": config.get("note", ""),
                            "thresholds": INDUSTRY_THRESHOLDS.get(industry, DEFAULT_FILTERS),
                        }

        # 3. 通过代码前缀匹配
        if code:
            for industry, config in INDUSTRY_MAP.items():
                for prefix in config["code_prefix"]:
                    if code.startswith(prefix):
                        return {
                            "industry": industry,
                            "confidence": 0.5,
                            "reason": f"代码'{code}'匹配前缀'{prefix}'",
                            "note": config.get("note", ""),
                            "thresholds": INDUSTRY_THRESHOLDS.get(industry, DEFAULT_FILTERS),
                        }

        # 4. 无法识别, 返回默认
        return {
            "industry": "通用",
            "confidence": 0.0,
            "reason": "无法识别行业, 使用通用标准",
            "note": "",
            "thresholds": DEFAULT_FILTERS,
        }

    @staticmethod
    def get_thresholds(code: str, name: str = "", full_code: str = "") -> Dict:
        """获取行业适用的阈值"""
        result = IndustryClassifier.classify(code, name, full_code)
        thresholds = DEFAULT_FILTERS.copy()
        # 覆盖行业特定阈值
        for key, value in result["thresholds"].items():
            if value is not None:
                thresholds[key] = value
        return thresholds


class FundamentalFilter:
    """基本面过滤器 - 支持分行业差异化检查"""

    @staticmethod
    def check(fund: Dict, quote: Dict, industry: str = "通用", 
              thresholds: Dict = None) -> Tuple[bool, List[str], List[str]]:
        """
        检查基本面是否达标
        
        Args:
            fund: 基本面数据
            quote: 行情数据
            industry: 行业名称 (影响检查逻辑)
            thresholds: 行业特定阈值 (如果为空则使用默认)
            
        Returns:
            Tuple[bool, List[str], List[str]]: 
                - 是否通过
                - 未通过原因列表
                - 备注说明列表 (如行业特性说明)
        """
        reasons = []
        notes = []
        
        if fund is None:
            reasons.append("无法获取基本面数据")
            return False, reasons, notes

        # 获取当前适用的阈值
        if thresholds is None:
            thresholds = DEFAULT_FILTERS.copy()
        else:
            # 合并: 行业阈值覆盖默认值
            merged = DEFAULT_FILTERS.copy()
            for key, value in thresholds.items():
                if value is not None:
                    merged[key] = value
            thresholds = merged

        # ROE 检查 (None 表示跳过此项检查)
        roe_min = thresholds.get("roe_min")
        roe = fund.get("roe")
        if roe_min is not None and roe is not None and roe < roe_min:
            reasons.append(f"ROE({roe:.2f}%) 低于行业要求 {roe_min}%")

        # 营收增长
        rev_growth_min = thresholds.get("revenue_growth_min")
        rev_growth = fund.get("revenue_growth")
        if rev_growth_min is not None and rev_growth is not None and rev_growth < rev_growth_min:
            reasons.append(f"营收同比增长({rev_growth:.2f}%) 低于 {rev_growth_min}%")

        # 净利润增长
        profit_growth_min = thresholds.get("profit_growth_min")
        profit_growth = fund.get("profit_growth")
        if profit_growth_min is not None and profit_growth is not None and profit_growth < profit_growth_min:
            reasons.append(f"净利润同比增长({profit_growth:.2f}%) 低于 {profit_growth_min}%")

        # 毛利率 (None 表示跳过)
        gross_min = thresholds.get("gross_margin_min")
        gross = fund.get("gross_margin")
        if gross_min is not None and gross is not None and gross < gross_min:
            reasons.append(f"销售毛利率({gross:.2f}%) 低于行业要求 {gross_min}%")

        # 净利率 (None 表示跳过)
        net_min = thresholds.get("net_margin_min")
        net = fund.get("net_margin")
        if net_min is not None and net is not None and net < net_min:
            reasons.append(f"销售净利率({net:.2f}%) 低于行业要求 {net_min}%")

        # 资产负债率
        debt_max = thresholds.get("debt_ratio_max")
        debt = fund.get("debt_ratio")
        if debt_max is not None and debt is not None and debt > debt_max:
            reasons.append(f"资产负债率({debt:.2f}%) 高于行业标准 {debt_max}%")

        # 流动比率 (None 表示跳过)
        current_min = thresholds.get("current_ratio_min")
        current = fund.get("current_ratio")
        if current_min is not None and current is not None and current < current_min:
            reasons.append(f"流动比率({current:.2f}) 低于行业要求 {current_min}")

        # PE 检查
        pe_min = thresholds.get("pe_min", 0.1)
        pe_max = thresholds.get("pe_max", 500)
        pe = quote.get("pe_dynamic") if quote else None
        if pe is not None:
            if pe < pe_min:
                reasons.append(f"市盈率({pe:.2f}) 为负或过低, 可能亏损")
            elif pe > pe_max:
                reasons.append(f"市盈率({pe:.2f}) 高于行业标准 {pe_max}, 估值泡沫风险")

        # 经营现金流检查 (行业可豁免)
        allow_negative_cf = thresholds.get("allow_negative_cashflow", False)
        cash_flow = fund.get("cash_flow_operate")
        if cash_flow is not None and cash_flow < 0:
            if not allow_negative_cf:
                reasons.append(f"经营现金流净额为负({cash_flow/1e8:.2f}亿), 造血能力差")
            else:
                notes.append(f"经营现金流为负({cash_flow/1e8:.2f}亿), {industry}行业常见季节性/周期性因素")

        # 添加行业特性说明
        if industry != "通用":
            industry_note = INDUSTRY_MAP.get(industry, {}).get("note", "")
            if industry_note:
                notes.append(f"📌 {industry}行业特性: {industry_note}")

        passed = len(reasons) == 0
        return passed, reasons, notes


class ScoringEngine:
    """多维度打分引擎"""

    @staticmethod
    def score_valuation(quote: Dict, fund: Dict) -> float:
        """估值分 (0-100)"""
        score = 50.0  # 基础分

        pe = quote.get("pe_dynamic") if quote else None
        pb = quote.get("pb") if quote else None

        # PE 打分 (越低越好)
        if pe is not None and pe > 0:
            if pe < 15:
                pe_score = 90
            elif pe < 25:
                pe_score = 75
            elif pe < 40:
                pe_score = 60
            elif pe < 80:
                pe_score = 40
            else:
                pe_score = 20
            score = score * 0.5 + pe_score * 0.5

        # PB 打分 (越低越好)
        if pb is not None and pb > 0:
            if pb < 1.5:
                pb_score = 90
            elif pb < 3:
                pb_score = 75
            elif pb < 6:
                pb_score = 60
            elif pb < 10:
                pb_score = 40
            else:
                pb_score = 20
            score = score * 0.6 + pb_score * 0.4

        return round(min(100, max(0, score)), 1)

    @staticmethod
    def score_price(quote: Dict, history: List[Dict]) -> float:
        """价格分 (0-100): 距52周高低点位置 + 趋势"""
        if not quote or not history:
            return 50.0

        price = quote.get("price", 0)
        if not price or price <= 0:
            return 50.0

        # 计算历史区间
        highs = [h["high"] for h in history if h["high"]]
        lows = [h["low"] for h in history if h["low"]]

        if not highs or not lows:
            return 50.0

        period_high = max(highs)
        period_low = min(lows)
        period_range = period_high - period_low

        if period_range <= 0:
            return 50.0

        # 价格位置分: 越低越有投资价值 (逆向思维)
        position = (price - period_low) / period_range
        # 距低点越近分数越高
        position_score = (1.0 - position) * 80 + 20

        # 趋势分: 基于近N日涨跌
        if len(history) >= 20:
            recent_20 = history[-20:]
            price_20d_ago = recent_20[0]["close"]
            if price_20d_ago > 0:
                change_20d = (price - price_20d_ago) / price_20d_ago * 100
                # 适度上涨加分, 过度上涨扣分
                if -5 <= change_20d <= 10:
                    trend_score = 80
                elif -15 <= change_20d < -5:
                    trend_score = 70  # 回调是买点
                elif change_20d > 10:
                    trend_score = max(30, 60 - (change_20d - 10) * 2)
                else:
                    trend_score = 40
            else:
                trend_score = 50
        else:
            trend_score = 50

        score = position_score * 0.5 + trend_score * 0.5
        return round(min(100, max(0, score)), 1)

    @staticmethod
    def score_market(quote: Dict, history: List[Dict]) -> float:
        """市场热度分 (0-100)"""
        if not quote:
            return 50.0

        score = 50.0

        # 换手率 (适中最好, 过低或过高都不好)
        turnover_rate = quote.get("turnover_rate")
        if turnover_rate is not None:
            if 0.5 <= turnover_rate <= 5:
                turnover_score = 85
            elif 0.2 <= turnover_rate < 0.5:
                turnover_score = 65
            elif 5 < turnover_rate <= 15:
                turnover_score = 55
            elif turnover_rate > 15:
                turnover_score = 30  # 过热
            else:
                turnover_score = 40  # 低迷
            score = score * 0.5 + turnover_score * 0.5

        # 成交量趋势
        if history and len(history) >= 10:
            recent_vol = sum(h["volume"] for h in history[-5:] if h["volume"]) / 5
            prev_vol = sum(h["volume"] for h in history[-10:-5] if h["volume"]) / 5
            if prev_vol > 0:
                vol_ratio = recent_vol / prev_vol
                if 0.8 <= vol_ratio <= 1.5:
                    vol_score = 75
                elif vol_ratio > 2.0:
                    vol_score = 40  # 放量过度
                elif vol_ratio < 0.5:
                    vol_score = 35  # 缩量过度
                else:
                    vol_score = 60
                score = score * 0.6 + vol_score * 0.4

        return round(min(100, max(0, score)), 1)

    @staticmethod
    def compute(quote: Dict, fund: Dict, history: List[Dict]) -> Dict:
        """计算综合得分"""
        val_score = ScoringEngine.score_valuation(quote, fund)
        price_score = ScoringEngine.score_price(quote, history)
        market_score = ScoringEngine.score_market(quote, history)

        # 加权综合分
        total = (
            val_score * SCORE_WEIGHTS["valuation"]
            + price_score * SCORE_WEIGHTS["price"]
            + market_score * SCORE_WEIGHTS["market"]
        )

        # 评级
        if total >= 80:
            grade = "⭐⭐⭐⭐⭐ 优秀"
        elif total >= 65:
            grade = "⭐⭐⭐⭐ 良好"
        elif total >= 50:
            grade = "⭐⭐⭐ 中性"
        elif total >= 35:
            grade = "⭐⭐ 偏弱"
        else:
            grade = "⭐ 较差"

        return {
            "valuation_score": val_score,
            "price_score": price_score,
            "market_score": market_score,
            "total_score": round(total, 1),
            "grade": grade,
        }


class KellyCriterion:
    """凯利公式 - 最优仓位计算"""

    @staticmethod
    def calculate(
        score_total: float,
        fund: Dict,
        history: List[Dict],
    ) -> Dict:
        """
        基于凯利公式计算最优仓位比例

        标准凯利公式: f* = (bp - q) / b
        其中:
          f* = 最优仓位比例
          b  = 盈亏比 (预期盈利 / 预期亏损)
          p  = 胜率 (获胜概率)
          q  = 失败率 (1 - p)

        在股票中的应用:
          - 胜率 p: 基于基本面质量 + 技术面信号综合评估
          - 盈亏比 b: 基于历史波动率和估值水平估算
        """
        # 1. 估算胜率 (p)
        base_win_rate = KELLY_WIN_RATE_BASE

        # 基本面质量调整 (ROE, 增长率等)
        fund_quality = 0.0
        if fund:
            if fund.get("roe", 0) and fund["roe"] > 15:
                fund_quality += 0.10
            elif fund.get("roe", 0) and fund["roe"] > 8:
                fund_quality += 0.05

            growth = fund.get("profit_growth") or 0
            if growth > 20:
                fund_quality += 0.08
            elif growth > 0:
                fund_quality += 0.04

            margin = fund.get("net_margin") or 0
            if margin > 20:
                fund_quality += 0.05
            elif margin > 10:
                fund_quality += 0.02

        # 综合得分调整
        score_adj = (score_total - 50) / 200  # -0.25 ~ +0.25

        win_prob = min(0.85, max(0.30, base_win_rate + fund_quality + score_adj))

        # 2. 估算盈亏比 (b)
        # 基于历史波动率计算
        volatility = 0.02  # 默认日波动 2%
        if history and len(history) >= 20:
            returns = []
            for i in range(1, len(history)):
                if history[i-1]["close"] and history[i]["close"]:
                    ret = (history[i]["close"] - history[i-1]["close"]) / history[i-1]["close"]
                    returns.append(ret)
            if returns:
                mean_ret = sum(returns) / len(returns)
                variance = sum((r - mean_ret)**2 for r in returns) / len(returns)
                volatility = math.sqrt(variance)

        # 年化波动率
        annual_vol = volatility * math.sqrt(252)

        # 预期盈利 (基于波动率和胜率)
        expected_win = annual_vol * win_prob * 2  # 胜率高时盈利空间大
        expected_loss = annual_vol * (1 - win_prob) * 2  # 止损空间

        # 盈亏比
        if expected_loss > 0:
            win_loss_ratio = expected_win / expected_loss
        else:
            win_loss_ratio = 2.0

        # 3. 凯利公式计算
        p = win_prob
        q = 1 - p
        b = win_loss_ratio

        if b > 0:
            kelly_fraction = (b * p - q) / b
        else:
            kelly_fraction = 0

        # 4. 半凯利调整 (更稳健)
        if KELLY_HALF_Kelly:
            kelly_fraction = kelly_fraction * 0.5

        # 5. 限制范围
        kelly_fraction = max(0, min(KELLY_MAX_POSITION, kelly_fraction))

        # 6. 换算为建议仓位等级
        if kelly_fraction >= 0.5:
            position_level = "🔴 高仓位 (50-70%)"
        elif kelly_fraction >= 0.3:
            position_level = "🟠 中高仓位 (30-50%)"
        elif kelly_fraction >= 0.15:
            position_level = "🟡 中仓位 (15-30%)"
        elif kelly_fraction > 0:
            position_level = "🟢 轻仓试探 (0-15%)"
        else:
            position_level = "⚫ 建议空仓 (观望)"

        return {
            "win_probability": round(win_prob, 3),
            "win_loss_ratio": round(win_loss_ratio, 2),
            "annual_volatility": round(annual_vol, 4),
            "kelly_fraction": round(kelly_fraction, 4),
            "kelly_position_pct": f"{kelly_fraction*100:.1f}%",
            "position_level": position_level,
            "half_kelly": KELLY_HALF_Kelly,
        }


# ============================================================
# 报告生成器
# ============================================================

class ReportGenerator:
    """分析报告生成器 - 支持行业识别"""

    @staticmethod
    def generate(
        stock_info: Dict,
        quote: Dict,
        fund: Dict,
        filter_result: Tuple,
        scores: Dict,
        kelly: Dict,
        industry_info: Dict = None,
    ) -> str:
        """
        生成完整的分析报告
        
        Args:
            stock_info: 股票基本信息
            quote: 实时行情
            fund: 基本面数据
            filter_result: (passed, reasons, notes) 或 (passed, reasons)
            scores: 打分结果
            kelly: 凯利公式结果
            industry_info: 行业识别信息
        """
        lines = []

        # 兼容旧格式 (2元素 vs 3元素)
        if len(filter_result) == 2:
            passed, reasons = filter_result
            notes = []
        else:
            passed, reasons, notes = filter_result

        # 标题
        lines.append("=" * 60)
        lines.append(f"  🤖 AI 股票分析报告 v2.0")
        lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)

        # 基本信息
        lines.append("")
        lines.append(f"【股票信息】")
        lines.append(f"  名称: {stock_info['name']}  |  代码: {stock_info['code']}")
        lines.append(f"  市场: {'上海' if stock_info['market'] == 'sh' else '深圳'}")
        
        # 行业标签
        if industry_info:
            industry = industry_info.get("industry", "通用")
            confidence = industry_info.get("confidence", 0)
            lines.append(f"  🏷️ 行业: {industry} (置信度: {confidence:.0%})")
            if industry_info.get("reason"):
                lines.append(f"  📝 识别依据: {industry_info['reason']}")

        # 实时行情
        if quote:
            lines.append("")
            lines.append(f"【实时行情】")
            lines.append(f"  现价: ¥{quote.get('price', 'N/A')}  |  涨跌: {quote.get('change_pct', 'N/A')}%")
            lines.append(f"  开盘: ¥{quote.get('open', 'N/A')}  |  最高: ¥{quote.get('high', 'N/A')}  |  最低: ¥{quote.get('low', 'N/A')}")
            lines.append(f"  昨收: ¥{quote.get('prev_close', 'N/A')}")
            lines.append(f"  成交量: {quote.get('volume', 'N/A')}手  |  成交额: {quote.get('amount_wan', 'N/A')}万元")
            lines.append(f"  换手率: {quote.get('turnover_rate', 'N/A')}%")
            lines.append(f"  市盈率(动态): {quote.get('pe_dynamic', 'N/A')}  |  市净率: {quote.get('pb', 'N/A')}")

        # 基本面数据
        if fund:
            lines.append("")
            lines.append(f"【基本面数据】(报告期: {fund.get('report_date', 'N/A')} {fund.get('report_type', '')})")
            
            # 显示行业适用的标准
            if industry_info and industry_info.get("thresholds"):
                th = industry_info["thresholds"]
                lines.append(f"  📏 行业标准: ROE≥{th.get('roe_min', 'N/A')}%, 负债率≤{th.get('debt_ratio_max', 'N/A')}%")
            
            lines.append(f"  盈利能力:")
            lines.append(f"    ROE(加权): {fund.get('roe', 'N/A')}%  |  ROA: {fund.get('roa', 'N/A')}%")
            lines.append(f"    毛利率: {fund.get('gross_margin', 'N/A')}%  |  净利率: {fund.get('net_margin', 'N/A')}%")
            lines.append(f"    EPS: ¥{fund.get('eps', 'N/A')}  |  BPS: ¥{fund.get('bps', 'N/A')}")
            lines.append(f"  成长能力:")
            lines.append(f"    营业收入: {ReportGenerator._fmt_amount(fund.get('revenue'))}  |  净利润: {ReportGenerator._fmt_amount(fund.get('net_profit'))}")
            lines.append(f"    营收同比: {fund.get('revenue_growth', 'N/A')}%  |  净利润同比: {fund.get('profit_growth', 'N/A')}%")
            lines.append(f"  财务健康:")
            lines.append(f"    资产负债率: {fund.get('debt_ratio', 'N/A')}%  |  流动比率: {fund.get('current_ratio', 'N/A')}  |  速动比率: {fund.get('quick_ratio', 'N/A')}")
            lines.append(f"    经营现金流: {ReportGenerator._fmt_amount(fund.get('cash_flow_operate'))}")
        else:
            lines.append("")
            lines.append("【基本面数据】⚠️ 无法获取, 分析可能不完整")

        # 基本面过滤结果
        lines.append("")
        lines.append(f"【基本面过滤】")
        if passed:
            lines.append(f"  ✅ 通过基本面筛选 (符合{industry_info.get('industry', '通用')}行业标准)")
        else:
            lines.append(f"  ❌ 未通过基本面筛选:")
            for r in reasons:
                lines.append(f"    ⚠️ {r}")
            lines.append(f"  💡 建议: 该股票基本面存在瑕疵, 谨慎参与或回避")
        
        # 显示行业备注
        if notes:
            lines.append(f"  📌 补充说明:")
            for note in notes:
                lines.append(f"    ℹ️ {note}")

        # 打分结果
        lines.append("")
        lines.append(f"【多维度打分】")
        lines.append(f"  估值分: {scores['valuation_score']}/100  (权重 {SCORE_WEIGHTS['valuation']*100:.0f}%)")
        lines.append(f"  价格分: {scores['price_score']}/100  (权重 {SCORE_WEIGHTS['price']*100:.0f}%)")
        lines.append(f"  热度分: {scores['market_score']}/100  (权重 {SCORE_WEIGHTS['market']*100:.0f}%)")
        lines.append(f"  ──────────────────────────────")
        lines.append(f"  综合得分: {scores['total_score']}/100  {scores['grade']}")

        # 凯利公式
        lines.append("")
        lines.append(f"【凯利公式 - 最优仓位】")
        lines.append(f"  胜率(估): {kelly['win_probability']*100:.1f}%  |  盈亏比: {kelly['win_loss_ratio']:.2f}")
        lines.append(f"  年化波动率: {kelly['annual_volatility']*100:.2f}%")
        lines.append(f"  凯利系数: {kelly['kelly_fraction']:.4f}")
        if kelly.get("half_kelly"):
            lines.append(f"  (采用半凯利策略, 更稳健)")
        lines.append(f"  ──────────────────────────────")
        lines.append(f"  ⭐ 建议仓位: {kelly['kelly_position_pct']}  {kelly['position_level']}")

        # 投资建议
        lines.append("")
        lines.append(f"【综合建议】")

        if not passed:
            lines.append(f"  🚫 回避: 基本面未达标, 不建议参与")
        elif scores["total_score"] >= 65 and kelly["kelly_fraction"] > 0.2:
            lines.append(f"  ✅ 积极: 基本面优良 + 综合得分高 + 凯利建议中高仓位")
            lines.append(f"     建议建仓: {kelly['kelly_position_pct']}, 分批建仓, 设置止损")
        elif scores["total_score"] >= 50:
            lines.append(f"  ⚠️ 谨慎: 综合得分一般, 建议轻仓试探")
            lines.append(f"     建议仓位: {kelly['kelly_position_pct']}, 严格止损, 控制风险")
        else:
            lines.append(f"  ⛔ 观望: 得分偏低, 风险较大, 建议观望或回避")

        # 免责声明
        lines.append("")
        lines.append("-" * 60)
        lines.append("⚠️ 免责声明: 本分析仅供参考, 不构成投资建议。")
        lines.append("   股市有风险, 投资需谨慎。请自主决策, 自负盈亏。")
        lines.append("=" * 60)

        return "\n".join(lines)

    @staticmethod
    def _fmt_amount(val) -> str:
        """格式化金额显示"""
        if val is None:
            return "N/A"
        val = float(val)
        if abs(val) >= 1e8:
            return f"{val/1e8:.2f}亿"
        elif abs(val) >= 1e4:
            return f"{val/1e4:.2f}万"
        else:
            return f"{val:.2f}元"


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("  🤖 AI 股票分析系统 v2.0 (行业差异化版)")
    print("  基于行业识别 + 基本面过滤 + 多维度打分 + 凯利公式")
    print("=" * 60)
    print()

    fetcher = StockDataFetcher()
    filter_engine = FundamentalFilter()
    classifier = IndustryClassifier()
    scorer = ScoringEngine()
    kelly = KellyCriterion()

    while True:
        print()
        keyword = input("请输入股票名称或代码 (输入 q 退出): ").strip()
        if keyword.lower() == "q":
            print("再见! 👋")
            break

        if not keyword:
            continue

        # 1. 搜索股票
        print(f"\n🔍 搜索中...")
        results = fetcher.search_stock(keyword)

        if not results:
            print("❌ 未找到匹配的股票, 请检查名称或代码")
            continue

        # 显示搜索结果
        if len(results) == 1:
            stock_info = results[0]
            print(f"  匹配: {stock_info['name']} ({stock_info['code']})")
        else:
            print(f"\n找到 {len(results)} 只匹配股票:")
            for i, r in enumerate(results[:5], 1):
                print(f"  [{i}] {r['name']} ({r['code']})")
            try:
                choice = input(f"请选择编号 (1-{min(len(results), 5)}, 默认1): ").strip()
                if choice:
                    idx = int(choice) - 1
                    if 0 <= idx < min(len(results), 5):
                        stock_info = results[idx]
                    else:
                        stock_info = results[0]
                else:
                    stock_info = results[0]
            except (ValueError, IndexError):
                stock_info = results[0]

        full_code = stock_info["full_code"]
        code = stock_info["code"]
        name = stock_info["name"]

        # 1.5 行业识别
        print(f"\n🏷️ 行业识别...")
        industry_info = classifier.classify(code, name, full_code)
        print(f"  行业: {industry_info['industry']} (置信度: {industry_info['confidence']:.0%})")
        if industry_info.get("note"):
            print(f"  特性: {industry_info['note']}")

        # 2. 获取实时行情
        print(f"\n📈 获取实时行情...")
        quote = fetcher.fetch_realtime_quote(full_code)
        if quote:
            print(f"  {quote['name']} 现价: ¥{quote.get('price', 'N/A')} ({quote.get('change_pct', 'N/A')}%)")
        else:
            print("  ⚠️ 实时行情获取失败")

        # 3. 获取基本面数据
        print(f"📊 获取基本面数据...")
        fund = fetcher.fetch_fundamental(code)
        if fund:
            print(f"  报告期: {fund.get('report_date', 'N/A')} ROE: {fund.get('roe', 'N/A')}%")
        else:
            print("  ⚠️ 基本面数据获取失败")

        # 4. 获取历史数据
        print(f"📉 获取历史K线...")
        history = fetcher.fetch_history(full_code, days=60)
        print(f"  获取到 {len(history)} 个交易日数据")

        # 5. 基本面过滤 (使用行业特定标准)
        industry = industry_info.get("industry", "通用")
        thresholds = industry_info.get("thresholds")
        passed, reasons, notes = filter_engine.check(fund, quote, industry, thresholds)

        # 显示过滤结果
        if passed:
            print(f"\n  ✅ 基本面过滤通过 (符合{industry}行业标准)")
        else:
            print(f"\n  ❌ 基本面过滤未通过:")
            for r in reasons:
                print(f"    ⚠️ {r}")
        if notes:
            for n in notes:
                print(f"    ℹ️ {n}")

        # 6. 多维度打分
        scores = scorer.compute(quote, fund, history)

        # 7. 凯利公式计算
        kelly_result = kelly.calculate(scores["total_score"], fund, history)

        # 8. 生成报告
        print(f"\n📝 生成分析报告...")
        report = ReportGenerator.generate(
            stock_info, quote, fund, (passed, reasons, notes), 
            scores, kelly_result, industry_info
        )
        print(report)

        # 保存报告
        save = input("\n是否保存报告到文件? (y/n, 默认n): ").strip()
        if save.lower() == "y":
            filename = f"分析报告_{code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"✅ 报告已保存: {filename}")


if __name__ == "__main__":
    main()
