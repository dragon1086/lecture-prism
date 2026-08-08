"""KIS domestic-stock adapter with injected client and market gate."""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import (
    DEFAULT_QUOTE_MAX_AGE,
    BrokerOrder,
    BrokerQuote,
    BrokerQuoteError,
    validate_broker_quote,
)
from .config import normalize_mode

_DEFAULT_KIS_CONFIG = Path(__file__).resolve().parents[1] / "trading" / "trading" / "config" / "kis_devlp.yaml"


def _yaml_default_mode(config_path: str | Path | None = None) -> str | None:
    """Read the simple `default_mode: demo|real` line without requiring PyYAML."""

    path = Path(config_path) if config_path else _DEFAULT_KIS_CONFIG
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip() == "default_mode":
            return value.strip().strip('"\'') or None
    return None


def selected_kis_mode(mode: str | None = None, *,
                      config_path: str | Path | None = None) -> str:
    """Resolve KIS mode from explicit args, `.env`, then kis_devlp.yaml."""

    return normalize_mode(
        mode
        or os.getenv("LECTURE_KIS_MODE")
        or os.getenv("KIS_MODE")
        or os.getenv("LECTURE_BROKER_MODE")
        or _yaml_default_mode(config_path),
        default="demo",
    )


class KISBrokerAdapter:
    name = "kis"

    def __init__(
        self,
        *,
        mode: str | None = None,
        client=None,
        gate=None,
        clock=None,
    ) -> None:
        self.mode = selected_kis_mode(mode)
        self._client = client
        self._gate = gate
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _client_dependency(self):
        if self._client is None:
            from .kis_client import KISClient, KISConfig

            config_mode = "paper" if self.mode == "demo" else "real"
            self._client = KISClient(KISConfig.from_env(config_mode))
        return self._client

    def _dependencies(self):
        self._client_dependency()
        if self._gate is None:
            import db
            from market_calendar import MarketGate

            self._gate = MarketGate(
                self._client,
                cache_get=db.get_market_day,
                cache_save=db.save_market_day,
                mode=self.mode,
            )
        return self._client, self._gate

    @staticmethod
    def _blocked(status) -> dict[str, Any]:
        return {
            "success": False,
            "accepted": False,
            "executed": False,
            "terminal": True,
            "status": "blocked",
            "order_no": None,
            "message": f"KIS 주문 차단: {status.reason}",
            "market_status": asdict(status),
        }

    async def place_order(self, order: BrokerOrder) -> dict[str, Any]:
        try:
            client, gate = self._dependencies()
            market_status = await asyncio.to_thread(
                gate.check, self._clock()
            )
        except Exception as exc:  # credentials/calendar uncertainty blocks orders
            return {
                "success": False,
                "accepted": False,
                "executed": False,
                "terminal": True,
                "status": "blocked",
                "mode": f"kis_{self.mode}_calendar_unavailable",
                "order_no": None,
                "message": f"KIS 주문 준비 실패: {exc}",
            }
        if not market_status.order_allowed:
            blocked = self._blocked(market_status)
            blocked["mode"] = f"kis_{self.mode}_{market_status.reason}"
            return blocked
        price = int(order.price or 0)
        try:
            result = await asyncio.to_thread(
                client.place_cash_order,
                order.ticker,
                order.side,
                int(order.quantity),
                price,
            )
        except Exception as exc:  # normalized beginner-readable boundary
            return {
                "success": False,
                "accepted": False,
                "executed": False,
                "terminal": False,
                "status": "unknown",
                "mode": f"kis_{self.mode}_failed",
                "order_no": None,
                "message": f"KIS 주문 결과 불명(재주문 금지): {exc}",
            }
        return {
            **result,
            "success": bool(result.get("accepted")),
            "mode": f"kis_{self.mode}",
            "current_price": price,
            "market_status": asdict(market_status),
        }

    async def get_account(self) -> dict[str, Any]:
        client, _ = self._dependencies()
        return await asyncio.to_thread(client.get_balance)

    async def check_authentication(self) -> dict[str, Any]:
        client = self._client_dependency()
        await asyncio.to_thread(client.authenticate)
        return {"authenticated": True}

    async def get_quote(self, ticker: str) -> BrokerQuote:
        client = self._client_dependency()
        try:
            quote = await asyncio.to_thread(client.get_quote, ticker)
            return validate_broker_quote(
                quote,
                expected_ticker=ticker,
                now=self._clock(),
                max_age=DEFAULT_QUOTE_MAX_AGE,
            )
        except BrokerQuoteError:
            raise
        except Exception as exc:
            raise BrokerQuoteError(f"KIS quote unavailable: {exc}") from exc

    async def get_orderable_quantity(self, ticker: str, price: int) -> int:
        client, _ = self._dependencies()
        return await asyncio.to_thread(
            client.get_orderable_quantity, ticker, int(price)
        )

    async def get_order_status(
        self, order_no: str, *, business_date: str | None = None
    ) -> dict[str, Any]:
        client, _ = self._dependencies()
        from market_calendar import KST

        selected_date = business_date or self._clock().astimezone(KST).strftime(
            "%Y%m%d"
        )
        return await asyncio.to_thread(
            client.get_order_status,
            order_no,
            business_date=selected_date,
        )

    async def get_pending_orders(
        self, *, business_date: str | None = None
    ) -> dict[str, Any]:
        client, _ = self._dependencies()
        from market_calendar import KST

        selected_date = business_date or self._clock().astimezone(KST).strftime(
            "%Y%m%d"
        )
        return await asyncio.to_thread(
            client.get_pending_orders,
            business_date=selected_date,
        )

    async def cancel_order(self, order_no: str, **details) -> dict[str, Any]:
        client, _ = self._dependencies()
        return await asyncio.to_thread(
            client.cancel_order, order_no, **details
        )

    async def is_market_open(self):
        _, gate = self._dependencies()
        return await asyncio.to_thread(gate.check, self._clock())
