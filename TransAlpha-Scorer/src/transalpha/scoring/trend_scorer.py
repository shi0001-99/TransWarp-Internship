from typing import Dict, Optional
from ..config import SCORING_CONFIG
from ..utils import score_by_bins


class TrendScorer:
    def __init__(self):
        self.config = SCORING_CONFIG["trend_momentum"]
    
    def score_five_day_return(self, five_day_return: Optional[float]) -> int:
        return score_by_bins(five_day_return, self.config["five_day_return_bins"], default=0)

    def score_twenty_day_return(self, twenty_day_return: Optional[float]) -> int:
        return score_by_bins(twenty_day_return, self.config["twenty_day_return_bins"], default=0)
    
    def score_sixty_day_momentum(self, sixty_day_return: Optional[float]) -> int:
        return score_by_bins(sixty_day_return, self.config["sixty_day_momentum_bins"], default=0)
    
    def score_fund_inflow_days(self, fund_inflow_days: Optional[int]) -> int:
        if fund_inflow_days is None:
            return 0
        
        bins = self.config["fund_inflow_days_bins"]
        if fund_inflow_days <= 0:
            return bins[0][1]
        elif fund_inflow_days <= 3:
            return bins[1][1]
        elif fund_inflow_days <= 5:
            return bins[2][1]
        elif fund_inflow_days <= 7:
            return bins[3][1]
        elif fund_inflow_days <= 10:
            return bins[4][1]
        else:
            return bins[5][1]
    
    def check_chase_high(self, three_day_return: Optional[float]) -> bool:
        threshold = self.config["chase_high_threshold"]
        return three_day_return is not None and three_day_return >= threshold
    
    def calculate_trend_momentum_score(self, market_data: Dict) -> Dict:
        three_day_return = market_data.get("three_day_return")
        is_chase_high = self.check_chase_high(three_day_return)
        
        if is_chase_high:
            return {
                "five_day_return_score": 0,
                "twenty_day_return_score": 0,
                "sixty_day_momentum_score": 0,
                "fund_inflow_days_score": 0,
                "trend_momentum_score": 0,
                "is_chase_high": True,
                "three_day_return": three_day_return,
            }
        
        five_day_score = self.score_five_day_return(market_data.get("five_day_return"))
        twenty_day_score = self.score_twenty_day_return(market_data.get("twenty_day_return"))
        sixty_day_score = self.score_sixty_day_momentum(market_data.get("sixty_day_return"))
        fund_inflow_score = self.score_fund_inflow_days(market_data.get("fund_inflow_days"))
        
        sub_weights = self.config["sub_weights"]
        total_score = (
            five_day_score * sub_weights["five_day_return_score"] +
            twenty_day_score * sub_weights["twenty_day_return_score"] +
            sixty_day_score * sub_weights["sixty_day_momentum_score"] +
            fund_inflow_score * sub_weights["fund_inflow_days_score"]
        )
        
        return {
            "five_day_return_score": five_day_score,
            "twenty_day_return_score": twenty_day_score,
            "sixty_day_momentum_score": sixty_day_score,
            "fund_inflow_days_score": fund_inflow_score,
            "trend_momentum_score": round(total_score, 1),
            "is_chase_high": False,
            "three_day_return": three_day_return,
        }
