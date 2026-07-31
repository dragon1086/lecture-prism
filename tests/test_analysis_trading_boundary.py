import unittest

import analysis
import analysis_agents
import trading


def _buy_analysis(*, decision: str = "보류") -> dict:
    return {
        "ticker": "005930",
        "sector": "반도체",
        "recommendation": "BUY",
        "decision": decision,
        "buy_score": 8,
        "current_price": 70_000,
        "target_price": 80_500,
        "stop_loss": 65_100,
        "risk_reward_ratio": 2.1,
        "rationale": "가격·거래량과 재무 근거가 함께 확인됨",
    }


class AnalysisTradingBoundaryTest(unittest.TestCase):
    def test_trading_does_not_trust_analysis_decision_label(self):
        decision = trading._decide_position(
            _buy_analysis(decision="보류"),
            {"slots_used": 0, "cash": 10_000_000, "holdings": []},
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision["action"], "BUY")

    def test_technical_prompt_stays_in_evidence_analysis_scope(self):
        prompt = analysis_agents.AGENT_SPECS["technical"].prompt
        self.assertNotIn("CANSLIM", prompt.upper())
        self.assertNotIn("컵&핸들", prompt)
        self.assertIn("주가", prompt)
        self.assertIn("거래량", prompt)
        self.assertIn("매수·매도 여부", prompt)
        self.assertIn("판단하지 마세요", prompt)
        self.assertNotIn("Enter", prompt)

    def test_trading_rejects_non_buy_recommendation_even_with_entry_label(self):
        candidate = _buy_analysis(decision="진입")
        candidate["recommendation"] = "HOLD"

        self.assertIsNone(
            trading._decide_position(
                candidate,
                {"slots_used": 0, "cash": 10_000_000, "holdings": []},
            )
        )

    def test_entry_decision_carries_bounded_memory_reference(self):
        candidate = _buy_analysis(decision="보류")
        candidate["memory_lessons"] = [
            "같은 종목 최근 손절 뒤에는 재진입 조건을 다시 확인한다."
        ]

        decision = trading._decide_position(
            candidate,
            {"slots_used": 0, "cash": 10_000_000, "holdings": []},
        )

        self.assertEqual(decision["memory_lessons"], candidate["memory_lessons"])


if __name__ == "__main__":
    unittest.main()
