from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from types import MappingProxyType
from typing import Callable, Mapping

from .cycle import CycleResult, TradingCycle
from .domain import (
    Candidate,
    EntryContext,
    EntryDecision,
    Market,
    OrderIntent,
    OrderSide,
    OrderType,
    Position,
)
from .ledger import Ledger
from .market_data import (
    FixtureMarketDataProvider,
    FixtureUniverseProvider,
    MarketDataProvider,
    MarketDataUnavailable,
    MarketSeries,
    UniverseMember,
    UniverseProvider,
    YFinanceMarketDataProvider,
    validate_series_for_profile,
)
from .paper_broker import PaperBroker
from .policy import gate_entry, policy_for
from .regime import RegimeResult, classify_market_regime
from .screening import OneilTrendStrategy, ScreeningStrategy, screen_candidates


_DEFAULT_EQUITY = MappingProxyType(
    {Market.KR: Decimal("100000000"), Market.US: Decimal("100000")}
)


def run_detailed_screening(
    *,
    profile: str,
    target_ticker: str | None = None,
    as_of: datetime | None = None,
    provider: MarketDataProvider | None = None,
    universe_provider: UniverseProvider | None = None,
    strategy: ScreeningStrategy | None = None,
) -> list[Candidate]:
    """Return regime-aware candidates without creating broker state.

    Fixture profiles are deterministic. Paper/live always select yfinance and
    propagate provider failures; this function has no demo fallback.
    """

    from datetime import timezone

    if profile not in {"classroom", "backtest", "paper", "live"}:
        raise ValueError("detailed screening requires an operating profile")
    current = as_of or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("as_of must be a timezone-aware datetime")
    selected_provider = provider
    if selected_provider is None:
        selected_provider = (
            FixtureMarketDataProvider.standard()
            if profile in {"classroom", "backtest"}
            else YFinanceMarketDataProvider()
        )
    selected_universe = universe_provider or FixtureUniverseProvider.standard()
    selected_strategy = strategy or OneilTrendStrategy()

    selected: list[Candidate] = []
    for market in Market:
        bundle = selected_provider.index_bundle(market, as_of=current)
        for series in (bundle.primary, bundle.secondary, bundle.volatility):
            if series is not None:
                validate_series_for_profile(series, profile, now=current)
        regime = classify_market_regime(bundle, as_of=current)
        members = tuple(selected_universe.members(market, as_of=current))
        if target_ticker is not None:
            members = tuple(
                member
                for member in members
                if member.instrument.symbol == target_ticker
            )
        series_by_instrument = {}
        for member in members:
            series = selected_provider.stock_series(
                member.instrument, as_of=current
            )
            validate_series_for_profile(series, profile, now=current)
            series_by_instrument[member.instrument] = series
        selected.extend(
            MarketPipeline._one_candidate_per_instrument(
                screen_candidates(
                    members,
                    series_by_instrument,
                    bundle.primary,
                    regime,
                    strategy=selected_strategy,
                )
            )
        )
    return selected


@dataclass(frozen=True)
class MarketSnapshot:
    as_of: datetime
    regimes: Mapping[Market, RegimeResult]
    primary_benchmarks: Mapping[Market, MarketSeries]
    universes: Mapping[Market, tuple[UniverseMember, ...]]
    stock_series: Mapping[tuple[Market, str], MarketSeries]
    quotes: Mapping[tuple[Market, str], Decimal]


@dataclass(frozen=True)
class MarketPreparation:
    run_id: str
    regimes: tuple[RegimeResult, ...]
    candidates: tuple[Candidate, ...]
    decisions: tuple[EntryDecision, ...]
    entry_contexts: tuple[EntryContext, ...]
    entry_intents: tuple[OrderIntent, ...]

    @classmethod
    def empty(cls, run_id: str) -> "MarketPreparation":
        return cls(run_id, (), (), (), (), ())


@dataclass(frozen=True)
class MarketCycleResult:
    prepared: MarketPreparation
    cycle: CycleResult

    @property
    def event_order(self) -> list[str]:
        return self.cycle.event_order


