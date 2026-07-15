import os
import unittest
from datetime import datetime, timezone

from brokers.kis_client import (
    KISClient,
    KISConfig,
    KISConfigError,
    KISResponseError,
    TransportResponse,
)


class _FakeTransport:
    def __init__(self):
        self.calls = []
        self.results = []

    def queue(self, body, headers=None):
        self.results.append(TransportResponse(body=body, headers=headers or {}))

    def queue_error(self, error):
        self.results.append(error)

    def request(
        self, method, url, *, headers=None, params=None, json_body=None, timeout=None
    ):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "params": dict(params or {}),
                "json_body": dict(json_body or {}),
                "timeout": timeout,
            }
        )
        if not self.results:
            raise AssertionError("fake transport has no queued response")
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class KISClientTests(unittest.TestCase):
    def setUp(self):
        self._gate_keys = (
            "LECTURE_ENABLE_LIVE_BROKER",
            "LECTURE_ENABLE_LIVE_KIS",
            "LECTURE_ALLOW_REAL_BROKER",
            "LECTURE_ALLOW_REAL_KIS",
        )
        self._saved_gates = {key: os.environ.get(key) for key in self._gate_keys}
        for key in self._gate_keys:
            os.environ.pop(key, None)
        os.environ["LECTURE_ENABLE_LIVE_BROKER"] = "1"
        self.config = KISConfig(
            mode="paper",
            app_key="paper-app-key",
            app_secret="paper-app-secret",
            account_no="12345678",
            product_code="01",
        )
        self.transport = _FakeTransport()
        self.clock = lambda: datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
        self.client = KISClient(
            self.config, transport=self.transport, clock=self.clock
        )
        self.transport.queue(
            {"access_token": "paper-access-token", "expires_in": 3600}
        )
        self.client.authenticate()
        self.transport.calls.clear()

    def tearDown(self):
        for key, value in self._saved_gates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_order_submission_is_blocked_when_safety_gate_is_closed(self):
        os.environ.pop("LECTURE_ENABLE_LIVE_BROKER", None)

        with self.assertRaises(KISConfigError):
            self.client.place_cash_order("005930", "BUY", 1, 70000)

        self.assertEqual([], self.transport.calls)

    def test_real_order_submission_requires_independent_real_money_gate(self):
        os.environ.pop("LECTURE_ALLOW_REAL_BROKER", None)
        real_transport = _FakeTransport()
        real_client = KISClient(
            KISConfig(
                mode="real",
                app_key="real-app-key",
                app_secret="real-app-secret",
                account_no="87654321",
            ),
            transport=real_transport,
            clock=self.clock,
        )

        with self.assertRaises(KISConfigError):
            real_client.place_cash_order("005930", "BUY", 1, 70000)

        self.assertEqual([], real_transport.calls)

    def test_config_from_env_isolates_paper_and_real_credentials(self):
        environ = {
            "KIS_PAPER_APP_KEY": "paper-key",
            "KIS_PAPER_APP_SECRET": "paper-secret",
            "KIS_PAPER_ACCOUNT_NO": "11112222",
            "KIS_REAL_APP_KEY": "real-key",
            "KIS_REAL_APP_SECRET": "real-secret",
            "KIS_REAL_ACCOUNT_NO": "99998888",
        }

        paper = KISConfig.from_env(environ, mode="paper")
        real = KISConfig.from_env(environ, mode="real")

        self.assertEqual("paper-key", paper.app_key)
        self.assertEqual("11112222", paper.account_no)
        self.assertEqual("real-key", real.app_key)
        self.assertEqual("99998888", real.account_no)
        self.assertIn("openapivts.koreainvestment.com:29443", paper.base_url)
        self.assertIn("openapi.koreainvestment.com:9443", real.base_url)
        for secret in ("paper-key", "paper-secret", "real-key", "real-secret"):
            self.assertNotIn(secret, repr(paper))
            self.assertNotIn(secret, repr(real))

    def test_paper_config_never_falls_back_to_real_credentials(self):
        environ = {
            "KIS_REAL_APP_KEY": "real-key",
            "KIS_REAL_APP_SECRET": "real-secret",
            "KIS_REAL_ACCOUNT_NO": "99998888",
        }

        with self.assertRaises(KISConfigError):
            KISConfig.from_env(environ, mode="paper")

    def test_authenticate_uses_paper_token_endpoint_and_namespace(self):
        transport = _FakeTransport()
        transport.queue({"access_token": "token-value", "expires_in": 7200})
        client = KISClient(self.config, transport=transport, clock=self.clock)

        token = client.authenticate()

        self.assertEqual("token-value", token)
        call = transport.calls[0]
        self.assertEqual("POST", call["method"])
        self.assertTrue(call["url"].endswith("/oauth2/tokenP"))
        self.assertIn("openapivts.koreainvestment.com:29443", call["url"])
        self.assertEqual(
            {
                "grant_type": "client_credentials",
                "appkey": "paper-app-key",
                "appsecret": "paper-app-secret",
            },
            call["json_body"],
        )

    def test_balance_uses_paper_tr_id_and_follows_continuation_keys(self):
        self.transport.queue(
            {
                "rt_cd": "0",
                "output1": [{"pdno": "005930"}],
                "output2": [{"tot_evlu_amt": "100000"}],
                "ctx_area_fk100": "next-fk",
                "ctx_area_nk100": "next-nk",
            },
            {"tr_cont": "M"},
        )
        self.transport.queue(
            {
                "rt_cd": "0",
                "output1": [{"pdno": "000660"}],
                "output2": [{"tot_evlu_amt": "200000"}],
                "ctx_area_fk100": "",
                "ctx_area_nk100": "",
            },
            {"tr_cont": ""},
        )

        result = self.client.get_balance()

        self.assertEqual(["005930", "000660"], [row["pdno"] for row in result["output1"]])
        self.assertEqual(2, len(self.transport.calls))
        self.assertEqual("VTTC8434R", self.transport.calls[0]["headers"]["tr_id"])
        self.assertEqual("next-fk", self.transport.calls[1]["params"]["CTX_AREA_FK100"])
        self.assertEqual("next-nk", self.transport.calls[1]["params"]["CTX_AREA_NK100"])
        self.assertEqual("N", self.transport.calls[1]["headers"]["tr_cont"])

    def test_orderable_quantity_uses_official_request_shape(self):
        self.transport.queue(
            {"rt_cd": "0", "output": {"nrcvb_buy_qty": "7"}}
        )

        result = self.client.get_orderable_quantity("005930", 70000)

        call = self.transport.calls[0]
        self.assertEqual("GET", call["method"])
        self.assertTrue(call["url"].endswith("/inquire-psbl-order"))
        self.assertEqual("VTTC8908R", call["headers"]["tr_id"])
        self.assertEqual("70000", call["params"]["ORD_UNPR"])
        self.assertEqual("7", result["nrcvb_buy_qty"])

    def test_paper_buy_and_sell_use_distinct_tr_ids_and_string_numbers(self):
        self.transport.queue(
            {"rt_cd": "0", "output": {"ODNO": "100", "KRX_FWDG_ORD_ORGNO": "01"}}
        )
        self.transport.queue(
            {"rt_cd": "0", "output": {"ODNO": "101", "KRX_FWDG_ORD_ORGNO": "01"}}
        )

        buy = self.client.place_cash_order("005930", "BUY", 1, 70000)
        sell = self.client.place_cash_order("005930", "SELL", 2, 71000)

        buy_call, sell_call = self.transport.calls
        self.assertEqual("VTTC0012U", buy_call["headers"]["tr_id"])
        self.assertEqual("VTTC0011U", sell_call["headers"]["tr_id"])
        self.assertEqual("1", buy_call["json_body"]["ORD_QTY"])
        self.assertEqual("70000", buy_call["json_body"]["ORD_UNPR"])
        self.assertEqual("2", sell_call["json_body"]["ORD_QTY"])
        self.assertEqual("71000", sell_call["json_body"]["ORD_UNPR"])
        self.assertEqual("accepted", buy["status"])
        self.assertTrue(buy["requires_reconciliation"])
        self.assertEqual("101", sell["order_no"])

    def test_post_order_timeout_is_unknown_and_is_never_retried(self):
        self.transport.queue_error(TimeoutError("synthetic timeout with paper-app-secret"))

        result = self.client.place_cash_order("005930", "BUY", 1, 70000)

        self.assertEqual(1, len(self.transport.calls))
        self.assertFalse(result["success"])
        self.assertEqual("unknown", result["status"])
        self.assertTrue(result["requires_reconciliation"])
        self.assertIsNone(result["order_no"])
        self.assertNotIn("paper-app-secret", repr(result))

    def test_post_order_connection_reset_is_unknown_and_is_never_retried(self):
        self.transport.queue_error(ConnectionResetError("response lost after submit"))

        result = self.client.place_cash_order("005930", "BUY", 1, 70000)

        self.assertEqual(1, len(self.transport.calls))
        self.assertFalse(result["success"])
        self.assertEqual("unknown", result["status"])
        self.assertTrue(result["requires_reconciliation"])
        self.assertIsNone(result["order_no"])

    def test_success_response_without_order_number_remains_unknown(self):
        self.transport.queue({"rt_cd": "0", "output": {}})

        result = self.client.place_cash_order("005930", "BUY", 1, 70000)

        self.assertEqual("unknown", result["status"])
        self.assertTrue(result["requires_reconciliation"])
        self.assertIsNone(result["order_no"])

    def test_success_response_without_output_remains_unknown(self):
        self.transport.queue({"rt_cd": "0"})

        result = self.client.place_cash_order("005930", "BUY", 1, 70000)

        self.assertEqual("unknown", result["status"])
        self.assertTrue(result["requires_reconciliation"])
        self.assertIsNone(result["order_no"])

    def test_response_with_order_number_but_missing_result_code_is_unknown(self):
        self.transport.queue({"output": {"ODNO": "100"}})

        result = self.client.place_cash_order("005930", "BUY", 1, 70000)

        self.assertEqual("unknown", result["status"])
        self.assertTrue(result["requires_reconciliation"])
        self.assertIsNone(result["order_no"])

    def test_fill_inquiry_uses_today_and_official_paper_tr_id(self):
        self.transport.queue({"rt_cd": "0", "output1": [], "output2": {}})

        self.client.get_order_status("100")

        call = self.transport.calls[0]
        self.assertEqual("VTTC0081R", call["headers"]["tr_id"])
        self.assertTrue(call["url"].endswith("/inquire-daily-ccld"))
        self.assertEqual("20260715", call["params"]["INQR_STRT_DT"])
        self.assertEqual("20260715", call["params"]["INQR_END_DT"])
        self.assertEqual("100", call["params"]["ODNO"])
        self.assertEqual("KRX", call["params"]["EXCG_ID_DVSN_CD"])

    def test_fill_inquiry_follows_official_continuation_pages(self):
        self.transport.queue(
            {
                "rt_cd": "0",
                "output1": [{"odno": "099"}],
                "output2": {},
                "ctx_area_fk100": "next-fk",
                "ctx_area_nk100": "next-nk",
            },
            {"tr_cont": "M"},
        )
        self.transport.queue(
            {
                "rt_cd": "0",
                "output1": [{"odno": "100"}],
                "output2": {},
                "ctx_area_fk100": "",
                "ctx_area_nk100": "",
            },
            {"tr_cont": ""},
        )

        result = self.client.get_order_status("100")

        self.assertEqual(["099", "100"], [row["odno"] for row in result["output1"]])
        self.assertEqual(2, len(self.transport.calls))
        self.assertEqual("next-fk", self.transport.calls[1]["params"]["CTX_AREA_FK100"])
        self.assertEqual("next-nk", self.transport.calls[1]["params"]["CTX_AREA_NK100"])
        self.assertEqual("N", self.transport.calls[1]["headers"]["tr_cont"])

    def test_market_day_uses_holiday_contract_and_exposes_open_flag(self):
        self.transport.queue(
            {"rt_cd": "0", "output": [{"bass_dt": "20260715", "opnd_yn": "Y"}]}
        )

        result = self.client.get_market_day()

        call = self.transport.calls[0]
        self.assertEqual("CTCA0903R", call["headers"]["tr_id"])
        self.assertTrue(call["url"].endswith("/chk-holiday"))
        self.assertEqual("20260715", call["params"]["BASS_DT"])
        self.assertTrue(result["is_open"])
        self.assertEqual("Y", result["opnd_yn"])

    def test_market_day_fails_closed_when_requested_date_is_missing(self):
        self.transport.queue(
            {"rt_cd": "0", "output": [{"bass_dt": "20260716", "opnd_yn": "Y"}]}
        )

        with self.assertRaises(KISResponseError):
            self.client.get_market_day("20260715")

    def test_daily_prices_use_business_dates_and_return_price_rows(self):
        rows = [{"stck_bsop_date": "20260714", "stck_clpr": "70000"}]
        self.transport.queue({"rt_cd": "0", "output1": {}, "output2": rows})

        result = self.client.get_daily_prices(
            "005930", start_date="20260701", end_date="20260714"
        )

        call = self.transport.calls[0]
        self.assertEqual("FHKST03010100", call["headers"]["tr_id"])
        self.assertEqual("20260701", call["params"]["FID_INPUT_DATE_1"])
        self.assertEqual("20260714", call["params"]["FID_INPUT_DATE_2"])
        self.assertEqual(rows, result)

    def test_cancel_order_uses_official_payload_and_string_numbers(self):
        self.transport.queue(
            {"rt_cd": "0", "output": {"ODNO": "200", "KRX_FWDG_ORD_ORGNO": "01"}}
        )

        self.client.cancel_order(
            "100", 3, branch_no="01", price=70000, cancel_all=False
        )

        call = self.transport.calls[0]
        self.assertEqual("VTTC0013U", call["headers"]["tr_id"])
        self.assertTrue(call["url"].endswith("/order-rvsecncl"))
        self.assertEqual("100", call["json_body"]["ORGN_ODNO"])
        self.assertEqual("02", call["json_body"]["RVSE_CNCL_DVSN_CD"])
        self.assertEqual("3", call["json_body"]["ORD_QTY"])
        self.assertEqual("70000", call["json_body"]["ORD_UNPR"])
        self.assertEqual("N", call["json_body"]["QTY_ALL_ORD_YN"])

    def test_invalid_response_raises_safe_error_and_repr_redacts_credentials(self):
        self.transport.queue(
            {
                "rt_cd": "1",
                "msg_cd": "EGW00001",
                "msg1": "rejected paper-app-secret paper-access-token",
            }
        )

        with self.assertRaises(KISResponseError) as caught:
            self.client.get_orderable_quantity("005930", 70000)

        text = str(caught.exception)
        self.assertIn("EGW00001", text)
        self.assertNotIn("paper-app-secret", text)
        self.assertNotIn("paper-access-token", text)
        self.assertNotIn("paper-app-secret", repr(self.client))
        self.assertNotIn("paper-access-token", repr(self.client))


if __name__ == "__main__":
    unittest.main()
