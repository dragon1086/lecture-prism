"""Small, injected KIS REST client for the domestic-stock teaching path.

The module is deliberately standard-library only.  Importing it never reads a
credential file and never opens the network; a request is made only when a
public client method is called.
"""

from __future__ import annotations

import json as json_module
import os
import socket
import time
from datetime import datetime
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .base import BrokerQuote, BrokerQuoteError, validate_broker_quote


PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


class KISRequestError(RuntimeError):
    """Raised when KIS returns an invalid or explicitly failed response."""


def _canonical_mode(value: str) -> str:
    mode = str(value).strip().lower()
    if mode in {"paper", "demo", "mock", "vps"}:
        return "paper"
    if mode in {"real", "live", "prod"}:
        return "real"
    raise ValueError("KIS mode must be paper/demo or real")


@dataclass(frozen=True)
class KISConfig:
    mode: str
    app_key: str = field(repr=False)
    app_secret: str = field(repr=False)
    account_no: str = field(repr=False)
    product_code: str = "01"
    base_url: str = field(init=False)

    def __post_init__(self) -> None:
        mode = _canonical_mode(self.mode)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "base_url", PAPER_BASE_URL if mode == "paper" else REAL_BASE_URL)

    @classmethod
    def from_env(cls, mode: str = "paper") -> "KISConfig":
        canonical = _canonical_mode(mode)
        prefix = "KIS_PAPER" if canonical == "paper" else "KIS_REAL"
        values = {
            "app_key": os.getenv(f"{prefix}_APP_KEY", "").strip(),
            "app_secret": os.getenv(f"{prefix}_APP_SECRET", "").strip(),
            "account_no": os.getenv(f"{prefix}_ACCOUNT_NO", "").strip(),
            "product_code": os.getenv(f"{prefix}_PRODUCT_CODE", "01").strip() or "01",
        }
        missing = [name for name in ("app_key", "app_secret", "account_no") if not values[name]]
        if missing:
            raise ValueError(f"missing {prefix} credentials: {', '.join(missing)}")
        return cls(canonical, **values)

    @classmethod
    def from_env_market_data(cls, mode: str = "paper") -> "KISConfig":
        """Load only credentials needed by KIS read-only market endpoints."""

        canonical = _canonical_mode(mode)
        prefix = "KIS_PAPER" if canonical == "paper" else "KIS_REAL"
        app_key = os.getenv(f"{prefix}_APP_KEY", "").strip()
        app_secret = os.getenv(f"{prefix}_APP_SECRET", "").strip()
        missing = [
            name
            for name, value in (("app_key", app_key), ("app_secret", app_secret))
            if not value
        ]
        if missing:
            raise ValueError(
                f"missing {prefix} market-data credentials: {', '.join(missing)}"
            )
        return cls(canonical, app_key, app_secret, "")


@dataclass(frozen=True)
class _HTTPResponse:
    body: dict[str, Any]
    headers: dict[str, str]
    status: int