def _positive_money_map(
    values: Mapping[Market, Decimal] | None,
) -> Mapping[Market, Decimal]:
    selected = dict(_DEFAULT_EQUITY if values is None else values)
    if set(selected) != set(Market):
        raise ValueError("money map must contain KR and US")
    if any(
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value <= 0
        for value in selected.values()
    ):
        raise ValueError("money values must be finite positive Decimals")
    return MappingProxyType(selected)


class MarketPipeline:
    """Fail-closed regime, screening, evidence, and paper-cycle integration."""

    def __init__(
        self,
        *,
        provider: MarketDataProvider,
        universe_provider: UniverseProvider,
        broker: PaperBroker,
        ledger: Ledger | None = None,
        profile: str = "classroom",
        strategy: ScreeningStrategy | None = None,
        analysis_score: Callable[[Candidate], Decimal | int] | None = None,
        llm_enter: Callable[[Candidate], bool | None] | None = None,
        account_equity: Mapping[Market, Decimal] | None = None,
        available_cash: Mapping[Market, Decimal] | None = None,
        strategy_exit: Callable[[Position, Decimal], str | None] | None = None,
    ) -> None:
        if profile not in {
            "mock",
            "classroom",
            "backtest",
            "real_data",
            "research",
            "paper",
            "live",
        }:
            raise ValueError(f"unsupported profile: {profile}")
        self.provider = provider
        self.universe_provider = universe_provider
        self.broker = broker
        self.ledger = ledger or broker.ledger
        if self.ledger.path != broker.ledger.path:
            raise ValueError("pipeline and broker must share one ledger")
        self.profile = profile
        self.strategy = strategy or OneilTrendStrategy()
        self.analysis_score = analysis_score or (lambda candidate: Decimal("10"))
        self.llm_enter = llm_enter or (lambda candidate: None)
        self.account_equity = _positive_money_map(account_equity)
        self.available_cash = _positive_money_map(available_cash)
        self.strategy_exit = strategy_exit

    def load_and_validate_snapshot(self, *, as_of: datetime) -> MarketSnapshot:
        if not isinstance(as_of, datetime) or as_of.tzinfo is None:
            raise ValueError("as_of must be a timezone-aware datetime")

        regimes: dict[Market, RegimeResult] = {}
        benchmarks: dict[Market, MarketSeries] = {}
        universes: dict[Market, tuple[UniverseMember, ...]] = {}
        stocks: dict[tuple[Market, str], MarketSeries] = {}
        quotes: dict[tuple[Market, str], Decimal] = {}
        for market in Market:
            bundle = self.provider.index_bundle(market, as_of=as_of)
            for series in (bundle.primary, bundle.secondary, bundle.volatility):
                if series is not None:
                    validate_series_for_profile(series, self.profile, now=as_of)
            regime = classify_market_regime(bundle, as_of=as_of)
            members = tuple(self.universe_provider.members(market, as_of=as_of))
            regimes[market] = regime
            benchmarks[market] = bundle.primary
            universes[market] = members
            for member in members:
                series = self.provider.stock_series(member.instrument, as_of=as_of)
                validate_series_for_profile(series, self.profile, now=as_of)
                key = (market, member.instrument.symbol)
                stocks[key] = series
                quotes[key] = series.bars[-1].close

        # A held symbol must have a fresh quote before the cycle is allowed to
        # mutate broker state. Unknown holdings are never guessed or skipped.
        for position in self.broker.get_positions():
            key = (position.market, position.symbol)
            if key in quotes:
                continue
            context = None
            if position.entry_client_order_id:
                try:
                    context = self.ledger.get_entry_context(
                        position.entry_client_order_id
                    )
                except ValueError:
                    context = None
            context_matches = (
                context is not None
                and context.strategy_id == position.strategy_id
                and context.candidate.instrument.market is position.market
                and context.candidate.instrument.symbol == position.symbol
            )
            if context_matches:
                series = self.provider.stock_series(
                    context.candidate.instrument, as_of=as_of
                )
            else:
                held_series = getattr(
                    self.provider, "held_position_series", None
                )
                if not callable(held_series):
                    raise MarketDataUnavailable(
                        f"provider cannot quote held position without valid "
                        f"provenance: {position.market.value}:{position.symbol}"
                    )
                series = held_series(position, as_of=as_of)
            validate_series_for_profile(series, self.profile, now=as_of)
            if (
                series.market is not position.market
                or series.symbol != position.symbol
                or series.currency != position.currency
            ):
                raise MarketDataUnavailable(
                    "held position series does not match position contract"
                )
            stocks[key] = series
            quotes[key] = series.bars[-1].close

        return MarketSnapshot(
            as_of=as_of,
            regimes=MappingProxyType(regimes),
            primary_benchmarks=MappingProxyType(benchmarks),
            universes=MappingProxyType(universes),
            stock_series=MappingProxyType(stocks),
            quotes=MappingProxyType(quotes),
        )

    @staticmethod
    def _one_candidate_per_instrument(
        candidates: tuple[Candidate, ...],
    ) -> tuple[Candidate, ...]:
        selected: list[Candidate] = []
        seen: set[tuple[Market, str]] = set()
        for candidate in candidates:
            key = (candidate.instrument.market, candidate.instrument.symbol)
            if key not in seen:
                selected.append(candidate)
                seen.add(key)
        return tuple(selected)

    def _quantity(
        self,
        decision: EntryDecision,
        *,
        remaining_cash: Decimal,
    ) -> Decimal:
        candidate = decision.candidate
        policy = decision.policy
        equity = self.account_equity[candidate.instrument.market]
        reserve = equity * policy.minimum_cash_pct / Decimal("100")
        spendable = max(Decimal("0"), remaining_cash - reserve)
        risk_per_share = candidate.reference_price - candidate.stop_price
        by_risk = (
            equity * policy.account_risk_pct / Decimal("100") / risk_per_share
        ).to_integral_value(rounding=ROUND_FLOOR)
        by_cash = (spendable / candidate.reference_price).to_integral_value(
            rounding=ROUND_FLOOR
        )
        quantity = min(by_risk, by_cash)
        lot = candidate.instrument.lot_size
        return (quantity / lot).to_integral_value(rounding=ROUND_FLOOR) * lot

    def prepare_entries(
        self,
        run_id: str,
        *,
        as_of: datetime,
        snapshot: MarketSnapshot | None = None,
    ) -> MarketPreparation:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id is required")
        selected_snapshot = snapshot or self.load_and_validate_snapshot(as_of=as_of)
        if selected_snapshot.as_of != as_of:
            raise ValueError("snapshot as_of mismatch")

        regimes: list[RegimeResult] = []
        candidates: list[Candidate] = []
        decisions: list[EntryDecision] = []
        contexts: list[EntryContext] = []
        intents: list[OrderIntent] = []
        remaining_cash = dict(self.available_cash)
        occupied = {market: 0 for market in Market}
        for position in self.broker.get_positions():
            occupied[position.market] += 1

        for market in Market:
            regime = selected_snapshot.regimes[market]
            members = selected_snapshot.universes[market]
            series_by_instrument = {
                member.instrument: selected_snapshot.stock_series[
                    (market, member.instrument.symbol)
                ]
                for member in members
            }
            screened = screen_candidates(
                members,
                series_by_instrument,
                selected_snapshot.primary_benchmarks[market],
                regime,
                strategy=self.strategy,
            )
            screened = self._one_candidate_per_instrument(screened)
            regimes.append(regime)
            candidates.extend(screened)
            for candidate in screened:
                decision = gate_entry(
                    candidate,
                    analysis_score=self.analysis_score(candidate),
                    llm_enter=self.llm_enter(candidate),
                    policy=policy_for(regime.regime),
                )
                decisions.append(decision)
                if not decision.allowed or occupied[market] >= decision.policy.maximum_slots:
                    continue
                quantity = self._quantity(
                    decision, remaining_cash=remaining_cash[market]
                )
                if quantity <= 0:
                    continue
                order_id = f"{run_id}:{market.value}:{candidate.instrument.symbol}:BUY"
                context = EntryContext(
                    client_order_id=order_id,
                    run_id=run_id,
                    candidate=candidate,
                    strategy_id=candidate.source,
                    policy=decision.policy,
                )
                intent = OrderIntent(
                    client_order_id=order_id,
                    market=market,
                    symbol=candidate.instrument.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=quantity,
                    limit_price=candidate.reference_price,
                    currency=candidate.instrument.currency,
                    strategy_id=candidate.source,
                    reason=f"{regime.regime.value}:{candidate.trigger_type.value}",
                )
                contexts.append(context)
                intents.append(intent)
                occupied[market] += 1
                remaining_cash[market] -= quantity * candidate.reference_price

        self.ledger.record_market_preparation(
            run_id, tuple(regimes), tuple(candidates), tuple(contexts)
        )
        return MarketPreparation(
            run_id,
            tuple(regimes),
            tuple(candidates),
            tuple(decisions),
            tuple(contexts),
            tuple(intents),
        )

    def _exit_policy_provider(
        self, snapshot: MarketSnapshot
    ) -> Callable[[Position], str | None]:
        def decide(position: Position) -> str | None:
            quote = snapshot.quotes[(position.market, position.symbol)]
            context = None
            if position.entry_client_order_id:
                try:
                    context = self.ledger.get_entry_context(
                        position.entry_client_order_id
                    )
                except ValueError:
                    # Legacy/corrupt provenance disables only adaptive exits.
                    # It must never prevent the cycle's absolute hard stop.
                    context = None
            if (
                context is not None
                and context.strategy_id != position.strategy_id
            ):
                context = None
            if context is not None and quote <= context.candidate.stop_price:
                return "scenario_stop"
            if quote <= position.average_price * Decimal("0.93"):
                return "stop"
            if context is None:
                return None
            position_series = snapshot.stock_series.get(
                (position.market, position.symbol)
            )
            bars = position_series.bars if position_series is not None else ()
            primary_periods = 120 if position.market is Market.KR else 200
            if quote < position.average_price and len(bars) >= primary_periods:
                primary_average = sum(
                    (bar.close for bar in bars[-primary_periods:]), Decimal("0")
                ) / Decimal(primary_periods)
                if quote < primary_average:
                    return "primary_ma_break"
            policy = policy_for(snapshot.regimes[position.market].regime)
            armed = position.high_since_entry >= position.average_price * Decimal("1.05")
            if armed and quote <= position.high_since_entry * (
                Decimal("1") - policy.trailing_pct / Decimal("100")
            ):
                return "regime_trailing_stop"
            if snapshot.regimes[position.market].regime.value in {
                "sideways",
                "moderate_bear",
                "strong_bear",
            } and quote >= context.candidate.target_price:
                return "weak_regime_target"
            if self.strategy_exit is not None:
                return self.strategy_exit(position, quote)
            return None

        return decide

    def run(
        self,
        run_id: str,
        *,
        as_of: datetime,
        auto_fill: bool = False,
    ) -> MarketCycleResult:
        snapshot = self.load_and_validate_snapshot(as_of=as_of)
        prepared_box: list[MarketPreparation] = []

        def supply_entries() -> list[OrderIntent]:
            prepared = self.prepare_entries(
                run_id, as_of=as_of, snapshot=snapshot
            )
            prepared_box.append(prepared)
            return list(prepared.entry_intents)

        cycle = TradingCycle(self.broker, dict(snapshot.quotes)).run_staged(
            run_id,
            supply_entries,
            exit_policy_provider=self._exit_policy_provider(snapshot),
            auto_fill=auto_fill,
        )
        prepared = (
            prepared_box[0]
            if prepared_box
            else MarketPreparation.empty(run_id)
        )
        return MarketCycleResult(prepared=prepared, cycle=cycle)
