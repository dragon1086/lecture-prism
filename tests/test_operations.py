import asyncio
import unittest
from unittest import mock

import operations


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


if __name__ == "__main__":
    unittest.main()
