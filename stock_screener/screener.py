#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选股引擎 - 多维度评分和Top10选股
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from data_fetcher import StockDataFetcher, StockAnalyzer


class StockScreener:
    """股票选股引擎"""
    
    def __init__(self):
        self.fetcher = StockDataFetcher()
        self.analyzer = StockAnalyzer()
        self.results = []
        self.last_update = None
    
    def run_screening(self, top_n: int = 10, min_score: float = 40.0) -> List[Dict]:
        """
        运行选股筛选
        
        Args:
            top_n: 返回前N只股票
            min_score: 最低综合分数门槛
            
        Returns:
            排名前N的股票列表
        """
        print("=" * 60)
        print("🚀 开始股票筛选...")
        print("=" * 60)
        
        # 1. 获取股票列表
        stocks = self.fetcher.get_stock_list()
        if not stocks:
            print("❌ 无法获取股票列表")
            return []
        
        # 2. 批量获取实时行情（先获取行情，再过滤）
        print(f"📊 准备分析 {len(stocks)} 只股票")
        quotes = self.fetcher.fetch_batch_quotes(stocks)
        
        # 3. 批量分析
        print("🔍 分析股票技术指标...")
        analyzed = []
        total = len(stocks)
        done = 0
        
        for stock in stocks:
            code = stock["code"]
            quote = quotes.get(code)
            
            if not quote or quote["price"] == 0:
                done += 1
                continue
            
            try:
                # 获取K线历史
                history = self.fetcher.fetch_kline_history(stock["full_code"], days=120)
                
                if not history or len(history) < 30:
                    done += 1
                    continue
                
                # 分析股票
                result = self._analyze_stock(stock, quote, history)
                analyzed.append(result)
                
            except Exception as e:
                pass
            
            done += 1
            if done % 200 == 0:
                print(f"  分析进度: {done}/{total} ({done*100//total}%)")
                time.sleep(0.3)
        
        print(f"  ✅ 分析完成 {len(analyzed)} 只股票")
        
        # 4. 排序并选出Top N
        analyzed.sort(key=lambda x: x["total_score"], reverse=True)
        
        # 过滤最低分
        qualified = [r for r in analyzed if r["total_score"] >= min_score]
        
        # 取前N
        top_stocks = qualified[:top_n]
        
        self.results = top_stocks
        self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"\n🎉 筛选完成！")
        print(f"   有效股票: {len(analyzed)}")
        print(f"   合格股票: {len(qualified)}")
        print(f"   返回Top: {len(top_stocks)}")
        
        return top_stocks
    
    def _analyze_stock(self, stock: Dict, quote: Dict, history: List[Dict]) -> Dict:
        """分析单只股票"""
        code = stock["code"]
        name = stock["name"]
        price = quote["price"]
        
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
        }
        
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
        
        # 3. 价格位置
        price_position = self.analyzer.calculate_price_position(history, price)
        result["price_position"] = price_position
        
        # 4. 计算综合分数
        total_score = self._calculate_score(result, quote)
        result["total_score"] = round(total_score, 1)
        
        # 5. 评级
        result["grade"] = self._get_grade(total_score)
        
        # 6. 建议
        result["advice"] = self._get_advice(result)
        
        return result
    
    def _calculate_score(self, result: Dict, quote: Dict) -> float:
        """计算综合评分（满分100）"""
        scores = []
        
        # 1. 均线趋势分 (30分)
        ma_score = 0
        alignment_score = result["ma_alignment"]["score"]
        ma_score += alignment_score * 0.15  # 均线排列15分
        
        # 各均线斜率
        for ma_key in ["ma5", "ma10", "ma20", "ma60"]:
            ma_data = result.get(ma_key, {})
            slope = ma_data.get("slope", 0)
            if slope > 2:
                ma_score += 3.75
            elif slope > 0:
                ma_score += 2.5
            elif slope > -2:
                ma_score += 1.25
        
        scores.append(("均线趋势", ma_score, 30))
        
        # 2. 成交量活跃度 (20分)
        vol_score = 50  # 基础分
        vol_ratio = result["volume_analysis"]["volume_ratio"]
        
        if 1.0 <= vol_ratio <= 2.0:
            vol_score = 80  # 温和放量
        elif 0.8 <= vol_ratio < 1.0:
            vol_score = 60  # 缩量
        elif vol_ratio > 2.0:
            vol_score = 70  # 明显放量
        elif vol_ratio < 0.5:
            vol_score = 30  # 严重缩量
        
        scores.append(("成交量", vol_score, 20))
        
        # 3. 价格位置分 (15分) - 逆向思维
        # 中等位置(30-70%)得分高，高位或低位扣分
        position = result["price_position"]
        if 30 <= position <= 70:
            price_score = 85  # 中间位置
        elif 10 <= position < 30:
            price_score = 75  # 相对低位
        elif 70 < position <= 90:
            price_score = 60  # 相对高位
        elif position < 10:
            price_score = 50  # 极低可能超跌
        else:
            price_score = 30  # 极高回调风险
        
        scores.append(("价格位置", price_score, 15))
        
        # 4. 换手率分 (15分)
        turnover = result["turnover_rate"]
        if 1 <= turnover <= 5:
            turnover_score = 90  # 活跃适中
        elif 0.5 <= turnover < 1:
            turnover_score = 70  # 活跃度偏低
        elif 5 < turnover <= 10:
            turnover_score = 60  # 偏高
        elif turnover > 10:
            turnover_score = 40  # 过热
        else:
            turnover_score = 50  # 低迷
        
        scores.append(("换手率", turnover_score, 15))
        
        # 5. 估值分 (10分)
        val_score = 50
        pe = result.get("pe", 0)
        pb = result.get("pb", 0)
        
        if 0 < pe <= 20:
            val_score = 90  # 低估
        elif 20 < pe <= 40:
            val_score = 75  # 合理
        elif 40 < pe <= 80:
            val_score = 55  # 偏高
        elif pe > 80:
            val_score = 35  # 高估
        elif pe <= 0:
            val_score = 40  # 亏损股
        
        scores.append(("估值", val_score, 10))
        
        # 6. 当日涨跌分 (10分)
        change = result.get("change_pct", 0)
        if 0 < change <= 3:
            change_score = 85  # 温和上涨
        elif 3 < change <= 7:
            change_score = 75  # 明显上涨
        elif change > 7:
            change_score = 55  # 涨停附近
        elif -3 <= change < 0:
            change_score = 65  # 小幅回调
        elif change < -3:
            change_score = 40  # 明显下跌
        else:
            change_score = 50  # 平盘
        
        scores.append(("当日涨跌", change_score, 10))
        
        # 计算加权总分
        total_weight = sum(w for _, _, w in scores)
        weighted_sum = sum(s * w for _, s, w in scores)
        total_score = weighted_sum / total_weight if total_weight > 0 else 0
        
        # 保存详细分数
        result["score_details"] = [
            {"name": name, "score": score, "weight": weight}
            for name, score, weight in scores
        ]
        
        return total_score
    
    def _get_grade(self, score: float) -> str:
        """获取评级"""
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
        """获取投资建议"""
        score = result["total_score"]
        alignment = result["ma_alignment"]["alignment"]
        
        if score >= 75 and alignment == "bullish":
            return "✅ 积极建仓：技术面优秀，均线多头排列，可考虑买入"
        elif score >= 65:
            return "⚠️ 谨慎关注：技术面良好，可逢低布局"
        elif score >= 55:
            return "🔍 观察为主：技术面中性，等待更好时机"
        elif score >= 45:
            return "⚠️ 谨慎：技术面偏弱，建议观望"
        else:
            return "⛔ 回避：技术面较差，不建议参与"
    
    def get_results_summary(self) -> Dict:
        """获取结果摘要"""
        return {
            "last_update": self.last_update,
            "total_results": len(self.results),
            "top_stocks": [
                {
                    "rank": i + 1,
                    "code": r["code"],
                    "name": r["name"],
                    "price": r["price"],
                    "total_score": r["total_score"],
                    "grade": r["grade"],
                    "advice": r["advice"],
                    "industry": r.get("industry", ""),
                    "change_pct": r.get("change_pct", 0),
                }
                for i, r in enumerate(self.results)
            ]
        }


if __name__ == "__main__":
    # 测试
    screener = StockScreener()
    results = screener.run_screening(top_n=10)
    
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['name']}({r['code']}): {r['total_score']:.1f}分 {r['grade']}")
        print(f"   建议: {r['advice']}")