#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选股引擎 v4.0 - 两轮预过滤 + 行业自适应阈值 + 多维度评分
- 第一轮：质量筛查（基本面一票否决）
- 第二轮：形态筛查（量价形态门槛）
- 行业自适应阈值：根据二级分类使用不同财务标准
- 新增技术指标：tail_pct（尾盘涨幅）/ vol_trend（量能趋势）/ circ_market_cap（流通市值）
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .data_fetcher import StockDataFetcher, StockAnalyzer, INDUSTRY_LEVEL2_MAP


class StockScreener:
    """股票选股引擎 v4.0"""
    
    def __init__(self):
        self.fetcher = StockDataFetcher()
        self.analyzer = StockAnalyzer()
        self.results = []
        self.last_update = None
        self.pre_filter_stats = {
            "quality_passed": 0,
            "pattern_passed": 0,
            "total_scanned": 0,
        }
        self.config = {
            "mode": "all",
            "min_market_cap": 50,
            "max_count": 500,
            "top_n": 10,
            "min_score": 50.0,
            "exclude_st": True,
            "circ_market_cap_range": (50, 500),
            "tail_pct_range": (3.0, 5.0),
            "turnover_rate_range": (3.0, 15.0),
        }
    
    def update_config(self, **kwargs):
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value

    def run_screening(self, top_n: int = None, min_score: float = None, 
                      mode: str = None, **kwargs) -> List[Dict]:
        top_n = top_n or self.config["top_n"]
        min_score = min_score or self.config["min_score"]
        mode = mode or self.config["mode"]
        
        self.config.update({k: v for k, v in kwargs.items() if k in self.config})
        
        print("=" * 60)
        print("🚀 开始股票筛选 v5.0 (基本面筛选 + 三维度打分)")
        print(f"   模式: {mode}")
        print(f"   市值范围: {self.config['circ_market_cap_range'][0]}亿-{self.config['circ_market_cap_range'][1]}亿")
        print(f"   过滤条件: 基本面达标即可入围")
        print(f"   打分维度: 基本面(40) + 技术面(40) + 资金面(20) = 100分")
        print("=" * 60)
        
        # Step 1: 获取股票列表
        stocks = self.fetcher.get_stock_list(
            mode=mode,
            min_market_cap=self.config['min_market_cap'],
            exclude_st=self.config['exclude_st'],
            max_count=self.config['max_count'],
        )
        if not stocks:
            print("❌ 无法获取股票列表")
            return []
        
        self.pre_filter_stats["total_scanned"] = len(stocks)
        print(f"\n📋 Step 1: 获取到 {len(stocks)} 只股票")
        
        # Step 2: 批量获取实时行情
        print("📊 Step 2: 获取实时行情...")
        quotes = self.fetcher.fetch_batch_quotes(stocks)
        
        # Step 3: 基本面筛选 + 三维度打分
        print("🔍 Step 3: 基本面筛选 + 三维度打分...")
        analyzed_results = self._process_stocks(stocks, quotes)
        
        if not analyzed_results:
            print("⚠️ 无股票通过基本面筛选，返回空结果")
            self.results = []
            self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return []
        
        # Step 4: 排序并选出Top N
        analyzed_results.sort(key=lambda x: x["total_score"], reverse=True)
        qualified = [r for r in analyzed_results if r["total_score"] >= min_score]
        top_stocks = qualified[:top_n]
        
        self.results = top_stocks
        self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"\n🎉 筛选完成！")
        print(f"   有效分析: {len(analyzed_results)}")
        print(f"   合格股票: {len(qualified)} (≥{min_score}分)")
        print(f"   返回Top: {len(top_stocks)}")
        
        return top_stocks

    def _pre_filter_quality(self, stock: Dict, quote: Dict, history: List[Dict]) -> Tuple[bool, List[str]]:
        """第一轮：质量筛查（基本面一票否决）"""
        reasons = []
        thresholds = stock.get("industry_thresholds", {})
        industry_level2 = stock.get("industry_level2", "通用")
        
        # 1. 排除 ST/*ST 股票
        name = stock.get("name", "")
        if "ST" in name or "st" in name or "*ST" in name:
            reasons.append("ST/*ST股票")
            return False, reasons
        
        # 2. ROE 检查
        roe_min = thresholds.get("roe_min", 3.0)
        fund = self._get_fundamental_safe(stock["code"])
        if fund:
            roe = fund.get("roe")
            if roe is not None and roe < roe_min:
                reasons.append(f"ROE({roe:.1f}%) < {roe_min}%")
            
            # 连续3年ROE下滑（简化版：检查趋势）
            roe_trend = self._check_roe_trend(stock["code"])
            if roe_trend == "declining":
                reasons.append("ROE连续3年下滑")
            
            # 净利润增长率
            profit_growth = fund.get("profit_growth")
            if profit_growth is not None and profit_growth < -30:
                reasons.append(f"净利润增长率({profit_growth:.1f}%)过低")
            
            # 自由现金流
            cash_flow_exempt = thresholds.get("cash_flow_exempt", False)
            free_cf = fund.get("free_cash_flow")
            if not cash_flow_exempt and free_cf is not None and free_cf < 0:
                reasons.append(f"自由现金流为负({free_cf/1e8:.2f}亿)")
            
            # 资产负债率
            debt_max = thresholds.get("debt_ratio_max", 70.0)
            debt = fund.get("debt_ratio")
            if debt is not None and debt > debt_max:
                reasons.append(f"资产负债率({debt:.1f}%) > {debt_max}%")
        else:
            # 无法获取基本面数据时，仅做技术面筛选
            pass
        
        passed = len(reasons) == 0
        return passed, reasons

    def _process_stocks(self, stocks: List[Dict], quotes: Dict, strict_mode: bool = True) -> List[Dict]:
        """处理股票列表 - 仅基本面过滤 + 三维度打分"""
        quality_passed = []
        analyzed_results = []
        
        total = len(stocks)
        done = 0
        skip_reasons = {"no_quote": 0, "no_history": 0, "quality_fail": 0}
        
        for stock in stocks:
            code = stock["code"]
            quote = quotes.get(code)
            
            if not quote or quote["price"] == 0:
                skip_reasons["no_quote"] += 1
                done += 1
                continue
            
            try:
                history = self.fetcher.fetch_kline_history(stock["full_code"], days=120)
                
                if not history or len(history) < 30:
                    skip_reasons["no_history"] += 1
                    done += 1
                    continue
                
                # 基本面过滤（唯一的筛选条件）
                quality_ok, quality_reasons = self._pre_filter_quality(stock, quote, history)
                
                if quality_ok:
                    quality_passed.append(stock)
                    
                    # 通过基本面筛选 → 进入三维度打分
                    result = self._analyze_stock(stock, quote, history)
                    analyzed_results.append(result)
                else:
                    skip_reasons["quality_fail"] += 1
                
            except Exception as e:
                print(f"    ⚠️ 分析 {code} 出错: {e}")
            
            done += 1
            if done % 100 == 0:
                print(f"  进度: {done}/{total} ({done*100//total}%) - 基本面通过: {len(quality_passed)}")
                time.sleep(0.2)
        
        self.pre_filter_stats["quality_passed"] = len(quality_passed)
        self.pre_filter_stats["pattern_passed"] = len(analyzed_results)
        
        mode_name = "严格" if strict_mode else "宽松"
        print(f"\n📊 [{mode_name}模式] 筛选统计:")
        print(f"  扫描总数: {total}")
        print(f"  无行情/停牌: {skip_reasons['no_quote']}")
        print(f"  无历史数据: {skip_reasons['no_history']}")
        print(f"  基本面通过: {len(quality_passed)} ({len(quality_passed)*100/max(total,1):.1f}%)")
        print(f"  进入三维度打分: {len(analyzed_results)}")
        
        return analyzed_results

    def _analyze_stock(self, stock: Dict, quote: Dict, history: List[Dict]) -> Dict:
        """分析单只股票 - 三大维度评分体系"""
        code = stock["code"]
        name = stock["name"]
        price = quote["price"]
        industry_level1 = stock.get("industry_level1", "通用")
        industry_level2 = stock.get("industry_level2", "通用")
        thresholds = stock.get("industry_thresholds", {})
        
        result = {
            "code": code,
            "name": name,
            "price": price,
            "change_pct": quote.get("change_pct", 0),
            "turnover_rate": quote.get("turnover_rate", 0),
            "pe": quote.get("pe_dynamic", 0),
            "pb": quote.get("pb", 0),
            "market_cap": stock.get("market_cap", 0),
            "industry": stock.get("industry", ""),
            "industry_level1": industry_level1,
            "industry_level2": industry_level2,
            "industry_thresholds": thresholds,
            "industry_note": stock.get("industry_note", ""),
        }
        
        # 获取基本面数据
        fund = self._get_fundamental_safe(code)
        result["fundamental"] = fund or {}
        
        # 1. 均线分析
        ma5_trend = self.analyzer.calculate_ma_trend(history, 5)
        ma10_trend = self.analyzer.calculate_ma_trend(history, 10)
        ma20_trend = self.analyzer.calculate_ma_trend(history, 20)
        ma60_trend = self.analyzer.calculate_ma_trend(history, 60)
        
        result["ma5"] = ma5_trend
        result["ma10"] = ma10_trend
        result["ma20"] = ma20_trend
        result["ma60"] = ma60_trend
        
        # 均线排列
        alignment = self.analyzer.check_ma_alignment(history)
        result["ma_alignment"] = alignment
        
        # 2. 成交量分析
        volume_analysis = self.analyzer.calculate_volume_ratio(history)
        result["volume_analysis"] = volume_analysis
        
        # 3. 3日成交量趋势
        vol_trend_3d = self.analyzer.check_volume_trend_3day(history)
        result["vol_trend"] = vol_trend_3d
        
        # 4. 尾盘涨幅
        tail_pct = self.analyzer.calculate_tail_pct(history, quote)
        result["tail_pct"] = tail_pct
        
        # 5. 价格位置
        price_position = self.analyzer.calculate_price_position(history, price)
        result["price_position"] = price_position
        
        # 6. 近5日/20日涨幅
        result["pct_5d"] = self.analyzer.calculate_pct_change(history, 5)
        result["pct_20d"] = self.analyzer.calculate_pct_change(history, 20)
        
        # 7. 流通市值（亿）
        market_cap = stock.get("market_cap", 0)
        result["circ_market_cap"] = round(market_cap / 1e8, 2) if market_cap else 0
        
        # 8. 换手率量化
        turnover = quote.get("turnover_rate", 0)
        result["turnover_rate_quantified"] = self._quantify_turnover(turnover)
        
        # 9. 计算三大维度评分
        fundamental_score = self._calc_fundamental_score(result, thresholds, industry_level2)
        technical_score = self._calc_technical_score(result, thresholds, industry_level2)
        capital_score = 20.0  # 资金面默认满分(待开发)
        
        result["fundamental_score"] = round(fundamental_score, 1)
        result["technical_score"] = round(technical_score, 1)
        result["capital_score"] = round(capital_score, 1)
        
        total_score = fundamental_score + technical_score + capital_score
        result["total_score"] = round(total_score, 1)
        
        # 10. 评级
        result["grade"] = self._get_grade(total_score)
        
        # 11. 建议
        result["advice"] = self._get_advice(result)
        
        # 12. 保存详细分数
        result["score_details"] = [
            {"category": "基本面", "score": result["fundamental_score"], "max": 40, "items": result.get("fundamental_items", [])},
            {"category": "技术面", "score": result["technical_score"], "max": 40, "items": result.get("technical_items", [])},
            {"category": "资金面", "score": result["capital_score"], "max": 20, "items": [
                {"name": "北向资金", "score": 5, "max": 10, "note": "待开发"},
                {"name": "主力资金", "score": 5, "max": 10, "note": "待开发"}
            ]},
        ]
        
        return result

    def _calc_fundamental_score(self, result: Dict, thresholds: Dict, industry_level2: str) -> float:
        """基本面得分（满分40分）- ROE(10) + 营收增速(10) + 自由现金流(8) + 估值(7) + 股息率(5)"""
        items = []
        fund = result.get("fundamental", {})
        
        # 行业自适应阈值
        industry_roe_min = thresholds.get("roe_min", 3.0)
        debt_max = thresholds.get("debt_ratio_max", 70.0)
        cash_flow_exempt = thresholds.get("cash_flow_exempt", False)
        
        # 1. ROE评分 (10分)
        roe = fund.get("roe")
        roe_score = 5.0
        if roe is not None:
            if roe >= industry_roe_min * 1.5:
                roe_score = 10.0
            elif roe >= industry_roe_min:
                roe_score = 10.0 - max(0, (industry_roe_min - roe) * 0.5)
            elif roe >= industry_roe_min * 0.7:
                roe_score = 6.0
            else:
                roe_score = 3.0
        items.append({"name": "ROE", "score": round(roe_score, 1), "max": 10, "value": f"{roe:.1f}%" if roe else "N/A"})
        
        # 2. 营收增速评分 (10分)
        profit_growth = fund.get("profit_growth")
        growth_score = 5.0
        if profit_growth is not None:
            if profit_growth >= 30:
                growth_score = 10.0
            elif profit_growth >= 15:
                growth_score = 8.0
            elif profit_growth >= 5:
                growth_score = 6.0
            elif profit_growth >= 0:
                growth_score = 4.0
            else:
                growth_score = 2.0
        items.append({"name": "营收增速", "score": round(growth_score, 1), "max": 10, "value": f"{profit_growth:.1f}%" if profit_growth else "N/A"})
        
        # 3. 自由现金流评分 (8分)
        free_cf = fund.get("free_cash_flow")
        cf_score = 4.0
        if cash_flow_exempt:
            cf_score = 6.0  # 金融/半导体豁免
        elif free_cf is not None:
            if free_cf > 0:
                cf_score = 8.0
            else:
                cf_score = 2.0
        items.append({"name": "自由现金流", "score": round(cf_score, 1), "max": 8, "value": "为正" if (free_cf and free_cf > 0) else "为负"})
        
        # 4. 估值评分 (7分) - PE/PB行业自适应
        pe = result.get("pe", 0)
        pb = result.get("pb", 0)
        val_score = 3.5
        
        pe_ranges = {
            "金融.国有大行": (4, 6), "金融.股份制银行": (5, 7),
            "金融.券商": (15, 25), "金融.保险": (10, 20),
            "科技.半导体设计": (50, 100), "科技.半导体制造": (30, 80),
            "科技.AI软件": (60, 120), "科技.消费电子": (30, 60),
            "消费.白酒": (25, 35), "消费.家电": (10, 15),
            "消费.医药生物": (30, 60), "新能源.锂电": (20, 40),
            "新能源.光伏": (15, 30), "周期.钢铁": (5, 15),
            "周期.有色": (10, 20), "地产基建.房地产": (5, 15),
            "地产基建.基建建材": (10, 20),
        }
        
        pe_range = pe_ranges.get(industry_level2, (15, 25))
        pe_low, pe_high = pe_range
        
        if pe <= 0:
            val_score = 2.0  # 亏损股
        elif pe_low <= pe <= pe_high:
            val_score = 7.0  # 行业合理估值
        elif pe < pe_low:
            val_score = 5.5  # 低于行业均值
        elif pe <= pe_high * 1.5:
            val_score = 3.5  # 略高
        else:
            val_score = 1.5  # 高估
        
        items.append({"name": "估值PE", "score": round(val_score, 1), "max": 7, "value": f"PE:{pe:.1f}" if pe else "N/A"})
        
        # 5. 股息率评分 (5分)
        dividend_yield = fund.get("dividend_yield", 0)
        div_score = 2.5
        
        dividend_thresholds = {
            "金融.国有大行": 4.0, "金融.股份制银行": 4.0,
            "公用事业": 3.0, "消费.白酒": 2.0,
        }
        div_min = dividend_thresholds.get(industry_level2, 1.0)
        
        if dividend_yield >= div_min * 2:
            div_score = 5.0
        elif dividend_yield >= div_min:
            div_score = 4.0
        elif dividend_yield >= div_min * 0.5:
            div_score = 3.0
        else:
            div_score = 1.5
        
        items.append({"name": "股息率", "score": round(div_score, 1), "max": 5, "value": f"{dividend_yield:.2f}%"})
        
        # 保存明细
        result["fundamental_items"] = items
        total = sum(item["score"] for item in items)
        return total

    def _calc_technical_score(self, result: Dict, thresholds: Dict, industry_level2: str) -> float:
        """技术面得分（满分40分）- 均线多头排列(12) + 尾盘拉升(8) + 成交量趋势(8) + 换手率(6) + 行业热度(6)"""
        items = []
        
        # 1. 均线多头排列 (12分)
        alignment = result.get("ma_alignment", {})
        ma_score = 6.0
        if alignment.get("alignment") == "bullish":
            ma_score = 12.0
        elif alignment.get("alignment") == "semi_bullish":
            ma_score = 8.0
        elif alignment.get("alignment") == "neutral":
            ma_score = 5.0
        elif alignment.get("alignment") == "bearish":
            ma_score = 2.0
        items.append({"name": "均线多头排列", "score": round(ma_score, 1), "max": 12, "value": alignment.get("alignment", "unknown")})
        
        # 2. 尾盘拉升 (8分)
        tail_pct = result.get("tail_pct", 0)
        tail_min, tail_max = self.config["tail_pct_range"]
        tail_score = 4.0
        if tail_min <= tail_pct <= tail_max:
            tail_score = 8.0  # [3%,5%] 满分
        elif 1.0 <= tail_pct < tail_min:
            tail_score = 5.0
        elif tail_pct > tail_max:
            tail_score = 4.0
        elif 0 <= tail_pct < 1.0:
            tail_score = 3.0
        else:
            tail_score = 2.0
        items.append({"name": "尾盘拉升", "score": round(tail_score, 1), "max": 8, "value": f"{tail_pct:.1f}%"})
        
        # 3. 成交量趋势 (8分)
        vol_trend = result.get("vol_trend", {})
        vol_score = 4.0
        if vol_trend.get("consecutive_up", False):
            vol_score = 8.0  # 连续3日放大
        elif vol_trend.get("trend") == "up":
            vol_score = 5.0
        elif vol_trend.get("trend") == "down":
            vol_score = 2.0
        items.append({"name": "成交量趋势", "score": round(vol_score, 1), "max": 8, "value": vol_trend.get("trend", "unknown")})
        
        # 4. 换手率 (6分)
        turnover = result.get("turnover_rate", 0)
        turn_score = 3.0
        if 5 <= turnover <= 10:
            turn_score = 6.0  # [5%,10%] 最活跃区间
        elif 3 <= turnover < 5:
            turn_score = 4.5
        elif 10 < turnover <= 15:
            turn_score = 4.0
        elif 1 <= turnover < 3:
            turn_score = 3.0
        elif turnover > 15:
            turn_score = 2.0
        else:
            turn_score = 1.5
        items.append({"name": "换手率", "score": round(turn_score, 1), "max": 6, "value": f"{turnover:.1f}%"})
        
        # 5. 行业热度 (6分) - 基于近5日涨幅
        pct_5d = result.get("pct_5d", 0)
        industry_score = 3.0
        
        # 简单行业热度判断（基于个股5日涨幅作为代理）
        if pct_5d > 10:
            industry_score = 6.0  # 行业热门
        elif pct_5d > 5:
            industry_score = 5.0
        elif pct_5d > 0:
            industry_score = 4.0
        elif pct_5d > -5:
            industry_score = 2.5
        else:
            industry_score = 1.5
        items.append({"name": "行业热度", "score": round(industry_score, 1), "max": 6, "value": f"5日涨{pct_5d:.1f}%"})
        
        # 保存明细
        result["technical_items"] = items
        total = sum(item["score"] for item in items)
        return total

    @staticmethod
    def _quantify_turnover(turnover: float) -> str:
        """量化换手率描述"""
        if turnover <= 0.5:
            return "低迷"
        elif turnover <= 3:
            return "适中"
        elif turnover <= 15:
            return "活跃"
        elif turnover <= 25:
            return "过热"
        else:
            return "异常"

    def _get_fundamental_safe(self, code: str) -> Optional[Dict]:
        """安全获取基本面数据"""
        try:
            return self.fetcher.fetch_fundamental(code)
        except Exception:
            return None

    def _check_roe_trend(self, code: str) -> str:
        """检查ROE趋势（简化版）"""
        fund = self._get_fundamental_safe(code)
        if not fund:
            return "unknown"
        roe = fund.get("roe")
        if roe is not None and roe > 3:
            return "stable"
        return "unknown"

    def _get_grade(self, score: float) -> str:
        if score >= 80:
            return "⭐⭐⭐⭐⭐ 优秀"
        elif score >= 70:
            return "⭐⭐⭐⭐ 良好"
        elif score >= 60:
            return "⭐⭐⭐ 中性"
        elif score >= 50:
            return "⭐⭐ 偏弱"
        else:
            return "⭐ 较差"
    
    def _get_advice(self, result: Dict) -> str:
        score = result["total_score"]
        alignment = result["ma_alignment"]["alignment"]
        vol_trend = result.get("vol_trend", {})
        industry_level2 = result.get("industry_level2", "通用")
        
        if score >= 75 and alignment == "bullish" and vol_trend.get("consecutive_up", False):
            return f"✅ 积极建仓：{industry_level2}行业，技术面优秀，均线多头排列+量能配合，可考虑买入"
        elif score >= 65:
            return f"⚠️ 谨慎关注：{industry_level2}行业，技术面良好，可逢低布局"
        elif score >= 55:
            return f"🔍 观察为主：{industry_level2}行业，技术面中性，等待更好时机"
        elif score >= 45:
            return f"⚠️ 谨慎：{industry_level2}行业，技术面偏弱，建议观望"
        else:
            return f"⛔ 回避：{industry_level2}行业，技术面较差，不建议参与"
    
    def get_results_summary(self) -> Dict:
        return {
            "last_update": self.last_update,
            "total_results": len(self.results),
            "pre_filter_stats": self.pre_filter_stats,
            "top_stocks": [
                {
                    "rank": i + 1,
                    "code": r["code"],
                    "name": r["name"],
                    "price": r["price"],
                    "total_score": r["total_score"],
                    "fundamental_score": r.get("fundamental_score", 0),
                    "technical_score": r.get("technical_score", 0),
                    "capital_score": r.get("capital_score", 0),
                    "grade": r["grade"],
                    "advice": r["advice"],
                    "industry_level1": r.get("industry_level1", ""),
                    "industry_level2": r.get("industry_level2", ""),
                    "change_pct": r.get("change_pct", 0),
                    "pe": r.get("pe", 0),
                    "pb": r.get("pb", 0),
                    "tail_pct": r.get("tail_pct", 0),
                    "circ_market_cap": r.get("circ_market_cap", 0),
                    "score_details": r.get("score_details", []),
                }
                for i, r in enumerate(self.results)
            ]
        }
    
    def cleanup(self):
        self.fetcher.clear_cache()
        print("🧹 已清理缓存，内存已释放")
    
    def get_memory_status(self) -> Dict:
        import sys
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            return {
                "memory_usage_mb": round(memory_info.rss / 1024 / 1024, 2),
                "memory_percent": round(process.memory_percent(), 2),
                "stock_count": len(self.results),
                "cache_size": self.fetcher.get_cache_size(),
            }
        except ImportError:
            return {
                "memory_usage_mb": "psutil未安装",
                "stock_count": len(self.results),
                "cache_size": self.fetcher.get_cache_size(),
            }


