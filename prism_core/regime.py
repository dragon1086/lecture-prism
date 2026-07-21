from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Sequence

from .domain import Market, Regime
from .market_data import DailyBar, IndexBundle, MarketSeries


class InsufficientMarketHistory(ValueError):
    """A requested market calculation does not have enough observations."""


class PulseState(str, Enum):
    UPTREND = "UPTREND"
    UNDER_PRESSURE = "UNDER_PRESSURE"
    CORRECTION = "CORRECTION"


@dataclass(frozen=True)
class RegimeResult:
    market: Market
    as_of: datetime
    regime: Regime
    confidence: Decimal
    pulse: PulseState
    metrics: Mapping[str, Decimal | str | int]
    reasons: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.market, Market):
            raise ValueError("market must be a Market")
        if (
            not isinstance(self.as_of, datetime)
            or self.as_of.tzinfo is None
            or self.as_of.utcoffset() is None
        ):
            raise ValueError("as_of must be a timezone-aware datetime")
        if not isinstance(self.regime, Regime):
            raise ValueError("regime must be a Regime")
        if (
            not isinstance(self.confidence, Decimal)
            or not self.confidence.is_finite()
            or not Decimal("0") <= self.confidence <= Decimal("1")
        ):
            raise ValueError("confidence must be a finite Decimal from 0 to 1")
        if not isinstance(self.pulse, PulseState):
            raise ValueError("pulse must be a PulseState")
        if not isinstance(self.metrics, Mapping):
            raise ValueError("metrics must be a mapping")
        normalized_metrics: dict[str, Decimal | str | int] = {}
        for key, value in self.metrics.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("metric keys must be non-empty strings")
            if isinstance(value, bool) or not isinstance(
                value, (Decimal, str, int)
            ):
                raise ValueError(
                    "metric values must be Decimal, str, or non-boolean int"
                )
            if isinstance(value, Decimal) and not value.is_finite():
                raise ValueError("Decimal metric values must be finite")
            normalized_metrics[key] = value
        object.__setattr__(
            self, "metrics", MappingProxyType(normalized_metrics)
        )
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(reason, str) and reason for reason in self.reasons
        ):
            raise ValueError("reasons must be a tuple of non-empty strings")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source is required")
        object.__setattr__(self, "source", self.source.strip())


def _window(
    bars: Sequence[DailyBar], periods: int, *, transitions: bool = False
) -> tuple[DailyBar, ...]:
    if not isinstance(periods, int) or isinstance(periods, bool) or periods <= 0:
        raise ValueError("periods must be a positive integer")
    required = periods + 1 if transitions else periods
    if len(bars) < required:
        raise InsufficientMarketHistory(
            f"requires {required} sessions but received {len(bars)}"
        )
    return tuple(bars[-required:])


def _sma(bars: Sequence[DailyBar], periods: int) -> Decimal:
    selected = _window(bars, periods)
    with localcontext() as context:
        context.prec = 28
        return sum((bar.close for bar in selected), Decimal("0")) / Decimal(periods)


def _return_pct(bars: Sequence[DailyBar], periods: int) -> Decimal:
    selected = _window(bars, periods, transitions=True)
    with localcontext() as context:
        context.prec = 28
        return (selected[-1].close / selected[0].close - Decimal("1")) * Decimal("100")


def _realized_volatility(bars: Sequence[DailyBar], periods: int) -> Decimal:
    selected = _window(bars, periods, transitions=True)
    with localcontext() as context:
        context.prec = 28
        returns = tuple(
            current.close / previous.close - Decimal("1")
            for previous, current in zip(selected, selected[1:])
        )
        mean = sum(returns, Decimal("0")) / Decimal(periods)
        variance = sum(
            ((daily_return - mean) ** 2 for daily_return in returns),
            Decimal("0"),
        ) / Decimal(periods)
        return variance.sqrt() * Decimal("252").sqrt() * Decimal("100")


