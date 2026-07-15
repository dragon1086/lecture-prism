"""Kiwoom REST API teaching adapter.

Official references checked on 2026-06-28:
- Kiwoom API guide: https://openapi.kiwoom.com/guide/apiguide
- Domains: https://api.kiwoom.com and https://mockapi.kiwoom.com
- Token API: POST /oauth2/token, api-id au10001
- Stock order API: POST /api/dostk/ordr, api-id kt10000/kt10001
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any

from .base import BrokerOrder
from .config import (
    broker_order_enabled,
    broker_real_allowed,
    mask_secret,
    normalize_mode,
)


class KiwoomBrokerAdapter:
    name = "kiwoom"
    TOKEN_API_ID = "au10001"
    BUY_API_ID = "kt10000"
    SELL_API_ID = "kt10001"
    TOKEN_PATH = "/oauth2/token"
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

    async def place_order(self, order: BrokerOrder) -> dict[str, Any]:
        if not broker_order_enabled("kiwoom"):
            return {
                "success": False,
                "status": "blocked",
                "accepted": False,
                "executed": False,
                "filled_qty": 0,
                "remaining_qty": int(order.quantity),
                "mode": f"kiwoom_{self.mode}_blocked",
                "order_no": None,
                "message": "키움 주문 안전 게이트가 닫혀 있어 주문하지 않습니다.",
            }
        if self.mode == "real" and not broker_real_allowed("kiwoom"):
            return {
                "success": False,
                "status": "live_blocked",
                "accepted": False,
                "executed": False,
                "filled_qty": 0,
                "remaining_qty": int(order.quantity),
                "mode": "real_blocked",
                "order_no": None,
                "message": "키움 실전투자 안전 게이트가 닫혀 있어 주문하지 않습니다.",
            }
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
        return {
            "success": success,
            "status": "accepted" if success else "rejected",
            "accepted": success,
            "executed": False,
            "filled_qty": 0,
            "remaining_qty": int(order.quantity),
            "requires_reconciliation": success,
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
