"""Optional Toss WTS adapter backed by the pinned ``tossctl`` JSON CLI."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import os
import re
from typing import Any

from .base import BrokerOrder, BrokerQuote
from .config import normalize_mode
from .tossctl import (
    TossctlClient,
    TossctlConfigurationError,
    TossctlError,
    TossctlUnknownMutationError,
)


_KR_TICKER = re.compile(r"^\d{6}$")


def _number(value: Any, *, default: Decimal = Decimal("0")) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
    return parsed if parsed.is_finite() else default


def _required_number(
    payload: dict[str, Any],
    key: str,
    *,
    error_type: type[TossctlError] = TossctlError,
) -> Decimal:
    if key not in payload or payload[key] is None or isinstance(payload[key], bool):
        raise error_type(f"Toss JSON field is required: {key}")
    try:
        parsed = Decimal(str(payload[key]))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise error_type(f"Toss JSON field must be numeric: {key}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise error_type(f"Toss JSON field must be finite and non-negative: {key}")
    return parsed


def _plain_number(value: int | float) -> str:
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("order number must be finite")
    return format(parsed.normalize(), "f")


def _auth_block(message: str, *, mode: str) -> dict[str, Any]:
    return {
        "success": False,
        "status": "blocked",
        "accepted": False,
        "executed": False,
        "terminal": True,
        "mode": f"toss_{mode}",
        "order_no": None,
        "message": message,
    }


class TossBrokerAdapter:
    name = "toss"

    def __init__(
        self,
        *,
        mode: str | None = None,
        client: TossctlClient | Any | None = None,
        clock=None,
    ) -> None:
        self.mode = normalize_mode(
            mode
            or os.getenv("TOSS_SECURITIES_MODE")
            or os.getenv("LECTURE_BROKER_MODE"),
            default="demo",
        )
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def client(self):
        if self._client is None:
            self._client = TossctlClient()
        return self._client

    async def _run(self, args: list[str], *, mutation: bool = False):
        return await asyncio.to_thread(
            self.client.run_json, args, mutation=mutation
        )

    async def check_auth(self) -> dict[str, Any]:
        try:
            status = await self._run(["auth", "status"])
        except TossctlConfigurationError as exc:
            return _auth_block(str(exc), mode="configuration_error")
        except TossctlError as exc:
            return _auth_block(str(exc), mode="auth_unknown")
        if not isinstance(status, dict):
            return _auth_block(
                "Toss 인증 상태 JSON 형식이 올바르지 않습니다.",
                mode="auth_unknown",
            )
        if not (
            status.get("active") is True
            and status.get("expired") is False
            and status.get("validated") is True
            and status.get("valid") is True
        ):
            return _auth_block(
                "Toss 앱에서 로그인 또는 세션 연장이 필요합니다.",
                mode="manual_action_required",
            )
        expiry = status.get("server_expires_at")
        try:
            expires_at = datetime.fromisoformat(
                str(expiry).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return _auth_block(
                "Toss 서버 세션 만료 시각을 확인할 수 없습니다.",
                mode="auth_unknown",
            )
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            return _auth_block(
                "Toss 앱에서 세션 연장이 필요합니다.",
                mode="manual_action_required",
            )
        return {"success": True, "status": "active", "expires_at": expiry}

    async def _require_auth(self) -> None:
        auth = await self.check_auth()
        if not auth.get("success"):
            raise TossctlError(auth.get("message", "Toss 인증이 필요합니다."))

    async def get_account(self) -> dict[str, Any]:
        await self._require_auth()
        summary = await self._run(["account", "summary"])
        if not isinstance(summary, dict):
            raise TossctlError("Toss account summary JSON 형식이 올바르지 않습니다.")
        return {
            "orderable_amount_krw": float(
                _required_number(summary, "orderable_amount_krw")
            ),
            "orderable_amount_usd": float(
                _required_number(summary, "orderable_amount_usd")
            ),
        }

    async def get_orderable_quantity(self, ticker: str, price: int) -> int:
        if price <= 0:
            raise ValueError("price must be positive")
        account = await self.get_account()
        amount = _number(account.get("orderable_amount_krw"))
        return max(int(amount // Decimal(str(price))), 0)

    async def get_sellable_quantity(self, ticker: str) -> int:
        await self._require_auth()
        sellable = await self._run(["quote", "sellable", str(ticker)])
        positions = await self._run(["portfolio", "positions"])
        if not isinstance(sellable, dict) or not isinstance(positions, list):
            raise TossctlError("Toss 보유 수량 JSON 형식이 올바르지 않습니다.")
        broker_quantity = _required_number(sellable, "sellable_quantity")
        if broker_quantity != broker_quantity.to_integral_value():
            raise TossctlError("Toss KR sellable_quantity must be an integer")
        broker_limit = int(broker_quantity)
        held = 0
        for position in positions:
            if not isinstance(position, dict):
                continue
            if str(position.get("symbol", "")) == str(ticker):
                quantity = _required_number(position, "quantity")
                if quantity != quantity.to_integral_value():
                    raise TossctlError("Toss KR position quantity must be an integer")
                held += int(quantity)
        return min(broker_limit, held)

    def _place_intent_args(self, order: BrokerOrder) -> list[str]:
        side = order.side
        ticker = str(order.ticker).strip()
        if side not in {"BUY", "SELL"}:
            raise ValueError("Toss supports BUY or SELL only")
        if not _KR_TICKER.fullmatch(ticker):
            raise ValueError("Toss lecture adapter requires a 6-digit KR ticker")
        if not isinstance(order.quantity, int) or order.quantity <= 0:
            raise ValueError("Toss KR quantity must be a positive integer")
        price = _number(order.price)
        if price <= 0 or price != price.to_integral_value():
            raise ValueError("Toss KR limit price must be a positive integer")
        return [
            "--symbol",
            ticker,
            "--market",
            "kr",
            "--side",
            side.lower(),
            "--type",
            "limit",
            "--qty",
            str(order.quantity),
            "--price",
            _plain_number(int(price)),
            "--currency-mode",
            "KRW",
        ]

    @staticmethod
    def _preview_token(preview: Any, *, kind: str) -> str:
        if not isinstance(preview, dict):
            raise TossctlError("Toss preview JSON 형식이 올바르지 않습니다.")
        token = str(preview.get("confirm_token") or "")
        if (
            preview.get("kind") != kind
            or not str(preview.get("canonical") or "")
            or not token
            or preview.get("live_ready") is not True
            or preview.get("mutation_ready") is not True
        ):
            raise TossctlError("Toss 주문 preview가 mutation 준비 상태가 아닙니다.")
        return token

    @staticmethod
    def _mutation_result(payload: Any, *, requested: int) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TossctlUnknownMutationError(
                "Toss mutation JSON 형식이 올바르지 않습니다."
            )
        raw_status = str(payload.get("status") or "unknown").lower()
        status_map = {
            "accepted": "accepted",
            "accepted_pending": "accepted",
            "filled": "filled",
            "filled_completed": "filled",
            "canceled": "canceled",
            "rejected": "rejected",
            "unknown": "unknown",
        }
        status = status_map.get(raw_status, "unknown")
        filled = 0
        average: Decimal | None = None
        if status == "filled":
            filled_value = _required_number(
                payload,
                "filled_quantity",
                error_type=TossctlUnknownMutationError,
            )
            average = _required_number(
                payload,
                "average_execution_price",
                error_type=TossctlUnknownMutationError,
            )
            if (
                filled_value != filled_value.to_integral_value()
                or int(filled_value) != requested
                or average <= 0
            ):
                raise TossctlUnknownMutationError(
                    "Toss filled mutation fields are inconsistent"
                )
            filled = int(filled_value)
        elif status == "accepted" and "filled_quantity" in payload:
            filled_value = _required_number(
                payload,
                "filled_quantity",
                error_type=TossctlUnknownMutationError,
            )
            if filled_value != 0:
                raise TossctlUnknownMutationError(
                    "Toss accepted mutation contains ambiguous fill quantity"
                )
        elif status == "canceled" and "filled_quantity" in payload:
            filled_value = _required_number(
                payload,
                "filled_quantity",
                error_type=TossctlUnknownMutationError,
            )
            if filled_value != filled_value.to_integral_value() or filled_value > requested:
                raise TossctlUnknownMutationError(
                    "Toss canceled mutation contains invalid fill quantity"
                )
            filled = int(filled_value)
            if filled:
                average = _required_number(
                    payload,
                    "average_execution_price",
                    error_type=TossctlUnknownMutationError,
                )
                if average <= 0:
                    raise TossctlUnknownMutationError(
                        "Toss canceled mutation is missing average execution price"
                    )
        remaining = max(requested - filled, 0)
        order_no = payload.get("order_id") or payload.get("current_order_id")
        if status in {"accepted", "filled", "canceled"} and (
            not isinstance(order_no, str) or not order_no.strip()
        ):
            status = "unknown"
            order_no = None
        terminal = status in {"filled", "canceled", "rejected"}
        return {
            "success": status not in {"unknown", "rejected"},
            "status": status,
            "accepted": status in {"accepted", "filled", "canceled"},
            "executed": status == "filled",
            "terminal": terminal,
            "mode": "toss_real",
            "order_no": str(order_no) if order_no else None,
            "order_date": payload.get("order_date"),
            "filled_qty": filled,
            "remaining_qty": remaining,
            "average_fill_price": float(average) if average is not None else None,
            "message": "; ".join(payload.get("warnings") or []),
        }

    async def place_order(self, order: BrokerOrder) -> dict[str, Any]:
        if self.mode != "real":
            return _auth_block(
                "Toss WTS에는 모의투자 backend가 없어 real 모드에서만 주문할 수 있습니다.",
                mode="mode_blocked",
            )
        auth = await self.check_auth()
        if not auth.get("success"):
            return auth
        try:
            intent_args = self._place_intent_args(order)
            preview = await self._run(["order", "preview", *intent_args])
            token = self._preview_token(preview, kind="place")
            payload = await self._run(
                [
                    "order",
                    "place",
                    *intent_args,
                    "--execute",
                    "--confirm",
                    token,
                ],
                mutation=True,
            )
            return self._mutation_result(payload, requested=order.quantity)
        except TossctlUnknownMutationError as exc:
            return {
                "success": False,
                "status": "unknown",
                "accepted": False,
                "executed": False,
                "terminal": False,
                "mode": "toss_real_unknown",
                "order_no": None,
                "filled_qty": 0,
                "remaining_qty": order.quantity,
                "message": str(exc),
            }
        except TossctlError as exc:
            return _auth_block(str(exc), mode="preview_blocked")
        except ValueError as exc:
            return _auth_block(str(exc), mode="validation_blocked")

    async def get_order_status(
        self, order_id: str, *, market: str = "kr"
    ) -> dict[str, Any]:
        await self._require_auth()
        payload = await self._run(
            ["order", "show", str(order_id), "--market", market]
        )
        return self._order_snapshot(payload)

    @staticmethod
    def _order_snapshot(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TossctlError("Toss order JSON 형식이 올바르지 않습니다.")
        requested = int(_number(payload.get("quantity")))
        filled = int(_number(payload.get("filled_quantity")))
        if requested <= 0 or filled < 0 or filled > requested:
            raise TossctlError("Toss order quantity fields are inconsistent")
        remaining = requested - filled
        raw_status = str(payload.get("status") or "").lower()
        if filled == requested and remaining == 0:
            status = "filled"
        elif any(word in raw_status for word in ("취소", "cancel")):
            status = "canceled"
        elif any(word in raw_status for word in ("거절", "reject")):
            status = "rejected"
        elif filled > 0:
            status = "partial"
        elif any(
            word in raw_status
            for word in ("대기", "접수", "accepted", "pending")
        ):
            status = "accepted"
        else:
            status = "unknown"
        terminal = status in {"filled", "canceled", "rejected"}
        average = _number(payload.get("average_execution_price"))
        return {
            "status": status,
            "accepted": status in {"accepted", "partial", "filled", "canceled"},
            "executed": status == "filled",
            "terminal": terminal,
            "order_no": str(payload.get("id") or "") or None,
            "order_date": payload.get("order_date"),
            "requested_qty": requested,
            "filled_qty": filled,
            "remaining_qty": remaining,
            "average_fill_price": float(average) if filled and average > 0 else None,
        }

    async def get_pending_orders(self) -> list[dict[str, Any]]:
        await self._require_auth()
        payload = await self._run(["orders", "list"])
        if not isinstance(payload, list):
            raise TossctlError("Toss pending orders JSON 형식이 올바르지 않습니다.")
        return payload

    async def get_completed_orders(
        self, *, market: str = "kr"
    ) -> list[dict[str, Any]]:
        await self._require_auth()
        payload = await self._run(["orders", "completed", "--market", market])
        if not isinstance(payload, list):
            raise TossctlError("Toss completed orders JSON 형식이 올바르지 않습니다.")
        return payload

    async def cancel_order(
        self, order_id: str, ticker: str
    ) -> dict[str, Any]:
        if self.mode != "real":
            return _auth_block(
                "Toss WTS 취소는 real 모드에서만 실행할 수 있습니다.",
                mode="mode_blocked",
            )
        auth = await self.check_auth()
        if not auth.get("success"):
            return auth
        current_payload = await self._run(
            ["order", "show", str(order_id), "--market", "kr"]
        )
        if not isinstance(current_payload, dict) or (
            str(current_payload.get("id") or "") != str(order_id)
            or str(current_payload.get("symbol") or "") != str(ticker)
        ):
            return _auth_block(
                "Toss 취소 대상 주문의 식별자 또는 종목이 일치하지 않습니다.",
                mode="cancel_target_mismatch",
            )
        current = self._order_snapshot(current_payload)
        if current["terminal"]:
            return current
        base = [
            "order",
            "cancel",
            "--order-id",
            str(order_id),
            "--symbol",
            str(ticker),
        ]
        try:
            preview = await self._run(base)
            token = self._preview_token(preview, kind="cancel")
            payload = await self._run(
                [*base, "--execute", "--confirm", token], mutation=True
            )
            return self._mutation_result(
                payload, requested=int(current["requested_qty"])
            )
        except TossctlUnknownMutationError as exc:
            return {
                **current,
                "status": "unknown",
                "accepted": False,
                "executed": False,
                "terminal": False,
                "mode": "toss_real_unknown",
                "message": str(exc),
            }
        except TossctlError as exc:
            return {
                **current,
                "mode": "toss_cancel_preview_blocked",
                "message": str(exc),
            }


class TossOfficialError(RuntimeError):
    """Base error for the official Toss Open API teaching boundary."""


class TossOfficialConfigurationError(TossOfficialError):
    """Raised when official Open API credentials/client are unavailable."""


class TossOfficialRateLimitError(TossOfficialError):
    """Raised when official REST rate limits make readiness unsafe."""


class TossOfficialSchemaError(TossOfficialError):
    """Raised when official REST payloads are missing required fields."""


def _official_block(message: str, *, mode: str) -> dict[str, Any]:
    return {
        "success": False,
        "status": "blocked",
        "accepted": False,
        "executed": False,
        "terminal": True,
        "mode": f"toss_official_{mode}",
        "order_no": None,
        "message": message,
    }


def _strict_decimal(payload: dict[str, Any], key: str) -> Decimal:
    if key not in payload or payload[key] is None or isinstance(payload[key], bool):
        raise TossOfficialSchemaError(f"Toss official field is required: {key}")
    try:
        parsed = Decimal(str(payload[key]))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TossOfficialSchemaError(
            f"Toss official field must be numeric: {key}"
        ) from exc
    if not parsed.is_finite() or parsed < 0:
        raise TossOfficialSchemaError(
            f"Toss official field must be finite and non-negative: {key}"
        )
    return parsed


def _official_iso(value: Any, *, fallback) -> datetime:
    if value in (None, ""):
        now = fallback()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise TossOfficialSchemaError("Toss official timestamp is malformed") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _call_error(exc: Exception) -> Exception:
    text = str(exc).lower()
    if isinstance(exc, TossOfficialError):
        return exc
    if "429" in text or "rate limit" in text or "rate-limit" in text:
        return TossOfficialRateLimitError("Toss official REST rate limit exceeded")
    return exc


class TossOfficialOpenAPIAdapter:
    """Official Toss Open API read-only/lifecycle boundary.

    This class deliberately does not implement live order E2E. The official
    API has no paper/demo environment, and order/cancel calls remain blocked
    until a separately approved real-account E2E is added.
    """

    name = "toss"
    integration = "official_open_api"
    credential_keys = (
        "TOSS_OPENAPI_CLIENT_ID",
        "TOSS_OPENAPI_CLIENT_SECRET",
        "TOSS_OPENAPI_ACCOUNT_SEQ",
    )

    def __init__(
        self,
        *,
        mode: str | None = None,
        client: Any | None = None,
        env: dict[str, str] | None = None,
        clock=None,
    ) -> None:
        source = env if env is not None else os.environ
        self.mode = normalize_mode(
            mode
            or source.get("TOSS_OPENAPI_MODE")
            or source.get("TOSS_SECURITIES_MODE")
            or source.get("LECTURE_BROKER_MODE"),
            default="real",
        )
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def missing_credentials(cls, env: dict[str, str] | Any) -> list[str]:
        return [key for key in cls.credential_keys if not str(env.get(key, "")).strip()]

    async def _call(self, *names: str, args: tuple[Any, ...] = ()):
        if self._client is None:
            raise TossOfficialConfigurationError(
                "Toss official Open API client is not configured"
            )
        method = None
        for name in names:
            candidate = getattr(self._client, name, None)
            if callable(candidate):
                method = candidate
                break
        if method is None:
            raise TossOfficialConfigurationError(
                "Toss official Open API client is missing read capability"
            )
        try:
            result = method(*args)
            if hasattr(result, "__await__"):
                return await result
            return result
        except Exception as exc:  # noqa: BLE001 - classify external read failures
            raise _call_error(exc) from exc

    def _require_live_read(self) -> None:
        if self.mode != "real":
            raise TossOfficialConfigurationError(
                "Toss official Open API has no paper/demo environment"
            )

    async def check_authentication(self) -> dict[str, Any]:
        await self.get_account()
        return {"authenticated": True}

    async def get_account(self) -> dict[str, Any]:
        self._require_live_read()
        payload = await self._call("accounts", "Accounts")
        if not isinstance(payload, list):
            raise TossOfficialSchemaError("Toss official accounts payload must be a list")
        accounts: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise TossOfficialSchemaError("Toss official account item is malformed")
            seq = item.get("accountSeq", item.get("id"))
            if seq in (None, "") or isinstance(seq, bool):
                raise TossOfficialSchemaError(
                    "Toss official accountSeq is required"
                )
            accounts.append(
                {
                    "account_seq": str(seq),
                    "account_type": str(item.get("accountType") or item.get("type") or ""),
                }
            )
        return {"accounts_count": len(accounts), "accounts": accounts}

    async def get_sellable_quantity(self, ticker: str) -> int:
        self._require_live_read()
        payload = await self._call("holdings", "Holdings", args=(str(ticker),))
        if not isinstance(payload, list):
            raise TossOfficialSchemaError("Toss official holdings payload must be a list")
        total = Decimal("0")
        for item in payload:
            if not isinstance(item, dict):
                raise TossOfficialSchemaError("Toss official holdings item is malformed")
            if str(item.get("symbol") or "") != str(ticker):
                continue
            quantity = _strict_decimal(item, "quantity")
            if quantity != quantity.to_integral_value():
                raise TossOfficialSchemaError(
                    "Toss official KR holding quantity must be an integer"
                )
            total += quantity
        return int(total)

    async def get_orderable_quantity(self, ticker: str, price: int) -> int:
        if price <= 0:
            raise ValueError("price must be positive")
        # The official REST buying-power endpoint is a read-only account path,
        # but live order E2E is still blocked elsewhere.
        self._require_live_read()
        payload = await self._call("buying_power", "BuyingPower", args=("KRW",))
        if not isinstance(payload, dict):
            raise TossOfficialSchemaError(
                "Toss official buying power payload must be an object"
            )
        amount = _strict_decimal(payload, "cashBuyingPower")
        return max(int(amount // Decimal(str(price))), 0)

    async def get_quote(self, ticker: str) -> BrokerQuote:
        self._require_live_read()
        payload = await self._call("quote", "Price", "Prices", args=(str(ticker),))
        if isinstance(payload, list):
            payload = next(
                (item for item in payload if isinstance(item, dict) and str(item.get("symbol")) == str(ticker)),
                None,
            )
        if not isinstance(payload, dict):
            raise TossOfficialSchemaError("Toss official quote payload is malformed")
        symbol = str(payload.get("symbol") or "")
        if symbol != str(ticker):
            raise TossOfficialSchemaError("Toss official quote ticker mismatch")
        raw_price = payload.get("price", payload.get("lastPrice"))
        price = _strict_decimal({"price": raw_price}, "price")
        if price != price.to_integral_value():
            raise TossOfficialSchemaError("Toss official KR quote price must be integral")
        currency = str(payload.get("currency") or "").upper()
        if currency != "KRW":
            raise TossOfficialSchemaError("Toss official quote currency must be KRW")
        market = str(payload.get("market") or payload.get("marketCountry") or "KRX").upper()
        if market in {"KOSPI", "KOSDAQ", "KR", ""}:
            market = "KRX"
        observed = _official_iso(
            payload.get("observedAt", payload.get("timestamp")),
            fallback=self._clock,
        )
        return BrokerQuote(
            ticker=symbol,
            price=int(price),
            currency="KRW",
            market=market,
            observed_at=observed,
            source="toss.official.openapi",
        )

    async def get_pending_orders(self) -> list[dict[str, Any]]:
        self._require_live_read()
        payload = await self._call("pending_orders", "Orders")
        if not isinstance(payload, list):
            raise TossOfficialSchemaError(
                "Toss official pending orders payload must be a list"
            )
        return [self.normalize_order_snapshot(item) for item in payload]

    async def get_order_status(self, order_id: str, *, market: str = "kr") -> dict[str, Any]:
        del market
        self._require_live_read()
        payload = await self._call("order_status", "OrderByID", args=(str(order_id),))
        return self.normalize_order_snapshot(payload)

    @staticmethod
    def normalize_order_snapshot(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TossOfficialSchemaError("Toss official order payload is malformed")
        order_no = payload.get("orderId") or payload.get("id")
        requested = _strict_decimal(payload, "quantity")
        if requested != requested.to_integral_value() or requested <= 0:
            raise TossOfficialSchemaError("Toss official order quantity is invalid")
        execution = payload.get("execution") or {}
        if not isinstance(execution, dict):
            raise TossOfficialSchemaError("Toss official execution payload is malformed")
        filled = _strict_decimal(
            {"filledQuantity": execution.get("filledQuantity", "0")},
            "filledQuantity",
        )
        if filled != filled.to_integral_value() or filled > requested:
            raise TossOfficialSchemaError("Toss official filled quantity is invalid")
        average = Decimal("0")
        if filled:
            average = _strict_decimal(
                {"averageFilledPrice": execution.get("averageFilledPrice")},
                "averageFilledPrice",
            )
            if average <= 0:
                raise TossOfficialSchemaError(
                    "Toss official filled order missing average price"
                )
        raw_status = str(payload.get("status") or "").strip().upper()
        if raw_status == "OPEN":
            status = "partial" if filled else "accepted"
        elif raw_status == "CLOSED":
            status = "filled" if filled == requested else "canceled"
        elif raw_status in {"CANCELED", "CANCELLED"}:
            status = "canceled"
        elif raw_status == "REJECTED":
            status = "rejected"
        else:
            status = "unknown"
        terminal = status in {"filled", "canceled", "rejected"}
        return {
            "status": status,
            "accepted": status in {"accepted", "partial", "filled", "canceled"},
            "executed": status == "filled",
            "terminal": terminal,
            "order_no": str(order_no) if order_no else None,
            "order_date": str(payload.get("orderedAt") or "")[:10] or None,
            "requested_qty": int(requested),
            "filled_qty": int(filled),
            "remaining_qty": max(int(requested - filled), 0),
            "average_fill_price": float(average) if filled else None,
        }

    async def place_order(self, order: BrokerOrder) -> dict[str, Any]:
        del order
        if self.mode != "real":
            return _official_block(
                "Toss official Open API has no paper/demo environment.",
                mode="paper_unavailable",
            )
        return _official_block(
            "Toss official live order E2E is not approved in lecture-prism.",
            mode="order_e2e_required",
        )

    async def cancel_order(self, order_id: str, **details) -> dict[str, Any]:
        del order_id, details
        if self.mode != "real":
            return _official_block(
                "Toss official Open API has no paper/demo environment.",
                mode="paper_unavailable",
            )
        return _official_block(
            "Toss official live cancel E2E is not approved in lecture-prism.",
            mode="order_e2e_required",
        )