def _drawdown(bars: Sequence[DailyBar], periods: int) -> Decimal:
    selected = _window(bars, periods)
    peak = max(bar.close for bar in selected)
    with localcontext() as context:
        context.prec = 28
        return (peak - selected[-1].close) / peak * Decimal("100")


def _distribution_days(bars: Sequence[DailyBar], periods: int) -> int:
    selected = _window(bars, periods, transitions=True)
    return sum(
        current.close < previous.close and current.volume > previous.volume
        for previous, current in zip(selected, selected[1:])
    )


def _breadth_state(ratio: Decimal | None) -> str:
    if ratio is None:
        return "unavailable"
    if (
        not isinstance(ratio, Decimal)
        or not ratio.is_finite()
        or not Decimal("0") <= ratio <= Decimal("1")
    ):
        raise ValueError("breadth ratio must be a finite Decimal from 0 to 1")
    if ratio >= Decimal("0.55"):
        return "broad"
    if ratio <= Decimal("0.45"):
        return "weak"
    return "neutral"


def _pulse_state(distribution_days: int, drawdown: Decimal) -> PulseState:
    if distribution_days >= 6 or drawdown >= Decimal("8"):
        return PulseState.CORRECTION
    if distribution_days >= 4:
        return PulseState.UNDER_PRESSURE
    return PulseState.UPTREND


@dataclass(frozen=True)
class RegimeThresholds:
    primary_ma: int
    secondary_ma: int
    momentum_days: int
    strong_bull_return: Decimal
    strong_bear_return: Decimal


_REGIME_THRESHOLDS = MappingProxyType(
    {
        Market.KR: RegimeThresholds(
            primary_ma=120,
            secondary_ma=60,
            momentum_days=10,
            strong_bull_return=Decimal("5"),
            strong_bear_return=Decimal("-5"),
        ),
        Market.US: RegimeThresholds(
            primary_ma=200,
            secondary_ma=50,
            momentum_days=20,
            strong_bull_return=Decimal("3"),
            strong_bear_return=Decimal("-5"),
        ),
    }
)

_CONFIDENCE = MappingProxyType(
    {
        Regime.STRONG_BULL: Decimal("0.90"),
        Regime.MODERATE_BULL: Decimal("0.75"),
        Regime.SIDEWAYS: Decimal("0.60"),
        Regime.MODERATE_BEAR: Decimal("0.75"),
        Regime.STRONG_BEAR: Decimal("0.90"),
    }
)


def _bars_as_of(series: MarketSeries, as_of: datetime) -> tuple[DailyBar, ...]:
    return tuple(bar for bar in series.bars if bar.session_date <= as_of.date())


def _classify_table(
    *,
    market: Market,
    close: Decimal,
    primary_ma: Decimal,
    secondary_ma: Decimal,
    momentum: Decimal,
    secondary_above_primary: bool,
    breadth: str,
    vix: Decimal | None,
    thresholds: RegimeThresholds,
) -> tuple[Regime, tuple[str, ...]]:
    if close > primary_ma:
        reasons = ["above_primary_ma"]
        if close >= secondary_ma:
            reasons.append("above_secondary_ma")
        if (
            close >= secondary_ma
            and momentum >= thresholds.strong_bull_return
            and secondary_above_primary
            and breadth != "weak"
            and (market is Market.KR or (vix is not None and vix < Decimal("20")))
        ):
            reasons.append("strong_positive_momentum")
            return Regime.STRONG_BULL, tuple(reasons)
        if close >= secondary_ma and momentum > 0:
            reasons.append("positive_momentum")
            return Regime.MODERATE_BULL, tuple(reasons)
        reasons.append("bull_confirmation_missing")
        return Regime.SIDEWAYS, tuple(reasons)

    if close < primary_ma:
        reasons = ["below_primary_ma"]
        if close <= secondary_ma:
            reasons.append("below_secondary_ma")
        strong_bear_confirmed = (
            close <= secondary_ma
            and momentum <= thresholds.strong_bear_return
            and not secondary_above_primary
            and (market is Market.KR or (vix is not None and vix >= Decimal("20")))
        )
        if strong_bear_confirmed:
            reasons.append("strong_negative_momentum")
            return Regime.STRONG_BEAR, tuple(reasons)
        if close <= secondary_ma and momentum < 0:
            reasons.append("negative_momentum")
            return Regime.MODERATE_BEAR, tuple(reasons)
        reasons.append("bear_rally_below_primary_ma")
        return Regime.SIDEWAYS, tuple(reasons)

    return Regime.SIDEWAYS, ("at_primary_ma",)


