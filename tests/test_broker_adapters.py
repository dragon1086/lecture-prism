import asyncio
from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from brokers.base import BrokerOrder, BrokerQuote, BrokerQuoteError, validate_broker_quote
from brokers.config import load_env_file
from brokers.kis import KISBrokerAdapter, selected_kis_mode
from brokers.kiwoom import KiwoomBrokerAdapter
from trading import _execute_broker_order, _live_cli_block_result
from market_calendar import KST, MarketStatus


_ENV_KEYS = {
    "LECTURE_BROKER",
    "LECTURE_BROKER_MODE",
    "LECTURE_ENABLE_LIVE_BROKER",
    "LECTURE_ALLOW_REAL_BROKER",
    "LECTURE_ENABLE_LIVE_KIS",
    "LECTURE_ALLOW_REAL_KIS",
    "LECTURE_KIS_MODE",
    "KIS_MODE",
    "LECTURE_ENABLE_LIVE_KIWOOM",
    "LECTURE_ALLOW_REAL_KIWOOM",
    "LECTURE_ENABLE_LIVE_TOSS",
    "LECTURE_ALLOW_REAL_TOSS",
    "LECTURE_ENABLE_LIVE_CUSTOM",
    "LECTURE_ALLOW_REAL_CUSTOM",
    "KIWOOM_MODE",
    "KIWOOM_APP_KEY",
    "KIWOOM_APPKEY",
    "KIWOOM_SECRET_KEY",
    "KIWOOM_SECRETKEY",
    "KIWOOM_ACCESS_TOKEN",
    "KIWOOM_BASE_URL",
    "KIWOOM_EXCHANGE",
    "KIWOOM_TRADE_TYPE",
    "TOSS_SECURITIES_MODE",
    "TOSS_SECURITIES_BASE_URL",
    "TOSS_SECURITIES_API_KEY",
    "TOSS_SECURITIES_ACCOUNT_ID",
    "TOSSCTL_PATH",
    "TOSSCTL_TIMEOUT_SECONDS",
}


def _decision():
    return {
        "action": "BUY",
        "ticker": "005930",
        "quantity": 2,
        "price": 70000,
        "reason": "테스트",
        "stop_loss": -0.07,
    }


