import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from transalpha.scoring.value_scorer import ValueScorer
from transalpha.scoring.trend_scorer import TrendScorer
from transalpha.scoring.dimension_scorer import DimensionScorer


class TestValueScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = ValueScorer()
    
    def test_pe_percentile_scoring(self):
        self.assertEqual(self.scorer.score_pe_percentile(5), 10)
        self.assertEqual(self.scorer.score_pe_percentile(15), 9)
        self.assertEqual(self.scorer.score_pe_percentile(25), 8)
        self.assertEqual(self.scorer.score_pe_percentile(45), 6)
        self.assertEqual(self.scorer.score_pe_percentile(50), 5)
        self.assertEqual(self.scorer.score_pe_percentile(75), 3)
        self.assertEqual(self.scorer.score_pe_percentile(95), 0)
    
    def test_roe_scoring(self):
        self.assertEqual(self.scorer.score_roe(25), 9)
        self.assertEqual(self.scorer.score_roe(18), 7)
        self.assertEqual(self.scorer.score_roe(12), 5)
        self.assertEqual(self.scorer.score_roe(3), 1)
        self.assertEqual(self.scorer.score_roe(-5), 0)
    
    def test_debt_ratio_scoring(self):
        self.assertEqual(self.scorer.score_debt_ratio(30), 9)
        self.assertEqual(self.scorer.score_debt_ratio(55), 5)
        self.assertEqual(self.scorer.score_debt_ratio(85), 0)


class TestTrendScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = TrendScorer()
    
    def test_five_day_return_scoring(self):
        self.assertEqual(self.scorer.score_five_day_return(-10), 0)
        self.assertEqual(self.scorer.score_five_day_return(-3), 2)
        self.assertEqual(self.scorer.score_five_day_return(-1), 4)
        self.assertEqual(self.scorer.score_five_day_return(1), 6)
        self.assertEqual(self.scorer.score_five_day_return(3), 8)
        self.assertEqual(self.scorer.score_five_day_return(6), 10)

    def test_twenty_day_return_scoring(self):
        self.assertEqual(self.scorer.score_twenty_day_return(-15), 0)
        self.assertEqual(self.scorer.score_twenty_day_return(-7), 1)
        self.assertEqual(self.scorer.score_twenty_day_return(-2), 3)
        self.assertEqual(self.scorer.score_twenty_day_return(2), 5)
        self.assertEqual(self.scorer.score_twenty_day_return(5), 7)
        self.assertEqual(self.scorer.score_twenty_day_return(8), 8)
        self.assertEqual(self.scorer.score_twenty_day_return(12), 9)
        self.assertEqual(self.scorer.score_twenty_day_return(20), 10)
    
    def test_chase_high_check(self):
        self.assertTrue(self.scorer.check_chase_high(15))
        self.assertTrue(self.scorer.check_chase_high(20))
        self.assertFalse(self.scorer.check_chase_high(14))
        self.assertFalse(self.scorer.check_chase_high(5))


class TestDimensionScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = DimensionScorer()
    
    def test_macro_scoring(self):
        macro_data = {"gdp_growth": 5, "pmi": 52, "m2_growth": 10, "policy_score": 7}
        score = self.scorer.score_macro(macro_data)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 10)
    
    def test_event_scoring(self):
        event_data = {"event_score": 8}
        self.assertEqual(self.scorer.score_event_news(event_data), 8)

    def test_macro_pmi_scoring(self):
        low = self.scorer.score_macro({"pmi": 42})
        mid = self.scorer.score_macro({"pmi": 52})
        high = self.scorer.score_macro({"pmi": 58})
        self.assertLess(low, mid)
        self.assertLess(mid, high)

    def test_fund_flow_default(self):
        self.assertEqual(self.scorer.score_fund_flow({}), 5)


