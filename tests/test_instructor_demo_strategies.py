import unittest
from unittest import mock

import data_source
import analysis
import screening
import trading


class TurtleInstructorDemoTests(unittest.TestCase):
    def test_breakout_requires_the_latest_close_to_exceed_the_previous_twenty(self):
        self.assertTrue(hasattr(screening, "_is_turtle_breakout"))
        prior = [100 + index for index in range(20)]

        self.assertTrue(screening._is_turtle_breakout(prior + [121]))
        self.assertFalse(screening._is_turtle_breakout(prior + [119]))
        self.assertFalse(screening._is_turtle_breakout([100, 101]))

    def test_ten_day_low_exit_is_checked_before_trailing_and_target(self):
        holding = {
            "ticker": "005930",
            "entry_price": 80,
            "high_since_entry": 130,
            "quantity": 3,
            "recent_lows": [96, 95, 94, 93, 92, 91, 90, 89, 88, 87],
        }

        decision = trading._decide_exit(holding, 86)

        self.assertEqual("SELL", decision["action"])
        self.assertIn("10일 저가 이탈", decision["reason"])


class AtrInstructorDemoTests(unittest.TestCase):
    def _analysis(self, atr):
        return {
            "ticker": "005930",
            "recommendation": "BUY",
            "buy_score": 8,
            "current_price": 100.0,
            "target_price": 130.0,
            "stop_loss": 90.0,
            "risk_reward_ratio": 3.0,
            "atr": atr,
        }

    def test_atr_uses_high_low_and_previous_close_true_ranges(self):
        self.assertTrue(hasattr(data_source, "calculate_atr"))

        result = data_source.calculate_atr(
            highs=[101, 103, 104, 106],
            lows=[99, 100, 100, 103],
            closes=[100, 102, 101, 104],
            period=3,
        )

        self.assertEqual(4.0, result)

    def test_mock_data_exposes_ohlc_history_and_atr(self):
        with mock.patch.dict("os.environ", {"LECTURE_PROFILE": "mock"}, clear=False):
            data = data_source.fetch_stock_data("005930")

        self.assertGreaterEqual(len(data["highs"]), 15)
        self.assertEqual(len(data["highs"]), len(data["lows"]))
        self.assertEqual(len(data["highs"]), len(data["closes"]))
        self.assertGreater(data["atr14"], 0)

    def test_larger_atr_reduces_quantity_and_moves_stop_farther_away(self):
        portfolio = {"cash": 10_000_000, "slots_used": 9, "holdings": []}

        narrow = trading._decide_position(self._analysis(5.0), portfolio)
        wide = trading._decide_position(self._analysis(10.0), portfolio)

        self.assertGreater(narrow["quantity"], wide["quantity"])
        self.assertGreater(narrow["stop_loss"], wide["stop_loss"])
        self.assertEqual(90.0, narrow["stop_loss"])
        self.assertEqual(80.0, wide["stop_loss"])

    def test_explicit_nonpositive_atr_rejects_entry(self):
        portfolio = {"cash": 10_000_000, "slots_used": 0, "holdings": []}

        self.assertIsNone(trading._decide_position(self._analysis(0), portfolio))


class MarketRegimeInstructorDemoTests(unittest.TestCase):
    def _analysis(self, regime, *, score=7, risk_reward=1.8):
        return {
            "ticker": "005930",
            "recommendation": "BUY",
            "buy_score": score,
            "current_price": 100.0,
            "target_price": 118.0,
            "stop_loss": 90.0,
            "risk_reward_ratio": risk_reward,
            "market_regime": regime,
        }

    def test_kospi_twenty_day_return_maps_to_three_regimes(self):
        self.assertTrue(hasattr(analysis, "_classify_market_regime"))

        self.assertEqual(
            "strong",
            analysis._classify_market_regime({"KOSPI": {"ret_20d": 2.5}}),
        )
        self.assertEqual(
            "sideways",
            analysis._classify_market_regime({"KOSPI": {"ret_20d": 0.4}}),
        )
        self.assertEqual(
            "weak",
            analysis._classify_market_regime({"KOSPI": {"ret_20d": -2.5}}),
        )

    def test_sideways_regime_reduces_the_maximum_entry_slots(self):
        portfolio = {"cash": 10_000_000, "slots_used": 8, "holdings": []}

        strong = trading._decide_position(self._analysis("strong"), portfolio)
        sideways = trading._decide_position(self._analysis("sideways"), portfolio)

        self.assertIsNotNone(strong)
        self.assertIsNone(sideways)

    def test_weak_regime_raises_score_and_risk_reward_gates(self):
        portfolio = {"cash": 10_000_000, "slots_used": 0, "holdings": []}

        strong = trading._decide_position(self._analysis("strong"), portfolio)
        weak = trading._decide_position(self._analysis("weak"), portfolio)

        self.assertIsNotNone(strong)
        self.assertIsNone(weak)


if __name__ == "__main__":
    unittest.main()
