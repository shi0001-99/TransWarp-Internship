from typing import Dict, List


class PositionSizer:
    def __init__(self, total_capital: float = 1000000, max_positions: int = 5):
        self.total_capital = total_capital
        self.max_positions = max_positions
        self.base_risk_ratio = 0.15

    def suggest_single_position(self, score_result: Dict, stock_price: float = None) -> Dict:
        score = score_result.get("overall_score")
        rating = score_result.get("rating", "")

        if score_result.get("is_blacklisted") or score is None:
            return {"suggested_ratio": 0, "suggested_shares": 0, "action": "不持仓", "reason": "黑名单/数据不足"}

        if score >= 9:
            ratio, action = 0.25, "重点配置"
        elif score >= 8:
            ratio, action = 0.20, "优先配置"
        elif score >= 6:
            ratio, action = 0.15, "适度配置"
        elif score >= 4:
            ratio, action = 0.08, "轻仓观察"
        else:
            ratio, action = 0, "不持仓"

        position_value = self.total_capital * self.base_risk_ratio * (ratio / 0.15)
        shares = 0
        if stock_price and stock_price > 0:
            shares = int(position_value / stock_price / 100) * 100

        return {
            "score": score,
            "rating": rating,
            "suggested_ratio": round(ratio * 100, 1),
            "suggested_value": round(position_value, 2),
            "suggested_shares": shares,
            "action": action,
        }

    def suggest_portfolio(self, score_results: List[Dict], stock_prices: Dict[str, float] = None) -> List[Dict]:
        valid = [r for r in score_results if not r.get("is_blacklisted") and r.get("overall_score") is not None]
        valid.sort(key=lambda x: x["overall_score"], reverse=True)
        selected = valid[:self.max_positions]

        suggestions = []
        for r in selected:
            code = r.get("stock_code", "")
            price = (stock_prices or {}).get(code)
            s = self.suggest_single_position(r, price)
            s["stock_code"] = code
            s["stock_name"] = r.get("stock_name", "")
            s["overall_score"] = r["overall_score"]
            s["rating"] = r["rating"]
            suggestions.append(s)

        total_ratio = sum(s["suggested_ratio"] for s in suggestions)
        if total_ratio > 0 and total_ratio > 80:
            scale = 80 / total_ratio
            for s in suggestions:
                s["suggested_ratio"] = round(s["suggested_ratio"] * scale, 1)
                s["suggested_value"] = round(s["suggested_value"] * scale, 2)

        return suggestions
