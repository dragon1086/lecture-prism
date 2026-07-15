import asyncio
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import brokers.kis as kis_module
from brokers.base import BrokerOrder
from brokers.config import load_env_file
from brokers.kis import KISBrokerAdapter, selected_kis_mode
from brokers.kiwoom import KiwoomBrokerAdapter
from trading import _execute_broker_order


_ENV_KEYS = {
    "LECTURE_BROKER",
    "LECTURE_BROKER_MODE",
    "LECTURE_ENABLE_LIVE_BROKER",
    "LECTURE_ALLOW_REAL_BROKER",
    "LECTURE_KIS_MODE",
    "KIS_MODE",
    "LECTURE_ENABLE_LIVE_KIS",
    "LECTURE_ALLOW_REAL_KIS",
    "KIS_PAPER_APP_KEY",
    "KIS_PAPER_APP_SECRET",
    "KIS_PAPER_ACCOUNT_NO",
    "KIS_PAPER_PRODUCT_CODE",
    "KIS_REAL_APP_KEY",
    "KIS_REAL_APP_SECRET",
    "KIS_REAL_ACCOUNT_NO",
    "KIS_REAL_PRODUCT_CODE",
    "LECTURE_ENABLE_LIVE_KIWOOM",
    "LECTURE_ALLOW_REAL_KIWOOM",
    "KIWOOM_MODE",
    "KIWOOM_APP_KEY",
    "KIWOOM_APPKEY",
    "KIWOOM_SECRET_KEY",
    "KIWOOM_SECRETKEY",
    "KIWOOM_ACCESS_TOKEN",
    "KIWOOM_EXCHANGE",
    "KIWOOM_TRADE_TYPE",
    "TOSS_SECURITIES_MODE",
    "TOSS_SECURITIES_BASE_URL",
    "TOSS_SECURITIES_API_KEY",
    "TOSS_SECURITIES_ACCOUNT_ID",
}


class _FakeMarketGate:
    def __init__(self, *, allowed=True, reason="market_open"):
        self.allowed = allowed
        self.reason = reason
        self.calls = []

    def check(self, now=None):
        self.calls.append(now)
        return SimpleNamespace(
            analysis_allowed=True,
            order_allowed=self.allowed,
            reason=self.reason,
        )


