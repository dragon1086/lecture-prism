from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import db
from brokers.base import BrokerOrder, BrokerQuote
from brokers.toss import (
    TossBrokerAdapter,
    TossctlQuoteAdapter,
    TossOfficialOpenAPIAdapter,
    TossOfficialRateLimitError,
    TossOfficialSchemaError,
)
from brokers.tossctl import (
    TossctlClient,
    TossctlConfigurationError,
    TossctlReadClient,
    TossctlUnknownMutationError,
)
from trading import (
    _execute_broker_order,
    _toss_attempted_at,
    reconcile_pending_toss_orders,
)


ACTIVE_AUTH = {
    "active": True,
    "expired": False,
    "validated": True,
    "valid": True,
    "server_expires_at": "2026-07-27T00:00:00Z",
    "session_file": "/redacted/session.json",
}


class FakeTossctl:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run_json(self, args, *, mutation=False):
        self.calls.append((list(args), mutation))
        if not self.responses:
            raise AssertionError(f"unexpected tossctl call: {args}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeOfficialOpenAPI:
    def __init__(self, responses=None, *, fail_at: str | None = None, error=None):
        self.responses = dict(responses or {})
        self.fail_at = fail_at
        self.error = error or RuntimeError("official read failed")
        self.calls = []
        self.order_calls = []

    def _response(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise self.error
        return self.responses[name]

    async def accounts(self):
        return self._response("accounts")

    async def holdings(self, symbol=None):
        self.calls.append(("holdings", symbol))
        if self.fail_at == "holdings":
            raise self.error
        return self.responses["holdings"]

    async def quote(self, symbol):
        self.calls.append(("quote", symbol))
        if self.fail_at == "quote":
            raise self.error
        return self.responses["quote"]

    async def pending_orders(self):
        return self._response("pending_orders")

    async def order_status(self, order_id):
        self.calls.append(("order_status", order_id))
        if self.fail_at == "order_status":
            raise self.error
        return self.responses["order_status"]

    async def place_order(self, order):
        self.order_calls.append(("place_order", order))
        raise AssertionError("official order E2E is not approved")

    async def cancel_order(self, order_id):
        self.order_calls.append(("cancel_order", order_id))
        raise AssertionError("official cancel E2E is not approved")


class TossctlClientTest(unittest.TestCase):
    def test_runner_uses_argument_list_fixed_backend_version_and_minimal_env(self):
        calls = []

        def runner(args, **kwargs):
            calls.append((args, kwargs))
            payload = (
                {"version": "0.24.1"}
                if args[-1] == "version"
                else ACTIVE_AUTH
            )
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "tossctl"
            executable.write_text("", encoding="utf-8")
            client = TossctlClient(
                executable=str(executable),
                runner=runner,
                environ={
                    "PATH": "/usr/bin",
                    "HOME": tmp,
                    "OPENAI_API_KEY": "must-not-leak",
                },
            )

            result = client.run_json(["auth", "status"])

        self.assertTrue(result["active"])
        self.assertEqual(
            calls[1][0],
            [
                client.executable,
                "--backend",
                "wts",
                "--output",
                "json",
                "auth",
                "status",
            ],
        )
        self.assertIs(calls[1][1]["shell"], False)
        self.assertNotIn("OPENAI_API_KEY", calls[1][1]["env"])

    def test_wrong_version_fails_closed(self):
        def runner(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps({"version": "0.25.0"}),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "tossctl"
            executable.write_text("", encoding="utf-8")
            client = TossctlClient(executable=str(executable), runner=runner)

            with self.assertRaises(TossctlConfigurationError):
                client.run_json(["auth", "status"])

    def test_mutation_timeout_is_unknown_never_a_retryable_read_error(self):
        calls = 0

        def runner(args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout=json.dumps({"version": "0.24.1"}),
                    stderr="",
                )
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "tossctl"
            executable.write_text("", encoding="utf-8")
            client = TossctlClient(executable=str(executable), runner=runner)

            with self.assertRaises(TossctlUnknownMutationError):
                client.run_json(
                    ["order", "place", "--execute", "--confirm", "token"],
                    mutation=True,
                )

    def test_non_finite_timeout_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "tossctl"
            executable.write_text("", encoding="utf-8")

            with self.assertRaises(TossctlConfigurationError):
                TossctlClient(executable=str(executable), timeout=float("nan"))


class TossctlReadClientTest(unittest.TestCase):
    def test_read_client_accepts_pinned_release_and_uses_openapi_backend(self):
        calls = []

        def runner(args, **kwargs):
            calls.append((args, kwargs))
            payload = (
                {"version": "0.43.1"}
                if args[-1] == "version"
                else {
                    "result": [
                        {
                            "symbol": "005930",
                            "lastPrice": "70100",
                            "currency": "KRW",
                            "timestamp": "2026-08-28T09:05:00+09:00",
                        }
                    ]
                }
            )
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "tossctl"
            executable.write_text("", encoding="utf-8")
            client = TossctlReadClient(executable=str(executable), runner=runner)

            result = client.run_json(["quote", "get", "005930"])

        self.assertEqual(result["result"][0]["lastPrice"], "70100")
        self.assertEqual(
            calls[1][0],
            [
                client.executable,
                "--backend",
                "openapi",
                "--output",
                "json",
                "quote",
                "get",
                "005930",
            ],
        )


class TossctlQuoteAdapterTest(unittest.TestCase):
    def test_read_only_quote_adapter_normalizes_latest_cli_payload(self):
        client = FakeTossctl(
            [
                {
                    "result": [
                        {
                            "symbol": "005930",
                            "lastPrice": "70100",
                            "currency": "KRW",
                            "timestamp": "2026-08-28T09:05:00+09:00",
                        }
                    ]
                }
            ]
        )
        adapter = TossctlQuoteAdapter(
            client=client,
            clock=lambda: datetime(2026, 8, 28, 0, 5, 30, tzinfo=timezone.utc),
        )

        quote = asyncio.run(adapter.get_quote("005930"))

        self.assertEqual(quote.ticker, "005930")
        self.assertEqual(quote.price, 70100)
        self.assertEqual(quote.currency, "KRW")
        self.assertEqual(quote.market, "KRX")
        self.assertEqual(quote.source, "tossctl.openapi")
        self.assertEqual(client.calls, [(["quote", "get", "005930"], False)])


class TossBrokerAdapterTest(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(
            os.environ,
            {
                "LECTURE_ENABLE_LIVE_BROKER": "1",
                "LECTURE_ALLOW_REAL_BROKER": "1",
                "LECTURE_ENABLE_LIVE_TOSS": "1",
                "LECTURE_ALLOW_REAL_TOSS": "1",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_real_place_and_cancel_block_without_live_gates_before_wts_access(self):
        client = FakeTossctl(
            [
                AssertionError("Toss auth must not run"),
                AssertionError("Toss order lookup must not run"),
            ]
        )
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        with patch.dict(
            os.environ,
            {
                "LECTURE_ENABLE_LIVE_BROKER": "0",
                "LECTURE_ALLOW_REAL_BROKER": "0",
                "LECTURE_ENABLE_LIVE_TOSS": "0",
                "LECTURE_ALLOW_REAL_TOSS": "0",
            },
            clear=False,
        ):
            place = asyncio.run(
                adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
            )
            cancel = asyncio.run(adapter.cancel_order("2026-07-20/10", "005930"))

        self.assertEqual(place["status"], "blocked")
        self.assertEqual(place["mode"], "toss_real_live_gate_blocked")
        self.assertEqual(cancel["status"], "blocked")
        self.assertEqual(cancel["mode"], "toss_real_live_gate_blocked")
        self.assertEqual(client.calls, [])

    def test_expired_auth_blocks_before_preview_or_mutation(self):
        client = FakeTossctl(
            [{**ACTIVE_AUTH, "expired": True, "valid": False}]
        )
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        result = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["mode"], "toss_manual_action_required")
        self.assertEqual(client.calls, [(["auth", "status"], False)])

    def test_buy_and_sell_use_preview_then_same_intent_for_place(self):
        preview = {
            "kind": "place",
            "canonical": "canonical-intent",
            "confirm_token": "abc123",
            "live_ready": True,
            "mutation_ready": True,
        }
        accepted = {
            "kind": "place",
            "status": "accepted_pending",
            "order_id": "2026-07-20/10",
            "symbol": "005930",
            "market": "kr",
            "quantity": 2,
            "filled_quantity": 0,
            "price": 70000,
            "order_date": "2026-07-20",
        }
        client = FakeTossctl(
            [ACTIVE_AUTH, preview, accepted, ACTIVE_AUTH, preview, accepted]
        )
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        buy = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 2, 70000))
        )
        sell = asyncio.run(
            adapter.place_order(BrokerOrder("SELL", "005930", 2, 70000))
        )

        self.assertTrue(buy["accepted"])
        self.assertTrue(sell["accepted"])
        previews = [call for call in client.calls if call[0][:2] == ["order", "preview"]]
        places = [call for call in client.calls if call[0][:2] == ["order", "place"]]
        self.assertEqual(len(previews), 2)
        self.assertEqual(len(places), 2)
        for preview_call, place_call in zip(previews, places):
            preview_args = preview_call[0][2:]
            place_args = place_call[0][2:]
            self.assertEqual(
                place_args[: len(preview_args)],
                preview_args,
            )
            self.assertEqual(place_args[-3:], ["--execute", "--confirm", "abc123"])
            self.assertFalse(preview_call[1])
            self.assertTrue(place_call[1])

    def test_account_limits_buy_and_sell_quantity(self):
        client = FakeTossctl(
            [
                ACTIVE_AUTH,
                {
                    "orderable_amount_krw": 150000,
                    "orderable_amount_usd": 0,
                },
                ACTIVE_AUTH,
                {
                    "product_code": "KR7005930003",
                    "symbol": "005930",
                    "sellable_quantity": 3,
                },
                [
                    {
                        "product_code": "KR7005930003",
                        "symbol": "005930",
                        "market_type": "KR_STOCK",
                        "quantity": 5,
                    }
                ],
            ]
        )
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        buy_qty = asyncio.run(adapter.get_orderable_quantity("005930", 70000))
        sell_qty = asyncio.run(adapter.get_sellable_quantity("005930"))

        self.assertEqual(buy_qty, 2)
        self.assertEqual(sell_qty, 3)

    def test_wts_quote_is_normalized_to_shared_broker_quote_contract(self):
        client = FakeTossctl(
            [
                ACTIVE_AUTH,
                {
                    "symbol": "005930",
                    "price": 70100,
                    "currency": "KRW",
                    "market": "KRX",
                    "timestamp": "2026-07-20T00:05:00Z",
                },
            ]
        )
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, 0, 5, 30, tzinfo=timezone.utc),
        )

        quote = asyncio.run(adapter.get_quote("005930"))

        self.assertIsInstance(quote, BrokerQuote)
        self.assertEqual(quote.ticker, "005930")
        self.assertEqual(quote.price, 70100)
        self.assertEqual(quote.currency, "KRW")
        self.assertEqual(quote.market, "KRX")
        self.assertEqual(client.calls[1][0], ["quote", "get", "005930"])

    def test_partial_order_status_is_normalized_by_quantities(self):
        client = FakeTossctl(
            [
                ACTIVE_AUTH,
                {
                    "id": "2026-07-20/10",
                    "symbol": "005930",
                    "market": "kr",
                    "side": "buy",
                    "status": "체결중",
                    "quantity": 3,
                    "filled_quantity": 1,
                    "price": 70000,
                    "average_execution_price": 69900,
                    "order_date": "2026-07-20",
                },
            ]
        )
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        result = asyncio.run(adapter.get_order_status("2026-07-20/10"))

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["filled_qty"], 1)
        self.assertEqual(result["remaining_qty"], 2)
        self.assertEqual(result["average_fill_price"], 69900)

    def test_cancel_previews_then_executes_and_returns_canceled(self):
        client = FakeTossctl(
            [
                ACTIVE_AUTH,
                {
                    "id": "2026-07-20/10",
                    "symbol": "005930",
                    "market": "kr",
                    "side": "buy",
                    "status": "체결대기",
                    "quantity": 2,
                    "filled_quantity": 0,
                    "price": 70000,
                    "order_date": "2026-07-20",
                },
                {
                    "kind": "cancel",
                    "canonical": "cancel-intent",
                    "confirm_token": "cancel123",
                    "live_ready": True,
                    "mutation_ready": True,
                },
                {
                    "kind": "cancel",
                    "status": "canceled",
                    "order_id": "2026-07-20/10",
                    "original_order_id": "2026-07-20/10",
                    "symbol": "005930",
                    "market": "kr",
                    "quantity": 2,
                    "filled_quantity": 0,
                    "price": 70000,
                    "order_date": "2026-07-20",
                },
            ]
        )
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        result = asyncio.run(
            adapter.cancel_order("2026-07-20/10", "005930")
        )

        self.assertEqual(result["status"], "canceled")
        self.assertTrue(result["terminal"])
        self.assertEqual(client.calls[-1][0][-3:], ["--execute", "--confirm", "cancel123"])
        self.assertTrue(client.calls[-1][1])

    def test_filled_mutation_with_missing_fill_evidence_becomes_unknown(self):
        client = FakeTossctl(
            [
                ACTIVE_AUTH,
                {
                    "kind": "place",
                    "canonical": "canonical-intent",
                    "confirm_token": "abc123",
                    "live_ready": True,
                    "mutation_ready": True,
                },
                {
                    "kind": "place",
                    "status": "filled_completed",
                    "order_id": "2026-07-20/10",
                    "symbol": "005930",
                    "market": "kr",
                    "quantity": 1,
                    "price": 70000,
                    "order_date": "2026-07-20",
                },
            ]
        )
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        result = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
        )

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["terminal"])

    def test_cancel_target_mismatch_blocks_before_preview(self):
        client = FakeTossctl(
            [
                ACTIVE_AUTH,
                {
                    "id": "2026-07-20/99",
                    "symbol": "005930",
                    "status": "체결대기",
                    "quantity": 1,
                    "filled_quantity": 0,
                },
            ]
        )
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        result = asyncio.run(
            adapter.cancel_order("2026-07-20/10", "005930")
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["mode"], "toss_cancel_target_mismatch")
        self.assertEqual(len(client.calls), 2)

    def test_missing_account_quantity_fields_raise_schema_error(self):
        client = FakeTossctl([ACTIVE_AUTH, {}])
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        with self.assertRaisesRegex(RuntimeError, "orderable_amount_krw"):
            asyncio.run(adapter.get_orderable_quantity("005930", 70000))

    def test_wts_pending_orders_reject_malformed_payload(self):
        client = FakeTossctl([ACTIVE_AUTH, {"orders": []}])
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        with self.assertRaisesRegex(RuntimeError, "pending orders JSON"):
            asyncio.run(adapter.get_pending_orders())

    def test_wts_unknown_order_status_fails_closed(self):
        client = FakeTossctl(
            [
                ACTIVE_AUTH,
                {
                    "id": "2026-07-20/10",
                    "symbol": "005930",
                    "market": "kr",
                    "side": "buy",
                    "status": "처리불명",
                    "quantity": 2,
                    "filled_quantity": 0,
                    "price": 70000,
                    "order_date": "2026-07-20",
                },
            ]
        )
        adapter = TossBrokerAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        result = asyncio.run(adapter.get_order_status("2026-07-20/10"))

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["terminal"])


