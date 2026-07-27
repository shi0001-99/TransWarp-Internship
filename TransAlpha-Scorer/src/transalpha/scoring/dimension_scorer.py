from typing import Dict, Optional
from ..config import SCORING_CONFIG
from ..utils import score_by_bins


class DimensionScorer:
    def __init__(self):
        self.macro_config = SCORING_CONFIG["macro"]
        self.fund_flow_config = SCORING_CONFIG["fund_flow"]
        self.event_config = SCORING_CONFIG["event_news"]
    
    def score_macro(self, macro_data: Dict) -> int:
        if not macro_data:
            return 5
        
        weights = self.macro_config["indicator_weights"]
        score = 0
        count = 0
        
        if macro_data.get("gdp_growth") is not None:
            gdp_score = score_by_bins(macro_data["gdp_growth"], self.macro_config["bins"], default=5)
            score += gdp_score * weights["gdp_growth"]
            count += weights["gdp_growth"]
        
        if macro_data.get("pmi") is not None:
            pmi_score = score_by_bins(macro_data["pmi"], self.macro_config["pmi_bins"], default=5)
            score += pmi_score * weights["pmi"]
            count += weights["pmi"]
        
        if macro_data.get("m2_growth") is not None:
            m2_score = score_by_bins(macro_data["m2_growth"], self.macro_config["bins"], default=5)
            score += m2_score * weights["m2_growth"]
            count += weights["m2_growth"]
        
        if macro_data.get("policy_score") is not None:
            policy_score = macro_data["policy_score"]
            score += policy_score * weights["policy_score"]
            count += weights["policy_score"]
        
        if count > 0:
            return round(score / count)
        return 5
    
    def score_fund_flow(self, fund_flow_data: Dict) -> int:
        if not fund_flow_data:
            return 5
        
        weights = self.fund_flow_config["indicator_weights"]
        score = 0
        count = 0
        
        if fund_flow_data.get("northbound_flow") is not None:
            north_score = score_by_bins(fund_flow_data["northbound_flow"], self.fund_flow_config["bins"], default=5)
            score += north_score * weights["northbound_flow"]
            count += weights["northbound_flow"]
        
        if fund_flow_data.get("margin_balance") is not None:
            margin_score = score_by_bins(fund_flow_data["margin_balance"], self.fund_flow_config["bins"], default=5)
            score += margin_score * weights["margin_balance"]
            count += weights["margin_balance"]
        
        if fund_flow_data.get("main_fund_flow") is not None:
            main_score = score_by_bins(fund_flow_data["main_fund_flow"], self.fund_flow_config["bins"], default=5)
            score += main_score * weights["main_fund_flow"]
            count += weights["main_fund_flow"]
        
        if count > 0:
            return round(score / count)
        return 5
    
    def score_event_news(self, event_data: Dict) -> int:
        if not event_data:
            return 5
        
        if event_data.get("event_score") is not None:
            return event_data["event_score"]
        
        earnings_surprise = event_data.get("earnings_surprise")
        if earnings_surprise is not None:
            if earnings_surprise >= 30:
                return 9
            elif earnings_surprise >= 10:
                return 7
            elif earnings_surprise >= 0:
                return 5
            elif earnings_surprise >= -10:
                return 3
            else:
                return 1
        
        recent_events = event_data.get("recent_events", [])
        events_str = " ".join(recent_events) if isinstance(recent_events, list) else str(recent_events)
        if "重大利好" in events_str:
            return 9
        elif "重大利空" in events_str:
            return 1
        elif "利好" in events_str:
            return 7
        elif "利空" in events_str:
            return 3
        
        return 5
