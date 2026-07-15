"""표준 라이브러리만 사용하는 최소 KIS 국내주식 REST 클라이언트."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol

from .config import broker_order_enabled, broker_real_allowed


_PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
_REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
_TOKEN_PATH = "/oauth2/tokenP"

_BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
_ORDERABLE_PATH = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
_CASH_ORDER_PATH = "/uapi/domestic-stock/v1/trading/order-cash"
_ORDER_STATUS_PATH = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
_CANCEL_PATH = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
_HOLIDAY_PATH = "/uapi/domestic-stock/v1/quotations/chk-holiday"
_DAILY_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"

_TR_IDS = {
    "paper": {
        "balance": "VTTC8434R",
        "orderable": "VTTC8908R",
        "buy": "VTTC0012U",
        "sell": "VTTC0011U",
        "status": "VTTC0081R",
        "cancel": "VTTC0013U",
    },
    "real": {
        "balance": "TTTC8434R",
        "orderable": "TTTC8908R",
        "buy": "TTTC0012U",
        "sell": "TTTC0011U",
        "status": "TTTC0081R",
        "cancel": "TTTC0013U",
    },
}


class KISConfigError(RuntimeError):
    """KIS 환경설정이 불완전하거나 안전하지 않을 때 발생한다."""


class KISResponseError(RuntimeError):
    """민감한 원문 응답을 포함하지 않는 KIS 응답 계약 오류."""


class KISTransportError(RuntimeError):
    """요청 URL이나 인증정보를 노출하지 않는 전송 오류."""


def _normalize_mode(value: object) -> str:
    mode = str(value or "paper").strip().lower()
    mode = {"demo": "paper", "vps": "paper", "prod": "real", "live": "real"}.get(
        mode, mode
    )
    if mode not in {"paper", "real"}:
        raise KISConfigError("KIS mode must be paper or real")
    return mode


@dataclass(frozen=True, repr=False)
class KISConfig:
    mode: str
    app_key: str
    app_secret: str
    account_no: str
    product_code: str = "01"

    def __post_init__(self) -> None:
        normalized = _normalize_mode(self.mode)
        object.__setattr__(self, "mode", normalized)
        if not all((self.app_key, self.app_secret, self.account_no, self.product_code)):
            raise KISConfigError("KIS credentials and account fields are required")

    @property
    def base_url(self) -> str:
        return _PAPER_BASE_URL if self.mode == "paper" else _REAL_BASE_URL

    @property
    def namespace(self) -> str:
        return "KIS_PAPER" if self.mode == "paper" else "KIS_REAL"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        mode: str | None = None,
    ) -> "KISConfig":
        values = os.environ if environ is None else environ
        selected = _normalize_mode(
            mode or values.get("KIS_MODE") or values.get("LECTURE_KIS_MODE")
        )
        prefix = "KIS_PAPER" if selected == "paper" else "KIS_REAL"
        fields = {
            "app_key": values.get(f"{prefix}_APP_KEY", "").strip(),
            "app_secret": values.get(f"{prefix}_APP_SECRET", "").strip(),
            "account_no": values.get(f"{prefix}_ACCOUNT_NO", "").strip(),
            "product_code": values.get(f"{prefix}_PRODUCT_CODE", "01").strip(),
        }
        missing = [name for name, value in fields.items() if not value]
        if missing:
            names = ", ".join(f"{prefix}_{name.upper()}" for name in missing)
            raise KISConfigError(f"Missing KIS configuration: {names}")
        return cls(mode=selected, **fields)

    def __repr__(self) -> str:
        suffix = self.account_no[-4:] if self.account_no else ""
        return (
            f"KISConfig(mode={self.mode!r}, account_no='***{suffix}', "
            f"product_code={self.product_code!r})"
        )


@dataclass(frozen=True, repr=False)
class TransportResponse:
    body: Mapping[str, Any]
    headers: Mapping[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return "TransportResponse(body=[REDACTED], headers=[REDACTED])"


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, object] | None = None,
        json_body: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> TransportResponse:
        """Send one HTTP request without hidden retries."""


class UrllibTransport:
    """Small synchronous transport; construction and import perform no I/O."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, object] | None = None,
        json_body: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> TransportResponse:
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}"
        payload = None
        if json_body is not None:
            payload = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers=dict(headers or {}),
            method=method,
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise KISResponseError("KIS response body must be an object")
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            return TransportResponse(body=parsed, headers=response_headers)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _date_text(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError("date must be YYYYMMDD")
    return text


def _number_text(value: int | float, *, positive: bool = False) -> str:
    if isinstance(value, bool) or int(value) != value:
        raise ValueError("quantity and price must be whole numbers")
    number = int(value)
    if positive and number <= 0:
        raise ValueError("quantity must be positive")
    if number < 0:
        raise ValueError("price must not be negative")
    return str(number)


def _header(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value)
    return ""


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    return isinstance(exc, urllib.error.URLError) and isinstance(
        exc.reason, (TimeoutError, socket.timeout)
    )


class KISClient:
    def __init__(
        self,
        config: KISConfig,
        transport: Transport | None = None,
        clock: Callable[[], datetime] | None = None,
        *,
        timeout: float = 5.0,
    ) -> None:
        self.config = config
        self._transport = transport or UrllibTransport()
        self._clock = clock or _utc_now
        self._timeout = max(0.1, min(float(timeout), 30.0))
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

    def __repr__(self) -> str:
        return f"KISClient(mode={self.config.mode!r}, authenticated={bool(self._access_token)})"

    def authenticate(self) -> str:
        now = _as_datetime(self._clock())
        if (
            self._access_token
            and self._token_expires_at is not None
            and now < self._token_expires_at
        ):
            return self._access_token
        try:
            response = self._transport.request(
                "POST",
                self.config.base_url + _TOKEN_PATH,
                headers={"content-type": "application/json; charset=utf-8"},
                json_body={
                    "grant_type": "client_credentials",
                    "appkey": self.config.app_key,
                    "appsecret": self.config.app_secret,
                },
                timeout=self._timeout,
            )
        except Exception as exc:
            raise KISTransportError("KIS authentication request failed") from exc
        body = self._body(response)
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise KISResponseError("KIS token response is missing access_token")
        try:
            expires_in = max(60, int(body.get("expires_in", 86400)))
        except (TypeError, ValueError) as exc:
            raise KISResponseError("KIS token response has invalid expires_in") from exc
        self._access_token = token
        self._token_expires_at = now + timedelta(seconds=max(1, expires_in - 30))
        return token

    def get_balance(self) -> dict[str, list[dict[str, Any]]]:
        tr_id = self._tr_id("balance")
        output1: list[dict[str, Any]] = []
        output2: list[dict[str, Any]] = []
        fk100 = ""
        nk100 = ""
        continuation = ""
        for _ in range(20):
            params = {
                **self._account_params(),
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "01",
                "CTX_AREA_FK100": fk100,
                "CTX_AREA_NK100": nk100,
            }
            response = self._request(
                "GET",
                _BALANCE_PATH,
                tr_id,
                params=params,
                continuation=continuation,
            )
            body = self._validate(response, tr_id)
            output1.extend(self._object_list(body.get("output1"), "output1", tr_id))
            output2.extend(self._object_list(body.get("output2"), "output2", tr_id))
            if _header(response.headers, "tr_cont") not in {"M", "F"}:
                return {"output1": output1, "output2": output2}
            fk100 = str(body.get("ctx_area_fk100") or "")
            nk100 = str(body.get("ctx_area_nk100") or "")
            if not fk100 and not nk100:
                raise KISResponseError(f"KIS pagination keys missing (tr_id={tr_id})")
            continuation = "N"
        raise KISResponseError(f"KIS pagination limit exceeded (tr_id={tr_id})")

    def get_orderable_quantity(self, ticker: str, price: int | float) -> dict[str, Any]:
        tr_id = self._tr_id("orderable")
        response = self._request(
            "GET",
            _ORDERABLE_PATH,
            tr_id,
            params={
                **self._account_params(),
                "PDNO": self._ticker(ticker),
                "ORD_UNPR": _number_text(price),
                "ORD_DVSN": "00",
                "CMA_EVLU_AMT_ICLD_YN": "N",
                "OVRS_ICLD_YN": "N",
            },
        )
        body = self._validate(response, tr_id)
        return self._object(body.get("output"), "output", tr_id)

    def place_cash_order(
        self, ticker: str, side: str, quantity: int, price: int | float
    ) -> dict[str, Any]:
        self._require_order_safety_gates()
        normalized_side = str(side).strip().upper()
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        tr_id = self._tr_id(normalized_side.lower())
        payload = {
            **self._account_params(),
            "PDNO": self._ticker(ticker),
            "ORD_DVSN": "00",
            "ORD_QTY": _number_text(quantity, positive=True),
            "ORD_UNPR": _number_text(price),
            "EXCG_ID_DVSN_CD": "KRX",
            "SLL_TYPE": "01" if normalized_side == "SELL" else "",
            "CNDT_PRIC": "",
        }
        return self._post_order(_CASH_ORDER_PATH, tr_id, payload)

    def get_order_status(
        self,
        order_no: str,
        *,
        start_date: str | date | datetime | None = None,
        end_date: str | date | datetime | None = None,
    ) -> dict[str, Any]:
        today = _date_text(self._clock())
        tr_id = self._tr_id("status")
        context_fk = ""
        context_nk = ""
        continuation = ""
        all_rows: list[dict[str, Any]] = []
        latest_output2: object = {}
        for _page in range(20):
            response = self._request(
                "GET",
                _ORDER_STATUS_PATH,
                tr_id,
                params={
                    **self._account_params(),
                    "INQR_STRT_DT": _date_text(start_date or today),
                    "INQR_END_DT": _date_text(end_date or today),
                    "SLL_BUY_DVSN_CD": "00",
                    "PDNO": "",
                    "CCLD_DVSN": "00",
                    "INQR_DVSN": "00",
                    "INQR_DVSN_3": "00",
                    "ORD_GNO_BRNO": "",
                    "ODNO": str(order_no),
                    "INQR_DVSN_1": "",
                    "EXCG_ID_DVSN_CD": "KRX",
                    "CTX_AREA_FK100": context_fk,
                    "CTX_AREA_NK100": context_nk,
                },
                continuation=continuation,
            )
            body = self._validate(response, tr_id)
            all_rows.extend(
                self._object_list(body.get("output1"), "output1", tr_id)
            )
            latest_output2 = body.get("output2", latest_output2)
            tr_cont = str(
                response.headers.get("tr_cont")
                or response.headers.get("TR_CONT")
                or ""
            ).upper()
            if tr_cont not in {"M", "F"}:
                result = dict(body)
                result["output1"] = all_rows
                result["output2"] = latest_output2
                return result
            context_fk = str(
                body.get("ctx_area_fk100") or body.get("CTX_AREA_FK100") or ""
            )
            context_nk = str(
                body.get("ctx_area_nk100") or body.get("CTX_AREA_NK100") or ""
            )
            if not context_fk and not context_nk:
                raise KISResponseError(
                    f"KIS continuation context missing (tr_id={tr_id})"
                )
            continuation = "N"
        raise KISResponseError(f"KIS continuation page limit exceeded (tr_id={tr_id})")

    def get_market_day(
        self, business_date: str | date | datetime | None = None
    ) -> dict[str, Any]:
        day = _date_text(business_date or self._clock())
        tr_id = "CTCA0903R"
        response = self._request(
            "GET",
            _HOLIDAY_PATH,
            tr_id,
            params={"BASS_DT": day, "CTX_AREA_FK": "", "CTX_AREA_NK": ""},
        )
        body = self._validate(response, tr_id)
        rows = self._object_list(body.get("output"), "output", tr_id)
        row = next((item for item in rows if str(item.get("bass_dt")) == day), None)
        if row is None or row.get("opnd_yn") not in {"Y", "N"}:
            raise KISResponseError(f"KIS holiday response missing opnd_yn (tr_id={tr_id})")
        return {"date": day, "opnd_yn": row["opnd_yn"], "is_open": row["opnd_yn"] == "Y"}

    def get_daily_prices(
        self,
        ticker: str,
        *,
        start_date: str | date | datetime | None = None,
        end_date: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        end_value = end_date or self._clock()
        start_value = start_date or (_as_datetime(self._clock()) - timedelta(days=30))
        tr_id = "FHKST03010100"
        response = self._request(
            "GET",
            _DAILY_PRICE_PATH,
            tr_id,
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": self._ticker(ticker),
                "FID_INPUT_DATE_1": _date_text(start_value),
                "FID_INPUT_DATE_2": _date_text(end_value),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        body = self._validate(response, tr_id)
        return self._object_list(body.get("output2"), "output2", tr_id)

    def cancel_order(
        self,
        order_no: str,
        quantity: int,
        *,
        branch_no: str,
        price: int | float = 0,
        cancel_all: bool = True,
    ) -> dict[str, Any]:
        self._require_order_safety_gates()
        tr_id = self._tr_id("cancel")
        payload = {
            **self._account_params(),
            "KRX_FWDG_ORD_ORGNO": str(branch_no),
            "ORGN_ODNO": str(order_no),
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": _number_text(quantity, positive=True),
            "ORD_UNPR": _number_text(price),
            "QTY_ALL_ORD_YN": "Y" if cancel_all else "N",
            "EXCG_ID_DVSN_CD": "KRX",
        }
        return self._post_order(_CANCEL_PATH, tr_id, payload)

    def _post_order(
        self, path: str, tr_id: str, payload: Mapping[str, object]
    ) -> dict[str, Any]:
        # 인증 실패는 주문 전 실패라 재시도 가능하다. 인증을 먼저 끝내 두면
        # 아래 예외는 주문 POST가 전송됐을 수도 있는 불명확 결과로 한정된다.
        self.authenticate()
        try:
            response = self._request(
                "POST", path, tr_id, json_body=payload, preserve_timeout=True
            )
        except (KISTransportError, TimeoutError, socket.timeout, urllib.error.URLError):
            return self._unknown_order_result(
                "KIS 주문 응답을 확인할 수 없습니다. 재주문 전 체결 조회가 필요합니다."
            )
        body = self._body(response)
        if "rt_cd" not in body or str(body.get("rt_cd") or "").strip() == "":
            return self._unknown_order_result(
                "KIS 주문 결과 코드를 확인할 수 없습니다. 재주문 전 체결 조회가 필요합니다."
            )
        body = self._validate(response, tr_id)
        raw_output = body.get("output")
        if not isinstance(raw_output, Mapping):
            return self._unknown_order_result(
                "KIS 주문번호를 확인할 수 없습니다. 재주문 전 체결 조회가 필요합니다."
            )
        output = dict(raw_output)
        order_no = output.get("ODNO")
        if not order_no:
            return self._unknown_order_result(
                "KIS 주문번호를 확인할 수 없습니다. 재주문 전 체결 조회가 필요합니다."
            )
        return {
            "success": True,
            "status": "accepted",
            "order_no": str(order_no),
            "branch_no": str(output.get("KRX_FWDG_ORD_ORGNO") or ""),
            "requires_reconciliation": True,
            "raw": output,
        }

    def _require_order_safety_gates(self) -> None:
        if not broker_order_enabled("kis"):
            raise KISConfigError("KIS order safety gate is disabled")
        if self.config.mode == "real" and not broker_real_allowed("kis"):
            raise KISConfigError("KIS real-money safety gate is disabled")

    @staticmethod
    def _unknown_order_result(message: str) -> dict[str, Any]:
        return {
            "success": False,
            "status": "unknown",
            "order_no": None,
            "branch_no": None,
            "requires_reconciliation": True,
            "message": message,
        }

    def _request(
        self,
        method: str,
        path: str,
        tr_id: str,
        *,
        params: Mapping[str, object] | None = None,
        json_body: Mapping[str, object] | None = None,
        continuation: str = "",
        preserve_timeout: bool = False,
    ) -> TransportResponse:
        headers = self._headers(tr_id)
        if continuation:
            headers["tr_cont"] = continuation
        try:
            response = self._transport.request(
                method,
                self.config.base_url + path,
                headers=headers,
                params=params,
                json_body=json_body,
                timeout=self._timeout,
            )
        except Exception as exc:
            if preserve_timeout and _is_timeout(exc):
                raise
            raise KISTransportError(
                f"KIS request failed (method={method}, tr_id={tr_id})"
            ) from exc
        if not isinstance(response, TransportResponse):
            raise KISResponseError(f"Invalid transport response (tr_id={tr_id})")
        return response

    def _headers(self, tr_id: str) -> dict[str, str]:
        token = self.authenticate()
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def _validate(self, response: TransportResponse, tr_id: str) -> Mapping[str, Any]:
        body = self._body(response)
        if str(body.get("rt_cd", "")) != "0":
            code = str(body.get("msg_cd") or body.get("rt_cd") or "unknown")
            raise KISResponseError(f"KIS API rejected request (tr_id={tr_id}, code={code})")
        return body

    @staticmethod
    def _body(response: TransportResponse) -> Mapping[str, Any]:
        if not isinstance(response, TransportResponse) or not isinstance(response.body, Mapping):
            raise KISResponseError("KIS response body must be an object")
        return response.body

    @staticmethod
    def _object(value: object, field_name: str, tr_id: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise KISResponseError(f"KIS response missing {field_name} (tr_id={tr_id})")
        return dict(value)

    @staticmethod
    def _object_list(value: object, field_name: str, tr_id: str) -> list[dict[str, Any]]:
        if isinstance(value, Mapping):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
            raise KISResponseError(f"KIS response missing {field_name} (tr_id={tr_id})")
        return [dict(item) for item in value]

    def _tr_id(self, operation: str) -> str:
        return _TR_IDS[self.config.mode][operation]

    def _account_params(self) -> dict[str, str]:
        return {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.product_code,
        }

    @staticmethod
    def _ticker(value: str) -> str:
        ticker = str(value).strip()
        if len(ticker) != 6 or not ticker.isdigit():
            raise ValueError("ticker must be a six-digit code")
        return ticker


__all__ = [
    "KISClient",
    "KISConfig",
    "KISConfigError",
    "KISResponseError",
    "KISTransportError",
    "TransportResponse",
    "UrllibTransport",
]