class TossOfficialOpenAPIAdapterTest(unittest.TestCase):
    def _official_client(self):
        return FakeOfficialOpenAPI(
            {
                "accounts": [
                    {
                        "accountSeq": 7,
                        "accountType": "BROKERAGE",
                    }
                ],
                "holdings": [
                    {
                        "symbol": "005930",
                        "marketCountry": "KR",
                        "currency": "KRW",
                        "quantity": "3",
                        "lastPrice": "70100",
                    }
                ],
                "quote": {
                    "symbol": "005930",
                    "price": "70100",
                    "currency": "KRW",
                    "market": "KOSPI",
                    "observedAt": "2026-07-20T00:00:00Z",
                },
                "pending_orders": [
                    {
                        "orderId": "ord-1",
                        "symbol": "005930",
                        "side": "BUY",
                        "status": "OPEN",
                        "quantity": "3",
                        "price": "70000",
                        "orderedAt": "2026-07-20T00:00:00Z",
                        "execution": {
                            "filledQuantity": "0",
                        },
                    }
                ],
                "order_status": {
                    "orderId": "ord-1",
                    "symbol": "005930",
                    "side": "BUY",
                    "status": "CLOSED",
                    "quantity": "3",
                    "price": "70000",
                    "orderedAt": "2026-07-20T00:00:00Z",
                    "execution": {
                        "filledQuantity": "3",
                        "averageFilledPrice": "69900",
                    },
                },
            }
        )

    def test_official_paper_is_blocked_without_client_calls(self):
        client = self._official_client()
        adapter = TossOfficialOpenAPIAdapter(mode="paper", client=client)

        result = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["mode"], "toss_official_paper_unavailable")
        self.assertEqual(client.calls, [])
        self.assertEqual(client.order_calls, [])

    def test_official_real_place_and_cancel_block_without_live_gates(self):
        client = self._official_client()
        adapter = TossOfficialOpenAPIAdapter(mode="real", client=client)

        with patch.dict(
            os.environ,
            {
                "LECTURE_ENABLE_LIVE_BROKER": "0",
                "LECTURE_ALLOW_REAL_BROKER": "0",
                "LECTURE_ENABLE_LIVE_TOSS": "0",
                "LECTURE_ALLOW_REAL_TOSS": "0",
            },
            clear=False,
        ):
            place = asyncio.run(
                adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
            )
            cancel = asyncio.run(adapter.cancel_order("ord-1"))

        self.assertEqual(place["status"], "blocked")
        self.assertEqual(place["mode"], "toss_official_real_live_gate_blocked")
        self.assertEqual(cancel["status"], "blocked")
        self.assertEqual(cancel["mode"], "toss_official_real_live_gate_blocked")
        self.assertEqual(client.calls, [])
        self.assertEqual(client.order_calls, [])

    def test_official_readonly_account_holdings_quote_pending_and_lifecycle_contract(self):
        client = self._official_client()
        adapter = TossOfficialOpenAPIAdapter(
            mode="real",
            client=client,
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        account = asyncio.run(adapter.get_account())
        sellable = asyncio.run(adapter.get_sellable_quantity("005930"))
        quote = asyncio.run(adapter.get_quote("005930"))
        pending = asyncio.run(adapter.get_pending_orders())
        status = asyncio.run(adapter.get_order_status("ord-1"))

        self.assertEqual(account["accounts_count"], 1)
        self.assertEqual(sellable, 3)
        self.assertIsInstance(quote, BrokerQuote)
        self.assertEqual(quote.price, 70100)
        self.assertEqual(pending[0]["status"], "accepted")
        self.assertEqual(status["status"], "filled")
        self.assertEqual(status["filled_qty"], 3)
        self.assertEqual(client.order_calls, [])

    def test_official_rate_limit_fails_closed(self):
        client = FakeOfficialOpenAPI(
            {"accounts": []},
            fail_at="accounts",
            error=TossOfficialRateLimitError("ACCOUNT group exceeded"),
        )
        adapter = TossOfficialOpenAPIAdapter(mode="real", client=client)

        with self.assertRaises(TossOfficialRateLimitError):
            asyncio.run(adapter.get_account())

    def test_official_malformed_payload_fails_closed(self):
        client = FakeOfficialOpenAPI({"accounts": [{"accountSeq": None}]})
        adapter = TossOfficialOpenAPIAdapter(mode="real", client=client)

        with self.assertRaises(TossOfficialSchemaError):
            asyncio.run(adapter.get_account())

    def test_official_unknown_order_status_fails_closed(self):
        adapter = TossOfficialOpenAPIAdapter(mode="real", client=self._official_client())

        result = adapter.normalize_order_snapshot(
            {
                "orderId": "ord-unknown",
                "symbol": "005930",
                "side": "BUY",
                "status": "SURPRISE",
                "quantity": "3",
                "price": "70000",
                "execution": {"filledQuantity": "0"},
            }
        )

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["terminal"])


class TossTradingLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "LECTURE_ENABLE_LIVE_BROKER": "1",
                "LECTURE_ALLOW_REAL_BROKER": "1",
                "TOSS_SECURITIES_MODE": "real",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def _submit_identityless_unknown(self, db_path: Path):
        adapter = type(
            "IdentitylessAdapter",
            (),
            {
                "get_orderable_quantity": AsyncMock(return_value=1),
                "place_order": AsyncMock(
                    return_value={
                        "status": "unknown",
                        "accepted": False,
                        "executed": False,
                        "terminal": False,
                        "order_no": None,
                        "message": "result unknown",
                    }
                ),
            },
        )()
        decision = {
            "action": "BUY",
            "ticker": "005930",
            "quantity": 1,
            "price": 70000,
            "reason": "test",
        }
        with (
            patch("brokers.factory.get_broker_adapter", return_value=adapter),
            patch("db.DB_PATH", db_path),
        ):
            result = asyncio.run(
                _execute_broker_order(decision, broker_name="toss")
            )
            state = db.get_pending_broker_orders(
                broker="toss", broker_mode="real"
            )[0]
        self.assertEqual(result["status"], "unknown")
        return state

    def test_unknown_submission_is_persisted_and_blocks_duplicate(self):
        get_orderable_quantity = AsyncMock(return_value=2)
        place_order = AsyncMock(
            return_value={
                "status": "unknown",
                "accepted": False,
                "executed": False,
                "terminal": False,
                "order_no": None,
                "message": "result unknown",
            }
        )
        adapter = type(
            "UnknownAdapter",
            (),
            {
                "get_orderable_quantity": get_orderable_quantity,
                "place_order": place_order,
            },
        )()
        decision = {
            "action": "BUY",
            "ticker": "005930",
            "quantity": 2,
            "price": 70000,
            "reason": "test",
        }

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("brokers.factory.get_broker_adapter", return_value=adapter),
                patch("db.DB_PATH", Path(tmp) / "toss.db"),
            ):
                first = asyncio.run(
                    _execute_broker_order(decision, broker_name="toss")
                )
                second = asyncio.run(
                    _execute_broker_order(decision, broker_name="toss")
                )

        self.assertEqual(first["status"], "unknown")
        self.assertFalse(first["terminal"])
        self.assertEqual(second["status"], "blocked")
        self.assertEqual(second["mode"], "toss_real_pending_order")
        self.assertEqual(place_order.await_count, 1)

    def test_sell_is_capped_by_toss_sellable_quantity(self):
        get_sellable_quantity = AsyncMock(return_value=2)
        place_order = AsyncMock(
            return_value={
                "status": "unknown",
                "accepted": False,
                "executed": False,
                "terminal": False,
                "order_no": None,
                "message": "result unknown",
            }
        )
        adapter = type(
            "SellAdapter",
            (),
            {
                "get_sellable_quantity": get_sellable_quantity,
                "place_order": place_order,
            },
        )()
        decision = {
            "action": "SELL",
            "ticker": "005930",
            "quantity": 5,
            "price": 70000,
            "reason": "test",
        }

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("brokers.factory.get_broker_adapter", return_value=adapter),
                patch("db.DB_PATH", Path(tmp) / "toss.db"),
            ):
                result = asyncio.run(
                    _execute_broker_order(decision, broker_name="toss")
                )

        self.assertEqual(result["quantity"], 2)
        get_sellable_quantity.assert_awaited_once_with("005930")
        submitted = place_order.await_args_list[0].args[0]
        self.assertEqual(submitted.side, "SELL")
        self.assertEqual(submitted.quantity, 2)

    def test_pre_mutation_block_is_terminal_and_does_not_poison_next_order(self):
        get_orderable_quantity = AsyncMock(return_value=1)
        place_order = AsyncMock(
            return_value={
                "status": "blocked",
                "accepted": False,
                "executed": False,
                "terminal": True,
                "order_no": None,
                "message": "preview blocked",
            }
        )
        adapter = type(
            "BlockedAdapter",
            (),
            {
                "get_orderable_quantity": get_orderable_quantity,
                "place_order": place_order,
            },
        )()
        decision = {
            "action": "BUY",
            "ticker": "005930",
            "quantity": 1,
            "price": 70000,
            "reason": "test",
        }

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("brokers.factory.get_broker_adapter", return_value=adapter),
                patch("db.DB_PATH", Path(tmp) / "toss.db"),
            ):
                first = asyncio.run(
                    _execute_broker_order(decision, broker_name="toss")
                )
                second = asyncio.run(
                    _execute_broker_order(decision, broker_name="toss")
                )

        self.assertEqual(first["status"], "rejected")
        self.assertTrue(first["terminal"])
        self.assertEqual(second["status"], "rejected")
        self.assertEqual(place_order.await_count, 2)

    def test_restart_reconcile_recovers_toss_fill_without_resubmission(self):
        get_orderable_quantity = AsyncMock(return_value=1)
        place_order = AsyncMock(
            return_value={
                "status": "accepted",
                "accepted": True,
                "executed": False,
                "terminal": False,
                "order_no": "2026-07-20/10",
                "order_date": "2026-07-20",
            }
        )
        get_order_status = AsyncMock(
            side_effect=[
                RuntimeError("temporary read failure"),
                {
                    "status": "filled",
                    "accepted": True,
                    "executed": True,
                    "terminal": True,
                    "order_no": "2026-07-20/10",
                    "filled_qty": 1,
                    "remaining_qty": 0,
                    "average_fill_price": 69900,
                },
            ]
        )
        adapter = type(
            "FilledAdapter",
            (),
            {
                "get_orderable_quantity": get_orderable_quantity,
                "place_order": place_order,
                "get_order_status": get_order_status,
            },
        )()
        decision = {
            "action": "BUY",
            "ticker": "005930",
            "quantity": 1,
            "price": 70000,
            "reason": "test",
        }

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("brokers.factory.get_broker_adapter", return_value=adapter),
                patch("db.DB_PATH", Path(tmp) / "toss.db"),
            ):
                submitted = asyncio.run(
                    _execute_broker_order(decision, broker_name="toss")
                )
                recovered = asyncio.run(
                    reconcile_pending_toss_orders(adapter=adapter, mode="real")
                )

        self.assertEqual(submitted["status"], "accepted")
        self.assertEqual(recovered[0]["status"], "filled")
        self.assertEqual(recovered[0]["filled_qty"], 1)
        self.assertEqual(place_order.await_count, 1)

    def test_identityless_recovery_rejects_order_from_another_trade_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "toss.db"
            state = self._submit_identityless_unknown(db_path)
            attempted_at = _toss_attempted_at(
                state.order.intent.client_order_id
            )
            get_order_status = AsyncMock()
            recovery_adapter = type(
                "RecoveryAdapter",
                (),
                {
                    "get_pending_orders": AsyncMock(
                        return_value=[
                            {
                                "id": "2000-01-01/10",
                                "order_date": "2000-01-01",
                                "submitted_at": attempted_at.isoformat(),
                                "symbol": "005930",
                                "side": "buy",
                                "quantity": 1,
                                "price": 70000,
                            }
                        ]
                    ),
                    "get_completed_orders": AsyncMock(return_value=[]),
                    "get_order_status": get_order_status,
                },
            )()

            with patch("db.DB_PATH", db_path):
                recovered = asyncio.run(
                    reconcile_pending_toss_orders(
                        adapter=recovery_adapter, mode="real"
                    )
                )
                remaining = db.get_pending_broker_orders(
                    broker="toss", broker_mode="real"
                )[0]

        self.assertEqual(recovered[0]["status"], "unknown")
        self.assertIsNone(remaining.broker_order_no)
        get_order_status.assert_not_awaited()

    def test_identityless_recovery_does_not_bind_two_identical_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "toss.db"
            state = self._submit_identityless_unknown(db_path)
            attempted_at = _toss_attempted_at(
                state.order.intent.client_order_id
            )
            kst = timezone(timedelta(hours=9))
            order_date = attempted_at.astimezone(kst).strftime("%Y-%m-%d")
            candidate = {
                "order_date": order_date,
                "submitted_at": attempted_at.isoformat(),
                "symbol": "005930",
                "side": "buy",
                "quantity": 1,
                "price": 70000,
            }
            get_order_status = AsyncMock()
            recovery_adapter = type(
                "AmbiguousRecoveryAdapter",
                (),
                {
                    "get_pending_orders": AsyncMock(
                        return_value=[
                            {**candidate, "id": f"{order_date}/10"},
                            {**candidate, "id": f"{order_date}/11"},
                        ]
                    ),
                    "get_completed_orders": AsyncMock(return_value=[]),
                    "get_order_status": get_order_status,
                },
            )()

            with patch("db.DB_PATH", db_path):
                recovered = asyncio.run(
                    reconcile_pending_toss_orders(
                        adapter=recovery_adapter, mode="real"
                    )
                )
                remaining = db.get_pending_broker_orders(
                    broker="toss", broker_mode="real"
                )[0]

        self.assertEqual(recovered[0]["status"], "unknown")
        self.assertIsNone(remaining.broker_order_no)
        get_order_status.assert_not_awaited()

    def test_invalid_broker_order_date_becomes_unknown_instead_of_crashing(self):
        adapter = type(
            "InvalidDateAdapter",
            (),
            {
                "get_orderable_quantity": AsyncMock(return_value=1),
                "place_order": AsyncMock(
                    return_value={
                        "status": "accepted",
                        "accepted": True,
                        "executed": False,
                        "terminal": False,
                        "order_no": "2026-07-20/10",
                        "order_date": "not-a-date",
                    }
                ),
            },
        )()
        decision = {
            "action": "BUY",
            "ticker": "005930",
            "quantity": 1,
            "price": 70000,
            "reason": "test",
        }

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("brokers.factory.get_broker_adapter", return_value=adapter),
                patch("db.DB_PATH", Path(tmp) / "toss.db"),
            ):
                result = asyncio.run(
                    _execute_broker_order(decision, broker_name="toss")
                )

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["terminal"])
        self.assertIn("식별자", result["message"])


if __name__ == "__main__":
    unittest.main()
