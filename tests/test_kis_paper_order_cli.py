from __future__ import annotations

import unittest
import io
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from brokers.base import BrokerQuote


@dataclass
class _Config:
    mode: str = "paper"


class _FakeClient:
    def __init__(self, *, mode: str = "paper") -> None:
        self.config = _Config(mode)
        self.orders: list[tuple[str, str, int, int]] = []

    def get_quote(self, ticker: str) -> BrokerQuote:
        return BrokerQuote(
            ticker=ticker,
            price=3_550,
            currency="KRW",
            market="KRX",
            observed_at=datetime.now(timezone.utc),
            source="test",
        )

    def place_cash_order(self, ticker: str, side: str, quantity: int, price: int):
        self.orders.append((ticker, side, quantity, price))
        return {
            "status": "accepted",
            "accepted": True,
            "executed": False,
            "order_no": "paper-1",
        }


class KISPaperOrderCliTest(unittest.TestCase):
    def test_cli_keeps_quote_visible_when_order_fails(self):
        module = self._module()
        client = _FakeClient()
        output, errors = io.StringIO(), io.StringIO()
        def reject(*args):
            self.assertIn("조회 가격: 3,550원", output.getvalue())
            raise ValueError("장운영일자가 주문일과 상이합니다")
        with patch.dict("os.environ", {"LECTURE_ENABLE_LIVE_BROKER": "1"}), patch.object(module, "_order_client", return_value=client), patch.object(client, "place_cash_order", side_effect=reject), patch("sys.argv", ["kis_paper_order.py", "061040"]), redirect_stdout(output), redirect_stderr(errors):
            code = module.main()
        self.assertEqual(code, 1)
        self.assertIn("종목코드: 061040", output.getvalue())
        self.assertIn("장운영일자가 주문일과 상이합니다", errors.getvalue())

    def test_new_cli_client_reuses_saved_token_without_request(self):
        from brokers.kis_client import KISConfig
        from tests.test_kis_client import FakeTransport, FakeResponse

        module = self._module()
        config = KISConfig("real", "fixture-key", "fixture-secret", "12345678")
        with TemporaryDirectory() as directory, patch.object(module, "PROJECT_ROOT", Path(directory)), patch.object(module, "selected_kis_mode", return_value="real"), patch.object(module.KISConfig, "from_env", return_value=config):
            first = module._order_client()
            first.transport = FakeTransport(FakeResponse({"access_token": "fixture-token", "expires_in": 3600}))
            self.assertEqual(first.authenticate(), "fixture-token")
            second = module._order_client()
            second.transport = FakeTransport()
            self.assertEqual(second.authenticate(), "fixture-token")
            self.assertEqual(second.transport.calls, [])
            self.assertNotIn(b"fixture-token", (Path(directory) / ".cache" / "KIS_real_order.token").read_bytes())

    def _module(self):
        try:
            from order import kis_paper_order
        except ModuleNotFoundError:
            self.fail("order.kis_paper_order 모듈이 필요합니다")
        return kis_paper_order

    def test_demo_mode_submits_one_share_market_buy(self):
        module = self._module()
        client = _FakeClient()

        with patch.dict(
            "os.environ", {"LECTURE_ENABLE_LIVE_BROKER": "1"}, clear=False
        ):
            result = module.run("061040", client=client)

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["ticker"], "061040")
        self.assertEqual(result["quote_price"], 3_550)
        self.assertEqual(result["quantity"], 1)
        self.assertEqual(result["mode"], "paper")
        self.assertEqual(client.orders, [("061040", "BUY", 1, 0)])

    def test_demo_mode_is_blocked_until_broker_calls_are_enabled(self):
        module = self._module()
        client = _FakeClient()

        with patch.dict(
            "os.environ",
            {
                "LECTURE_ENABLE_LIVE_BROKER": "0",
            },
            clear=False,
        ):
            result = module.run("061040", client=client)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["mode"], "kis_paper_live_gate_blocked")
        self.assertEqual(client.orders, [])

    def test_real_mode_submits_when_both_live_gates_are_enabled(self):
        module = self._module()
        client = _FakeClient(mode="real")

        with patch.dict(
            "os.environ",
            {
                "LECTURE_ENABLE_LIVE_BROKER": "1",
                "LECTURE_ALLOW_REAL_BROKER": "1",
            },
            clear=False,
        ):
            result = module.run("061040", client=client)

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["mode"], "real")
        self.assertEqual(client.orders, [("061040", "BUY", 1, 0)])

    def test_real_mode_is_blocked_without_both_live_gates(self):
        module = self._module()
        client = _FakeClient(mode="real")

        with patch.dict(
            "os.environ",
            {
                "LECTURE_ENABLE_LIVE_BROKER": "0",
                "LECTURE_ALLOW_REAL_BROKER": "0",
            },
            clear=False,
        ):
            result = module.run("061040", client=client)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["mode"], "kis_real_live_gate_blocked")
        self.assertEqual(client.orders, [])

    def test_rejects_invalid_domestic_ticker(self):
        module = self._module()

        with self.assertRaisesRegex(ValueError, "6자리"):
            module.run("RFTECH", client=_FakeClient())

    def test_env_mode_selects_matching_credentials(self):
        module = self._module()

        with (
            patch.dict("os.environ", {"LECTURE_BROKER_MODE": "real"}, clear=False),
            patch.object(module.KISConfig, "from_env", return_value=_Config("real")) as config,
            patch.object(module, "KISClient", return_value=_FakeClient(mode="real")),
        ):
            client = module._order_client()

        config.assert_called_once_with("real")
        self.assertEqual(client.config.mode, "real")


if __name__ == "__main__":
    unittest.main()