class TestCompositeScorer(unittest.TestCase):
    def setUp(self):
        from unittest.mock import MagicMock
        from transalpha.scoring.composite_scorer import CompositeScorer
        from transalpha.scoring.value_scorer import ValueScorer
        from transalpha.scoring.trend_scorer import TrendScorer
        from transalpha.scoring.dimension_scorer import DimensionScorer

        self.mock_fetcher = MagicMock()
        self.mock_fetcher.get_stock_score_data.return_value = {
            "basic_info": {"stock_code": "000001.SZ", "stock_name": "平安银行", "industry": "银行",
                           "industry_code": "BK0477", "is_st": False},
            "financial": {"consecutive_loss_years": 0, "pe_ttm": 8, "pb": 1.2, "roe_ttm": 12,
                          "roe_history": [10, 11, 12], "gross_margin": 35, "gross_margin_history": [30, 33, 35],
                          "net_margin": 15, "net_margin_history": [12, 14, 15],
                          "debt_ratio": 60, "operating_cash_flow": 1e9,
                          "operating_cash_flow_history": [1e8, 2e8, 1e9],
                          "revenue_history": [1e9, 1.1e9, 1.2e9], "net_profit_history": [1e8, 1.1e8, 1.2e8]},
            "market": {"five_day_return": 1.5, "twenty_day_return": 3.5, "sixty_day_return": 8,
                       "three_day_return": 2, "turnover_rate": 1.5, "fund_inflow_days": 3},
            "industry": {"pe_percentile": 30, "pb_percentile": 40},
            "macro": {"gdp_growth": 5.0, "pmi": 52, "m2_growth": 8.5, "policy_score": 6},
            "fund_flow": {},
            "event": {},
        }
        self.scorer = CompositeScorer(data_fetcher=self.mock_fetcher)

    def test_normal_stock_scoring(self):
        result = self.scorer.calculate_composite_score("000001.SZ")
        self.assertFalse(result["is_blacklisted"])
        self.assertIsNotNone(result["overall_score"])
        self.assertIn("rating", result)
        self.assertGreaterEqual(result["overall_score"], 0)
        self.assertLessEqual(result["overall_score"], 10)

    def test_st_stock_blacklisted(self):
        self.mock_fetcher.get_stock_score_data.return_value["basic_info"]["is_st"] = True
        result = self.scorer.calculate_composite_score("000001.SZ")
        self.assertTrue(result["is_blacklisted"])
        self.assertEqual(result["rating"], "黑名单剔除")

    def test_consecutive_loss_blacklisted(self):
        self.mock_fetcher.get_stock_score_data.return_value["financial"]["consecutive_loss_years"] = 2
        result = self.scorer.calculate_composite_score("000001.SZ")
        self.assertTrue(result["is_blacklisted"])

    def test_chase_high_warning(self):
        self.mock_fetcher.get_stock_score_data.return_value["market"]["three_day_return"] = 16
        result = self.scorer.calculate_composite_score("000001.SZ")
        self.assertFalse(result["is_blacklisted"])
        self.assertTrue(any("追高预警" in w for w in result["warnings"]))

    def test_high_turnover_blacklisted(self):
        self.mock_fetcher.get_stock_score_data.return_value["market"]["turnover_rate"] = 25
        result = self.scorer.calculate_composite_score("000001.SZ")
        self.assertTrue(result["is_blacklisted"])

    def test_high_pe_percentile_blacklisted(self):
        self.mock_fetcher.get_stock_score_data.return_value["industry"]["pe_percentile"] = 95
        result = self.scorer.calculate_composite_score("000001.SZ")
        self.assertTrue(result["is_blacklisted"])

    def test_high_pe_blacklisted(self):
        self.mock_fetcher.get_stock_score_data.return_value["industry"]["pe_percentile"] = 95
        result = self.scorer.calculate_composite_score("000001.SZ")
        self.assertTrue(result["is_blacklisted"])
        self.assertTrue(any("PE行业分位" in r for r in result["blacklist_reasons"]))

    def test_stock_meets_threshold(self):
        result = self.scorer.calculate_composite_score("000001.SZ")
        self.assertIn("meets_threshold", result)

    def test_rating_values(self):
        from transalpha.config import SCORING_CONFIG
        rc = SCORING_CONFIG["rating"]
        # Force a high score scenario
        self.mock_fetcher.get_stock_score_data.return_value["financial"]["debt_ratio"] = 30
        result = self.scorer.calculate_composite_score("000001.SZ")
        if result["overall_score"] and result["overall_score"] >= rc["good"]:
            self.assertIn(result["rating"], ["优秀", "良好"])


class TestPositionSizer(unittest.TestCase):
    def setUp(self):
        from transalpha.scoring.position_sizer import PositionSizer
        self.sizer = PositionSizer(total_capital=1000000, max_positions=5)

    def _make_result(self, score, blacklisted=False):
        return {
            "stock_code": "000001.SZ",
            "stock_name": "平安银行",
            "overall_score": score,
            "rating": "优秀" if score and score >= 9 else ("良好" if score and score >= 8 else "中等"),
            "is_blacklisted": blacklisted,
        }

    def test_blacklisted_zero_position(self):
        pos = self.sizer.suggest_single_position(self._make_result(8, blacklisted=True), 10)
        self.assertEqual(pos["suggested_ratio"], 0)
        self.assertEqual(pos["action"], "不持仓")

    def test_excellent_score_25pct(self):
        pos = self.sizer.suggest_single_position(self._make_result(9), 20)
        self.assertEqual(pos["suggested_ratio"], 25)
        self.assertEqual(pos["action"], "重点配置")

    def test_good_score_20pct(self):
        pos = self.sizer.suggest_single_position(self._make_result(8), 20)
        self.assertEqual(pos["suggested_ratio"], 20)

    def test_medium_score_15pct(self):
        pos = self.sizer.suggest_single_position(self._make_result(7), 20)
        self.assertEqual(pos["suggested_ratio"], 15)

    def test_watch_score_8pct(self):
        pos = self.sizer.suggest_single_position(self._make_result(5), 20)
        self.assertEqual(pos["suggested_ratio"], 8)

    def test_reject_score_0pct(self):
        pos = self.sizer.suggest_single_position(self._make_result(2), 20)
        self.assertEqual(pos["suggested_ratio"], 0)
        self.assertEqual(pos["action"], "不持仓")

    def test_shares_calculated(self):
        pos = self.sizer.suggest_single_position(self._make_result(9), 20)
        expected_value = 1000000 * 0.15 * (0.25 / 0.15)
        expected_shares = int(expected_value / 20 / 100) * 100
        self.assertEqual(pos["suggested_shares"], expected_shares)

    def test_portfolio_top_n_selected(self):
        results = [self._make_result(9, blacklisted=True),
                   self._make_result(8),
                   self._make_result(7),
                   self._make_result(6),
                   self._make_result(5),
                   self._make_result(4)]
        prices = {"000001.SZ": 10}
        suggestions = self.sizer.suggest_portfolio(results, prices)
        self.assertLessEqual(len(suggestions), 5)
        for s in suggestions:
            self.assertNotEqual(s["action"], "不持仓")

    def test_portfolio_total_ratio_capped(self):
        results = [self._make_result(9), self._make_result(9),
                   self._make_result(9), self._make_result(9)]
        suggestions = self.sizer.suggest_portfolio(results)
        total_ratio = sum(s["suggested_ratio"] for s in suggestions)
        self.assertLessEqual(total_ratio, 80)


if __name__ == "__main__":
    unittest.main()