if __name__ == "__main__":
    screener = StockScreener()
    results = screener.run_screening(top_n=10, mode="hot")
    
    print("\n" + "=" * 70)
    print("📋 Top 10 选股结果（三大维度评分）:")
    print("=" * 70)
    print(f"{'排名':<4} {'名称':<10} {'代码':<8} {'总分':<6} {'基本面':<8} {'技术面':<8} {'资金面':<8} {'行业':<16} {'评级':<10}")
    print("-" * 70)
    for i, r in enumerate(results, 1):
        total = r['total_score']
        fund = r.get('fundamental_score', 0)
        tech = r.get('technical_score', 0)
        cap = r.get('capital_score', 0)
        industry = r.get('industry_level2', '')[:8]
        grade = r['grade'][:6]
        print(f"{i:<4} {r['name']:<10} {r['code']:<8} {total:<6.1f} {fund:<8.1f} {tech:<8.1f} {cap:<8.1f} {industry:<16} {grade:<10}")
        
        # 打印小分明细
        if r.get('score_details'):
            print(f"     基本面小分: ", end="")
            for item in r['score_details'][0].get('items', []):
                print(f"{item['name']}:{item['score']:.0f}/{item['max']} ", end="")
            print()
            print(f"     技术面小分: ", end="")
            for item in r['score_details'][1].get('items', []):
                print(f"{item['name']}:{item['score']:.0f}/{item['max']} ", end="")
            print()
    
    print("\n" + "=" * 70)
    print("💡 评分体系: 基本面(40) + 技术面(40) + 资金面(20) = 满分100")
    print("📖 详情文档: docs/stock-scoring_auto_workflow.md")