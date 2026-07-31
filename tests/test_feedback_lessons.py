import asyncio
import unittest
from unittest import mock

import feedback


class FeedbackLessonTest(unittest.TestCase):
    def test_lesson_uses_analysis_values_without_intermediate_trade_plan(self):
        result = {"ticker": "005930", "action": "BUY", "executed": True}
        analysis = {
            "buy_score": 8,
            "risk_reward_ratio": 2.0,
            "stop_loss": 66_900,
            "rationale": "거래량을 동반한 추세 돌파",
        }

        lesson = asyncio.run(
            feedback._extract_lesson(result, analysis, "JUDGMENT")
        )

        self.assertIn("매수점수 8/10", lesson)
        self.assertIn("손익비 2.0:1", lesson)
        self.assertIn("손절가 66,900원", lesson)
        self.assertNotIn("trade_plan", lesson)

    def test_filled_buy_is_recorded_without_inventing_outcome_lesson(self):
        buy = {
            "ticker": "005930",
            "action": "BUY",
            "status": "filled",
            "executed": True,
            "filled_qty": 2,
        }
        analysis = {"ticker": "005930", "buy_score": 8}

        with mock.patch("feedback.db.save_analysis"), mock.patch(
            "feedback.db.save_trade"
        ) as save_trade, mock.patch("feedback.db.save_lesson") as save_lesson:
            asyncio.run(feedback.run_feedback([buy], [analysis]))

        save_trade.assert_called_once_with(buy)
        save_lesson.assert_not_called()

    def test_filled_sell_creates_short_outcome_lesson(self):
        sell = {
            "ticker": "005930",
            "action": "SELL",
            "status": "filled",
            "executed": True,
            "filled_qty": 2,
            "reason": "트레일링 스탑",
        }
        analysis = {
            "ticker": "005930",
            "buy_score": 8,
            "risk_reward_ratio": 2.0,
            "stop_loss": 66_900,
        }

        with mock.patch("feedback.db.save_analysis"), mock.patch(
            "feedback.db.save_trade"
        ), mock.patch("feedback.db.save_lesson") as save_lesson:
            asyncio.run(feedback.run_feedback([sell], [analysis]))

        self.assertEqual(save_lesson.call_count, 1)
        self.assertEqual(save_lesson.call_args.kwargs["tier"], "short")


if __name__ == "__main__":
    unittest.main()