class BrokerAdapterTest(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key in _ENV_KEYS:
            saved = self._saved[key]
            if saved is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = saved

    def test_load_env_file_does_not_override_existing_env_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text('LECTURE_BROKER=kiwoom\nQUOTED_VALUE="hello world"\n', encoding="utf-8")
            os.environ["LECTURE_BROKER"] = "kis"

            load_env_file(env_path)

            self.assertEqual(os.environ["LECTURE_BROKER"], "kis")
            self.assertEqual(os.environ["QUOTED_VALUE"], "hello world")

    def test_kiwoom_order_payload_uses_official_order_fields(self):
        os.environ["KIWOOM_ACCESS_TOKEN"] = "token"
        adapter = KiwoomBrokerAdapter(mode="demo")
        calls = []

        def fake_request(path, payload, *, headers):
            calls.append((path, payload, headers))
            return {"return_code": 0, "return_msg": "정상적으로 처리되었습니다", "ord_no": "00024"}

        adapter._request_json = fake_request  # type: ignore[method-assign]

        result = asyncio.run(adapter.place_order(BrokerOrder("BUY", "005930", 3, 70000)))

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "accepted")
        self.assertTrue(result["accepted"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])
        self.assertEqual(result["order_no"], "00024")
        self.assertEqual(calls[0][0], "/api/dostk/ordr")
        self.assertEqual(calls[0][2]["api-id"], "kt10000")
        self.assertEqual(
            calls[0][1],
            {
                "dmst_stex_tp": "KRX",
                "stk_cd": "005930",
                "ord_qty": "3",
                "ord_uv": "70000",
                "trde_tp": "0",
                "cond_uv": "",
            },
        )

    def test_kiwoom_adapter_fails_closed_without_credentials(self):
        adapter = KiwoomBrokerAdapter(mode="demo")

        result = asyncio.run(adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000)))

        self.assertFalse(result["success"])
        self.assertEqual(result["mode"], "kiwoom_credentials_missing")

    def test_kis_mode_ignores_deleted_yaml_default_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "kis_devlp.yaml"
            config_path.write_text("default_mode: real\n", encoding="utf-8")

            self.assertEqual(selected_kis_mode(config_path=config_path), "demo")

        os.environ["LECTURE_KIS_MODE"] = "real"
        self.assertEqual(selected_kis_mode(), "real")

    def test_kis_adapter_maps_buy_and_sell_to_injected_client(self):
        calls = []

        class Client:
            def place_cash_order(self, ticker, side, quantity, price):
                calls.append((ticker, side, quantity, price))
                return {
                    "status": "accepted",
                    "accepted": True,
                    "executed": False,
                    "terminal": False,
                    "order_no": str(len(calls)),
                    "message": "accepted",
                }

        class Gate:
            def check(self, now):
                return MarketStatus(
                    now, "20260720", True, True, True, "open", "cache"
                )

        adapter = KISBrokerAdapter(
            mode="demo",
            client=Client(),
            gate=Gate(),
            clock=lambda: datetime(2026, 7, 20, 10, 0, tzinfo=KST),
        )

        buy = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 3, 70000))
        )
        sell = asyncio.run(
            adapter.place_order(BrokerOrder("SELL", "005930", 2, 71000))
        )

        self.assertEqual(
            calls,
            [("005930", "BUY", 3, 70000), ("005930", "SELL", 2, 71000)],
        )
        self.assertTrue(buy["accepted"])
        self.assertFalse(buy["executed"])
        self.assertEqual(sell["order_no"], "2")

    def test_broker_quote_validator_accepts_fresh_domestic_krw_quote(self):
        observed = datetime(2026, 7, 20, 1, 5, tzinfo=timezone.utc)
        quote = BrokerQuote(
            ticker="005930",
            price=70100,
            currency="KRW",
            market="KRX",
            observed_at=observed,
            source="kis.inquire-price",
        )

        validated = validate_broker_quote(
            quote,
            expected_ticker="005930",
            now=observed + timedelta(seconds=30),
            max_age=timedelta(minutes=1),
        )

        self.assertEqual(validated.price, 70100)

    def test_broker_quote_validator_rejects_bad_domestic_quote_contracts(self):
        observed = datetime(2026, 7, 20, 1, 5, tzinfo=timezone.utc)
        valid = {
            "ticker": "005930",
            "price": 70100,
            "currency": "KRW",
            "market": "KRX",
            "observed_at": observed,
            "source": "kis.inquire-price",
        }
        cases = [
            ("wrong ticker", {"ticker": "000660"}),
            ("non-KRW", {"currency": "USD"}),
            ("zero price", {"price": 0}),
            ("negative price", {"price": -1}),
            ("non-integral price", {"price": 70100.5}),
            ("stale timestamp", {"observed_at": observed - timedelta(minutes=2)}),
        ]
        for name, override in cases:
            with self.subTest(name=name):
                quote = BrokerQuote(**{**valid, **override})
                with self.assertRaises(BrokerQuoteError):
                    validate_broker_quote(
                        quote,
                        expected_ticker="005930",
                        now=observed,
                        max_age=timedelta(minutes=1),
                    )

    def test_kis_adapter_get_quote_uses_client_quote_and_validation(self):
        observed = datetime(2026, 7, 20, 1, 5, tzinfo=timezone.utc)

        class Client:
            def get_quote(self, ticker):
                self.ticker = ticker
                return BrokerQuote(
                    ticker=ticker,
                    price=70100,
                    currency="KRW",
                    market="KRX",
                    observed_at=observed,
                    source="kis.inquire-price",
                )

        client = Client()
        adapter = KISBrokerAdapter(
            mode="demo",
            client=client,
            gate=object(),
            clock=lambda: observed + timedelta(seconds=10),
        )

        quote = asyncio.run(adapter.get_quote("005930"))

        self.assertEqual(client.ticker, "005930")
        self.assertEqual(quote.price, 70100)

    def test_kis_adapter_market_block_happens_before_order_post(self):
        class Client:
            def place_cash_order(self, *args):
                raise AssertionError("order POST must not run")

        class Gate:
            def check(self, now):
                return MarketStatus(
                    now,
                    "20260718",
                    False,
                    False,
                    False,
                    "weekend",
                    "deterministic",
                )

        adapter = KISBrokerAdapter(
            mode="demo",
            client=Client(),
            gate=Gate(),
            clock=lambda: datetime(2026, 7, 18, 10, 0, tzinfo=KST),
        )

        result = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["mode"], "kis_demo_weekend")
        self.assertTrue(result["terminal"])

    def test_kis_real_place_and_cancel_block_without_live_gates(self):
        calls = []

        class Client:
            def place_cash_order(self, *args):
                calls.append(("place", args))
                raise AssertionError("real KIS order POST must not run")

            def cancel_order(self, *args, **kwargs):
                calls.append(("cancel", args, kwargs))
                raise AssertionError("real KIS cancel POST must not run")

        class Gate:
            def check(self, now):
                calls.append(("gate", now))
                raise AssertionError("market gate must not run before live gate")

        adapter = KISBrokerAdapter(
            mode="real",
            client=Client(),
            gate=Gate(),
            clock=lambda: datetime(2026, 7, 20, 10, 0, tzinfo=KST),
        )

        place = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
        )
        cancel = asyncio.run(
            adapter.cancel_order(
                "42", quantity=1, order_date="20260720", org_no="12345"
            )
        )

        self.assertEqual(place["status"], "blocked")
        self.assertEqual(place["mode"], "kis_real_live_gate_blocked")
        self.assertTrue(place["terminal"])
        self.assertEqual(cancel["status"], "blocked")
        self.assertEqual(cancel["mode"], "kis_real_live_gate_blocked")
        self.assertEqual(calls, [])

    def test_kis_adapter_treats_post_boundary_exception_as_unknown(self):
        class Client:
            def place_cash_order(self, *args):
                raise ConnectionError("connection reset after write")

        class Gate:
            def check(self, now):
                return MarketStatus(
                    now, "20260720", True, True, True, "open", "cache"
                )

        adapter = KISBrokerAdapter(
            mode="demo",
            client=Client(),
            gate=Gate(),
            clock=lambda: datetime(2026, 7, 20, 10, 0, tzinfo=KST),
        )

        result = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
        )

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])

    def test_kis_order_status_default_date_uses_kst_calendar_day(self):
        calls = []

        class Client:
            def get_order_status(self, order_no, *, business_date):
                calls.append((order_no, business_date))
                return {"rows": []}

        adapter = KISBrokerAdapter(
            mode="demo",
            client=Client(),
            gate=object(),
            clock=lambda: datetime.fromisoformat("2026-07-19T15:30:00+00:00"),
        )

        asyncio.run(adapter.get_order_status("1001"))

        self.assertEqual(calls, [("1001", "20260720")])

    def test_kis_accepted_order_is_not_reported_as_executed_by_trading(self):
        os.environ["LECTURE_ENABLE_LIVE_BROKER"] = "1"
        os.environ["LECTURE_KIS_MODE"] = "demo"
        adapter = type(
            "AcceptedAdapter",
            (),
            {
                "get_orderable_quantity": AsyncMock(return_value=2),
                "place_order": AsyncMock(
                    return_value={
                        "success": True,
                        "status": "accepted",
                        "accepted": True,
                        "executed": False,
                        "terminal": False,
                        "order_no": "1001",
                        "org_no": "91252",
                        "message": "accepted",
                    }
                )
            },
        )()

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("brokers.factory.get_broker_adapter", return_value=adapter),
                patch("db.DB_PATH", Path(tmp) / "accepted.db"),
            ):
                result = asyncio.run(
                    _execute_broker_order(_decision(), broker_name="kis")
                )

        self.assertEqual(result["status"], "accepted")
        self.assertTrue(result["accepted"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["terminal"])
        self.assertEqual(result["requested_qty"], 2)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["remaining_qty"], 2)

    def test_kiwoom_real_place_and_cancel_block_without_live_gates(self):
        os.environ["KIWOOM_ACCESS_TOKEN"] = "token"
        adapter = KiwoomBrokerAdapter(mode="real")
        calls = []

        def fake_request(path, payload, *, headers):
            calls.append((path, payload, headers))
            raise AssertionError("real Kiwoom mutation POST must not run")

        adapter._request_json = fake_request  # type: ignore[method-assign]

        place = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
        )
        cancel = asyncio.run(
            adapter.cancel_order("KW1001", ticker="005930", quantity=1)
        )

        self.assertEqual(place["status"], "blocked")
        self.assertEqual(place["mode"], "kiwoom_real_live_gate_blocked")
        self.assertTrue(place["terminal"])
        self.assertEqual(cancel["status"], "blocked")
        self.assertEqual(cancel["mode"], "kiwoom_real_live_gate_blocked")
        self.assertEqual(calls, [])

    def test_trading_blocks_live_broker_until_explicitly_enabled(self):
        os.environ["LECTURE_BROKER"] = "kiwoom"

        result = asyncio.run(_execute_broker_order(_decision()))

        self.assertFalse(result["executed"])
        self.assertEqual(result["mode"], "live_blocked")
        self.assertEqual(result["broker"], "kiwoom")

    def test_live_cli_blocks_before_exit_quote_monitoring(self):
        with patch.dict(
            os.environ,
            {
                "LECTURE_BROKER": "kis",
                "LECTURE_ENABLE_LIVE_BROKER": "0",
                "LECTURE_ALLOW_REAL_BROKER": "0",
            },
            clear=False,
        ):
            result = _live_cli_block_result()

        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "live_blocked")
        self.assertFalse(result["executed"])
        self.assertEqual(result["broker"], "kis")

    def test_live_gate_isolated_test_never_reads_config_or_calls_adapter(self):
        live_keys = {
            key
            for key in os.environ
            if key.startswith("LECTURE_")
            and ("ENABLE_LIVE" in key or "ALLOW_REAL" in key)
        } | {
            "LECTURE_ENABLE_LIVE_BROKER",
            "LECTURE_ALLOW_REAL_BROKER",
            "LECTURE_ENABLE_LIVE_KIS",
            "LECTURE_ALLOW_REAL_KIS",
            "LECTURE_ENABLE_LIVE_KIWOOM",
            "LECTURE_ALLOW_REAL_KIWOOM",
            "LECTURE_ENABLE_LIVE_TOSS",
            "LECTURE_ALLOW_REAL_TOSS",
            "LECTURE_ENABLE_LIVE_CUSTOM",
            "LECTURE_ALLOW_REAL_CUSTOM",
        }
        sanitized = {key: "0" for key in live_keys}
        forbidden_place_order = AsyncMock(
            side_effect=AssertionError("broker place_order must not run")
        )
        forbidden_adapter = type(
            "ForbiddenAdapter",
            (),
            {"place_order": forbidden_place_order},
        )()

        with patch.dict(os.environ, sanitized, clear=False):
            with (
                patch(
                    "brokers.factory.get_broker_adapter",
                    side_effect=AssertionError(
                        "broker factory must not run"
                    ),
                ) as get_adapter,
            ):
                result = asyncio.run(
                    _execute_broker_order(_decision(), broker_name="kis")
                )

        self.assertFalse(result["executed"])
        self.assertEqual(result["mode"], "live_blocked")
        self.assertEqual(result["broker"], "kis")
        get_adapter.assert_not_called()
        forbidden_place_order.assert_not_awaited()

    def test_toss_demo_mode_is_blocked_before_wts_access(self):
        os.environ["LECTURE_ENABLE_LIVE_BROKER"] = "1"

        with patch(
            "brokers.factory.get_broker_adapter",
            side_effect=AssertionError("demo mode must not load Toss adapter"),
        ) as get_adapter:
            result = asyncio.run(
                _execute_broker_order(_decision(), broker_name="toss")
            )

        self.assertFalse(result["executed"])
        self.assertEqual(result["mode"], "toss_demo_unavailable")
        self.assertEqual(result["broker"], "toss")
        self.assertIn("모의투자", result["message"])
        get_adapter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
