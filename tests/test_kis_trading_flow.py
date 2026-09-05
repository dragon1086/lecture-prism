import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import feedback
from prism_core.domain import OrderStatus
from trading import (
    _execute_broker_order,
    _simulate_trade,
    reconcile_pending_kis_orders,
)


def decision(*, action="BUY", quantity=10):
    return {
        "action": action,
        "ticker": "005930",
        "quantity": quantity,
        "price": 70000,
        "reason": "flow test",
        "stop_loss": -0.07,
    }


class FakeKISAdapter:
    def __init__(self, order_result, inquiry=None, *, orderable=10, holdings=10):
        self.order_result = order_result
        self.inquiry = inquiry
        self.orderable = orderable
        self.holdings = holdings
        self.placed = []
        self.inquiries = []

    async def get_orderable_quantity(self, ticker, price):
        return self.orderable

    async def get_account(self):
        return {
            "positions": [
                {"pdno": "005930", "hldg_qty": str(self.holdings)}
            ],
            "summary": [],
        }

    async def place_order(self, order):
        self.placed.append(order)
        return dict(self.order_result)

    async def get_order_status(self, order_no, *, business_date=None):
        self.inquiries.append((order_no, business_date))
        if isinstance(self.inquiry, Exception):
            raise self.inquiry
        return self.inquiry if self.inquiry is not None else {"rows": []}


def accepted(order_no="1001"):
    return {
        "status": "accepted",
        "accepted": True,
        "executed": False,
        "terminal": False,
        "order_no": order_no,
        "org_no": "91252",
        "message": "accepted",
        "mode": "kis_demo",
    }


class KISTradingFlowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db_path = db.DB_PATH
        db.DB_PATH = Path(self._tmp.name) / "flow.db"
        self._env = patch.dict(
            os.environ,
            {
                "LECTURE_ENABLE_LIVE_BROKER": "1",
                "LECTURE_BROKER_MODE": "demo",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        db.DB_PATH = self._old_db_path
        self._tmp.cleanup()

    def execute(self, adapter, selected_decision=None):
        with patch(
            "brokers.factory.get_broker_adapter", return_value=adapter
        ):
            return asyncio.run(
                _execute_broker_order(
                    selected_decision or decision(), broker_name="kis"
                )
            )

    def test_buy_quantity_is_capped_by_kis_orderable_quantity(self):
        adapter = FakeKISAdapter(accepted(), orderable=3)

        result = self.execute(adapter)

        self.assertEqual(adapter.placed[0].quantity, 3)
        self.assertEqual(result["requested_qty"], 3)
        self.assertEqual(result["status"], "accepted")

    def test_buy_blocks_when_adapter_cannot_query_orderable_quantity(self):
        class MissingOrderableAdapter:
            async def place_order(self, order):
                raise AssertionError("order POST must not run")

        result = self.execute(MissingOrderableAdapter())

        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["executed"])
        self.assertEqual(result["requested_qty"], 0)

    def test_sell_quantity_is_capped_by_current_holding(self):
        adapter = FakeKISAdapter(accepted(), holdings=4)

        result = self.execute(
            adapter, decision(action="SELL", quantity=10)
        )

        self.assertEqual(adapter.placed[0].quantity, 4)
        self.assertEqual(result["requested_qty"], 4)

    def test_accepted_order_is_persisted_before_inquiry(self):
        class InspectingAdapter(FakeKISAdapter):
            async def get_order_status(inner_self, order_no, *, business_date=None):
                state = db.get_broker_order_state(inner_self.client_order_id)
                self.assertEqual(state.status, OrderStatus.ACCEPTED)
                return await super().get_order_status(
                    order_no, business_date=business_date
                )

        adapter = InspectingAdapter(accepted())
        original_place = adapter.place_order

        async def place_and_capture(order):
            adapter.client_order_id = order.client_order_id
            return await original_place(order)

        adapter.place_order = place_and_capture

        result = self.execute(adapter)

        self.assertEqual(result["status"], "accepted")
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])

    def test_accepted_response_without_full_broker_identity_becomes_unknown(self):
        incomplete = accepted()
        incomplete["org_no"] = ""
        adapter = FakeKISAdapter(incomplete)

        result = self.execute(adapter)

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])
        self.assertEqual(adapter.inquiries, [])
        state = db.get_broker_order_state(result["client_order_id"])
        self.assertEqual(state.status, OrderStatus.UNKNOWN)

    def test_partial_fill_is_not_reported_as_completed_trade(self):
        adapter = FakeKISAdapter(
            accepted(),
            {
                "rows": [
                    {
                        "odno": "1001",
                        "ord_qty": "10",
                        "tot_ccld_qty": "4",
                        "rmn_qty": "6",
                        "avg_prvs": "70100",
                    }
                ]
            },
        )

        result = self.execute(adapter)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["filled_qty"], 4)
        self.assertEqual(result["remaining_qty"], 6)
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])

    def test_inquiry_row_without_matching_order_number_is_never_attributed(self):
        adapter = FakeKISAdapter(
            accepted(),
            {
                "rows": [
                    {
                        "ord_qty": "10",
                        "tot_ccld_qty": "10",
                        "rmn_qty": "0",
                        "avg_prvs": "70100",
                    }
                ]
            },
        )

        result = self.execute(adapter)

        self.assertEqual(result["status"], "accepted")
        self.assertFalse(result["executed"])
        self.assertEqual(result["filled_qty"], 0)

    def test_filled_inquiry_is_the_only_executed_terminal_result(self):
        adapter = FakeKISAdapter(
            accepted(),
            {
                "rows": [
                    {
                        "odno": "1001",
                        "ord_qty": "10",
                        "tot_ccld_qty": "10",
                        "rmn_qty": "0",
                        "avg_prvs": "70100",
                    }
                ]
            },
        )

        result = self.execute(adapter)

        self.assertEqual(result["status"], "filled")
        self.assertTrue(result["executed"])
        self.assertTrue(result["terminal"])
        self.assertEqual(result["executed_price"], 70100)

    def test_unknown_post_is_recoverable_and_never_inquired_without_identity(self):
        adapter = FakeKISAdapter(
            {
                "status": "unknown",
                "accepted": False,
                "executed": False,
                "terminal": False,
                "order_no": None,
                "message": "timeout",
                "mode": "kis_demo",
            }
        )

        result = self.execute(adapter)

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])
        self.assertEqual(adapter.inquiries, [])
        state = db.get_broker_order_state(result["client_order_id"])
        self.assertEqual(state.status, OrderStatus.UNKNOWN)

    def test_second_cycle_never_posts_while_identityless_unknown_is_pending(self):
        adapter = FakeKISAdapter(
            {
                "status": "unknown",
                "accepted": False,
                "executed": False,
                "terminal": False,
                "order_no": None,
                "message": "timeout",
                "mode": "kis_demo",
            }
        )
        first = self.execute(adapter)
        adapter.order_result = accepted("1002")

        second = self.execute(adapter)

        self.assertEqual(first["status"], "unknown")
        self.assertEqual(second["status"], "blocked")
        self.assertEqual(second["mode"], "kis_demo_pending_order")
        self.assertEqual(len(adapter.placed), 1)

    def test_two_concurrent_cycles_atomically_admit_only_one_order(self):
        barrier = threading.Barrier(2)
        lock = threading.Lock()

        class ConcurrentAdapter(FakeKISAdapter):
            async def get_orderable_quantity(self, ticker, price):
                barrier.wait(timeout=2)
                return 10

            async def place_order(inner_self, order):
                with lock:
                    inner_self.placed.append(order)
                    order_no = str(1000 + len(inner_self.placed))
                return accepted(order_no)

        adapter = ConcurrentAdapter(accepted())

        with patch(
            "brokers.factory.get_broker_adapter", return_value=adapter
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        asyncio.run,
                        _execute_broker_order(decision(), broker_name="kis"),
                    )
                    for _ in range(2)
                ]
                results = [future.result(timeout=5) for future in futures]

        self.assertEqual(len(adapter.placed), 1)
        self.assertEqual(
            sorted(result["status"] for result in results),
            ["accepted", "blocked"],
        )

    def test_unhandled_kis_post_exception_is_persisted_as_unknown(self):
        class RaisingAdapter(FakeKISAdapter):
            async def place_order(self, order):
                raise ConnectionError("connection dropped")

        result = self.execute(RaisingAdapter(accepted()))

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])
        self.assertIn("client_order_id", result)
        state = db.get_broker_order_state(result["client_order_id"])
        self.assertEqual(state.status, OrderStatus.UNKNOWN)

    def test_restart_reconciliation_finishes_persisted_accepted_order(self):
        adapter = FakeKISAdapter(accepted(), TimeoutError("first inquiry timeout"))
        first = self.execute(adapter)
        self.assertEqual(first["status"], "accepted")

        adapter.inquiry = {
            "rows": [
                {
                    "odno": "1001",
                    "ord_qty": "10",
                    "tot_ccld_qty": "10",
                    "rmn_qty": "0",
                    "avg_prvs": "70200",
                }
            ]
        }
        recovered = asyncio.run(
            reconcile_pending_kis_orders(adapter=adapter, mode="demo")
        )

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["status"], "filled")
        self.assertTrue(recovered[0]["executed"])
        state = db.get_broker_order_state(first["client_order_id"])
        self.assertEqual(state.status, OrderStatus.FILLED)

    def test_feedback_records_filled_buy_without_inventing_outcome_lesson(self):
        filled = {
            **decision(quantity=2),
            "status": "filled",
            "executed": True,
            "filled_qty": 2,
        }
        pending = {
            **decision(quantity=2),
            "status": "accepted",
            "executed": False,
            "filled_qty": 0,
        }
        impossible_zero_fill = {
            **decision(quantity=2),
            "status": "filled",
            "executed": True,
            "filled_qty": 0,
        }
        saved_trades = []
        saved_lessons = []

        with (
            patch("feedback.db.save_analysis"),
            patch("feedback.db.save_trade", side_effect=saved_trades.append),
            patch(
                "feedback.db.save_lesson",
                side_effect=lambda **values: saved_lessons.append(values),
            ),
        ):
            asyncio.run(
                feedback.run_feedback(
                    [pending, impossible_zero_fill, filled],
                    [{"ticker": "005930", "rationale": "breakout"}],
                )
            )

        self.assertEqual(saved_trades, [filled])
        self.assertEqual(saved_lessons, [])

    def test_simulation_remains_a_completed_fill_for_feedback(self):
        result = _simulate_trade(decision(quantity=2))

        self.assertEqual(result["status"], "filled")
        self.assertTrue(result["accepted"])
        self.assertTrue(result["executed"])
        self.assertTrue(result["terminal"])
        self.assertEqual(result["requested_qty"], 2)
        self.assertEqual(result["filled_qty"], 2)
        self.assertEqual(result["remaining_qty"], 0)


if __name__ == "__main__":
    unittest.main()