class _FakeKISClient:
    def __init__(self):
        self.order_calls = []
        self.account = {"output1": [{"pdno": "005930"}], "output2": []}

    def place_cash_order(self, ticker, side, quantity, price):
        self.order_calls.append((ticker, side, quantity, price))
        return {
            "success": True,
            "status": "accepted",
            "order_no": str(100 + len(self.order_calls)),
            "branch_no": "01",
            "requires_reconciliation": False,
        }

    def get_balance(self):
        return self.account

    def get_orderable_quantity(self, ticker, price):
        return {"ticker": ticker, "price": price, "nrcvb_buy_qty": "7"}

    def get_order_status(self, order_no, **kwargs):
        return {"order_no": order_no, "kwargs": kwargs}

    def cancel_order(self, order_no, quantity, **kwargs):
        return {"order_no": order_no, "quantity": quantity, "kwargs": kwargs}


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
            if self._saved[key] is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = self._saved[key]

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

    def test_kis_mode_can_fall_back_to_yaml_default_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "kis_devlp.yaml"
            config_path.write_text("default_mode: real\n", encoding="utf-8")

            self.assertEqual(selected_kis_mode(config_path=config_path), "real")

    def test_kis_adapter_maps_buy_and_sell_without_marking_acceptance_filled(self):
        client = _FakeKISClient()
        adapter = KISBrokerAdapter(
            mode="demo", client=client, market_gate=_FakeMarketGate()
        )

        buy = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
        )
        sell = asyncio.run(
            adapter.place_order(BrokerOrder("SELL", "005930", 2, 71000))
        )

        self.assertEqual(
            [("005930", "BUY", 1, 70000), ("005930", "SELL", 2, 71000)],
            client.order_calls,
        )
        for result in (buy, sell):
            self.assertTrue(result["success"])
            self.assertTrue(result["accepted"])
            self.assertFalse(result["executed"])
            self.assertEqual("accepted", result["status"])
            self.assertEqual("market_open", result["market_status"])

    def test_kis_adapter_blocks_post_when_market_gate_denies(self):
        client = _FakeKISClient()
        adapter = KISBrokerAdapter(
            mode="demo",
            client=client,
            market_gate=_FakeMarketGate(allowed=False, reason="market_closed"),
        )

        result = asyncio.run(
            adapter.place_order(BrokerOrder("BUY", "005930", 1, 70000))
        )

        self.assertFalse(result["success"])
        self.assertFalse(result["executed"])
        self.assertEqual("blocked", result["status"])
        self.assertEqual("market_closed", result["reason"])
        self.assertEqual("market_closed", result["market_status"])
        self.assertEqual([], client.order_calls)

    def test_kis_adapter_exposes_account_status_cancel_and_market_methods(self):
        client = _FakeKISClient()
        gate = _FakeMarketGate()
        adapter = KISBrokerAdapter(mode="demo", client=client, market_gate=gate)

        self.assertEqual(client.account, adapter.get_account())
        self.assertEqual(
            {"ticker": "005930", "price": 70000, "nrcvb_buy_qty": "7"},
            adapter.get_orderable_quantity("005930", 70000),
        )
        self.assertEqual(
            {"order_no": "101", "kwargs": {"start_date": "20260715"}},
            adapter.get_order_status("101", start_date="20260715"),
        )
        self.assertEqual(
            {
                "order_no": "101",
                "quantity": 2,
                "kwargs": {"branch_no": "01", "price": 70000, "cancel_all": False},
            },
            adapter.cancel_order(
                "101", 2, branch_no="01", price=70000, cancel_all=False
            ),
        )
        self.assertTrue(adapter.is_market_open())

    def test_importing_kis_adapter_without_config_performs_no_io(self):
        with patch("pathlib.Path.read_text", side_effect=AssertionError("file I/O")), patch(
            "urllib.request.urlopen", side_effect=AssertionError("network I/O")
        ):
            reloaded = importlib.reload(kis_module)

        self.assertTrue(hasattr(reloaded, "KISBrokerAdapter"))

    def test_trading_blocks_live_broker_until_explicitly_enabled(self):
        os.environ["LECTURE_BROKER"] = "kiwoom"

        result = asyncio.run(_execute_broker_order(_decision()))

        self.assertFalse(result["executed"])
        self.assertEqual(result["mode"], "live_blocked")
        self.assertEqual(result["broker"], "kiwoom")

    def test_kis_paper_still_requires_the_live_broker_enable_gate(self):
        result = asyncio.run(_execute_broker_order(_decision(), broker_name="kis"))

        self.assertFalse(result["executed"])
        self.assertEqual("live_blocked", result["mode"])
        self.assertEqual("kis", result["broker"])

    def test_kis_real_mode_still_requires_the_second_live_gate(self):
        os.environ["LECTURE_KIS_MODE"] = "real"
        os.environ["LECTURE_ENABLE_LIVE_BROKER"] = "1"

        result = asyncio.run(_execute_broker_order(_decision(), broker_name="kis"))

        self.assertFalse(result["executed"])
        self.assertEqual("real_blocked", result["mode"])
        self.assertEqual("kis", result["broker"])

    def test_toss_adapter_is_safe_unsupported_template(self):
        os.environ["LECTURE_ENABLE_LIVE_BROKER"] = "1"

        result = asyncio.run(_execute_broker_order(_decision(), broker_name="toss"))

        self.assertFalse(result["executed"])
        self.assertEqual(result["mode"], "toss_unsupported")
        self.assertEqual(result["broker"], "toss")
        self.assertIn("공개 주문 API", result["message"])


if __name__ == "__main__":
    unittest.main()
