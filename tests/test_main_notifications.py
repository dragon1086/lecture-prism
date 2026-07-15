import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import db
import main


class _RecordingDispatcher:
    def __init__(self, fail_once_on=None):
        self.fail_once_on = fail_once_on
        self.started = False
        self.closed = False
        self.events = []

    async def start(self):
        self.started = True

    async def enqueue(self, event):
        if self.fail_once_on == event.event_type:
            self.fail_once_on = None
            raise RuntimeError("synthetic notification failure")
        self.events.append(event)

    async def close(self, timeout=5.0):
        self.closed = True


class MainNotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._temp_dir.name) / "prism.db"

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._temp_dir.cleanup()

    @staticmethod
    def _analysis(ticker="005930"):
        return {
            "ticker": ticker,
            "recommendation": "BUY",
            "decision": "매수",
            "buy_score": 7,
            "target_price": 120_000,
            "data_source": "yfinance",
            "data_as_of": "2026-07-10",
        }

    async def _run_with_stages(
        self, dispatcher, *, candidates=None, analysis=None, trades=None,
        dry_run=True,
    ):
        candidates = ["005930"] if candidates is None else candidates
        analysis = self._analysis() if analysis is None else analysis
        trades = [] if trades is None else trades
        with patch(
            "screening.run_screening", new=AsyncMock(return_value=candidates)
        ), patch(
            "analysis.run_analysis", new=AsyncMock(return_value=analysis)
        ), patch(
            "report_writer.write_reports", return_value=[]
        ), patch(
            "trading.run_trading", new=AsyncMock(return_value=trades)
        ), patch(
            "feedback.run_feedback", new=AsyncMock(return_value=None)
        ):
            return await main.run_pipeline(dispatcher=dispatcher, dry_run=dry_run)

    async def test_normal_run_persists_ordered_stage_lifecycle_and_flushes(self):
        dispatcher = _RecordingDispatcher()

        await self._run_with_stages(dispatcher)

        expected = [
            "pipeline.started",
            "market.checked",
            "screening.started",
            "screening.completed",
            "analysis.started",
            "analysis.completed",
            "trading.started",
            "trading.decision",
            "order.status",
            "trading.completed",
            "feedback.started",
            "feedback.saved",
            "pipeline.completed",
        ]
        self.assertTrue(dispatcher.started)
        self.assertTrue(dispatcher.closed)
        self.assertEqual(expected, [event.event_type for event in dispatcher.events])
        self.assertEqual(
            list(range(1, len(expected) + 1)),
            [event.sequence for event in dispatcher.events],
        )
        self.assertEqual("2026-07-10", dispatcher.events[5].data_as_of)
        self.assertEqual("started", dispatcher.events[0].status)
        self.assertEqual("skipped", dispatcher.events[1].status)
        self.assertEqual("started", dispatcher.events[2].status)
        self.assertNotIn("completed", {event.status for event in dispatcher.events})

        run = db.get_latest_pipeline_run()
        self.assertEqual("succeeded", run["status"])
        self.assertEqual("yfinance", run["data_source"])
        self.assertEqual("2026-07-10", run["data_as_of"])
        self.assertEqual(
            expected,
            [row["event_type"] for row in db.get_pipeline_events(run["run_id"])],
        )

    async def test_mixed_ticker_provenance_is_preserved_per_analysis(self):
        dispatcher = _RecordingDispatcher()
        analyses = [
            self._analysis("005930"),
            {
                **self._analysis("000660"),
                "data_source": "mock",
                "data_as_of": None,
            },
        ]
        with patch(
            "screening.run_screening", new=AsyncMock(return_value=["005930", "000660"])
        ), patch(
            "analysis.run_analysis", new=AsyncMock(side_effect=analyses)
        ), patch(
            "report_writer.write_reports", return_value=[]
        ), patch(
            "trading.run_trading", new=AsyncMock(return_value=[])
        ):
            await main.run_pipeline(dispatcher=dispatcher)

        snapshot = db.get_dashboard_snapshot("latest")
        self.assertEqual("mixed", snapshot["run"]["data_source"])
        self.assertEqual("2026-07-10", snapshot["run"]["data_as_of"])
        self.assertEqual(
            [("yfinance", "2026-07-10"), ("mock", None)],
            [(row["data_source"], row["data_as_of"]) for row in snapshot["analyses"]],
        )

    async def test_live_blocked_result_updates_run_and_order_truth(self):
        dispatcher = _RecordingDispatcher()
        trades = [
            {
                "ticker": "005930",
                "action": "BUY",
                "status": "live_blocked",
                "requested_qty": 5,
                "filled_qty": 0,
                "remaining_qty": 5,
                "executed": False,
                "mode": "live_blocked",
            }
        ]

        await self._run_with_stages(
            dispatcher, trades=trades, dry_run=False
        )

        self.assertEqual("live_blocked", db.get_latest_pipeline_run()["trade_state"])
        order_event = next(
            event for event in dispatcher.events if event.event_type == "order.status"
        )
        self.assertEqual("live_blocked", order_event.details["order_status"])
        self.assertEqual("skipped", order_event.status)

    async def test_each_order_result_emits_truthful_order_status_event(self):
        dispatcher = _RecordingDispatcher()
        trades = [
            {
                "ticker": "005930",
                "action": "BUY",
                "status": "accepted",
                "requested_qty": 5,
                "filled_qty": 0,
                "remaining_qty": 5,
                "executed": False,
                "mode": "kis_demo",
            },
            {
                "ticker": "000660",
                "action": "BUY",
                "status": "partial_fill",
                "requested_qty": 3,
                "filled_qty": 1,
                "remaining_qty": 2,
                "executed": False,
                "mode": "kis_demo",
            },
        ]

        await self._run_with_stages(dispatcher, trades=trades)

        order_events = [
            event for event in dispatcher.events
            if event.event_type == "order.status"
        ]
        self.assertEqual(["005930", "000660"], [e.ticker for e in order_events])
        self.assertEqual(
            ["accepted", "partial_fill"],
            [e.details["order_status"] for e in order_events],
        )
        self.assertEqual([0, 1], [e.details["filled_qty"] for e in order_events])
        self.assertTrue(all(e.run_id == trades[0]["run_id"] for e in order_events))

    async def test_broker_market_status_is_persisted_for_dashboard(self):
        dispatcher = _RecordingDispatcher()
        trades = [
            {
                "ticker": "005930",
                "action": "BUY",
                "status": "blocked",
                "requested_qty": 0,
                "filled_qty": 0,
                "remaining_qty": 0,
                "executed": False,
                "mode": "kis_demo_blocked",
                "market_status": "market_closed",
            }
        ]

        await self._run_with_stages(dispatcher, trades=trades)

        self.assertEqual(
            "market_closed", db.get_latest_pipeline_run()["market_status"]
        )

    async def test_empty_screening_still_completes_and_flushes(self):
        dispatcher = _RecordingDispatcher()

        await self._run_with_stages(dispatcher, candidates=[])

        self.assertEqual(
            [
                "pipeline.started",
                "market.checked",
                "screening.started",
                "screening.completed",
                "pipeline.completed",
            ],
            [event.event_type for event in dispatcher.events],
        )
        self.assertEqual("pipeline.completed", dispatcher.events[-1].event_type)
        self.assertTrue(dispatcher.closed)
        self.assertEqual("succeeded", db.get_latest_pipeline_run()["status"])

    async def test_stage_failure_emits_pipeline_failed_records_stage_and_closes(self):
        dispatcher = _RecordingDispatcher()
        with patch(
            "screening.run_screening", new=AsyncMock(return_value=["005930"])
        ), patch(
            "analysis.run_analysis", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await main.run_pipeline(dispatcher=dispatcher)

        self.assertEqual("pipeline.failed", dispatcher.events[-1].event_type)
        self.assertEqual("failed", dispatcher.events[-1].status)
        self.assertTrue(dispatcher.closed)
        run = db.get_latest_pipeline_run()
        self.assertEqual("failed", run["status"])
        self.assertEqual("analysis", run["failure_stage"])

    async def test_notification_failure_is_fail_open_and_final_close_still_runs(self):
        dispatcher = _RecordingDispatcher(fail_once_on="screening.started")

        await self._run_with_stages(dispatcher)

        self.assertTrue(dispatcher.closed)
        run = db.get_latest_pipeline_run()
        self.assertEqual("succeeded", run["status"])
        self.assertEqual(
            "pipeline.completed",
            db.get_pipeline_events(run["run_id"])[-1]["event_type"],
        )


if __name__ == "__main__":
    unittest.main()
