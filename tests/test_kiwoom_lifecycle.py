import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from brokers.base import BrokerOrder
from brokers.kiwoom import KiwoomBrokerAdapter
from prism_core.domain import OrderStatus
from trading import (
    _execute_broker_order,
    _kiwoom_snapshot_values,
    reconcile_pending_kiwoom_orders,
)


def decision(*, action="BUY", quantity=10):
    return {
        "action": action,
        "ticker": "005930",
        "quantity": quantity,
        "price": 70000,
        "reason": "kiwoom lifecycle test",
        "stop_loss": -0.07,
    }


class FakeKiwoomAdapter:
    def __init__(self, order_result, inquiry=None, *, orderable=10, sellable=10):
        self.order_result = order_result
        self.inquiry = inquiry
        self.orderable = orderable
        self.sellable = sellable
        self.placed = []
        self.inquiries = []

    async def get_orderable_quantity(self, ticker, price):
        return self.orderable

    async def get_sellable_quantity(self, ticker):
        return self.sellable

    async def place_order(self, order):
        self.placed.append(order)
        return dict(self.order_result)

    async def get_order_status(self, order_no, *, business_date=None):
        self.inquiries.append((order_no, business_date))
        if isinstance(self.inquiry, Exception):
            raise self.inquiry
        return self.inquiry if self.inquiry is not None else {
            "status": "accepted",
            "accepted": True,
            "executed": False,
            "terminal": False,
            "order_no": order_no,
            "filled_qty": 0,
            "remaining_qty": 10,
        }


def accepted(order_no="KW1001"):
    return {
        "status": "accepted",
        "accepted": True,
        "executed": False,
        "terminal": False,
        "order_no": order_no,
        "message": "accepted",
        "mode": "kiwoom_demo",
    }


