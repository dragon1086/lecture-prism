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


class PositionFillConflict(ValueError):
    """A SELL fill conflicts with the persisted position."""

    def __init__(self, market: Market, symbol: str, reason: str):
        self.market = market
        self.symbol = symbol
        self.reason = reason
        messages = {
            "missing": "cannot sell a missing position",
            "quantity_changed": "sell quantity exceeds position",
            "strategy_changed": "sell strategy does not own position",
        }
        message = messages.get(reason, "sell conflicts with position")
        super().__init__(message)


class PositionEntryConflict(ValueError):
    """A BUY fill is not owned by the position's original entry order."""


def validate_market_contract(
    market: Market,
    symbol: str,
    *,
    currency: str | None = None,
    quantity: Decimal | None = None,
    price: Decimal | None = None,
    quantity_name: str = "quantity",
    price_name: str = "price",
) -> str | None:
    """Validate values without guessing a market from the symbol."""

    if not isinstance(market, Market):
        raise ValueError("market must be a Market")
    if not isinstance(symbol, str):
        raise ValueError("symbol is required")
    if market is Market.KR:
        if len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
            raise ValueError("KR symbol must be exactly six ASCII digits")
    elif (
        not symbol
        or not symbol.isascii()
        or not symbol.isalpha()
        or not symbol.isupper()
    ):
        raise ValueError("US symbol must contain uppercase ASCII letters only")

    normalized_currency = None
    if currency is not None:
        if not isinstance(currency, str):
            raise ValueError("currency is required")
        normalized_currency = currency.strip().upper()
        expected_currency = "KRW" if market is Market.KR else "USD"
        if normalized_currency != expected_currency:
            raise ValueError(
                f"{market.value} order currency must be {expected_currency}"
            )

    for name, value in ((quantity_name, quantity), (price_name, price)):
        if value is None:
            continue
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError(f"{name} must be a finite Decimal")
        if market is Market.KR and value != value.to_integral_value():
            raise ValueError(f"KR {name} must be a whole number")
    return normalized_currency


@dataclass(frozen=True)
class Instrument:
    """A tradeable instrument with an explicit market and settlement contract."""

    symbol: str
    market: Market
    exchange: str
    currency: str
    name: str
    sector: str
    lot_size: Decimal
    price_precision: int

    def __post_init__(self) -> None:
        if not isinstance(self.lot_size, Decimal) or not self.lot_size.is_finite():
            raise ValueError("lot_size must be a finite Decimal")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")
        currency = validate_market_contract(
            self.market,
            self.symbol,
            currency=self.currency,
            quantity=self.lot_size,
            quantity_name="lot_size",
        )
        for field_name in ("exchange", "name", "sector"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")
            object.__setattr__(self, field_name, value.strip())
        if not isinstance(self.price_precision, int) or isinstance(
            self.price_precision, bool
        ) or self.price_precision < 0:
            raise ValueError("price_precision must be a non-negative integer")
        if self.market is Market.KR and self.price_precision != 0:
            raise ValueError("KR price_precision must be 0")
        object.__setattr__(self, "currency", currency)


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
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        currency = validate_market_contract(
            self.market,
            self.symbol,
            currency=self.currency,
            quantity=self.quantity,
            price=self.limit_price,
            price_name="limit_price",
        )
        object.__setattr__(self, "currency", currency)
        if self.order_type is OrderType.LIMIT and (self.limit_price is None or self.limit_price <= 0):
            raise ValueError("limit order requires a positive limit_price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market order requires limit_price=None")


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
    entry_client_order_id: str | None = None
