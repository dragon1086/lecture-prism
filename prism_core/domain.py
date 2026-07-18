from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Market(str, Enum):
    KR = "KR"
    US = "US"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PREVIEWED = "PREVIEWED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"
    UNKNOWN = "UNKNOWN"


_TRANSITIONS = {
    OrderStatus.CREATED: {OrderStatus.PREVIEWED, OrderStatus.REJECTED},
    OrderStatus.PREVIEWED: {OrderStatus.SUBMITTED, OrderStatus.REJECTED},
    OrderStatus.SUBMITTED: {OrderStatus.ACCEPTED, OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.UNKNOWN},
    OrderStatus.ACCEPTED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.UNKNOWN},
    OrderStatus.PARTIALLY_FILLED: {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.UNKNOWN},
    OrderStatus.UNKNOWN: {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED},
    OrderStatus.FILLED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.CANCELED: set(),
}


def validate_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in _TRANSITIONS[current]


@dataclass(frozen=True)
class OrderIntent:
    client_order_id: str
    market: Market
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None
    currency: str
    strategy_id: str = "default_oneil"
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.market, Market):
            raise ValueError("market must be a Market")
        if not isinstance(self.side, OrderSide):
            raise ValueError("side must be an OrderSide")
        if not isinstance(self.order_type, OrderType):
            raise ValueError("order_type must be an OrderType")
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite():
            raise ValueError("quantity must be a finite Decimal")
        if self.limit_price is not None and (
            not isinstance(self.limit_price, Decimal) or not self.limit_price.is_finite()
        ):
            raise ValueError("limit_price must be a finite Decimal")
        if not self.client_order_id.strip():
            raise ValueError("client_order_id is required")
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        currency = self.currency.strip().upper()
        object.__setattr__(self, "currency", currency)
        if self.market is Market.KR:
            if currency != "KRW":
                raise ValueError("KR order currency must be KRW")
            if self.quantity != self.quantity.to_integral_value():
                raise ValueError("KR quantity must be a whole number")
        if self.market is Market.US and currency != "USD":
            raise ValueError("US order currency must be USD")
        if self.order_type is OrderType.LIMIT and (self.limit_price is None or self.limit_price <= 0):
            raise ValueError("limit order requires a positive limit_price")


@dataclass(frozen=True)
class OrderRecord:
    intent: OrderIntent
    status: OrderStatus
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Decimal | None = None


@dataclass(frozen=True)
class Fill:
    fill_id: str
    client_order_id: str
    market: Market
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    currency: str


@dataclass(frozen=True)
class Position:
    market: Market
    symbol: str
    quantity: Decimal
    average_price: Decimal
    currency: str
    high_since_entry: Decimal
    strategy_id: str
