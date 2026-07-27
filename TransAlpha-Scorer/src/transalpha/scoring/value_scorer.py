from typing import Dict, Optional
from ..config import SCORING_CONFIG
from ..utils import score_by_bins


class ValueScorer:
    def __init__(self):
        self.config = SCORING_CONFIG["value_fundamental"]
    
    def score_pe_percentile(self, pe_percentile: Optional[float]) -> int:
        return score_by_bins(pe_percentile, self.config["pe_percentile_bins"], default=0)
    
    def score_pb_percentile(self, pb_percentile: Optional[float]) -> int:
        return score_by_bins(pb_percentile, self.config["pb_percentile_bins"], default=0)
    
    def score_roe(self, roe_ttm: Optional[float], roe_history: Optional[list] = None, consecutive_loss_years: int = 0) -> int:
        if consecutive_loss_years >= SCORING_CONFIG["blacklist"]["consecutive_loss_years"]:
            return 0
        
        base_score = score_by_bins(roe_ttm, self.config["roe_bins"], default=0)
        
        if roe_history and len(roe_history) >= 2:
            consecutive_years_above_15 = sum(1 for r in roe_history[-3:] if r and r >= 15)
            if consecutive_years_above_15 >= 3:
                base_score += self.config["roe_bonus"]["consecutive_3_years_above_15"]
            elif consecutive_years_above_15 >= 2:
                base_score += self.config["roe_bonus"]["consecutive_2_years_above_15"]
            
            if len(roe_history) >= 2:
                if roe_history[-1] and roe_history[-2]:
                    yoy_change = roe_history[-1] - roe_history[-2]
                    if yoy_change < -5:
                        base_score += self.config["roe_penalty"]["yoy_drop_above_5"]
                
                consecutive_drops = 0
                for i in range(len(roe_history) - 1, 0, -1):
                    if roe_history[i] and roe_history[i-1]:
                        if roe_history[i] < roe_history[i-1]:
                            consecutive_drops += 1
                        else:
                            break
                if consecutive_drops >= 2:
                    base_score += self.config["roe_penalty"]["consecutive_2_years_drop"]
        
        return max(0, min(10, base_score))
    
    def score_gross_margin(self, gross_margin: Optional[float], gross_margin_history: Optional[list] = None) -> int:
        base_score = score_by_bins(gross_margin, self.config["gross_margin_bins"], default=0)
        
        if gross_margin_history and len(gross_margin_history) >= 2:
            if gross_margin_history[-1] and gross_margin_history[-2]:
                yoy_change = gross_margin_history[-1] - gross_margin_history[-2]
                if yoy_change >= 5:
                    base_score += self.config["gross_margin_bonus"]["yoy_increase_above_5"]
                elif yoy_change <= -5:
                    base_score += self.config["gross_margin_penalty"]["yoy_drop_above_5"]
            
            consecutive_drops = 0
            for i in range(len(gross_margin_history) - 1, 0, -1):
                if gross_margin_history[i] and gross_margin_history[i-1]:
                    if gross_margin_history[i] < gross_margin_history[i-1]:
                        consecutive_drops += 1
                    else:
                        break
            if consecutive_drops >= 2:
                base_score += self.config["gross_margin_penalty"]["consecutive_2_years_drop"]
        
        return max(0, min(10, base_score))
    
    def score_net_margin(self, net_margin: Optional[float]) -> int:
        return score_by_bins(net_margin, self.config["net_margin_bins"], default=0)
    
    def score_debt_ratio(self, debt_ratio: Optional[float], industry: str = "") -> int:
        score = score_by_bins(debt_ratio, self.config["debt_ratio_bins"], default=9)
        
        if industry and debt_ratio is not None:
            if "银行" in industry or "证券" in industry or "保险" in industry:
                adjusted_ratio = min(debt_ratio / 90 * 100, 100)
                score = score_by_bins(adjusted_ratio, self.config["debt_ratio_bins"], default=9)
            elif "电力" in industry or "钢铁" in industry or "煤炭" in industry:
                if debt_ratio <= 70:
                    score = max(score, 5)
        
        return score
    
    def score_cash_flow(self, cash_flow_status: str) -> int:
        bins = self.config["cash_flow_bins"]
        scores = self.config["cash_flow_scores"]
        if cash_flow_status in bins:
            return scores[bins.index(cash_flow_status)]
        return 0
    
    def score_growth_stability(self, growth_status: str) -> int:
        bins = self.config["growth_stability_bins"]
        scores = self.config["growth_stability_scores"]
        if growth_status in bins:
            return scores[bins.index(growth_status)]
        return 0
    
    def score_earnings_quality(self, roe_score: int, cash_flow_score: int, growth_stability_score: int) -> float:
        weights = self.config["earnings_quality_weights"]
        return (
            roe_score * weights["roe_score"] +
            cash_flow_score * weights["cash_flow_score"] +
            growth_stability_score * weights["growth_stability_score"]
        )
    
    def calculate_value_fundamental_score(self, financial_data: Dict, pe_percentile: Optional[float] = None, pb_percentile: Optional[float] = None, industry: str = "") -> Dict:
        pe_score = self.score_pe_percentile(pe_percentile) if pe_percentile is not None else 5
        pb_score = self.score_pb_percentile(pb_percentile) if pb_percentile is not None else 5
        
        roe_score = self.score_roe(
            financial_data.get("roe_ttm"),
            financial_data.get("roe_history", []),
            financial_data.get("consecutive_loss_years", 0)
        )
        
        cash_flow_status = self._determine_cash_flow_status(financial_data.get("operating_cash_flow_history", []))
        cash_flow_score = self.score_cash_flow(cash_flow_status)
        
        growth_status = self._determine_growth_status(
            financial_data.get("revenue_history", []),
            financial_data.get("net_profit_history", [])
        )
        growth_stability_score = self.score_growth_stability(growth_status)
        
        earnings_quality_score = self.score_earnings_quality(roe_score, cash_flow_score, growth_stability_score)
        
        debt_ratio_score = self.score_debt_ratio(financial_data.get("debt_ratio"), industry)
        
        sub_weights = self.config["sub_weights"]
        total_score = (
            pe_score * sub_weights["pe_score"] +
            pb_score * sub_weights["pb_score"] +
            roe_score * sub_weights["roe_score"] +
            earnings_quality_score * sub_weights["earnings_quality_score"] +
            debt_ratio_score * sub_weights["debt_ratio_score"]
        )
        
        return {
            "pe_score": pe_score,
            "pb_score": pb_score,
            "roe_score": roe_score,
            "cash_flow_score": cash_flow_score,
            "growth_stability_score": growth_stability_score,
            "earnings_quality_score": round(earnings_quality_score, 1),
            "debt_ratio_score": debt_ratio_score,
            "value_fundamental_score": round(total_score, 1),
        }
    
    def _determine_cash_flow_status(self, cash_flow_history: Optional[list]) -> str:
        if not cash_flow_history:
            return "occasional_negative_but_overall_positive"
        
        positive_count = sum(1 for cf in cash_flow_history if cf and cf > 0)
        if positive_count == len(cash_flow_history):
            if len(cash_flow_history) >= 2:
                if cash_flow_history[-1] > cash_flow_history[-2]:
                    return "continuous_positive_and_growing"
            return "continuous_positive"
        elif positive_count >= len(cash_flow_history) * 0.7:
            return "occasional_negative_but_overall_positive"
        else:
            return "continuous_negative"
    
    def _determine_growth_status(self, revenue_history: Optional[list], profit_history: Optional[list]) -> str:
        history = revenue_history if revenue_history else profit_history
        if not history or len(history) < 2:
            return "basically_stable"
        
        consecutive_growth = 0
        consecutive_decline = 0
        for i in range(len(history) - 1, 0, -1):
            if history[i] is None or history[i-1] is None:
                break
            if history[i] > history[i-1]:
                consecutive_growth += 1
                consecutive_decline = 0
            elif history[i] < history[i-1]:
                consecutive_decline += 1
                consecutive_growth = 0
            if consecutive_growth >= 3 or consecutive_decline >= 3:
                break
        
        if consecutive_decline >= 3:
            return "continuous_decline"
        elif consecutive_decline >= 2:
            return "continuous_decline"
        elif consecutive_growth >= 3:
            return "continuous_3_years_growth"
        elif consecutive_growth >= 2:
            return "continuous_2_years_growth"
        else:
            return "basically_stable"