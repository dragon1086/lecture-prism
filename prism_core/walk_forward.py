from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from statistics import median
from types import MappingProxyType
from typing import Callable, Mapping

from .domain import Instrument, Market, Regime, RegimePolicy, TriggerType
from .market_data import IndexBundle, MarketSeries, UniverseMember
from .policy import gate_entry, policy_for
from .regime import classify_market_regime
from .screening import OneilTrendStrategy, ScreeningStrategy, screen_candidates


HistoricalMarketData = Mapping[
    Market,
    tuple[
        IndexBundle,
        tuple[UniverseMember, ...],
        Mapping[Instrument, MarketSeries],
    ],
]


@dataclass(frozen=True)
class WalkForwardConfig:
    warmup_sessions: int = 220
    evaluation_sessions: int = 63
    step_sessions: int = 21
    maximum_holding_sessions: int = 60
    slippage_bps: Decimal = Decimal("10")
    minimum_samples: int = 30

    def __post_init__(self) -> None:
        for name in (
            "warmup_sessions",
            "evaluation_sessions",
            "step_sessions",
            "maximum_holding_sessions",
            "minimum_samples",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            not isinstance(self.slippage_bps, Decimal)
            or not self.slippage_bps.is_finite()
            or self.slippage_bps < 0
            or self.slippage_bps >= Decimal("10000")
        ):
            raise ValueError("slippage_bps must be a finite Decimal below 10000")


@dataclass(frozen=True)
class TradeSample:
    market: Market
    symbol: str
    regime: Regime
    strategy_id: str
    trigger_type: TriggerType
    entry_date: date
    exit_date: date
    entry_price: Decimal
    exit_price: Decimal
    return_pct: Decimal
    mfe_pct: Decimal
    mae_pct: Decimal
    exit_reason: str
    holding_sessions: int


@dataclass(frozen=True)
class SegmentMetrics:
    market: Market
    regime: Regime
    strategy_id: str
    trigger_type: TriggerType
    sample_count: int
    win_rate: Decimal
    mean_return_pct: Decimal
    median_return_pct: Decimal
    mean_mfe_pct: Decimal
    mean_mae_pct: Decimal
    stop_count: int
    mean_holding_sessions: Decimal
    maximum_losing_streak: int
    policy_change_allowed: bool
    status: str


@dataclass(frozen=True)
class WalkForwardReport:
    config: WalkForwardConfig
    samples: tuple[TradeSample, ...]
    segments: tuple[SegmentMetrics, ...]
    comparison_deltas: Mapping[
        tuple[Market, Regime, str, TriggerType], Decimal
    ]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "comparison_deltas",
            MappingProxyType(dict(self.comparison_deltas)),
        )


def _slice_series(series: MarketSeries, decision_date: date) -> MarketSeries:
    bars = tuple(
        bar for bar in series.bars if bar.session_date <= decision_date
    )
    if len(bars) < 20:
        raise ValueError("walk-forward slice requires at least 20 sessions")
    as_of = datetime.combine(
        bars[-1].session_date, time(23, 59), tzinfo=timezone.utc
    )
    return replace(series, bars=bars, fetched_at=min(series.fetched_at, as_of))


def _slice_bundle(bundle: IndexBundle, decision_date: date) -> IndexBundle:
    return IndexBundle(
        primary=_slice_series(bundle.primary, decision_date),
        secondary=_slice_series(bundle.secondary, decision_date),
        volatility=(
            _slice_series(bundle.volatility, decision_date)
            if bundle.volatility is not None
            else None
        ),
        # A single bundle-level breadth value has no historical timestamp.
        # Reusing it at every t would leak the final snapshot into the past.
        breadth_ratio=None,
    )


def _quantize(value: Decimal, series: MarketSeries, *, rounding) -> Decimal:
    return value.quantize(
        Decimal("1").scaleb(-series.price_precision),
        rounding=rounding,
    )


def _adverse_buy(price: Decimal, config: WalkForwardConfig) -> Decimal:
    return price * (
        Decimal("1") + config.slippage_bps / Decimal("10000")
    )


def _adverse_sell(price: Decimal, config: WalkForwardConfig) -> Decimal:
    return price * (
        Decimal("1") - config.slippage_bps / Decimal("10000")
    )


