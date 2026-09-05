from __future__ import annotations

import os
import io
import json
import socket
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from brokers.kis_client import KISClient, KISConfig, KISRequestError, _URLTransport
from brokers.kis_client import PAPER_BASE_URL, REAL_BASE_URL


@dataclass
class FakeResponse:
    body: dict
    headers: dict | None = None
    status: int = 200


class FakeTransport:
    """Deterministic transport contract for the stdlib KIS client."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, *, headers=None, params=None, json=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "headers": dict(headers or {}),
                "params": dict(params or {}),
                "json": dict(json or {}),
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def ok(output=None, **extra):
    return FakeResponse({"rt_cd": "0", "msg1": "정상", "output": output or {}, **extra})


class KISConfigTest(unittest.TestCase):
    def test_http_error_keeps_provider_reason_but_redacts_credentials(self):
        config = KISConfig("real", "test-app-key", "test-app-secret", "12345678")
        body = json.dumps({"error_code": "EGW00133", "error_description": "rate limit test-app-secret", "access_token": "must-not-print"}).encode()
        error = HTTPError(config.base_url, 403, "Forbidden", {}, io.BytesIO(body))
        with patch("brokers.kis_client.urlopen", side_effect=error):
            with self.assertRaises(KISRequestError) as caught:
                KISClient(config).authenticate()
        message = str(caught.exception)
        self.assertIn("EGW00133", message)
        self.assertIn("/oauth2/tokenP", message)
        self.assertNotIn("test-app-secret", message)
        self.assertNotIn("must-not-print", message)
        self.assertEqual(caught.exception.status, 403)
        self.assertFalse(caught.exception.retryable)

    def test_from_env_uses_mode_specific_credential_namespace(self):
        env = {
            "KIS_PAPER_APP_KEY": "paper-key",
            "KIS_PAPER_APP_SECRET": "paper-secret",
            "KIS_PAPER_ACCOUNT_NO": "11111111",
            "KIS_REAL_APP_KEY": "real-key",
            "KIS_REAL_APP_SECRET": "real-secret",
            "KIS_REAL_ACCOUNT_NO": "99999999",
        }
        with patch.dict(os.environ, env, clear=True):
            paper = KISConfig.from_env(mode="paper")
            real = KISConfig.from_env(mode="real")

        self.assertEqual((paper.app_key, paper.app_secret, paper.account_no),
                         ("paper-key", "paper-secret", "11111111"))
        self.assertEqual((real.app_key, real.app_secret, real.account_no),
                         ("real-key", "real-secret", "99999999"))
        self.assertNotEqual(paper.base_url, real.base_url)

    def test_paper_and_real_modes_use_separate_official_hosts(self):
        paper = KISConfig("paper", "paper-key", "paper-secret", "paper-account")
        real = KISConfig("real", "real-key", "real-secret", "real-account")

        self.assertEqual(paper.base_url, PAPER_BASE_URL)
        self.assertEqual(real.base_url, REAL_BASE_URL)
        self.assertIn("openapivts", paper.base_url)
        self.assertNotIn("openapivts", real.base_url)

    def test_config_repr_redacts_credentials_and_account(self):
        config = KISConfig("paper", "public-app-key", "top-secret", "12345678")
        rendered = repr(config)
        self.assertNotIn("public-app-key", rendered)
        self.assertNotIn("top-secret", rendered)
        self.assertNotIn("12345678", rendered)

    def test_market_data_config_needs_no_account_and_keeps_modes_separate(self):
        env = {
            "KIS_PAPER_APP_KEY": "paper-key",
            "KIS_PAPER_APP_SECRET": "paper-secret",
            "KIS_REAL_APP_KEY": "real-key",
            "KIS_REAL_APP_SECRET": "real-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            paper = KISConfig.from_env_market_data("paper")
            real = KISConfig.from_env_market_data("real")

        self.assertEqual((paper.mode, paper.app_key, paper.app_secret),
                         ("paper", "paper-key", "paper-secret"))
        self.assertEqual((real.mode, real.app_key, real.app_secret),
                         ("real", "real-key", "real-secret"))
        self.assertEqual(paper.account_no, "")
        self.assertEqual(real.account_no, "")


class KISClientRequestContractTest(unittest.TestCase):
    def config(self):
        return KISConfig("paper", "app-key", "app-secret", "12345678", "01")

    def authenticated_client(self, *responses):
        transport = FakeTransport(
            FakeResponse({"access_token": "paper-token", "token_type": "Bearer", "expires_in": 3600}),
            *responses,
        )
        client = KISClient(self.config(), transport=transport)
        self.assertEqual(client.authenticate(), "paper-token")
        return client, transport

    def test_authenticate_uses_token_endpoint_and_mode_credentials(self):
        client, transport = self.authenticated_client()
        call = transport.calls[0]
        self.assertEqual((call["method"], call["path"]), ("POST", "/oauth2/tokenP"))
        self.assertEqual(call["json"], {
            "grant_type": "client_credentials",
            "appkey": "app-key",
            "appsecret": "app-secret",
        })
        self.assertNotIn("paper-token", repr(client))

    def test_authenticate_reuses_encrypted_market_data_token_cache(self):
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "KIS_paper_market_data.token"
            first_transport = FakeTransport(
                FakeResponse({
                    "access_token": "paper-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                })
            )
            first = KISClient(
                self.config(),
                transport=first_transport,
                token_cache_path=cache_path,
            )
            self.assertEqual(first.authenticate(), "paper-token")

            second_transport = FakeTransport()
            second = KISClient(
                self.config(),
                transport=second_transport,
                token_cache_path=cache_path,
            )
            self.assertEqual(second.authenticate(), "paper-token")
            self.assertEqual(second_transport.calls, [])

    def test_authenticate_uses_official_absolute_token_expiry_when_present(self):
        observed = datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc)
        transport = FakeTransport(
            FakeResponse({
                "access_token": "paper-token",
                "access_token_token_expired": "2026-08-27 12:00:00",
            })
        )
        client = KISClient(
            self.config(),
            transport=transport,
            clock=lambda: observed,
        )

        client.authenticate()

        self.assertGreater(
            client._token_expires_at - observed.timestamp(),
            10 * 60 * 60,
        )

    def test_expired_token_is_refreshed_before_order_post(self):
        now = [1000.0]
        transport = FakeTransport(
            FakeResponse({"access_token": "first-token", "expires_in": 1}),
            FakeResponse({"access_token": "second-token", "expires_in": 3600}),
            ok({"ODNO": "1"}),
        )
        client = KISClient(self.config(), transport=transport, clock=lambda: now[0])
        client.authenticate()
        now[0] += 2

        client.place_cash_order("005930", "BUY", 1, 70000)

        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(transport.calls[1]["path"], "/oauth2/tokenP")
        self.assertEqual(transport.calls[2]["headers"]["authorization"], "Bearer second-token")

    def test_paper_buy_and_sell_use_official_tr_ids_and_string_body(self):
        client, transport = self.authenticated_client(ok({"ODNO": "1"}), ok({"ODNO": "2"}))

        client.place_cash_order("005930", "BUY", 3, 70000)
        client.place_cash_order("005930", "SELL", 2, 71000)

        buy, sell = transport.calls[1:]
        self.assertEqual(buy["path"], "/uapi/domestic-stock/v1/trading/order-cash")
        self.assertEqual(sell["path"], "/uapi/domestic-stock/v1/trading/order-cash")
        self.assertEqual(buy["headers"]["tr_id"], "VTTC0012U")
        self.assertEqual(sell["headers"]["tr_id"], "VTTC0011U")
        self.assertEqual(buy["json"], {
            "CANO": "12345678", "ACNT_PRDT_CD": "01", "PDNO": "005930",
            "ORD_DVSN": "00", "ORD_QTY": "3", "ORD_UNPR": "70000",
            "EXCG_ID_DVSN_CD": "KRX",
        })
        self.assertEqual(sell["json"]["ORD_QTY"], "2")
        self.assertEqual(sell["json"]["ORD_UNPR"], "71000")

    def test_zero_price_cash_order_uses_market_order_code(self):
        client, transport = self.authenticated_client(ok({"ODNO": "1"}))

        client.place_cash_order("061040", "BUY", 1, 0)

        order_call = transport.calls[1]
        self.assertEqual(order_call["json"]["ORD_DVSN"], "01")
        self.assertEqual(order_call["json"]["ORD_UNPR"], "0")

    def test_balance_follows_continuation_headers_until_last_page(self):
        first = FakeResponse(
            {"rt_cd": "0", "output1": [{"pdno": "005930"}], "output2": [{"dnca_tot_amt": "1000"}],
             "ctx_area_fk100": "NEXT-FK", "ctx_area_nk100": "NEXT-NK"},
            {"tr_cont": "M"},
        )
        last = FakeResponse(
            {"rt_cd": "0", "output1": [{"pdno": "000660"}], "output2": [{"dnca_tot_amt": "1000"}],
             "ctx_area_fk100": "", "ctx_area_nk100": ""},
            {"tr_cont": "D"},
        )
        client, transport = self.authenticated_client(first, last)

        result = client.get_balance()

        self.assertEqual([item["pdno"] for item in result["positions"]], ["005930", "000660"])
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(transport.calls[1]["path"], "/uapi/domestic-stock/v1/trading/inquire-balance")
        self.assertEqual(transport.calls[2]["params"]["CTX_AREA_FK100"], "NEXT-FK")
        self.assertEqual(transport.calls[2]["params"]["CTX_AREA_NK100"], "NEXT-NK")
        self.assertEqual(transport.calls[2]["headers"]["tr_cont"], "N")

    def test_orderable_quantity_uses_official_query_and_parses_quantity(self):
        client, transport = self.authenticated_client(ok({"nrcvb_buy_qty": "17"}))
        self.assertEqual(client.get_orderable_quantity("005930", 70000), 17)
        call = transport.calls[1]
        self.assertEqual(call["path"], "/uapi/domestic-stock/v1/trading/inquire-psbl-order")
        self.assertEqual(call["params"]["PDNO"], "005930")
        self.assertEqual(call["params"]["ORD_UNPR"], "70000")

    def test_fill_inquiry_uses_daily_ccld_tr_id_and_business_date(self):
        first = FakeResponse(
            {
                "rt_cd": "0",
                "output1": [{"odno": "42", "tot_ccld_qty": "1"}],
                "output2": {"tot_ord_qty": "2"},
                "ctx_area_fk100": "NEXT-FK",
                "ctx_area_nk100": "NEXT-NK",
            },
            {"tr_cont": "M"},
        )
        last = FakeResponse(
            {
                "rt_cd": "0",
                "output1": [{"odno": "42", "tot_ccld_qty": "2"}],
                "output2": {"tot_ord_qty": "2"},
                "ctx_area_fk100": "",
                "ctx_area_nk100": "",
            },
            {"tr_cont": "D"},
        )
        client, transport = self.authenticated_client(first, last)
        result = client.get_order_status("42", business_date="20260720")
        call = transport.calls[1]
        self.assertEqual(call["path"], "/uapi/domestic-stock/v1/trading/inquire-daily-ccld")
        self.assertEqual(call["headers"]["tr_id"], "VTTC0081R")
        self.assertEqual(call["params"]["INQR_STRT_DT"], "20260720")
        self.assertEqual(call["params"]["INQR_END_DT"], "20260720")
        self.assertEqual(call["params"]["ODNO"], "42")
        self.assertEqual(transport.calls[2]["headers"]["tr_cont"], "N")
        self.assertEqual(transport.calls[2]["params"]["CTX_AREA_FK100"], "NEXT-FK")
        self.assertEqual(len(result["rows"]), 2)

    def test_pending_order_inquiry_uses_daily_ccld_without_order_number(self):
        client, transport = self.authenticated_client(
            FakeResponse(
                {
                    "rt_cd": "0",
                    "output1": [{"odno": "42", "rmn_qty": "1"}],
                    "output2": {"tot_ord_qty": "1"},
                    "ctx_area_fk100": "",
                    "ctx_area_nk100": "",
                },
                {"tr_cont": "D"},
            )
        )

        result = client.get_pending_orders(business_date="20260720")

        call = transport.calls[1]
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["path"], "/uapi/domestic-stock/v1/trading/inquire-daily-ccld")
        self.assertEqual(call["headers"]["tr_id"], "VTTC0081R")
        self.assertEqual(call["params"]["INQR_STRT_DT"], "20260720")
        self.assertEqual(call["params"]["INQR_END_DT"], "20260720")
        self.assertEqual(call["params"]["ODNO"], "")
        self.assertEqual(call["params"]["CCLD_DVSN"], "02")
        self.assertEqual(result["rows"], [{"odno": "42", "rmn_qty": "1"}])

    def test_market_day_uses_holiday_contract_and_opnd_yn(self):
        client, transport = self.authenticated_client(ok([{"bass_dt": "20260720", "opnd_yn": "N"}]))
        result = client.get_market_day("20260720")
        call = transport.calls[1]
        self.assertEqual(call["path"], "/uapi/domestic-stock/v1/quotations/chk-holiday")
        self.assertEqual(call["headers"]["tr_id"], "CTCA0903R")
        self.assertEqual(call["params"]["BASS_DT"], "20260720")
        self.assertFalse(result["is_open"])

    def test_daily_prices_uses_explicit_date_range(self):
        response = FakeResponse({
            "rt_cd": "0",
            "output1": {"prdy_vrss": "100"},
            "output2": [{"stck_bsop_date": "20260720"}],
        })
        client, transport = self.authenticated_client(response)
        rows = client.get_daily_prices("005930", "20260701", "20260720")
        call = transport.calls[1]
        self.assertEqual(call["path"], "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice")
        self.assertEqual(call["params"]["FID_INPUT_ISCD"], "005930")
        self.assertEqual(call["params"]["FID_INPUT_DATE_1"], "20260701")
        self.assertEqual(call["params"]["FID_INPUT_DATE_2"], "20260720")
        self.assertEqual(rows[0]["stck_bsop_date"], "20260720")

    def test_daily_investor_flow_uses_official_contract_and_normalizes_rows(self):
        response = FakeResponse({
            "rt_cd": "0",
            "output1": {"stck_prpr": "70100"},
            "output2": [
                {
                    "stck_bsop_date": "20260719",
                    "orgn_ntby_qty": "-1200",
                    "frgn_ntby_qty": "3500",
                    "prsn_ntby_qty": "-2300",
                },
                {
                    "stck_bsop_date": "20260720",
                    "orgn_ntby_qty": "1500",
                    "frgn_ntby_qty": "-500",
                    "prsn_ntby_qty": "-1000",
                },
            ],
        })
        client, transport = self.authenticated_client(response)

        rows = client.get_investor_flow("005930", "20260720")

        call = transport.calls[1]
        self.assertEqual(call["method"], "GET")
        self.assertEqual(
            call["path"],
            "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily",
        )
        self.assertEqual(call["headers"]["tr_id"], "FHPTJ04160001")
        self.assertEqual(call["params"], {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": "005930",
            "FID_INPUT_DATE_1": "20260720",
            "FID_ORG_ADJ_PRC": "0",
            "FID_ETC_CLS_CODE": "",
        })
        self.assertEqual(rows, [
            {
                "as_of": "2026-07-20",
                "institution_net_buy": 1500,
                "foreign_net_buy": -500,
                "individual_net_buy": -1000,
                "source": "kis.investor-trade-by-stock-daily",
            },
            {
                "as_of": "2026-07-19",
                "institution_net_buy": -1200,
                "foreign_net_buy": 3500,
                "individual_net_buy": -2300,
                "source": "kis.investor-trade-by-stock-daily",
            },
        ])

    def test_daily_investor_flow_rejects_invalid_quantity(self):
        response = FakeResponse({
            "rt_cd": "0",
            "output1": {},
            "output2": [{
                "stck_bsop_date": "20260720",
                "orgn_ntby_qty": "not-a-number",
                "frgn_ntby_qty": "1",
                "prsn_ntby_qty": "-1",
            }],
        })
        client, _ = self.authenticated_client(response)

        with self.assertRaisesRegex(KISRequestError, "invalid quantity"):
            client.get_investor_flow("005930", "20260720")

    def test_daily_investor_flow_rejects_invalid_business_date(self):
        response = FakeResponse({
            "rt_cd": "0",
            "output1": {},
            "output2": [{
                "stck_bsop_date": "20261340",
                "orgn_ntby_qty": "1",
                "frgn_ntby_qty": "1",
                "prsn_ntby_qty": "-2",
            }],
        })
        client, _ = self.authenticated_client(response)

        with self.assertRaisesRegex(KISRequestError, "invalid date"):
            client.get_investor_flow("005930", "20260720")

    def test_daily_investor_flow_redacts_provider_failure(self):
        client, _ = self.authenticated_client(
            RuntimeError("provider echoed app-key app-secret 12345678")
        )

        with self.assertRaises(KISRequestError) as raised:
            client.get_investor_flow("005930", "20260720")

        rendered = str(raised.exception)
        self.assertNotIn("app-key", rendered)
        self.assertNotIn("app-secret", rendered)
        self.assertNotIn("12345678", rendered)

    def test_current_quote_uses_official_inquire_price_contract(self):
        observed = datetime(2026, 7, 20, 1, 5, 6, tzinfo=timezone.utc)
        transport = FakeTransport(
            FakeResponse({"access_token": "paper-token", "expires_in": 3600}),
            ok(
                {
                    "stck_prpr": "70100",
                    "stck_shrn_iscd": "005930",
                    "rprs_mrkt_kor_name": "KOSPI",
                }
            ),
        )
        client = KISClient(
            self.config(),
            transport=transport,
            clock=lambda: observed,
        )

        quote = client.get_quote("005930")

        call = transport.calls[1]
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["path"], "/uapi/domestic-stock/v1/quotations/inquire-price")
        self.assertEqual(call["headers"]["tr_id"], "FHKST01010100")
        self.assertEqual(
            call["params"],
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930"},
        )
        self.assertEqual(quote.ticker, "005930")
        self.assertEqual(quote.price, 70100)
        self.assertEqual(quote.currency, "KRW")
        self.assertEqual(quote.market, "KRX")
        self.assertEqual(quote.observed_at, observed)
        self.assertEqual(quote.source, "kis.inquire-price")

    def test_current_quote_rejects_mismatched_kis_ticker(self):
        client, _ = self.authenticated_client(
            ok({"stck_prpr": "70100", "stck_shrn_iscd": "000660"})
        )

        with self.assertRaises(KISRequestError):
            client.get_quote("005930")

    def test_current_quote_rejects_non_integral_domestic_price(self):
        client, _ = self.authenticated_client(
            ok({"stck_prpr": "70100.5", "stck_shrn_iscd": "005930"})
        )

        with self.assertRaises(KISRequestError):
            client.get_quote("005930")

    def test_current_quote_transport_timeout_is_not_converted_to_mock_price(self):
        client, transport = self.authenticated_client(TimeoutError("quote timed out"))

        with self.assertRaises(TimeoutError):
            client.get_quote("005930")

        self.assertEqual(len(transport.calls), 2)

    def test_cancel_uses_official_endpoint_tr_id_and_uppercase_string_payload(self):
        client, transport = self.authenticated_client(ok({"ODNO": "42"}))
        client.cancel_order("42", quantity=3, order_date="20260720", org_no="12345")
        call = transport.calls[1]
        self.assertEqual(call["path"], "/uapi/domestic-stock/v1/trading/order-rvsecncl")
        self.assertEqual(call["headers"]["tr_id"], "VTTC0013U")
        self.assertEqual(call["json"], {
            "CANO": "12345678", "ACNT_PRDT_CD": "01", "KRX_FWDG_ORD_ORGNO": "12345",
            "ORGN_ODNO": "42", "ORD_DVSN": "00", "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": "3", "ORD_UNPR": "0", "QTY_ALL_ORD_YN": "N",
            "EXCG_ID_DVSN_CD": "KRX",
        })

    def test_cancel_post_timeout_is_unknown_and_never_retried(self):
        client, transport = self.authenticated_client(TimeoutError("app-secret late"))

        result = client.cancel_order("42", quantity=3, order_date="20260720", org_no="12345")

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["terminal"])
        self.assertEqual(len(transport.calls), 2)
        self.assertNotIn("app-secret", result["message"])

    def test_order_post_timeout_is_unknown_and_never_retried(self):
        client, transport = self.authenticated_client(TimeoutError("secret app-secret timed out"))
        result = client.place_cash_order("005930", "BUY", 1, 70000)
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["executed"])
        self.assertEqual(len(transport.calls), 2)
        self.assertNotIn("app-secret", result["message"])

    def test_url_transport_normalizes_wrapped_socket_timeout(self):
        transport = _URLTransport("https://example.invalid")
        with patch("brokers.kis_client.urlopen", side_effect=URLError(socket.timeout("late"))):
            with self.assertRaises(TimeoutError):
                transport.request("POST", "/order", json={"value": "1"}, timeout=1)

    def test_url_transport_marks_only_transient_http_statuses_retryable(self):
        transport = _URLTransport("https://example.invalid")
        for status, retryable in ((503, True), (429, True), (403, False)):
            error = HTTPError("https://example.invalid", status, "failed", {}, None)
            with self.subTest(status=status), patch(
                "brokers.kis_client.urlopen", side_effect=error
            ):
                with self.assertRaises(KISRequestError) as raised:
                    transport.request("GET", "/readonly", timeout=1)
                self.assertEqual(raised.exception.status, status)
                self.assertEqual(raised.exception.retryable, retryable)

    def test_invalid_side_quantity_price_and_malformed_response_fail_closed(self):
        client, transport = self.authenticated_client(ok())
        for args in (("005930", "HOLD", 1, 70000), ("005930", "BUY", 0, 70000),
                     ("005930", "BUY", 1, -1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                client.place_cash_order(*args)
        self.assertEqual(len(transport.calls), 1)

        malformed = FakeTransport(FakeResponse({"access_token": "token"}), FakeResponse({"rt_cd": "0"}))
        malformed_client = KISClient(self.config(), transport=malformed)
        malformed_client.authenticate()
        with self.assertRaises(KISRequestError):
            malformed_client.place_cash_order("005930", "BUY", 1, 70000)


if __name__ == "__main__":
    unittest.main()
