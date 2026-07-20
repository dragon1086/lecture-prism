"""Broker adapter contracts for lecture-prism.

The lecture default remains simulation-only. These adapters are intentionally
small teaching wrappers so students can add another broker without rewriting
`trading.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


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


class BrokerAdapter(Protocol):
    """Minimal interface every broker module must implement."""

    name: str
    mode: str

    async def place_order(self, order: BrokerOrder) -> dict[str, Any]:
        """Place an order and return a normalized result dictionary."""


class BrokerConfigError(RuntimeError):
    """Raised when an adapter cannot be configured safely."""
