import asyncio
import inspect
import unittest
from unittest import mock

import main
import runtime_config


def _analysis() -> dict:
    return {
        "ticker": "005930",
        "company_name": "삼성전자",
        "recommendation": "BUY",
        "decision": "진입",
        "buy_score": 8,
        "target_price": 79_700,
        "current_price": 71_200,
        "stop_loss": 66_900,
        "rationale": "추세 돌파",
        "risk": "시장 조정",
    }


def _trade() -> dict:
    return {
        "ticker": "005930",
        "action": "BUY",
        "status": "filled",
        "executed": True,
        "filled_qty": 3,
        "executed_price": 71_200,
        "quantity": 3,
        "price": 71_200,
        "reason": "추세 돌파",
        "mode": "simulation",
    }


class RecordingNotifier:
    def __init__(self):
        self.events = []

    async def screening(self, candidates, **context):
        self.events.append(("screening", list(candidates), context))
        return True

    async def analysis(self, result):
        self.events.append(("analysis", result["ticker"]))
        return True

    async def trading(self, analyses, trades):
        self.events.append(
            ("trading", [row["ticker"] for row in analyses], [row["action"] for row in trades])
        )
        return True

    async def summary(self, analyses, trades):
        self.events.append(("summary", len(analyses), len(trades)))
        return True


class ExplodingNotifier:
    async def screening(self, *args, **kwargs):
        raise RuntimeError("screening notification failed")

    async def analysis(self, *args, **kwargs):
        raise RuntimeError("analysis notification failed")

    async def trading(self, *args, **kwargs):
        raise RuntimeError("trading notification failed")

    async def summary(self, *args, **kwargs):
        raise RuntimeError("summary notification failed")


class MainNotificationContractTest(unittest.TestCase):
    def test_pipeline_accepts_injectable_notifier(self):
        self.assertIn("notifier", inspect.signature(main.run_pipeline).parameters)


class MainNotificationFlowTest(unittest.TestCase):
    def _run(self, notifier):
        analysis = _analysis()
        trade = _trade()
        feedback = mock.AsyncMock()
        with mock.patch(
            "screening.run_screening",
            new=mock.AsyncMock(return_value=["005930"]),
        ), mock.patch(
            "analysis.run_analysis",
            new=mock.AsyncMock(return_value=analysis),
        ), mock.patch(
            "report_writer.write_reports",
            return_value=[],
        ), mock.patch(
            "trading.run_trading",
            new=mock.AsyncMock(return_value=[trade]),
        ), mock.patch(
            "feedback.run_feedback",
            new=feedback,
        ):
            result = asyncio.run(
                main.run_pipeline(
                    config=runtime_config.load_runtime_config("mock"),
                    notifier=notifier,
                )
            )
        return result, feedback

    def test_pipeline_notifies_each_stage_in_execution_order(self):
        notifier = RecordingNotifier()

        result, feedback = self._run(notifier)

        self.assertIsNone(result)
        self.assertEqual(
            [event[0] for event in notifier.events],
            ["screening", "analysis", "trading", "summary"],
        )
        self.assertEqual(notifier.events[1], ("analysis", "005930"))
        feedback.assert_awaited_once()

    def test_notification_exceptions_do_not_stop_feedback_or_pipeline(self):
        result, feedback = self._run(ExplodingNotifier())

        self.assertIsNone(result)
        feedback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
