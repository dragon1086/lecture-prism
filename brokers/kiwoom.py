"""Kiwoom REST API teaching adapter.

Official references checked on 2026-08-09:
- Kiwoom API guide: https://openapi.kiwoom.com/guide/apiguide
- Domains: https://api.kiwoom.com and https://mockapi.kiwoom.com
- Token API: POST /oauth2/token, api-id au10001
- Quote API: POST /api/dostk/mrkcond, api-id ka10007
- Account APIs: POST /api/dostk/acnt, api-id kt00011/kt00018
- Order APIs: POST /api/dostk/ordr, api-id kt10000/kt10001/kt10003
- Order inquiry APIs: POST /api/dostk/acnt, api-id ka10075/ka10076
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import urllib.error
import urllib.request
from typing import Any

from .base import BrokerOrder, BrokerQuote
from .config import mask_secret, normalize_mode


class KiwoomBrokerAdapter:
    name = "kiwoom"
    TOKEN_API_ID = "au10001"
    QUOTE_API_ID = "ka10007"
    ORDERABLE_API_ID = "kt00011"
    ACCOUNT_BALANCE_API_ID = "kt00018"
    PENDING_ORDERS_API_ID = "ka10075"
    FILLED_ORDERS_API_ID = "ka10076"
    BUY_API_ID = "kt10000"
    SELL_API_ID = "kt10001"
    CANCEL_API_ID = "kt10003"
    TOKEN_PATH = "/oauth2/token"
    MARKET_CONDITION_PATH = "/api/dostk/mrkcond"
    ACCOUNT_PATH = "/api/dostk/acnt"
    ORDER_PATH = "/api/dostk/ordr"

    def __init__(self, *, mode: str | None = None, timeout: float = 10.0) -> None:
        self.mode = normalize_mode(mode or os.getenv("KIWOOM_MODE") or os.getenv("LECTURE_BROKER_MODE"), default="demo")
        self.timeout = timeout
        self.base_url = (
            os.getenv("KIWOOM_BASE_URL")
            or ("https://api.kiwoom.com" if self.mode == "real" else "https://mockapi.kiwoom.com")
        ).rstrip("/")
        self.app_key = os.getenv("KIWOOM_APP_KEY") or os.getenv("KIWOOM_APPKEY")
        self.secret_key = os.getenv("KIWOOM_SECRET_KEY") or os.getenv("KIWOOM_SECRETKEY")
        self.token = os.getenv("KIWOOM_ACCESS_TOKEN")
        self.exchange = os.getenv("KIWOOM_EXCHANGE", "KRX").strip().upper() or "KRX"

    def describe_credentials(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "base_url": self.base_url,
            "app_key": mask_secret(self.app_key),
            "secret_key": mask_secret(self.secret_key),
            "token": "set" if self.token else "missing",
            "exchange": self.exchange,
        }

    def _request_json(self, path: str, payload: dict[str, Any], *, headers: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json;charset=UTF-8", **headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - user-configured official API host
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "ignore")
            return {"return_code": str(exc.code), "return_msg": text or str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"return_code": "network_error", "return_msg": str(exc)}

        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError:
            return {"return_code": "invalid_json", "return_msg": text[:500]}

    async def _access_token(self) -> str | None:
        if self.token:
            return self.token
        if not self.app_key or not self.secret_key:
            return None

        response = await asyncio.to_thread(
            self._request_json,
            self.TOKEN_PATH,
            {
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "secretkey": self.secret_key,
            },
            headers={"api-id": self.TOKEN_API_ID},
        )
        if str(response.get("return_code", "0")) != "0" and "token" not in response:
            self.token = None
            return None
        self.token = response.get("token")
        return self.token

    @staticmethod
    def _is_success(response: dict[str, Any]) -> bool:
        return str(response.get("return_code", "0")) == "0"

    async def _authorized_post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        api_id: str,
    ) -> dict[str, Any]:
        token = await self._access_token()
        if not token:
            raise RuntimeError("Kiwoom credentials missing")
        response = await asyncio.to_thread(
            self._request_json,
            path,
            payload,
            headers={
                "authorization": f"Bearer {token}",
                "cont-yn": "N",
                "next-key": "",
                "api-id": api_id,
            },
        )
        if not self._is_success(response):
            raise RuntimeError("Kiwoom read-only request failed")
        return response

    async def check_authentication(self) -> dict[str, Any]:
        token = await self._access_token()
        if not token:
            raise RuntimeError("Kiwoom credentials missing")
        return {"authenticated": True, "mode": self.mode}

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        text = str(value if value is not None else "").strip().replace(",", "")
        text = text.lstrip("+")
        try:
            parsed = Decimal(text)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError("Kiwoom numeric field is malformed") from exc
        if not parsed.is_finite():
            raise RuntimeError("Kiwoom numeric field is malformed")
        return abs(parsed)

    @classmethod
    def _int(cls, value: Any) -> int:
        parsed = cls._decimal(value)
        if parsed != parsed.to_integral_value():
            raise RuntimeError("Kiwoom integer field is malformed")
        return int(parsed)

    @staticmethod
    def _row_value(row: dict[str, Any], *names: str):
        lower = {str(key).lower(): value for key, value in row.items()}
        for name in names:
            if name.lower() in lower:
                return lower[name.lower()]
        return None

    @staticmethod
    def _rows(response: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(response, dict):
            return []
        if isinstance(response.get("rows"), list):
            return [row for row in response["rows"] if isinstance(row, dict)]
        rows: list[dict[str, Any]] = []
        for value in response.values():
            if isinstance(value, list):
                rows.extend(row for row in value if isinstance(row, dict))
        return rows

    async def get_quote(self, ticker: str) -> BrokerQuote:
        response = await self._authorized_post(
            self.MARKET_CONDITION_PATH,
            {"stk_cd": str(ticker)},
            api_id=self.QUOTE_API_ID,
        )
        if str(response.get("stk_cd") or ticker).strip() != str(ticker):
            raise RuntimeError("Kiwoom quote ticker mismatch")
        price_value = response.get("cur_prc")
        if price_value in (None, ""):
            raise RuntimeError("Kiwoom quote response missing cur_prc")
        return BrokerQuote(
            ticker=str(ticker),
            price=self._int(price_value),
            currency="KRW",
            market="KRX",
            observed_at=datetime.now(timezone.utc),
            source=f"kiwoom.{self.QUOTE_API_ID}",
        )

    async def get_orderable_quantity(self, ticker: str, price: int) -> int:
        if int(price) <= 0:
            raise ValueError("price must be positive")
        response = await self._authorized_post(
            self.ACCOUNT_PATH,
            {"stk_cd": str(ticker), "uv": str(int(price))},
            api_id=self.ORDERABLE_API_ID,
        )
        value = response.get("min_ord_alowq")
        if value in (None, ""):
            raise RuntimeError("Kiwoom orderable response missing min_ord_alowq")
        return self._int(value)

    async def get_account(self) -> dict[str, Any]:
        response = await self._authorized_post(
            self.ACCOUNT_PATH,
            {"qry_tp": "1", "dmst_stex_tp": self.exchange},
            api_id=self.ACCOUNT_BALANCE_API_ID,
        )
        positions = []
        for row in self._rows(response):
            ticker = str(
                self._row_value(row, "stk_cd", "pdno", "ticker") or ""
            ).strip()
            if not ticker:
                continue
            held = self._row_value(row, "rmnd_qty", "hldg_qty", "quantity")
            sellable = self._row_value(
                row, "trde_able_qty", "ord_psbl_qty", "sellable_quantity"
            )
            positions.append(
                {
                    "pdno": ticker,
                    "ticker": ticker,
                    "hldg_qty": str(held or "0"),
                    "quantity": str(held or "0"),
                    "trde_able_qty": str(sellable if sellable not in (None, "") else held or "0"),
                    "name": str(self._row_value(row, "stk_nm", "name") or ""),
                    "raw": row,
                }
            )
        return {"positions": positions, "raw": response}

    async def get_sellable_quantity(self, ticker: str) -> int:
        account = await self.get_account()
        sellable = 0
        for position in account.get("positions", []):
            if str(position.get("pdno") or position.get("ticker") or "") != str(ticker):
                continue
            sellable += max(self._int(position.get("trde_able_qty", 0)), 0)
        return sellable

    async def get_pending_orders(self, *, business_date: str | None = None) -> dict[str, Any]:
        del business_date
        response = await self._authorized_post(
            self.ACCOUNT_PATH,
            {
                "all_stk_tp": "0",
                "trde_tp": "0",
                "stk_cd": "",
                "stex_tp": "0",
            },
            api_id=self.PENDING_ORDERS_API_ID,
        )
        return {"rows": self._rows(response), "raw": response}

    async def get_completed_orders(self, *, business_date: str | None = None) -> dict[str, Any]:
        del business_date
        response = await self._authorized_post(
            self.ACCOUNT_PATH,
            {
                "stk_cd": "",
                "qry_tp": "0",
                "sell_tp": "0",
                "ord_no": "",
                "stex_tp": "0",
            },
            api_id=self.FILLED_ORDERS_API_ID,
        )
        return {"rows": self._rows(response), "raw": response}

    @staticmethod
    def _unknown_order_snapshot(order_no: str) -> dict[str, Any]:
        return {
            "status": "unknown",
            "accepted": False,
            "executed": False,
            "terminal": False,
            "order_no": str(order_no),
            "filled_qty": 0,
            "remaining_qty": 0,
        }

    @classmethod
    def _order_snapshot(
        cls, response: dict[str, Any], *, order_no: str, requested_qty: int | None = None
    ) -> dict[str, Any] | None:
        for row in cls._rows(response):
            row_order_no = str(
                cls._row_value(row, "ord_no", "odno", "order_no") or ""
            )
            if row_order_no != str(order_no):
                continue
            requested_value = cls._row_value(row, "ord_qty", "requested_qty")
            filled_value = cls._row_value(
                row, "cntr_qty", "tot_ccld_qty", "ccld_qty", "filled_qty"
            )
            remaining_value = cls._row_value(row, "oso_qty", "rmn_qty", "remaining_qty")
            if any(value in (None, "") for value in (requested_value, filled_value, remaining_value)):
                return cls._unknown_order_snapshot(order_no)
            average_value = cls._row_value(
                row, "avg_prvs", "avg_ccld_unpr", "average_fill_price"
            )
            try:
                requested = cls._int(requested_value)
                filled = cls._int(filled_value)
                remaining = cls._int(remaining_value)
                average = cls._int(average_value) if filled and average_value else None
            except RuntimeError:
                return cls._unknown_order_snapshot(order_no)
            if (
                requested <= 0
                or filled > requested
                or remaining > requested
                or filled + remaining != requested
            ):
                return cls._unknown_order_snapshot(order_no)
            raw_state = str(cls._row_value(row, "ord_stt", "status") or "")
            if "취소" in raw_state or "cancel" in raw_state.lower():
                status = "canceled"
            elif requested > 0 and filled >= requested and remaining == 0:
                status = "filled"
            elif filled > 0:
                status = "partial"
            else:
                status = "accepted"
            return {
                "status": status,
                "accepted": status != "unknown",
                "executed": status == "filled",
                "terminal": status in {"filled", "canceled"},
                "order_no": str(order_no),
                "filled_qty": filled,
                "remaining_qty": remaining,
                "average_fill_price": average,
            }
        return None

    async def get_order_status(
        self, order_no: str, *, business_date: str | None = None
    ) -> dict[str, Any]:
        pending = await self.get_pending_orders(business_date=business_date)
        snapshot = self._order_snapshot(pending, order_no=order_no)
        if snapshot is not None:
            return snapshot
        completed = await self.get_completed_orders(business_date=business_date)
        snapshot = self._order_snapshot(completed, order_no=order_no)
        if snapshot is not None:
            return snapshot
        return self._unknown_order_snapshot(order_no)

    async def cancel_order(
        self, order_no: str, *, ticker: str, quantity: int, **details
    ) -> dict[str, Any]:
        del details
        token = await self._access_token()
        if not token:
            return {
                "success": False,
                "status": "blocked",
                "accepted": False,
                "executed": False,
                "terminal": True,
                "mode": "kiwoom_credentials_missing",
                "order_no": None,
                "message": "KIWOOM_ACCESS_TOKEN 또는 KIWOOM_APP_KEY/KIWOOM_SECRET_KEY가 필요합니다.",
            }
        payload = {
            "dmst_stex_tp": self.exchange,
            "orig_ord_no": str(order_no),
            "stk_cd": str(ticker),
            "cncl_qty": str(int(quantity)),
        }
        response = await asyncio.to_thread(
            self._request_json,
            self.ORDER_PATH,
            payload,
            headers={
                "authorization": f"Bearer {token}",
                "cont-yn": "N",
                "next-key": "",
                "api-id": self.CANCEL_API_ID,
            },
        )
        success = self._is_success(response)
        return {
            "success": success,
            "status": "cancel_accepted" if success else "unknown",
            "accepted": success,
            "executed": False,
            "terminal": False,
            "mode": f"kiwoom_{self.mode}",
            "order_no": response.get("ord_no") or str(order_no),
            "message": response.get("return_msg", "Kiwoom cancel requested" if success else "Kiwoom cancel failed"),
            "api_id": self.CANCEL_API_ID,
            "payload": payload,
            "raw": response,
        }

    async def place_order(self, order: BrokerOrder) -> dict[str, Any]:
        if order.side not in {"BUY", "SELL"}:
            return {
                "success": False,
                "mode": f"kiwoom_{self.mode}_unsupported_side",
                "order_no": None,
                "message": f"Unsupported Kiwoom order side: {order.action}",
                "credentials": self.describe_credentials(),
            }

        token = await self._access_token()
        if not token:
            return {
                "success": False,
                "mode": "kiwoom_credentials_missing",
                "order_no": None,
                "message": "KIWOOM_ACCESS_TOKEN 또는 KIWOOM_APP_KEY/KIWOOM_SECRET_KEY가 필요합니다.",
                "credentials": self.describe_credentials(),
            }

        api_id = self.BUY_API_ID if order.side == "BUY" else self.SELL_API_ID
        price = int(order.price or 0)
        trade_type = os.getenv("KIWOOM_TRADE_TYPE") or ("0" if price > 0 else "3")
        order_unit_price = "" if trade_type == "3" else str(price)
        payload = {
            "dmst_stex_tp": self.exchange,  # KRX, NXT, SOR
            "stk_cd": order.ticker,
            "ord_qty": str(int(order.quantity)),
            "ord_uv": order_unit_price,
            "trde_tp": trade_type,  # 0: 보통, 3: 시장가 등 (공식 문서 기준)
            "cond_uv": "",
        }
        response = await asyncio.to_thread(
            self._request_json,
            self.ORDER_PATH,
            payload,
            headers={
                "authorization": f"Bearer {token}",
                "cont-yn": "N",
                "next-key": "",
                "api-id": api_id,
            },
        )
        success = self._is_success(response)
        if not success:
            return {
                "success": False,
                "status": "unknown",
                "accepted": False,
                "executed": False,
                "terminal": False,
                "mode": f"kiwoom_{self.mode}",
                "order_no": response.get("ord_no"),
                "stock_code": order.ticker,
                "quantity": order.quantity,
                "current_price": price,
                "message": response.get("return_msg", "Kiwoom order result is unknown"),
                "api_id": api_id,
                "payload": {**payload, "stk_cd": order.ticker},
                "raw": response,
            }
        return {
            "success": success,
            "status": "accepted",
            "accepted": True,
            "executed": False,
            "terminal": False,
            "mode": f"kiwoom_{self.mode}",
            "order_no": response.get("ord_no"),
            "stock_code": order.ticker,
            "quantity": order.quantity,
            "current_price": price,
            "message": response.get("return_msg", "Kiwoom order requested" if success else "Kiwoom order failed"),
            "api_id": api_id,
            "payload": {**payload, "stk_cd": order.ticker},
            "raw": response,
        }