class KiwoomAdapterContractTest(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {"KIWOOM_ACCESS_TOKEN": "token"}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_quote_uses_official_ka10007_market_condition_contract(self):
        adapter = KiwoomBrokerAdapter(mode="demo")
        calls = []

        def fake_request(path, payload, *, headers):
            calls.append((path, payload, headers))
            return {
                "return_code": 0,
                "stk_cd": "005930",
                "cur_prc": "+70,100",
            }

        adapter._request_json = fake_request  # type: ignore[method-assign]

        quote = asyncio.run(adapter.get_quote("005930"))

        self.assertEqual(quote.ticker, "005930")
        self.assertEqual(quote.price, 70100)
        self.assertEqual(quote.currency, "KRW")
        self.assertEqual(quote.market, "KRX")
        self.assertEqual(quote.source, "kiwoom.ka10007")
        self.assertEqual(calls[0][0], "/api/dostk/mrkcond")
        self.assertEqual(calls[0][1], {"stk_cd": "005930"})
        self.assertEqual(calls[0][2]["api-id"], "ka10007")

    def test_orderable_quantity_uses_official_kt00011_contract(self):
        adapter = KiwoomBrokerAdapter(mode="demo")
        calls = []

        def fake_request(path, payload, *, headers):
            calls.append((path, payload, headers))
            return {
                "return_code": 0,
                "stk_cd": "005930",
                "min_ord_alowq": "3",
                "entr": "210000",
            }

        adapter._request_json = fake_request  # type: ignore[method-assign]

        quantity = asyncio.run(adapter.get_orderable_quantity("005930", 70000))

        self.assertEqual(quantity, 3)
        self.assertEqual(calls[0][0], "/api/dostk/acnt")
        self.assertEqual(calls[0][1], {"stk_cd": "005930", "uv": "70000"})
        self.assertEqual(calls[0][2]["api-id"], "kt00011")

    def test_account_positions_use_official_kt00018_contract_for_sellable_quantity(self):
        adapter = KiwoomBrokerAdapter(mode="demo")

        def fake_request(path, payload, *, headers):
            self.assertEqual(path, "/api/dostk/acnt")
            self.assertEqual(headers["api-id"], "kt00018")
            return {
                "return_code": 0,
                "acnt_evlt_remn_indv_tot": [
                    {
                        "stk_cd": "005930",
                        "stk_nm": "삼성전자",
                        "rmnd_qty": "7",
                        "trde_able_qty": "5",
                    }
                ],
            }

        adapter._request_json = fake_request  # type: ignore[method-assign]

        account = asyncio.run(adapter.get_account())
        sellable = asyncio.run(adapter.get_sellable_quantity("005930"))

        self.assertEqual(account["positions"][0]["pdno"], "005930")
        self.assertEqual(account["positions"][0]["hldg_qty"], "7")
        self.assertEqual(sellable, 5)

    def test_unfilled_filled_and_cancelled_rows_normalize_to_lifecycle_states(self):
        cases = [
            (
                {
                    "rows": [
                        {
                            "ord_no": "KW1001",
                            "ord_qty": "10",
                            "cntr_qty": "0",
                            "oso_qty": "10",
                            "ord_stt": "접수",
                        }
                    ]
                },
                "accepted",
                0,
                10,
                False,
            ),
            (
                {
                    "rows": [
                        {
                            "ord_no": "KW1001",
                            "ord_qty": "10",
                            "cntr_qty": "4",
                            "oso_qty": "6",
                            "avg_prvs": "70100",
                        }
                    ]
                },
                "partial",
                4,
                6,
                False,
            ),
            (
                {
                    "rows": [
                        {
                            "ord_no": "KW1001",
                            "ord_qty": "10",
                            "cntr_qty": "0",
                            "oso_qty": "10",
                            "ord_stt": "취소",
                        }
                    ]
                },
                "canceled",
                0,
                10,
                True,
            ),
            (
                {
                    "rows": [
                        {
                            "ord_no": "KW1001",
                            "ord_qty": "10",
                            "cntr_qty": "10",
                            "oso_qty": "0",
                            "avg_prvs": "70200",
                        }
                    ]
                },
                "filled",
                10,
                0,
                True,
            ),
        ]
        for inquiry, want_status, want_filled, want_remaining, want_terminal in cases:
            with self.subTest(want_status=want_status):
                adapter = KiwoomBrokerAdapter(mode="demo")
                adapter.get_pending_orders = lambda *, business_date=None, _inquiry=inquiry: _async(_inquiry)  # type: ignore[method-assign]

                status = asyncio.run(adapter.get_order_status("KW1001", business_date="20260810"))

                self.assertEqual(status["status"], want_status)
                self.assertEqual(status["filled_qty"], want_filled)
                self.assertEqual(status["remaining_qty"], want_remaining)
                self.assertEqual(status["terminal"], want_terminal)

    def test_order_status_unknown_when_official_rows_do_not_match_order_number(self):
        adapter = KiwoomBrokerAdapter(mode="demo")
        adapter.get_pending_orders = lambda *, business_date=None: _async({"rows": [{"ord_no": "OTHER"}]})  # type: ignore[method-assign]
        adapter.get_completed_orders = lambda *, business_date=None: _async({"rows": []})  # type: ignore[method-assign]

        result = asyncio.run(adapter.get_order_status("KW1001", business_date="20260810"))

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])

    def test_malformed_ka10075_matching_row_fails_closed_as_unknown(self):
        adapter = KiwoomBrokerAdapter(mode="demo")

        def fake_request(path, payload, *, headers):
            self.assertEqual(path, "/api/dostk/acnt")
            if headers["api-id"] == "ka10075":
                return {"return_code": 0, "rows": [{"ord_no": "KW1001"}]}
            if headers["api-id"] == "ka10076":
                return {"return_code": 0, "rows": []}
            self.fail(f"unexpected API ID: {headers['api-id']}")

        adapter._request_json = fake_request  # type: ignore[method-assign]

        result = asyncio.run(adapter.get_order_status("KW1001", business_date="20260810"))

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])

    def test_malformed_ka10076_matching_row_fails_closed_as_unknown(self):
        adapter = KiwoomBrokerAdapter(mode="demo")

        def fake_request(path, payload, *, headers):
            self.assertEqual(path, "/api/dostk/acnt")
            if headers["api-id"] == "ka10075":
                return {"return_code": 0, "rows": []}
            if headers["api-id"] == "ka10076":
                return {"return_code": 0, "rows": [{"ord_no": "KW1001"}]}
            self.fail(f"unexpected API ID: {headers['api-id']}")

        adapter._request_json = fake_request  # type: ignore[method-assign]

        result = asyncio.run(adapter.get_order_status("KW1001", business_date="20260810"))

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])

    def test_malformed_average_price_ka10075_matching_row_fails_closed_as_unknown(self):
        adapter = KiwoomBrokerAdapter(mode="demo")

        def fake_request(path, payload, *, headers):
            self.assertEqual(path, "/api/dostk/acnt")
            if headers["api-id"] == "ka10075":
                return {
                    "return_code": 0,
                    "rows": [
                        {
                            "ord_no": "KW1001",
                            "ord_qty": "10",
                            "cntr_qty": "4",
                            "oso_qty": "6",
                            "avg_prvs": "not-a-price",
                        }
                    ],
                }
            if headers["api-id"] == "ka10076":
                return {"return_code": 0, "rows": []}
            self.fail(f"unexpected API ID: {headers['api-id']}")

        adapter._request_json = fake_request  # type: ignore[method-assign]

        try:
            result = asyncio.run(adapter.get_order_status("KW1001", business_date="20260810"))
        except RuntimeError:
            result = {"status": "exception"}

        self.assertEqual(result["status"], "unknown")

    def test_quantity_incoherent_ka10075_matching_row_fails_closed_as_unknown(self):
        adapter = KiwoomBrokerAdapter(mode="demo")

        def fake_request(path, payload, *, headers):
            self.assertEqual(path, "/api/dostk/acnt")
            if headers["api-id"] == "ka10075":
                return {
                    "return_code": 0,
                    "rows": [
                        {
                            "ord_no": "KW1001",
                            "ord_qty": "10",
                            "cntr_qty": "1",
                            "oso_qty": "0",
                            "avg_prvs": "70200",
                        }
                    ],
                }
            if headers["api-id"] == "ka10076":
                return {"return_code": 0, "rows": []}
            self.fail(f"unexpected API ID: {headers['api-id']}")

        adapter._request_json = fake_request  # type: ignore[method-assign]

        result = asyncio.run(adapter.get_order_status("KW1001", business_date="20260810"))

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])

    def test_quantity_incoherent_ka10076_matching_row_fails_closed_as_unknown(self):
        adapter = KiwoomBrokerAdapter(mode="demo")

        def fake_request(path, payload, *, headers):
            self.assertEqual(path, "/api/dostk/acnt")
            if headers["api-id"] == "ka10075":
                return {"return_code": 0, "rows": []}
            if headers["api-id"] == "ka10076":
                return {
                    "return_code": 0,
                    "rows": [
                        {
                            "ord_no": "KW1001",
                            "ord_qty": "10",
                            "cntr_qty": "1",
                            "oso_qty": "0",
                            "avg_prvs": "70200",
                        }
                    ],
                }
            self.fail(f"unexpected API ID: {headers['api-id']}")

        adapter._request_json = fake_request  # type: ignore[method-assign]

        result = asyncio.run(adapter.get_order_status("KW1001", business_date="20260810"))

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])

    def test_cancel_order_uses_official_kt10003_contract_without_marking_terminal(self):
        adapter = KiwoomBrokerAdapter(mode="demo")
        calls = []

        def fake_request(path, payload, *, headers):
            calls.append((path, payload, headers))
            return {"return_code": 0, "return_msg": "취소 주문 접수", "ord_no": "KW2001"}

        adapter._request_json = fake_request  # type: ignore[method-assign]

        result = asyncio.run(adapter.cancel_order("KW1001", ticker="005930", quantity=3))

        self.assertEqual(result["status"], "cancel_accepted")
        self.assertTrue(result["accepted"])
        self.assertFalse(result["terminal"])
        self.assertEqual(calls[0][0], "/api/dostk/ordr")
        self.assertEqual(calls[0][2]["api-id"], "kt10003")
        self.assertEqual(
            calls[0][1],
            {
                "dmst_stex_tp": "KRX",
                "orig_ord_no": "KW1001",
                "stk_cd": "005930",
                "cncl_qty": "3",
            },
        )

    def test_transport_and_malformed_responses_fail_closed(self):
        adapter = KiwoomBrokerAdapter(mode="demo")
        failures = [
            {"return_code": "network_error", "return_msg": "timeout"},
            {"return_code": 0, "stk_cd": "005930"},
        ]
        for response in failures:
            with self.subTest(response=response):
                adapter._request_json = lambda *args, _response=response, **kwargs: _response  # type: ignore[method-assign]

                with self.assertRaises(RuntimeError):
                    asyncio.run(adapter.get_quote("005930"))


class KiwoomTradingLifecycleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db_path = db.DB_PATH
        db.DB_PATH = Path(self._tmp.name) / "kiwoom-flow.db"
        self._env = patch.dict(
            os.environ,
            {
                "LECTURE_ENABLE_LIVE_BROKER": "1",
                "KIWOOM_MODE": "demo",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        db.DB_PATH = self._old_db_path
        self._tmp.cleanup()

    def execute(self, adapter, selected_decision=None):
        with patch("brokers.factory.get_broker_adapter", return_value=adapter):
            return asyncio.run(
                _execute_broker_order(
                    selected_decision or decision(), broker_name="kiwoom"
                )
            )

    def test_accepted_kiwoom_order_is_pending_not_executed_and_blocks_duplicate_post(self):
        adapter = FakeKiwoomAdapter(accepted())

        first = self.execute(adapter)
        second = self.execute(adapter)

        self.assertEqual(first["status"], "accepted")
        self.assertFalse(first["executed"])
        self.assertFalse(first["terminal"])
        self.assertEqual(second["status"], "blocked")
        self.assertEqual(second["mode"], "kiwoom_demo_pending_order")
        self.assertEqual(len(adapter.placed), 1)
        state = db.get_broker_order_state(first["client_order_id"])
        self.assertEqual(state.status, OrderStatus.ACCEPTED)
        self.assertEqual(state.broker_org_no, "kiwoom")
        self.assertEqual(state.broker_order_no, "KW1001")

    def test_kiwoom_partial_fill_is_not_reported_as_terminal_execution(self):
        adapter = FakeKiwoomAdapter(
            accepted(),
            {
                "status": "partial",
                "accepted": True,
                "executed": False,
                "terminal": False,
                "order_no": "KW1001",
                "filled_qty": 4,
                "remaining_qty": 6,
                "average_fill_price": 70100,
            },
        )

        result = self.execute(adapter)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["filled_qty"], 4)
        self.assertEqual(result["remaining_qty"], 6)
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])

    def test_kiwoom_filled_inquiry_is_only_terminal_executed_result(self):
        adapter = FakeKiwoomAdapter(
            accepted(),
            {
                "status": "filled",
                "accepted": True,
                "executed": True,
                "terminal": True,
                "order_no": "KW1001",
                "filled_qty": 10,
                "remaining_qty": 0,
                "average_fill_price": 70200,
            },
        )

        result = self.execute(adapter)

        self.assertEqual(result["status"], "filled")
        self.assertTrue(result["executed"])
        self.assertTrue(result["terminal"])
        self.assertEqual(result["executed_price"], 70200)

    def test_kiwoom_under_counted_filled_inquiry_stays_unknown(self):
        inquiry = {
            "status": "filled",
            "order_no": "KW1001",
            "filled_qty": 1,
            "remaining_qty": 0,
            "average_fill_price": 70200,
        }

        status, filled, remaining, average = _kiwoom_snapshot_values(
            inquiry, requested=10
        )

        self.assertEqual(status, OrderStatus.UNKNOWN)
        self.assertEqual(filled, 0)
        self.assertEqual(remaining, 10)
        self.assertIsNone(average)

    def test_kiwoom_unknown_post_exception_stays_restartable(self):
        class RaisingAdapter(FakeKiwoomAdapter):
            async def place_order(self, order):
                raise TimeoutError("post boundary unknown")

        result = self.execute(RaisingAdapter(accepted()))

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["terminal"])
        state = db.get_broker_order_state(result["client_order_id"])
        self.assertEqual(state.status, OrderStatus.UNKNOWN)

    def test_restart_reconciliation_recovers_persisted_kiwoom_fill_without_resubmission(self):
        adapter = FakeKiwoomAdapter(accepted(), TimeoutError("first inquiry timeout"))
        first = self.execute(adapter)
        self.assertEqual(first["status"], "accepted")

        adapter.inquiry = {
            "status": "filled",
            "accepted": True,
            "executed": True,
            "terminal": True,
            "order_no": "KW1001",
            "filled_qty": 10,
            "remaining_qty": 0,
            "average_fill_price": 70200,
        }
        recovered = asyncio.run(
            reconcile_pending_kiwoom_orders(adapter=adapter, mode="demo")
        )

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["status"], "filled")
        self.assertEqual(len(adapter.placed), 1)
        state = db.get_broker_order_state(first["client_order_id"])
        self.assertEqual(state.status, OrderStatus.FILLED)


async def _async(value):
    return value


if __name__ == "__main__":
    unittest.main()
