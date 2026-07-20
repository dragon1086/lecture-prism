from __future__ import annotations

import os
import socket
import unittest
from dataclasses import dataclass
from urllib.error import URLError
from unittest.mock import patch

from brokers.kis_client import KISClient, KISConfig, KISRequestError, _URLTransport


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

    def test_config_repr_redacts_credentials_and_account(self):
        config = KISConfig("paper", "public-app-key", "top-secret", "12345678")
        rendered = repr(config)
        self.assertNotIn("public-app-key", rendered)
        self.assertNotIn("top-secret", rendered)
        self.assertNotIn("12345678", rendered)


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
