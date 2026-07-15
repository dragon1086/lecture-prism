import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import feedback
import trading
from brokers.base import BrokerOrder


def _decision(**overrides):
    value = {
        "action": "BUY",
        "ticker": "005930",
        "quantity": 10,
        "price": 10_000,
        "reason": "테스트 주문",
        "stop_loss": -0.07,
    }
    value.update(overrides)
    return value


def _analysis():
    return {
        "ticker": "005930",
        "recommendation": "BUY",
        "buy_score": 8,
        "current_price": 10_000,
        "rationale": "테스트 분석",
    }


def _stored_order(**overrides):
    value = {
        "broker": "kis",
        "mode": "paper",
        "client_request_id": "request-1",
        "order_date": "2026-07-15",
        "org_no": "01",
        "order_no": "100",
        "ticker": "005930",
        "side": "BUY",
        "status": "accepted",
        "requested_qty": 5,
        "filled_qty": 0,
        "remaining_qty": 5,
        "requested_price": 70_000,
        "avg_fill_price": None,
    }
    value.update(overrides)
    return value


class _FakeKISAdapter:
    name = "kis"
    mode = "demo"

    def __init__(
        self,
        *,
        account=None,
        orderable=None,
        order_result=None,
        inquiry_results=None,
        inquiry_error=None,
    ):
        self.account = account or {
            "output1": [],
            "output2": [{"dnca_tot_amt": "1000000"}],
        }
        self.orderable = orderable or {
            "nrcvb_buy_qty": "100",
            "ord_psbl_cash": "1000000",
        }
        self.order_result = order_result or {
            "success": True,
            "status": "accepted",
            "accepted": True,
            "executed": False,
            "terminal": False,
            "order_no": "100",
            "branch_no": "01",
            "mode": "kis_demo",
            "message": "accepted",
        }
        self.inquiry_results = list(inquiry_results or [])
        self.inquiry_error = inquiry_error
        self.order_calls = []
        self.orderable_calls = []
        self.inquiry_calls = []
        self.submitting_snapshots = []

    def get_account(self):
        return self.account

    def get_orderable_quantity(self, ticker, price):
        self.orderable_calls.append((ticker, price))
        return self.orderable

    async def place_order(self, order: BrokerOrder):
        self.order_calls.append(order)
        self.submitting_snapshots.append(
            [row["status"] for row in db.get_pending_broker_orders()]
        )
        return dict(self.order_result)

    def get_order_status(self, order_no, **kwargs):
        self.inquiry_calls.append((order_no, kwargs))
        if self.inquiry_error is not None:
            raise self.inquiry_error
        if not self.inquiry_results:
            return {"output1": []}
        return self.inquiry_results.pop(0)


class KISTradingFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._temp_dir.name) / "prism.db"
        self._saved_env = {
            key: os.environ.get(key)
            for key in (
                "LECTURE_ENABLE_LIVE_BROKER",
                "LECTURE_ALLOW_REAL_BROKER",
                "LECTURE_KIS_MODE",
                "KIS_MODE",
            )
        }
        os.environ["LECTURE_ENABLE_LIVE_BROKER"] = "1"
        os.environ["LECTURE_KIS_MODE"] = "demo"
        os.environ.pop("LECTURE_ALLOW_REAL_BROKER", None)

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        db.DB_PATH = self._original_db_path
        self._temp_dir.cleanup()

    async def _execute(self, decision, adapter):
        with patch("brokers.factory.get_broker_adapter", return_value=adapter):
            return await trading._execute_broker_order(decision, broker_name="kis")

    def _broker_rows(self):
        with sqlite3.connect(db.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM broker_orders")]

    async def test_accepted_order_is_persisted_but_not_executed(self):
        adapter = _FakeKISAdapter(
            inquiry_error=RuntimeError("synthetic inquiry outage")
        )

        result = await self._execute(_decision(), adapter)

        self.assertFalse(result["executed"])
        self.assertEqual("accepted", result.get("status"))
        self.assertTrue(result["accepted"])
        self.assertFalse(result["terminal"])
        self.assertTrue(result["requires_reconciliation"])
        self.assertEqual([["submitting"]], adapter.submitting_snapshots)
        self.assertEqual("accepted", self._broker_rows()[0]["status"])

    async def test_market_blocked_order_is_persisted_as_blocked_not_rejected(self):
        adapter = _FakeKISAdapter(
            order_result={
                "success": False,
                "status": "blocked",
                "accepted": False,
                "executed": False,
                "terminal": True,
                "order_no": None,
                "branch_no": None,
                "mode": "kis_demo",
                "message": "현재 시장 상태에서는 주문하지 않습니다.",
            }
        )

        result = await self._execute(_decision(), adapter)

        self.assertEqual("blocked", result["status"])
        self.assertFalse(result["executed"])
        self.assertEqual("blocked", self._broker_rows()[0]["status"])

    async def test_buy_quantity_is_capped_by_orderable_and_account_cash(self):
        adapter = _FakeKISAdapter(
            account={"output1": [], "output2": [{"dnca_tot_amt": "30000"}]},
            orderable={"nrcvb_buy_qty": "5", "ord_psbl_cash": "50000"},
            inquiry_error=RuntimeError("leave accepted pending"),
        )

        result = await self._execute(_decision(quantity=10, price=10_000), adapter)

        self.assertEqual(3, adapter.order_calls[0].quantity)
        self.assertEqual(3, result["requested_qty"])
        self.assertEqual(3, self._broker_rows()[0]["requested_qty"])
        self.assertEqual([("005930", 10_000)], adapter.orderable_calls)

    async def test_sell_quantity_is_capped_by_actual_holding(self):
        adapter = _FakeKISAdapter(
            account={
                "output1": [
                    {"pdno": "005930", "hldg_qty": "4", "ord_psbl_qty": "3"}
                ],
                "output2": [{"dnca_tot_amt": "0"}],
            },
            inquiry_error=RuntimeError("leave accepted pending"),
        )

        result = await self._execute(
            _decision(action="SELL", quantity=10, price=70_000), adapter
        )

        self.assertEqual("SELL", adapter.order_calls[0].side)
        self.assertEqual(3, adapter.order_calls[0].quantity)
        self.assertEqual(3, result["requested_qty"])
        self.assertEqual([], adapter.orderable_calls)

    async def test_exit_decision_propagates_holding_quantity(self):
        decisions = await trading.run_exit_check(
            [
                {
                    "ticker": "005930",
                    "quantity": 4,
                    "entry_price": 70_000,
                    "high_since_entry": 70_000,
                }
            ],
            {"005930": 60_000},
        )

        self.assertEqual(4, decisions[0].get("quantity"))

    async def test_post_timeout_is_unknown_and_is_never_retried(self):
        adapter = _FakeKISAdapter(
            order_result={
                "success": False,
                "status": "unknown",
                "accepted": False,
                "executed": False,
                "terminal": False,
                "order_no": None,
                "branch_no": None,
                "requires_reconciliation": True,
                "mode": "kis_demo",
                "message": "timeout; reconcile before retry",
            }
        )

        result = await self._execute(_decision(), adapter)

        self.assertEqual("unknown", result.get("status"))
        self.assertFalse(result["executed"])
        self.assertTrue(result["requires_reconciliation"])
        self.assertEqual(1, len(adapter.order_calls))
        self.assertEqual("unknown", self._broker_rows()[0]["status"])

    async def test_acceptance_is_saved_before_inquiry_and_partial_is_not_executed(self):
        adapter = _FakeKISAdapter(
            inquiry_results=[
                {
                    "output1": [
                        {
                            "odno": "100",
                            "ord_qty": "5",
                            "tot_ccld_qty": "2",
                            "rmn_qty": "3",
                            "avg_prvs": "70100",
                        }
                    ]
                }
            ],
            orderable={"nrcvb_buy_qty": "5", "ord_psbl_cash": "500000"},
        )

        result = await self._execute(_decision(quantity=5, price=70_000), adapter)

        self.assertEqual("partial_fill", result.get("status"))
        self.assertFalse(result["executed"])
        self.assertTrue(result["requires_reconciliation"])
        self.assertEqual(2, result["filled_qty"])
        self.assertEqual(3, result["remaining_qty"])
        self.assertEqual(70_100, result["avg_fill_price"])
        self.assertEqual("partial_fill", self._broker_rows()[0]["status"])

    async def test_pending_recovery_progresses_unfilled_partial_and_filled_without_post(self):
        db.save_broker_order(_stored_order())
        adapter = _FakeKISAdapter(
            inquiry_results=[
                {
                    "output1": [
                        {
                            "odno": "100",
                            "ord_qty": "5",
                            "tot_ccld_qty": "0",
                            "rmn_qty": "5",
                            "avg_prvs": "0",
                        }
                    ]
                },
                {
                    "output1": [
                        {
                            "odno": "100",
                            "ord_qty": "5",
                            "tot_ccld_qty": "2",
                            "rmn_qty": "3",
                            "avg_prvs": "70100",
                        }
                    ]
                },
                {
                    "output1": [
                        {
                            "odno": "100",
                            "ord_qty": "5",
                            "tot_ccld_qty": "5",
                            "rmn_qty": "0",
                            "avg_prvs": "70200",
                        }
                    ]
                },
            ]
        )
        reconcile = getattr(trading, "reconcile_pending_broker_orders", None)
        self.assertTrue(callable(reconcile))

        snapshots = []
        for _ in range(3):
            snapshots.append((await reconcile(adapter=adapter, mode="paper"))[0])

        self.assertEqual(
            ["unfilled", "partial_fill", "filled"],
            [item["status"] for item in snapshots],
        )
        self.assertEqual([False, False, True], [item["executed"] for item in snapshots])
        self.assertEqual(
            [True, True, False],
            [item["requires_reconciliation"] for item in snapshots],
        )
        self.assertEqual(5, snapshots[-1]["filled_qty"])
        self.assertEqual(0, snapshots[-1]["remaining_qty"])
        self.assertEqual(70_200, snapshots[-1]["avg_fill_price"])
        self.assertEqual([], adapter.order_calls)
        self.assertEqual("filled", self._broker_rows()[0]["status"])

    async def test_unknown_without_order_number_recovers_only_from_unique_matching_inquiry(self):
        db.save_broker_order(
            _stored_order(
                status="unknown",
                org_no=None,
                order_no=None,
                requested_qty=5,
                remaining_qty=5,
            )
        )
        adapter = _FakeKISAdapter(
            inquiry_results=[
                {
                    "output1": [
                        {
                            "odno": "200",
                            "ord_gno_brno": "02",
                            "pdno": "005930",
                            "sll_buy_dvsn_cd": "02",
                            "ord_qty": "5",
                            "tot_ccld_qty": "0",
                            "rmn_qty": "5",
                            "avg_prvs": "0",
                        }
                    ]
                }
            ]
        )

        results = await trading.reconcile_pending_broker_orders(
            adapter=adapter, mode="paper"
        )

        self.assertEqual(1, len(results))
        self.assertEqual("unfilled", results[0]["status"])
        self.assertEqual("200", results[0]["order_no"])
        self.assertEqual(
            [
                (
                    "",
                    {"start_date": "2026-07-15", "end_date": "2026-07-15"},
                )
            ],
            adapter.inquiry_calls,
        )
        self.assertEqual([], adapter.order_calls)

    async def test_feedback_only_records_fills_and_keeps_acceptance_unknown_pending(self):
        db.save_broker_order(_stored_order(client_request_id="accepted"))
        db.save_broker_order(
            _stored_order(
                client_request_id="unknown",
                org_no=None,
                order_no=None,
                status="unknown",
            )
        )
        accepted = {
            **_decision(quantity=5, price=70_000),
            "status": "accepted",
            "accepted": True,
            "executed": False,
            "terminal": False,
            "requested_qty": 5,
            "filled_qty": 0,
            "remaining_qty": 5,
            "mode": "kis_demo",
        }
        unknown = {
            **accepted,
            "status": "unknown",
            "accepted": False,
        }
        filled = {
            **accepted,
            "status": "filled",
            "executed": True,
            "terminal": True,
            "filled_qty": 5,
            "remaining_qty": 0,
            "avg_fill_price": 70_200,
            "executed_price": 70_200,
        }

        await feedback.run_feedback([accepted, unknown, filled], [_analysis()])

        self.assertEqual(1, db.count_rows("trade_history"))
        self.assertEqual(1, db.count_rows("feedback_lessons"))
        self.assertEqual(
            {"accepted", "unknown"},
            {row["status"] for row in db.get_pending_broker_orders()},
        )

    async def test_simulation_feedback_behavior_remains_completed(self):
        result = trading._simulate_trade(_decision(quantity=2))

        await feedback.run_feedback([result], [_analysis()])

        self.assertTrue(result["executed"])
        self.assertEqual("simulation", result["mode"])
        self.assertEqual(1, db.count_rows("trade_history"))


if __name__ == "__main__":
    unittest.main()
