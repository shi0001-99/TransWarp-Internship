from typing import Dict, Optional
from ..config import SCORING_CONFIG
from .value_scorer import ValueScorer
from .trend_scorer import TrendScorer
from .dimension_scorer import DimensionScorer
from ..data.data_fetcher import DataFetcher


class CompositeScorer:
    def __init__(self, data_fetcher=None, value_scorer=None, trend_scorer=None, dimension_scorer=None):
        self.data_fetcher = data_fetcher or DataFetcher()
        self.value_scorer = value_scorer or ValueScorer()
        self.trend_scorer = trend_scorer or TrendScorer()
        self.dimension_scorer = dimension_scorer or DimensionScorer()
        self.weights = SCORING_CONFIG["weights"]
        self.rating_config = SCORING_CONFIG["rating"]
        self.blacklist_config = SCORING_CONFIG["blacklist"]
    
    def check_blacklist(self, stock_data: Dict) -> Dict[str, object]:
        basic_info = stock_data.get("basic_info", {})
        financial = stock_data.get("financial", {})
        market = stock_data.get("market", {})
        industry = stock_data.get("industry", {})
        
        blacklist_reasons = []
        
        if basic_info.get("is_st", False):
            blacklist_reasons.append("ST/ST*标识")
        
        if financial.get("consecutive_loss_years", 0) >= self.blacklist_config["consecutive_loss_years"]:
            blacklist_reasons.append(f"连续{self.blacklist_config['consecutive_loss_years']}年亏损")
        
        turnover_rate = market.get("turnover_rate")
        if turnover_rate is not None and turnover_rate > self.blacklist_config["turnover_threshold"]:
            blacklist_reasons.append(f"单日换手率{turnover_rate:.1f}%>20%")
        
        pe_percentile = industry.get("pe_percentile")
        if pe_percentile is not None and pe_percentile > self.blacklist_config["pe_percentile_threshold"]:
            blacklist_reasons.append(f"PE行业分位{pe_percentile:.1f}%>90%")
        
        return {
            "is_blacklisted": len(blacklist_reasons) > 0,
            "blacklist_reasons": blacklist_reasons,
        }
    
    def calculate_composite_score(self, stock_code: str) -> Dict:
        stock_data = self.data_fetcher.get_stock_score_data(stock_code)
        
        blacklist_result = self.check_blacklist(stock_data)
        if blacklist_result["is_blacklisted"]:
            return {
                "stock_code": stock_code,
                "stock_name": stock_data["basic_info"].get("stock_name", ""),
                "industry": stock_data["basic_info"].get("industry", ""),
                "is_blacklisted": True,
                "blacklist_reasons": blacklist_result["blacklist_reasons"],
                "overall_score": None,
                "rating": "黑名单剔除",
            }
        
        industry = stock_data["basic_info"].get("industry", "")
        pe_percentile = stock_data["industry"].get("pe_percentile")
        pb_percentile = stock_data["industry"].get("pb_percentile")
        
        value_result = self.value_scorer.calculate_value_fundamental_score(
            stock_data["financial"], 
            pe_percentile, 
            pb_percentile,
            industry
        )
        
        trend_result = self.trend_scorer.calculate_trend_momentum_score(stock_data["market"])
        
        macro_score = self.dimension_scorer.score_macro(stock_data["macro"])
        fund_flow_score = self.dimension_scorer.score_fund_flow(stock_data["fund_flow"])
        event_score = self.dimension_scorer.score_event_news(stock_data["event"])
        
        total_score = (
            value_result["value_fundamental_score"] * self.weights["value_fundamental"] +
            trend_result["trend_momentum_score"] * self.weights["trend_momentum"] +
            macro_score * self.weights["macro"] +
            fund_flow_score * self.weights["fund_flow"] +
            event_score * self.weights["event_news"]
        )
        
        rating = self._determine_rating(total_score)
        
        warnings = []
        three_day_return = stock_data["market"].get("three_day_return")
        if three_day_return is not None and three_day_return >= self.blacklist_config["chase_high_warn_threshold"]:
            warnings.append(f"追高预警：近3日涨幅{three_day_return:.1f}%≥15%")
        if pe_percentile is not None and pe_percentile > self.blacklist_config["pe_percentile_threshold"]:
            warnings.append(f"高估值预警：PE行业分位{pe_percentile:.1f}%>90%")
        
        return {
            "stock_code": stock_code,
            "stock_name": stock_data["basic_info"].get("stock_name", ""),
            "industry": industry,
            "is_blacklisted": False,
            "value_fundamental": {
                "pe_score": value_result["pe_score"],
                "pb_score": value_result["pb_score"],
                "roe_score": value_result["roe_score"],
                "cash_flow_score": value_result["cash_flow_score"],
                "growth_stability_score": value_result["growth_stability_score"],
                "earnings_quality_score": value_result["earnings_quality_score"],
                "debt_ratio_score": value_result["debt_ratio_score"],
                "value_fundamental_score": value_result["value_fundamental_score"],
            },
            "trend_momentum": {
                "five_day_return_score": trend_result["five_day_return_score"],
                "twenty_day_return_score": trend_result["twenty_day_return_score"],
                "sixty_day_momentum_score": trend_result["sixty_day_momentum_score"],
                "fund_inflow_days_score": trend_result["fund_inflow_days_score"],
                "trend_momentum_score": trend_result["trend_momentum_score"],
                "is_chase_high": trend_result["is_chase_high"],
                "three_day_return": trend_result["three_day_return"],
            },
            "dimensions": {
                "macro_score": macro_score,
                "fund_flow_score": fund_flow_score,
                "event_score": event_score,
            },
            "overall_score": round(total_score, 1),
            "rating": rating,
            "warnings": warnings,
            "meets_threshold": total_score >= self.rating_config["medium"],
        }
    
    def _determine_rating(self, score: float) -> str:
        if score >= self.rating_config["excellent"]:
            return "优秀"
        elif score >= self.rating_config["good"]:
            return "良好"
        elif score >= self.rating_config["medium"]:
            return "中等"
        elif score >= self.rating_config["watch"]:
            return "观察"
        else:
            return "淘汰"