def _trade_from_candidate(
    candidate,
    full_series: MarketSeries,
    decision_date: date,
    policy: RegimePolicy,
    config: WalkForwardConfig,
) -> TradeSample | None:
    entry_index = next(
        (
            index
            for index, bar in enumerate(full_series.bars)
            if bar.session_date > decision_date
        ),
        None,
    )
    if entry_index is None:
        return None
    entry_bar = full_series.bars[entry_index]
    entry_price = _quantize(
        _adverse_buy(entry_bar.open, config),
        full_series,
        rounding=ROUND_CEILING,
    )
    high_water = entry_price
    maximum_seen = entry_price
    minimum_seen = entry_price
    exit_price = None
    exit_reason = None
    exit_index = None
    required_last_index = (
        entry_index + config.maximum_holding_sessions - 1
    )
    if required_last_index >= len(full_series.bars):
        return None
    last_index = required_last_index
    weak_regime = candidate.regime in {
        Regime.SIDEWAYS,
        Regime.MODERATE_BEAR,
        Regime.STRONG_BEAR,
    }

    for index in range(entry_index, last_index + 1):
        bar = full_series.bars[index]
        maximum_seen = max(maximum_seen, bar.open)
        minimum_seen = min(minimum_seen, bar.open)
        if bar.low <= candidate.stop_price:
            raw_exit = min(bar.open, candidate.stop_price)
            exit_price = _quantize(
                _adverse_sell(raw_exit, config),
                full_series,
                rounding=ROUND_FLOOR,
            )
            minimum_seen = min(minimum_seen, raw_exit)
            exit_reason = "hard_stop"
            exit_index = index
            break
        trail_armed = high_water >= entry_price * Decimal("1.05")
        trail_price = high_water * (
            Decimal("1") - policy.trailing_pct / Decimal("100")
        )
        if trail_armed and bar.low <= trail_price:
            raw_exit = min(bar.open, trail_price)
            exit_price = _quantize(
                _adverse_sell(raw_exit, config),
                full_series,
                rounding=ROUND_FLOOR,
            )
            minimum_seen = min(minimum_seen, raw_exit)
            exit_reason = "trailing_stop"
            exit_index = index
            break
        if weak_regime and bar.high >= candidate.target_price:
            exit_price = _quantize(
                _adverse_sell(candidate.target_price, config),
                full_series,
                rounding=ROUND_FLOOR,
            )
            maximum_seen = max(maximum_seen, candidate.target_price)
            exit_reason = "weak_regime_target"
            exit_index = index
            break
        if index == required_last_index:
            exit_price = _quantize(
                _adverse_sell(bar.close, config),
                full_series,
                rounding=ROUND_FLOOR,
            )
            maximum_seen = max(maximum_seen, bar.high)
            minimum_seen = min(minimum_seen, bar.low)
            exit_reason = "max_hold"
            exit_index = index
            break
        high_water = max(high_water, bar.high)
        maximum_seen = max(maximum_seen, bar.high)
        minimum_seen = min(minimum_seen, bar.low)

    if exit_price is None or exit_reason is None or exit_index is None:
        return None
    hundred = Decimal("100")
    return TradeSample(
        market=candidate.instrument.market,
        symbol=candidate.instrument.symbol,
        regime=candidate.regime,
        strategy_id=candidate.source,
        trigger_type=candidate.trigger_type,
        entry_date=entry_bar.session_date,
        exit_date=full_series.bars[exit_index].session_date,
        entry_price=entry_price,
        exit_price=exit_price,
        return_pct=(exit_price / entry_price - Decimal("1")) * hundred,
        mfe_pct=max(
            Decimal("0"),
            (maximum_seen / entry_price - Decimal("1")) * hundred,
        ),
        mae_pct=min(
            Decimal("0"),
            (minimum_seen / entry_price - Decimal("1")) * hundred,
        ),
        exit_reason=exit_reason,
        holding_sessions=exit_index - entry_index + 1,
    )


def _simulate(
    history: HistoricalMarketData,
    *,
    config: WalkForwardConfig,
    strategy: ScreeningStrategy,
    policy_provider: Callable[[Regime], RegimePolicy],
) -> tuple[TradeSample, ...]:
    samples = []
    for market in sorted(history, key=lambda item: item.value):
        if not isinstance(market, Market):
            raise ValueError("history keys must be Market values")
        bundle, universe, stock_map = history[market]
        session_count = len(bundle.primary.bars)
        if session_count <= config.warmup_sessions:
            continue
        processed_dates: set[date] = set()
        busy_until: dict[tuple[Market, str], date] = {}
        first_decision = config.warmup_sessions - 1
        first_decision_date = bundle.primary.bars[
            first_decision
        ].session_date
        if any(member.as_of > first_decision_date for member in universe):
            raise ValueError(
                "walk-forward requires a point-in-time universe snapshot "
                "known by the first decision date"
            )
        for window_start in range(
            first_decision, session_count - 1, config.step_sessions
        ):
            window_stop = min(
                session_count - 1,
                window_start + config.evaluation_sessions,
            )
            for decision_index in range(window_start, window_stop):
                decision_date = bundle.primary.bars[decision_index].session_date
                if decision_date in processed_dates:
                    continue
                processed_dates.add(decision_date)
                sliced_bundle = _slice_bundle(bundle, decision_date)
                as_of = datetime.combine(
                    decision_date, time(23, 59), tzinfo=timezone.utc
                )
                regime = classify_market_regime(sliced_bundle, as_of=as_of)
                active_universe = tuple(universe)
                eligible_universe = []
                sliced_stocks = {}
                for member in active_universe:
                    series = stock_map.get(member.instrument)
                    if series is None:
                        raise ValueError(
                            "historical stock series missing for universe member"
                        )
                    if sum(
                        bar.session_date <= decision_date
                        for bar in series.bars
                    ) < 20:
                        continue
                    sliced = _slice_series(
                        series, decision_date
                    )
                    if sliced.bars[-1].session_date != decision_date:
                        continue
                    eligible_universe.append(member)
                    sliced_stocks[member.instrument] = sliced
                candidates = screen_candidates(
                    tuple(eligible_universe),
                    sliced_stocks,
                    sliced_bundle.primary,
                    regime,
                    strategy=strategy,
                )
                policy = policy_provider(regime.regime)
                if not isinstance(policy, RegimePolicy):
                    raise ValueError("policy_provider must return RegimePolicy")
                for candidate in candidates:
                    decision = gate_entry(
                        candidate,
                        analysis_score=Decimal("10"),
                        policy=policy,
                    )
                    if not decision.allowed:
                        continue
                    sample = _trade_from_candidate(
                        candidate,
                        stock_map[candidate.instrument],
                        decision_date,
                        policy,
                        config,
                    )
                    if sample is not None:
                        key = (sample.market, sample.symbol)
                        if (
                            key in busy_until
                            and sample.entry_date <= busy_until[key]
                        ):
                            continue
                        samples.append(sample)
                        busy_until[key] = sample.exit_date
    return tuple(
        sorted(
            samples,
            key=lambda item: (
                item.entry_date,
                item.market.value,
                item.strategy_id,
                item.trigger_type.value,
            ),
        )
    )


