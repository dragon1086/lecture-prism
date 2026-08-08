import asyncio
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import operations
import operations_runtime


class OperationsTest(unittest.TestCase):
    def test_holding_monitor_only_executes_exit_decisions(self):
        holdings = [
            {
                "ticker": "005930",
                "entry_price": 80_000,
                "quantity": 2,
                "high_since_entry": 82_000,
            }
        ]
        sell = {
            "action": "SELL",
            "ticker": "005930",
            "quantity": 2,
            "price": 72_000,
            "reason": "손절",
        }

        with mock.patch(
            "operations.trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
        ), mock.patch(
            "operations.trading._load_holding_prices",
            new=mock.AsyncMock(return_value={"005930": 72_000}),
        ), mock.patch(
            "operations.trading._persist_holding_highs",
            new=mock.AsyncMock(),
        ), mock.patch(
            "operations.trading.run_exit_check",
            new=mock.AsyncMock(return_value=[sell]),
        ), mock.patch(
            "operations.trading._execute_decision",
            new=mock.AsyncMock(return_value={**sell, "status": "filled"}),
        ), mock.patch(
            "feedback.run_feedback",
            new=mock.AsyncMock(),
        ) as run_feedback:
            results = asyncio.run(operations.run_holding_monitor(dry_run=True))

        self.assertEqual([row["action"] for row in results], ["SELL"])
        run_feedback.assert_awaited_once_with(results, [])

    def test_reconciliation_is_read_only_and_isolates_provider_failure(self):
        with mock.patch(
            "operations.trading.reconcile_pending_kis_orders",
            new=mock.AsyncMock(side_effect=RuntimeError("temporary outage")),
        ):
            result = asyncio.run(operations.run_order_reconciliation("kis"))

        self.assertEqual(result["broker"], "kis")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["orders"], [])

    def test_reconciliation_rejects_broker_without_pending_order_reader(self):
        result = asyncio.run(operations.run_order_reconciliation("kiwoom"))

        self.assertEqual(result["broker"], "kiwoom")
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["orders"], [])

    def test_status_output_reports_operations_snapshot_without_secret_values(self):
        self.assertTrue(hasattr(operations, "print_status"))
        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            store.record_scheduler_status("running", pid=9876, heartbeat_at="2026-08-08T09:30:00+00:00")
            store.record_job_success("monitor", "2026-08-08T09:31:00+00:00")
            out = StringIO()

            operations.print_status(
                state_store=store,
                output=out,
                profile="live",
                execute_broker=True,
                env={
                    "LECTURE_ENABLE_LIVE_BROKER": "1",
                    "LECTURE_ALLOW_REAL_BROKER": "1",
                    "LECTURE_UNATTENDED_LIVE_ACK": operations_runtime.LIVE_BROKER_UNATTENDED_ACK,
                    "OPENAI_API_KEY": "sk-secret-operations-status",
                    "KIS_APP_SECRET": "kis-secret-operations-status",
                },
                unresolved_order_count=lambda: 2,
                last_data_timestamp=lambda: "2026-08-08T09:29:00+00:00",
                now=lambda: "2026-08-08T09:32:00+00:00",
            )

        text = out.getvalue()
        self.assertIn("profile: live", text)
        self.assertIn("account_mode: real", text)
        self.assertIn("scheduler_pid: 9876", text)
        self.assertIn("scheduler_heartbeat: 2026-08-08T09:30:00+00:00", text)
        self.assertIn("monitor: success", text)
        self.assertIn("unresolved_order_count: 2", text)
        self.assertIn("last_data_timestamp: 2026-08-08T09:29:00+00:00", text)
        self.assertIn("next_jobs:", text)
        self.assertNotIn("sk-secret-operations-status", text)
        self.assertNotIn("kis-secret-operations-status", text)
        self.assertNotIn(operations_runtime.LIVE_BROKER_UNATTENDED_ACK, text)


if __name__ == "__main__":
    unittest.main()