class _URLTransport:
    """Default transport. Tests replace this object with a deterministic fake."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> _HTTPResponse:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        payload = None if json is None else json_module.dumps(json).encode("utf-8")
        request = Request(url, data=payload, headers=dict(headers or {}), method=method)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed configured KIS hosts
                raw = response.read().decode("utf-8")
                return _HTTPResponse(
                    body={} if not raw else json_module.loads(raw),
                    headers={key.lower(): value for key, value in response.headers.items()},
                    status=int(response.status),
                )
        except (socket.timeout, TimeoutError) as exc:
            raise TimeoutError(str(exc)) from exc
        except HTTPError as exc:
            raise KISRequestError(f"KIS HTTP request failed: {exc}") from exc
        except URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise TimeoutError(str(exc.reason)) from exc
            raise KISRequestError(f"KIS HTTP request failed: {exc}") from exc
        except ValueError as exc:
            raise KISRequestError(f"KIS HTTP request failed: {exc}") from exc


class KISClient:
    """Clean-room domestic-stock client with explicit request contracts."""

    def __init__(self, config: KISConfig, transport=None, clock=None, *, timeout: float = 10.0) -> None:
        self.config = config
        self.transport = transport or _URLTransport(config.base_url)
        self.clock = clock
        self.timeout = float(timeout)
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def __repr__(self) -> str:
        return f"KISClient(mode={self.config.mode!r}, authenticated={self._access_token is not None})"

    def _redact(self, value: object) -> str:
        text = str(value)
        for secret in (self.config.app_key, self.config.app_secret, self.config.account_no, self._access_token):
            if secret:
                text = text.replace(secret, "<redacted>")
        return text

    def _now(self) -> float:
        value = self.clock() if self.clock is not None else time.time()
        if isinstance(value, datetime):
            return value.timestamp()
        return float(value)

    def _now_datetime(self) -> datetime:
        value = self.clock() if self.clock is not None else None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=KST).astimezone(UTC)
            return value.astimezone(UTC)
        return datetime.fromtimestamp(self._now(), UTC)

    @staticmethod
    def _body(response: object) -> dict[str, Any]:
        body = getattr(response, "body", None)
        if not isinstance(body, dict):
            raise KISRequestError("KIS response body is not an object")
        return body

    def authenticate(self) -> str:
        if self._access_token and self._now() < self._token_expires_at:
            return self._access_token
        self._access_token = None
        try:
            response = self.transport.request(
                "POST",
                "/oauth2/tokenP",
                headers={"Content-Type": "application/json"},
                json={
                    "grant_type": "client_credentials",
                    "appkey": self.config.app_key,
                    "appsecret": self.config.app_secret,
                },
                timeout=self.timeout,
            )
        except Exception as exc:
            raise KISRequestError(self._redact(exc)) from exc
        body = self._body(response)
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise KISRequestError("KIS token response did not contain access_token")
        self._access_token = token
        expires_in = body.get("expires_in")
        try:
            lifetime = float(expires_in)
        except (TypeError, ValueError):
            lifetime = 6 * 60 * 60
        if lifetime <= 0:
            raise KISRequestError("KIS token response has invalid expiry")
        safety_margin = min(60.0, lifetime * 0.1)
        self._token_expires_at = self._now() + max(0.1, lifetime - safety_margin)
        return token

    def _headers(self, tr_id: str, *, tr_cont: str = "") -> dict[str, str]:
        token = self.authenticate()
        return {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
            "tr_cont": tr_cont,
        }

    def _call(
        self,
        method: str,
        path: str,
        tr_id: str,
        *,
        params: Mapping[str, str] | None = None,
        payload: Mapping[str, str] | None = None,
        tr_cont: str = "",
        require_output: bool = True,
    ) -> tuple[dict[str, Any], Mapping[str, str]]:
        try:
            response = self.transport.request(
                method,
                path,
                headers=self._headers(tr_id, tr_cont=tr_cont),
                params=params,
                json=payload,
                timeout=self.timeout,
            )
        except TimeoutError:
            raise
        except Exception as exc:
            raise KISRequestError(self._redact(exc)) from exc
        status = getattr(response, "status", 200)
        if not isinstance(status, int) or status < 200 or status >= 300:
            raise KISRequestError(f"KIS HTTP status {status}")
        body = self._body(response)
        if body.get("rt_cd") != "0":
            raise KISRequestError(self._redact(body.get("msg1") or "KIS request failed"))
        if require_output and "output" not in body:
            raise KISRequestError("KIS success response did not contain output")
        headers = getattr(response, "headers", None)
        return body, headers if isinstance(headers, Mapping) else {}

    @property
    def _paper(self) -> bool:
        return self.config.mode == "paper"

    def place_cash_order(self, ticker: str, side: str, quantity: int, price: int) -> dict[str, Any]:
        normalized_side = str(side).strip().upper()
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if int(quantity) <= 0:
            raise ValueError("quantity must be positive")
        if int(price) < 0:
            raise ValueError("price cannot be negative")
        tr_id = {
            (True, "BUY"): "VTTC0012U",
            (True, "SELL"): "VTTC0011U",
            (False, "BUY"): "TTTC0012U",
            (False, "SELL"): "TTTC0011U",
        }[(self._paper, normalized_side)]
        payload = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.product_code,
            "PDNO": str(ticker),
            "ORD_DVSN": "00",
            "ORD_QTY": str(int(quantity)),
            "ORD_UNPR": str(int(price)),
            "EXCG_ID_DVSN_CD": "KRX",
        }
        try:
            body, _ = self._call(
                "POST",
                "/uapi/domestic-stock/v1/trading/order-cash",
                tr_id,
                payload=payload,
            )
        except TimeoutError as exc:
            return {
                "status": "unknown",
                "accepted": False,
                "executed": False,
                "terminal": False,
                "order_no": None,
                "message": self._redact(exc),
            }
        output = body["output"]
        if not isinstance(output, Mapping) or not output.get("ODNO"):
            raise KISRequestError("KIS order response did not contain ODNO")
        return {
            "status": "accepted",
            "accepted": True,
            "executed": False,
            "terminal": False,
            "order_no": str(output["ODNO"]),
            "org_no": str(output.get("KRX_FWDG_ORD_ORGNO", "")),
            "message": str(body.get("msg1", "")),
            "raw": dict(output),
        }

    def get_balance(self, *, max_pages: int = 10) -> dict[str, Any]:
        positions: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        fk = nk = ""
        tr_cont = ""
        for _ in range(max_pages):
            params = {
                "CANO": self.config.account_no,
                "ACNT_PRDT_CD": self.config.product_code,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": fk,
                "CTX_AREA_NK100": nk,
            }
            body, headers = self._call(
                "GET",
                "/uapi/domestic-stock/v1/trading/inquire-balance",
                "VTTC8434R" if self._paper else "TTTC8434R",
                params=params,
                tr_cont=tr_cont,
                require_output=False,
            )
            page_positions = body.get("output1", [])
            page_summaries = body.get("output2", [])
            if not isinstance(page_positions, list) or not isinstance(page_summaries, list):
                raise KISRequestError("KIS balance response has invalid output shape")
            positions.extend(dict(item) for item in page_positions if isinstance(item, Mapping))
            summaries.extend(dict(item) for item in page_summaries if isinstance(item, Mapping))
            continuation = str(headers.get("tr_cont", headers.get("TR_CONT", ""))).upper()
            if continuation not in {"M", "F"}:
                return {"positions": positions, "summary": summaries}
            fk = str(body.get("ctx_area_fk100", ""))
            nk = str(body.get("ctx_area_nk100", ""))
            if not fk and not nk:
                raise KISRequestError("KIS balance continuation keys are missing")
            tr_cont = "N"
        raise KISRequestError("KIS balance pagination exceeded max_pages")

    def get_orderable_quantity(self, ticker: str, price: int) -> int:
        params = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.product_code,
            "PDNO": str(ticker),
            "ORD_UNPR": str(int(price)),
            "ORD_DVSN": "01",
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N",
        }
        body, _ = self._call(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-psbl-order",
            "VTTC8908R" if self._paper else "TTTC8908R",
            params=params,
        )
        output = body["output"]
        if not isinstance(output, Mapping):
            raise KISRequestError("KIS orderable response has invalid output")
        raw = output.get("nrcvb_buy_qty", output.get("max_buy_qty"))
        try:
            return int(str(raw))
        except (TypeError, ValueError) as exc:
            raise KISRequestError("KIS orderable response has invalid quantity") from exc

    def get_order_status(
        self,
        order_no: str,
        *,
        business_date: str,
        max_pages: int = 10,
    ) -> dict[str, Any]:
        params = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.product_code,
            "INQR_STRT_DT": business_date,
            "INQR_END_DT": business_date,
            "SLL_BUY_DVSN_CD": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "INQR_DVSN": "00",
            "INQR_DVSN_3": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": str(order_no),
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        rows: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        tr_cont = ""
        for _ in range(max_pages):
            body, headers = self._call(
                "GET",
                "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
                "VTTC0081R" if self._paper else "TTTC0081R",
                params=params,
                tr_cont=tr_cont,
                require_output=False,
            )
            output1 = body.get("output1", [])
            output2 = body.get("output2", {})
            if not isinstance(output1, list) or not isinstance(output2, Mapping):
                raise KISRequestError("KIS order-status response has invalid output shape")
            rows.extend(dict(row) for row in output1 if isinstance(row, Mapping))
            summaries.append(dict(output2))
            continuation = str(headers.get("tr_cont", headers.get("TR_CONT", ""))).upper()
            if continuation not in {"M", "F"}:
                return {"order_no": str(order_no), "rows": rows, "summary": summaries}
            fk = str(body.get("ctx_area_fk100", ""))
            nk = str(body.get("ctx_area_nk100", ""))
            if not fk and not nk:
                raise KISRequestError("KIS order-status continuation keys are missing")
            params["CTX_AREA_FK100"] = fk
            params["CTX_AREA_NK100"] = nk
            tr_cont = "N"
        raise KISRequestError("KIS order-status pagination exceeded max_pages")

    def get_pending_orders(
        self,
        *,
        business_date: str,
        max_pages: int = 10,
    ) -> dict[str, Any]:
        params = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.product_code,
            "INQR_STRT_DT": business_date,
            "INQR_END_DT": business_date,
            "SLL_BUY_DVSN_CD": "00",
            "PDNO": "",
            "CCLD_DVSN": "02",
            "INQR_DVSN": "00",
            "INQR_DVSN_3": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        rows: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        tr_cont = ""
        for _ in range(max_pages):
            body, headers = self._call(
                "GET",
                "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
                "VTTC0081R" if self._paper else "TTTC0081R",
                params=params,
                tr_cont=tr_cont,
                require_output=False,
            )
            output1 = body.get("output1", [])
            output2 = body.get("output2", {})
            if not isinstance(output1, list) or not isinstance(output2, Mapping):
                raise KISRequestError("KIS pending-order response has invalid output shape")
            rows.extend(dict(row) for row in output1 if isinstance(row, Mapping))
            summaries.append(dict(output2))
            continuation = str(headers.get("tr_cont", headers.get("TR_CONT", ""))).upper()
            if continuation not in {"M", "F"}:
                return {"rows": rows, "summary": summaries}
            fk = str(body.get("ctx_area_fk100", ""))
            nk = str(body.get("ctx_area_nk100", ""))
            if not fk and not nk:
                raise KISRequestError("KIS pending-order continuation keys are missing")
            params["CTX_AREA_FK100"] = fk
            params["CTX_AREA_NK100"] = nk
            tr_cont = "N"
        raise KISRequestError("KIS pending-order pagination exceeded max_pages")

    def get_market_day(self, business_date: str) -> dict[str, Any]:
        body, _ = self._call(
            "GET",
            "/uapi/domestic-stock/v1/quotations/chk-holiday",
            "CTCA0903R",
            params={"BASS_DT": business_date, "CTX_AREA_FK": "", "CTX_AREA_NK": ""},
        )
        output = body["output"]
        rows = output if isinstance(output, list) else [output]
        row = next((item for item in rows if isinstance(item, Mapping)), None)
        if row is None or row.get("opnd_yn") not in {"Y", "N"}:
            raise KISRequestError("KIS holiday response has invalid opnd_yn")
        return {
            "business_date": str(row.get("bass_dt", business_date)),
            "is_open": row["opnd_yn"] == "Y",
            "raw": dict(row),
        }

    def get_daily_prices(self, ticker: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        body, _ = self._call(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": str(ticker),
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
            require_output=False,
        )
        output1 = body.get("output1")
        output2 = body.get("output2")
        if not isinstance(output1, Mapping) or not isinstance(output2, list):
            raise KISRequestError("KIS daily-price response has invalid output shape")
        if any(not isinstance(row, Mapping) for row in output2):
            raise KISRequestError("KIS daily-price response contains an invalid row")
        return [dict(row) for row in output2]

    def get_investor_flow(
        self, ticker: str, as_of_date: str
    ) -> list[dict[str, object]]:
        selected_ticker = str(ticker).strip()
        selected_date = str(as_of_date).strip()
        if len(selected_ticker) != 6 or not selected_ticker.isdigit():
            raise ValueError("ticker must be a six-digit domestic stock code")
        try:
            datetime.strptime(selected_date, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("as_of_date must use YYYYMMDD") from exc

        body, _ = self._call(
            "GET",
            "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily",
            "FHPTJ04160001",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": selected_ticker,
                "FID_INPUT_DATE_1": selected_date,
                "FID_ORG_ADJ_PRC": "0",
                "FID_ETC_CLS_CODE": "",
            },
            require_output=False,
        )
        rows = body.get("output2")
        if not isinstance(rows, list) or not rows:
            raise KISRequestError("KIS investor-flow response has no rows")

        normalized: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise KISRequestError("KIS investor-flow response contains an invalid row")
            raw_date = str(row.get("stck_bsop_date") or "").strip()
            try:
                parsed_date = datetime.strptime(raw_date, "%Y%m%d").strftime(
                    "%Y-%m-%d"
                )
            except ValueError as exc:
                raise KISRequestError(
                    "KIS investor-flow response has invalid date"
                ) from exc
            try:
                institution = int(str(row.get("orgn_ntby_qty") or "").strip())
                foreign = int(str(row.get("frgn_ntby_qty") or "").strip())
                individual = int(str(row.get("prsn_ntby_qty") or "").strip())
            except ValueError as exc:
                raise KISRequestError(
                    "KIS investor-flow response has invalid quantity"
                ) from exc
            normalized.append(
                {
                    "as_of": parsed_date,
                    "institution_net_buy": institution,
                    "foreign_net_buy": foreign,
                    "individual_net_buy": individual,
                    "source": "kis.investor-trade-by-stock-daily",
                }
            )
        return sorted(normalized, key=lambda item: str(item["as_of"]), reverse=True)

    @staticmethod
    def _quote_observed_at(output: Mapping[str, Any], fallback: datetime) -> datetime:
        business_date = str(output.get("stck_bsop_date") or "").strip()
        trade_time = str(output.get("stck_cntg_hour") or "").strip()
        if business_date and trade_time:
            compact_time = trade_time.replace(":", "").zfill(6)[:6]
            try:
                return datetime.strptime(
                    f"{business_date}{compact_time}", "%Y%m%d%H%M%S"
                ).replace(tzinfo=KST).astimezone(UTC)
            except ValueError as exc:
                raise KISRequestError("KIS quote timestamp fields are invalid") from exc
        return fallback

    def get_quote(self, ticker: str) -> BrokerQuote:
        selected_ticker = str(ticker).strip()
        if not selected_ticker:
            raise ValueError("ticker is required")
        body, _ = self._call(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": selected_ticker,
            },
        )
        output = body["output"]
        if not isinstance(output, Mapping):
            raise KISRequestError("KIS quote response has invalid output")
        raw_price = output.get("stck_prpr")
        try:
            parsed_price = Decimal(str(raw_price))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise KISRequestError("KIS quote response has invalid stck_prpr") from exc
        if parsed_price != parsed_price.to_integral_value():
            raise KISRequestError("KIS quote response has non-integral stck_prpr")
        price = int(parsed_price)
        output_ticker = str(output.get("stck_shrn_iscd") or selected_ticker).strip()
        quote = BrokerQuote(
            ticker=output_ticker,
            price=price,
            currency="KRW",
            market="KRX",
            observed_at=self._quote_observed_at(output, self._now_datetime()),
            source="kis.inquire-price",
        )
        try:
            return validate_broker_quote(
                quote,
                expected_ticker=selected_ticker,
                now=self._now_datetime(),
            )
        except BrokerQuoteError as exc:
            raise KISRequestError(str(exc)) from exc

    def cancel_order(
        self,
        order_no: str,
        *,
        quantity: int,
        order_date: str,
        org_no: str,
    ) -> dict[str, Any]:
        del order_date  # kept in the public contract for reconciliation/audit callers
        payload = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.product_code,
            "KRX_FWDG_ORD_ORGNO": str(org_no),
            "ORGN_ODNO": str(order_no),
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": str(int(quantity)),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "N",
            "EXCG_ID_DVSN_CD": "KRX",
        }
        try:
            body, _ = self._call(
                "POST",
                "/uapi/domestic-stock/v1/trading/order-rvsecncl",
                "VTTC0013U" if self._paper else "TTTC0013U",
                payload=payload,
            )
        except TimeoutError as exc:
            return {
                "status": "unknown",
                "accepted": False,
                "executed": False,
                "terminal": False,
                "order_no": str(order_no),
                "message": self._redact(exc),
            }
        output = body["output"]
        if not isinstance(output, Mapping) or not output.get("ODNO"):
            raise KISRequestError("KIS cancel response did not contain ODNO")
        return {"accepted": True, "executed": False, "status": "cancel_pending", "raw": dict(output)}