def classify_market_regime(bundle: IndexBundle, *, as_of: datetime) -> RegimeResult:
    """Classify a supplied index snapshot without consulting external state."""

    if not isinstance(bundle, IndexBundle):
        raise ValueError("bundle must be an IndexBundle")
    if (
        not isinstance(as_of, datetime)
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        raise ValueError("as_of must be a timezone-aware datetime")

    market = bundle.primary.market
    thresholds = _REGIME_THRESHOLDS[market]
    primary_bars = _bars_as_of(bundle.primary, as_of)
    secondary_bars = _bars_as_of(bundle.secondary, as_of)

    close = primary_bars[-1].close if primary_bars else Decimal("0")
    primary_average = _sma(primary_bars, thresholds.primary_ma)
    secondary_average = _sma(primary_bars, thresholds.secondary_ma)
    momentum = _return_pct(primary_bars, thresholds.momentum_days)
    secondary_index_average = _sma(secondary_bars, thresholds.primary_ma)
    secondary_index_close = secondary_bars[-1].close
    secondary_above_primary = secondary_index_close > secondary_index_average
    realized_volatility = _realized_volatility(primary_bars, 20)
    drawdown = _drawdown(primary_bars, 50)
    distribution_days = _distribution_days(primary_bars, 25)
    breadth = _breadth_state(bundle.breadth_ratio)
    vix = None
    if bundle.volatility is not None:
        volatility_bars = _bars_as_of(bundle.volatility, as_of)
        if not volatility_bars:
            raise InsufficientMarketHistory(
                "volatility series has no observation at as_of"
            )
        vix = volatility_bars[-1].close

    regime, reasons = _classify_table(
        market=market,
        close=close,
        primary_ma=primary_average,
        secondary_ma=secondary_average,
        momentum=momentum,
        secondary_above_primary=secondary_above_primary,
        breadth=breadth,
        vix=vix,
        thresholds=thresholds,
    )

    high_volatility = realized_volatility >= Decimal("30") or (
        vix is not None and vix >= Decimal("30")
    )
    if (
        regime in {Regime.STRONG_BULL, Regime.MODERATE_BULL}
        and high_volatility
        and drawdown >= Decimal("8")
    ):
        regime = Regime.SIDEWAYS
        reasons = reasons + ("high_vol_drawdown",)

    pulse = _pulse_state(distribution_days, drawdown)

    metrics: dict[str, Decimal | str | int] = {
        "close": close,
        "primary_ma": primary_average,
        "primary_ma_period": thresholds.primary_ma,
        "secondary_ma": secondary_average,
        "secondary_ma_period": thresholds.secondary_ma,
        "momentum_pct": momentum,
        "momentum_days": thresholds.momentum_days,
        "realized_volatility_pct": realized_volatility,
        "drawdown_pct": drawdown,
        "distribution_days": distribution_days,
        "breadth": breadth,
        "secondary_index_close": secondary_index_close,
        "secondary_index_primary_ma": secondary_index_average,
        "secondary_index_above_primary": int(secondary_above_primary),
    }
    if vix is not None:
        metrics["vix"] = vix

    return RegimeResult(
        market=market,
        as_of=as_of,
        regime=regime,
        confidence=_CONFIDENCE[regime],
        pulse=pulse,
        metrics=metrics,
        reasons=reasons,
        source=bundle.primary.source,
    )
