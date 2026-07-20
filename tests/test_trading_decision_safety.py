import unittest

import trading


class TradingDecisionSafetyTest(unittest.TestCase):
    def test_high_score_hold_cannot_create_buy_order(self):
        analysis = {
            "ticker": "005930",
            "recommendation": "HOLD",
            "decision": "보류",
            "buy_score": 10,
            "current_price": 70000,
        }
        portfolio = {"slots_used": 0, "cash": 10_000_000}

        self.assertIsNone(trading._decide_position(analysis, portfolio))

    def test_buy_requires_quantitative_decision_and_score_together(self):
        analysis = {
            "ticker": "005930",
            "recommendation": "BUY",
            "decision": "진입",
            "buy_score": 8,
            "current_price": 70000,
        }
        portfolio = {"slots_used": 0, "cash": 10_000_000}

        self.assertIsNotNone(trading._decide_position(analysis, portfolio))


if __name__ == "__main__":
    unittest.main()