def _average(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _maximum_losing_streak(samples: tuple[TradeSample, ...]) -> int:
    longest = current = 0
    for sample in sorted(samples, key=lambda item: (item.entry_date, item.exit_date)):
        if sample.return_pct < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _segments(
    samples: tuple[TradeSample, ...], config: WalkForwardConfig
) -> tuple[SegmentMetrics, ...]:
    grouped: dict[
        tuple[Market, Regime, str, TriggerType], list[TradeSample]
    ] = {}
    for sample in samples:
        key = (
            sample.market,
            sample.regime,
            sample.strategy_id,
            sample.trigger_type,
        )
        grouped.setdefault(key, []).append(sample)
    results = []
    for key in sorted(
        grouped,
        key=lambda item: (item[0].value, item[1].value, item[2], item[3].value),
    ):
        values = tuple(grouped[key])
        returns = tuple(item.return_pct for item in values)
        holding = tuple(Decimal(item.holding_sessions) for item in values)
        enough = len(values) >= config.minimum_samples
        results.append(
            SegmentMetrics(
                market=key[0],
                regime=key[1],
                strategy_id=key[2],
                trigger_type=key[3],
                sample_count=len(values),
                win_rate=(
                    Decimal(sum(value > 0 for value in returns))
                    / Decimal(len(values))
                    * Decimal("100")
                ),
                mean_return_pct=_average(returns),
                median_return_pct=Decimal(median(returns)),
                mean_mfe_pct=_average(tuple(item.mfe_pct for item in values)),
                mean_mae_pct=_average(tuple(item.mae_pct for item in values)),
                stop_count=sum(item.exit_reason == "hard_stop" for item in values),
                mean_holding_sessions=_average(holding),
                maximum_losing_streak=_maximum_losing_streak(values),
                policy_change_allowed=enough,
                status="ready" if enough else "insufficient_sample",
            )
        )
    return tuple(results)


def run_walk_forward(
    history: HistoricalMarketData,
    *,
    config: WalkForwardConfig,
    strategy: ScreeningStrategy | None = None,
    policy_provider: Callable[[Regime], RegimePolicy] = policy_for,
) -> WalkForwardReport:
    if not isinstance(history, Mapping):
        raise ValueError("history must be a mapping")
    if not isinstance(config, WalkForwardConfig):
        raise ValueError("config must be WalkForwardConfig")
    if not callable(policy_provider):
        raise ValueError("policy_provider must be callable")
    selected_strategy = strategy or OneilTrendStrategy()
    baseline_strategy = (
        None
        if policy_provider is policy_for
        else copy.deepcopy(selected_strategy)
    )
    selected_samples = _simulate(
        history,
        config=config,
        strategy=selected_strategy,
        policy_provider=policy_provider,
    )
    selected_segments = _segments(selected_samples, config)

    if policy_provider is policy_for:
        baseline_segments = selected_segments
    else:
        baseline_samples = _simulate(
            history,
            config=config,
            strategy=baseline_strategy,
            policy_provider=policy_for,
        )
        baseline_segments = _segments(baseline_samples, config)
    selected_by_key = {
        (item.market, item.regime, item.strategy_id, item.trigger_type): item
        for item in selected_segments
    }
    baseline = {
        (item.market, item.regime, item.strategy_id, item.trigger_type): item
        for item in baseline_segments
    }
    deltas = {}
    for key in sorted(
        set(selected_by_key) & set(baseline),
        key=lambda item: (item[0].value, item[1].value, item[2], item[3].value),
    ):
        selected = selected_by_key.get(key)
        comparison = baseline.get(key)
        deltas[key] = (
            selected.mean_return_pct if selected is not None else Decimal("0")
        ) - (
            comparison.mean_return_pct
            if comparison is not None
            else Decimal("0")
        )
    return WalkForwardReport(
        config=config,
        samples=selected_samples,
        segments=selected_segments,
        comparison_deltas=deltas,
    )
