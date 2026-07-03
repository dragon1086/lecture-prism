import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from brokers.base import BrokerOrder
from brokers.config import load_env_file
from brokers.kis import selected_kis_mode
from brokers.kiwoom import KiwoomBrokerAdapter
from trading import _execute_broker_order


_ENV_KEYS = {
    "LECTURE_BROKER",
    "LECTURE_BROKER_MODE",
    "LECTURE_ENABLE_LIVE_BROKER",
    "LECTURE_ALLOW_REAL_BROKER",
    "LECTURE_KIS_MODE",
    "KIS_MODE",
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

    def test_trading_blocks_live_broker_until_explicitly_enabled(self):
        os.environ["LECTURE_BROKER"] = "kiwoom"

        result = asyncio.run(_execute_broker_order(_decision()))

        self.assertFalse(result["executed"])
        self.assertEqual(result["mode"], "live_blocked")
        self.assertEqual(result["broker"], "kiwoom")

    def test_toss_adapter_is_safe_unsupported_template(self):
        os.environ["LECTURE_ENABLE_LIVE_BROKER"] = "1"

        result = asyncio.run(_execute_broker_order(_decision(), broker_name="toss"))

        self.assertFalse(result["executed"])
        self.assertEqual(result["mode"], "toss_unsupported")
        self.assertEqual(result["broker"], "toss")
        self.assertIn("공개 주문 API", result["message"])


if __name__ == "__main__":
    unittest.main()
