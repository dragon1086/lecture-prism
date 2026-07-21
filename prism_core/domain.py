from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class Market(str, Enum):
    KR = "KR"
    US = "US"


class Regime(str, Enum):
    STRONG_BULL = "strong_bull"
    MODERATE_BULL = "moderate_bull"
    SIDEWAYS = "sideways"
    MODERATE_BEAR = "moderate_bear"
    STRONG_BEAR = "strong_bear"


class TriggerType(str, Enum):
    BREAKOUT = "breakout"
    PULLBACK = "pullback"
    VOLUME_SURGE = "volume_surge"
    RELATIVE_STRENGTH = "relative_strength"
    OVERSOLD_REBOUND = "oversold_rebound"


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


@dataclass(frozen=True)
class Candidate:
    instrument: Instrument
    as_of: datetime
    trigger_type: TriggerType
    regime: Regime
    feature_values: Mapping[str, Decimal | str | bool]
    component_scores: Mapping[str, Decimal]
    final_score: Decimal
    reference_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    risk_reward_ratio: Decimal
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise ValueError("instrument must be an Instrument")
        if (
            not isinstance(self.as_of, datetime)
            or self.as_of.tzinfo is None
            or self.as_of.utcoffset() is None
        ):
            raise ValueError("as_of must be a timezone-aware datetime")
        if not isinstance(self.trigger_type, TriggerType):
            raise ValueError("trigger_type must be a TriggerType")
        if not isinstance(self.regime, Regime):
            raise ValueError("regime must be a Regime")
        if not isinstance(self.feature_values, Mapping):
            raise ValueError("feature_values must be a mapping")
        features: dict[str, Decimal | str | bool] = {}
        for key, value in self.feature_values.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("feature keys must be non-empty strings")
            if not isinstance(value, (Decimal, str, bool)):
                raise ValueError("feature values must be Decimal, str, or bool")
            if isinstance(value, Decimal) and not value.is_finite():
                raise ValueError("Decimal feature values must be finite")
            features[key] = value
        object.__setattr__(self, "feature_values", MappingProxyType(features))

        if not isinstance(self.component_scores, Mapping):
            raise ValueError("component_scores must be a mapping")
        components: dict[str, Decimal] = {}
        for key, value in self.component_scores.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("component score keys must be non-empty strings")
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value < 0
            ):
                raise ValueError(
                    "component scores must be finite non-negative Decimals"
                )
            components[key] = value
        object.__setattr__(
            self, "component_scores", MappingProxyType(components)
        )

        if (
            not isinstance(self.final_score, Decimal)
            or not self.final_score.is_finite()
            or self.final_score < 0
            or self.final_score > 10
        ):
            raise ValueError("final_score must be a finite Decimal between 0 and 10")
        price_quantum = Decimal("1").scaleb(-self.instrument.price_precision)
        for name in (
            "reference_price",
            "stop_price",
            "target_price",
            "risk_reward_ratio",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive Decimal")
            if name != "risk_reward_ratio" and value != value.quantize(price_quantum):
                raise ValueError(
                    f"{name} must match instrument price_precision"
                )
        if self.stop_price >= self.reference_price:
            raise ValueError("stop_price must be below reference_price")
        if self.target_price <= self.reference_price:
            raise ValueError("target_price must be above reference_price")
        derived_ratio = (self.target_price - self.reference_price) / (
            self.reference_price - self.stop_price
        )
        if abs(self.risk_reward_ratio - derived_ratio) > Decimal("0.01"):
            raise ValueError("risk_reward_ratio must match prices within 0.01")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source is required")
        object.__setattr__(self, "source", self.source.strip())


@dataclass(frozen=True)
class RegimePolicy:
    active_triggers: frozenset[TriggerType]
    minimum_candidate_score: Decimal
    minimum_analysis_score: Decimal
    minimum_risk_reward: Decimal
    maximum_stop_pct: Decimal
    account_risk_pct: Decimal
    maximum_slots: int
    minimum_cash_pct: Decimal
    trailing_pct: Decimal

    def __post_init__(self) -> None:
        if (
            not isinstance(self.active_triggers, frozenset)
            or not self.active_triggers
            or not all(
                isinstance(trigger, TriggerType)
                for trigger in self.active_triggers
            )
        ):
            raise ValueError(
                "active_triggers must be a non-empty frozenset of TriggerType"
            )
        non_negative = (
            "minimum_candidate_score",
            "minimum_analysis_score",
            "minimum_cash_pct",
        )
        positive = (
            "minimum_risk_reward",
            "maximum_stop_pct",
            "account_risk_pct",
            "trailing_pct",
        )
        for name in non_negative + positive:
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name} must be a finite Decimal")
            if name in non_negative and value < 0:
                raise ValueError(f"{name} must be non-negative")
            if name in positive and value <= 0:
                raise ValueError(f"{name} must be positive")
        if (
            not isinstance(self.maximum_slots, int)
            or isinstance(self.maximum_slots, bool)
            or self.maximum_slots <= 0
        ):
            raise ValueError("maximum_slots must be a positive integer")


@dataclass(frozen=True)
class EntryDecision:
    candidate: Candidate
    allowed: bool
    analysis_score: Decimal
    reasons: tuple[str, ...]
    policy: RegimePolicy

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, Candidate):
            raise ValueError("candidate must be a Candidate")
        if not isinstance(self.allowed, bool):
            raise ValueError("allowed must be a bool")
        if (
            not isinstance(self.analysis_score, Decimal)
            or not self.analysis_score.is_finite()
            or self.analysis_score < 0
        ):
            raise ValueError(
                "analysis_score must be a finite non-negative Decimal"
            )
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(reason, str) and reason for reason in self.reasons
        ):
            raise ValueError("reasons must be a tuple of non-empty strings")
        if not isinstance(self.policy, RegimePolicy):
            raise ValueError("policy must be a RegimePolicy")


@dataclass(frozen=True)
class EntryContext:
    client_order_id: str
    run_id: str
    candidate: Candidate
    strategy_id: str
    policy: RegimePolicy

    def __post_init__(self) -> None:
        for name in ("client_order_id", "run_id", "strategy_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value.strip())
        if not isinstance(self.candidate, Candidate):
            raise ValueError("candidate must be a Candidate")
        if not isinstance(self.policy, RegimePolicy):
            raise ValueError("policy must be a RegimePolicy")


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
