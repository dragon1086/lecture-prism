"""Broker adapter contracts for lecture-prism.

The lecture default remains simulation-only. These adapters are intentionally
small teaching wrappers so students can add another broker without rewriting
`trading.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import os
from typing import Any, Iterable, Protocol


DEFAULT_QUOTE_MAX_AGE = timedelta(minutes=5)


@dataclass(frozen=True)
class BrokerOrder:
    """Normalized order request passed from `trading.py` to a broker adapter."""

    action: str
    ticker: str
    quantity: int
    price: int | float | None = None
    reason: str = ""
    client_order_id: str | None = None

    @property
    def side(self) -> str:
        return str(self.action).strip().upper()


@dataclass(frozen=True)
class BrokerQuote:
    """Fresh broker-sourced price used for paper/live trading decisions."""

    ticker: str
    price: int | float
    currency: str
    market: str
    observed_at: datetime
    source: str


class BrokerQuoteError(RuntimeError):
    """Raised when a broker quote is missing, stale, or unsafe to use."""


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def real_mode_mutation_block(
    broker_name: str,
    mode: str,
    *,
    mode_prefix: str | None = None,
) -> dict[str, Any] | None:
    """Return a fail-closed result unless real-money mutation gates are set.

    Read-only broker methods use their own readiness checks. This guard is only
    for direct place/cancel boundaries that can mutate a real account.
    """

    if str(mode).strip().lower() != "real":
        return None
    broker = str(broker_name).strip().upper()
    enabled = any(
        _truthy(os.getenv(key))
        for key in ("LECTURE_ENABLE_LIVE_BROKER", f"LECTURE_ENABLE_LIVE_{broker}")
    )
    allowed = any(
        _truthy(os.getenv(key))
        for key in ("LECTURE_ALLOW_REAL_BROKER", f"LECTURE_ALLOW_REAL_{broker}")
    )
    if enabled and allowed:
        return None
    prefix = mode_prefix or str(broker_name).strip().lower()
    return {
        "success": False,
        "status": "blocked",
        "accepted": False,
        "executed": False,
        "terminal": True,
        "mode": f"{prefix}_real_live_gate_blocked",
        "order_no": None,
        "message": (
            f"{prefix} real mutation blocked: set "
            f"LECTURE_ENABLE_LIVE_BROKER=1 and "
            f"LECTURE_ALLOW_REAL_BROKER=1, or the matching "
            f"broker-specific live gates, before direct place/cancel calls."
        ),
    }


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise BrokerQuoteError("quote observed_at must be a datetime")
    if value.tzinfo is None:
        raise BrokerQuoteError("quote observed_at must include timezone")
    return value.astimezone(timezone.utc)


def validate_broker_quote(
    quote: BrokerQuote,
    *,
    expected_ticker: str,
    now: datetime | None = None,
    max_age: timedelta = DEFAULT_QUOTE_MAX_AGE,
    allowed_markets: Iterable[str] = ("KRX", "KR"),
) -> BrokerQuote:
    """Validate the shared quote contract for domestic broker execution paths."""

    if not isinstance(quote, BrokerQuote):
        raise BrokerQuoteError("broker quote must be a BrokerQuote")
    expected = str(expected_ticker).strip()
    if not expected or str(quote.ticker).strip() != expected:
        raise BrokerQuoteError(
            f"quote ticker mismatch: expected {expected}, got {quote.ticker}"
        )
    if str(quote.currency).strip().upper() != "KRW":
        raise BrokerQuoteError(f"unsupported quote currency: {quote.currency}")
    market = str(quote.market).strip().upper()
    if market not in {str(item).strip().upper() for item in allowed_markets}:
        raise BrokerQuoteError(f"unsupported quote market: {quote.market}")
    try:
        price = Decimal(str(quote.price))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BrokerQuoteError("quote price must be numeric") from exc
    if price <= 0:
        raise BrokerQuoteError("quote price must be positive")
    if price != price.to_integral_value():
        raise BrokerQuoteError("KRW domestic quote price must be integral")

    observed_at = _utc(quote.observed_at)
    checked_at = _utc(now or datetime.now(timezone.utc))
    if checked_at - observed_at > max_age:
        raise BrokerQuoteError("quote is stale")
    if observed_at - checked_at > timedelta(seconds=5):
        raise BrokerQuoteError("quote timestamp is in the future")
    if not str(quote.source).strip():
        raise BrokerQuoteError("quote source is required")
    return quote


class BrokerAdapter(Protocol):
    """Minimal interface every broker module must implement."""

    name: str
    mode: str

    async def place_order(self, order: BrokerOrder) -> dict[str, Any]:
        """Place an order and return a normalized result dictionary."""

    async def get_quote(self, ticker: str) -> BrokerQuote:
        """Return a fresh broker-sourced quote for a domestic ticker."""


class BrokerConfigError(RuntimeError):
    """Raised when an adapter cannot be configured safely."""
