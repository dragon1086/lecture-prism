from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Mapping, Protocol, Sequence, runtime_checkable

from .domain import Candidate, Instrument, TriggerType
from .market_data import MarketSeries, UniverseMember
from .regime import RegimeResult


_HUNDRED = Decimal("100")


class _InsufficientStockHistory(ValueError):
    """A single universe member lacks enough history for this strategy."""


def _average(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("cannot average an empty sequence")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _return_pct(current: Decimal, previous: Decimal) -> Decimal:
    return (current / previous - Decimal("1")) * _HUNDRED


def _realized_volatility(closes: Sequence[Decimal], periods: int = 20) -> Decimal:
    selected = closes[-(periods + 1) :]
    returns = tuple(
        current / previous - Decimal("1")
        for previous, current in zip(selected, selected[1:])
    )
    mean = _average(returns)
    variance = _average(tuple((value - mean) ** 2 for value in returns))
    with localcontext() as context:
        context.prec = 28
        return variance.sqrt() * Decimal("252").sqrt() * _HUNDRED


class OneilTrendStrategy:
    """Deterministic O'Neil-style trend triggers with separate evidence scores."""

    strategy_id = "oneil_trend_v1"
    supported_triggers = frozenset(TriggerType)

    def evaluate(
        self,
        instrument: Instrument,
        series: MarketSeries,
        benchmark: MarketSeries,
        regime: RegimeResult,
    ) -> tuple[Candidate, ...]:
        _validate_series(instrument, series)
        if benchmark.market is not instrument.market:
            raise ValueError("benchmark market must match instrument market")
        if regime.market is not instrument.market:
            raise ValueError("regime market must match instrument market")
        if len(benchmark.bars) < 21:
            raise ValueError("OneilTrendStrategy requires 21 benchmark sessions")
        if len(series.bars) < 252:
            raise _InsufficientStockHistory(
                "OneilTrendStrategy requires 252 stock sessions"
            )

        closes = tuple(bar.close for bar in series.bars)
        current = closes[-1]
        previous = closes[-2]
        sma20 = _average(closes[-20:])
        sma50 = _average(closes[-50:])
        average_volume20 = _average(
            tuple(bar.volume for bar in series.bars[-21:-1])
        )
        volume_ratio = (
            series.bars[-1].volume / average_volume20
            if average_volume20 > 0
            else Decimal("0")
        )
        high_52w = max(closes[-252:])
        recent_high = max(closes[-20:])
        momentum = _return_pct(current, closes[-21])
        benchmark_momentum = _return_pct(
            benchmark.bars[-1].close,
            benchmark.bars[-21].close,
        )
        latest_return = _return_pct(current, previous)
        relative_strength = momentum - benchmark_momentum
        pullback_depth = (recent_high - current) / recent_high * _HUNDRED
        features = {
            "volume_ratio": volume_ratio,
            "price_vs_sma20_pct": _return_pct(current, sma20),
            "price_vs_sma50_pct": _return_pct(current, sma50),
            "high_52w_distance_pct": _return_pct(current, high_52w),
            "relative_strength_pct": relative_strength,
            "momentum_pct": momentum,
            "volatility_pct": _realized_volatility(closes),
            "pullback_depth_pct": pullback_depth,
            "latest_return_pct": latest_return,
        }

        triggers: list[tuple[TriggerType, dict[str, Decimal], Decimal]] = []
        if current >= max(closes[-21:-1]) and volume_ratio >= Decimal("1.5"):
            triggers.append(
                (
                    TriggerType.BREAKOUT,
                    {"breakout": Decimal("4"), "trend": Decimal("3"), "volume": Decimal("2")},
                    Decimal("7"),
                )
            )
        if (
            current > sma50
            and Decimal("2") <= pullback_depth <= Decimal("8")
            and latest_return > 0
        ):
            triggers.append(
                (
                    TriggerType.PULLBACK,
                    {"trend": Decimal("4"), "pullback": Decimal("3"), "rebound": Decimal("2")},
                    Decimal("6"),
                )
            )
        if volume_ratio >= Decimal("1.5") and latest_return > 0:
            triggers.append(
                (
                    TriggerType.VOLUME_SURGE,
                    {"volume": Decimal("5"), "price": Decimal("2"), "trend": Decimal("1")},
                    Decimal("7"),
                )
            )
        if relative_strength >= Decimal("3") and current > sma50:
            triggers.append(
                (
                    TriggerType.RELATIVE_STRENGTH,
                    {"relative_strength": Decimal("5"), "trend": Decimal("3")},
                    Decimal("6"),
                )
            )
        if pullback_depth >= Decimal("8") and latest_return > 0:
            triggers.append(
                (
                    TriggerType.OVERSOLD_REBOUND,
                    {"oversold": Decimal("5"), "rebound": Decimal("3")},
                    Decimal("5"),
                )
            )

        return tuple(
            self._candidate(
                instrument,
                regime,
                trigger,
                features,
                scores,
                stop_pct,
                current,
            )
            for trigger, scores, stop_pct in triggers
        )

    def _candidate(
        self,
        instrument: Instrument,
        regime: RegimeResult,
        trigger: TriggerType,
        features: Mapping[str, Decimal],
        scores: Mapping[str, Decimal],
        stop_pct: Decimal,
        reference: Decimal,
    ) -> Candidate:
        quantum = Decimal("1").scaleb(-instrument.price_precision)
        risk = reference * stop_pct / _HUNDRED
        stop = (reference - risk).quantize(quantum, rounding=ROUND_HALF_UP)
        target = (reference + risk * Decimal("2")).quantize(
            quantum, rounding=ROUND_HALF_UP
        )
        risk_reward = (target - reference) / (reference - stop)
        return Candidate(
            instrument=instrument,
            as_of=regime.as_of,
            trigger_type=trigger,
            regime=regime.regime,
            feature_values=features,
            component_scores=scores,
            final_score=min(Decimal("10"), sum(scores.values(), Decimal("0"))),
            reference_price=reference,
            stop_price=stop,
            target_price=target,
            risk_reward_ratio=risk_reward,
            source=self.strategy_id,
        )


@runtime_checkable
class ScreeningStrategy(Protocol):
    strategy_id: str
    supported_triggers: frozenset[TriggerType]

    def evaluate(
        self,
        instrument: Instrument,
        series: MarketSeries,
        benchmark: MarketSeries,
        regime: RegimeResult,
    ) -> tuple[Candidate, ...]: ...


def _validate_series(instrument: Instrument, series: MarketSeries) -> None:
    if not isinstance(series, MarketSeries):
        raise ValueError("series must be a MarketSeries")
    if (
        series.market is not instrument.market
        or series.symbol != instrument.symbol
        or series.currency != instrument.currency
        or series.price_precision != instrument.price_precision
    ):
        raise ValueError("series must match instrument market, currency, and symbol")


def _validate_strategy(strategy: object) -> None:
    strategy_id = getattr(strategy, "strategy_id", None)
    if not isinstance(strategy_id, str) or not strategy_id.strip():
        raise ValueError("strategy_id must be a non-empty string")
    supported_triggers = getattr(strategy, "supported_triggers", None)
    if (
        type(supported_triggers) is not frozenset
        or not supported_triggers
        or not all(isinstance(trigger, TriggerType) for trigger in supported_triggers)
    ):
        raise ValueError(
            "supported_triggers must be a non-empty frozenset of TriggerType"
        )
    if not callable(getattr(strategy, "evaluate", None)):
        raise ValueError("strategy evaluate must be callable")


def screen_candidates(
    universe: tuple[UniverseMember, ...],
    series_by_instrument: Mapping[Instrument, MarketSeries],
    benchmark: MarketSeries,
    regime: RegimeResult,
    *,
    strategy: ScreeningStrategy,
) -> tuple[Candidate, ...]:
    """Evaluate an injected strategy and return a deterministic candidate rank."""

    _validate_strategy(strategy)
    if not isinstance(regime, RegimeResult):
        raise ValueError("regime must be a RegimeResult")
    if not isinstance(benchmark, MarketSeries):
        raise ValueError("benchmark must be a MarketSeries")
    if benchmark.market is not regime.market:
        raise ValueError("benchmark market must match regime market")
    if not isinstance(universe, tuple):
        raise ValueError("universe must be a tuple")
    if not isinstance(series_by_instrument, Mapping):
        raise ValueError("series_by_instrument must be a mapping")

    candidates: list[Candidate] = []
    for member in universe:
        if not isinstance(member, UniverseMember):
            raise ValueError("universe must contain UniverseMember values")
        instrument = member.instrument
        if instrument.market is not regime.market:
            raise ValueError("universe instrument market must match regime market")
        try:
            series = series_by_instrument[instrument]
        except KeyError as exc:
            raise ValueError("missing series for universe instrument") from exc
        _validate_series(instrument, series)

        try:
            evaluated = strategy.evaluate(instrument, series, benchmark, regime)
        except _InsufficientStockHistory:
            continue
        if not isinstance(evaluated, tuple):
            raise ValueError("strategy evaluate must return a tuple")
        for candidate in evaluated:
            if not isinstance(candidate, Candidate):
                raise ValueError("strategy must return Candidate values")
            if candidate.instrument != instrument:
                raise ValueError(
                    "candidate must match instrument market, currency, and symbol"
                )
            if candidate.regime is not regime.regime:
                raise ValueError("candidate regime must match screening regime")
            if candidate.as_of != regime.as_of:
                raise ValueError("candidate as_of must match screening regime")
            if candidate.trigger_type not in strategy.supported_triggers:
                raise ValueError("candidate trigger is not supported by strategy")
            candidates.append(candidate)

    identities = sorted(
        (
            candidate.instrument.market.value,
            candidate.instrument.symbol,
            candidate.trigger_type.value,
        )
        for candidate in candidates
    )
    for previous, current in zip(identities, identities[1:]):
        if current == previous:
            raise ValueError(
                "duplicate candidate identity: " + ":".join(current)
            )

    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                -candidate.final_score,
                candidate.instrument.symbol,
                candidate.trigger_type.value,
            ),
        )
    )
