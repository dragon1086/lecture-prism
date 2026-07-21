from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
import unittest

from prism_core.domain import (
    Candidate,
    Instrument,
    Market,
    Regime,
    RegimePolicy,
    TriggerType,
)
from prism_core.market_data import DailyBar, IndexBundle, MarketSeries, UniverseMember
from prism_core.market_data import (
    FIXTURE_AS_OF,
    FixtureMarketDataProvider,
    FixtureUniverseProvider,
)
from prism_core.policy import policy_for
from prism_core.walk_forward import WalkForwardConfig, run_walk_forward


def _bars(market, *, count=230, descending=False, ambiguous_at=None):
    values = []
    for index in range(count):
        level = Decimal("400") - Decimal(index) if descending else Decimal("100") + Decimal(index)
        if market is Market.KR:
            level = level.quantize(Decimal("1"))
        else:
            level = level.quantize(Decimal("0.01"))
        low, high = level - Decimal("1"), level + Decimal("1")
        if index == ambiguous_at:
            low, high = Decimal("100"), Decimal("400")
        values.append(DailyBar(
            session_date=date(2025, 1, 1) + timedelta(days=index),
            open=level,
            high=high,
            low=low,
            close=level,
            volume=Decimal("1000000") + index,
        ))
    return tuple(values)


def _series(market, symbol, bars):
    return MarketSeries(
        market=market,
        symbol=symbol,
        currency="KRW" if market is Market.KR else "USD",
        price_precision=0 if market is Market.KR else 2,
        bars=bars,
        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source="fixture",
        is_fixture=True,
    )


def _history(*, markets=(Market.US,), descending=False, ambiguous_at=None):
    result = {}
    for market in markets:
        market_descending = descending or market is Market.US
        stock_symbol = "005930" if market is Market.KR else "AAPL"
        instrument = Instrument(
            stock_symbol,
            market,
            "XKRX" if market is Market.KR else "XNAS",
            "KRW" if market is Market.KR else "USD",
            stock_symbol,
            "Technology",
            Decimal("1"),
            0 if market is Market.KR else 2,
        )
        stock = _series(
            market,
            stock_symbol,
            _bars(
                market,
                descending=market_descending,
                ambiguous_at=ambiguous_at,
            ),
        )
        primary = _series(
            market, "PRIMARY", _bars(market, descending=market_descending)
        )
        secondary = _series(
            market, "SECONDARY", _bars(market, descending=market_descending)
        )
        volatility = None
        if market is Market.US:
            volatility = _series(
                market,
                "VIX",
                tuple(replace(bar, open=Decimal("25"), high=Decimal("26"),
                              low=Decimal("24"), close=Decimal("25"))
                      for bar in _bars(market, descending=market_descending)),
            )
        result[market] = (
            IndexBundle(primary, secondary, volatility, Decimal("0.50")),
            (UniverseMember(instrument, "fixture", stock.bars[0].session_date),),
            {instrument: stock},
        )
    return result


class _SignalStrategy:
    strategy_id = "walk_fixture"
    supported_triggers = frozenset(TriggerType)

    def __init__(self):
        self.observed = []
        self.breadth_observed = []

    def evaluate(self, instrument, series, benchmark, regime):
        self.observed.append((regime.as_of.date(), series.bars[-1].session_date))
        self.breadth_observed.append(regime.metrics["breadth"])
        reference = series.bars[-1].close
        quantum = Decimal("1").scaleb(-instrument.price_precision)
        stop = (reference * Decimal("0.95")).quantize(quantum)
        target = (reference + (reference - stop) * Decimal("2")).quantize(quantum)
        trigger = (
            TriggerType.BREAKOUT
            if instrument.market is Market.KR
            else TriggerType.OVERSOLD_REBOUND
        )
        return (Candidate(
            instrument=instrument,
            as_of=regime.as_of,
            trigger_type=trigger,
            regime=regime.regime,
            feature_values={"fixture": True},
            component_scores={"signal": Decimal("10")},
            final_score=Decimal("10"),
            reference_price=reference,
            stop_price=stop,
            target_price=target,
            risk_reward_ratio=(target - reference) / (reference - stop),
            source=self.strategy_id,
        ),)


class _CallSensitiveStrategy(_SignalStrategy):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def evaluate(self, instrument, series, benchmark, regime):
        self.calls += 1
        if self.calls > 5:
            return ()
        return super().evaluate(instrument, series, benchmark, regime)


CONFIG = WalkForwardConfig(
    warmup_sessions=220,
    evaluation_sessions=5,
    step_sessions=5,
    maximum_holding_sessions=2,
    slippage_bps=Decimal("100"),
    minimum_samples=30,
)


class WalkForwardTest(unittest.TestCase):
    def test_decision_at_t_is_sliced_and_entry_is_next_open_with_adverse_slippage(self):
        history = _history()
        strategy = _SignalStrategy()
        report = run_walk_forward(history, config=CONFIG, strategy=strategy)

        self.assertTrue(strategy.observed)
        self.assertTrue(all(decision == observed for decision, observed in strategy.observed))
        first = report.samples[0]
        stock = next(iter(history[Market.US][2].values()))
        entry_bar = next(bar for bar in stock.bars if bar.session_date == first.entry_date)
        self.assertEqual(first.entry_price, entry_bar.open * Decimal("1.01"))

    def test_ambiguous_ohlc_bar_chooses_stop_before_target(self):
        report = run_walk_forward(
            _history(ambiguous_at=220), config=replace(CONFIG, evaluation_sessions=1),
            strategy=_SignalStrategy(),
        )
        self.assertEqual(report.samples[0].exit_reason, "hard_stop")
        self.assertEqual(report.samples[0].mfe_pct, Decimal("0"))

    def test_untimestamped_breadth_and_future_universe_members_never_leak(self):
        history = _history()
        strategy = _SignalStrategy()

        run_walk_forward(history, config=CONFIG, strategy=strategy)

        self.assertTrue(strategy.breadth_observed)
        self.assertEqual(set(strategy.breadth_observed), {"unavailable"})

        bundle, universe, stocks = history[Market.US]
        future_member = replace(
            universe[0], as_of=bundle.primary.bars[-1].session_date
        )
        history[Market.US] = (bundle, (future_member,), stocks)
        future_strategy = _SignalStrategy()

        with self.assertRaisesRegex(ValueError, "point-in-time universe"):
            run_walk_forward(
                history, config=CONFIG, strategy=future_strategy
            )
        self.assertEqual(future_strategy.observed, [])

    def test_final_date_fixture_universe_fails_instead_of_backfilling_history(self):
        provider = FixtureMarketDataProvider.standard()
        universe_provider = FixtureUniverseProvider.standard()
        market = Market.US
        bundle = provider.index_bundle(market, as_of=FIXTURE_AS_OF)
        universe = universe_provider.members(market, as_of=FIXTURE_AS_OF)
        stocks = {
            member.instrument: provider.stock_series(
                member.instrument, as_of=FIXTURE_AS_OF
            )
            for member in universe
        }

        with self.assertRaisesRegex(ValueError, "point-in-time universe"):
            run_walk_forward(
                {market: (bundle, universe, stocks)},
                config=CONFIG,
                strategy=_SignalStrategy(),
            )

    def test_gap_through_stop_fills_at_worse_open_with_sell_slippage(self):
        history = _history()
        bundle, universe, stocks = history[Market.US]
        instrument, stock = next(iter(stocks.items()))
        bars = list(stock.bars)
        bars[220] = replace(
            bars[220],
            open=Decimal("100"),
            high=Decimal("400"),
            low=Decimal("90"),
            close=Decimal("100"),
        )
        history[Market.US] = (
            bundle,
            universe,
            {instrument: replace(stock, bars=tuple(bars))},
        )

        report = run_walk_forward(
            history,
            config=replace(CONFIG, evaluation_sessions=1),
            strategy=_SignalStrategy(),
        )

        self.assertEqual(report.samples[0].exit_reason, "hard_stop")
        self.assertEqual(report.samples[0].entry_price, Decimal("101.00"))
        self.assertEqual(report.samples[0].exit_price, Decimal("99.00"))

    def test_stop_exit_metrics_include_known_open_but_not_post_exit_high(self):
        history = _history()
        bundle, universe, stocks = history[Market.US]
        instrument, stock = next(iter(stocks.items()))
        bars = list(stock.bars)
        bars[221] = replace(
            bars[221],
            open=Decimal("300"),
            high=Decimal("400"),
            low=Decimal("100"),
            close=Decimal("200"),
        )
        history[Market.US] = (
            bundle,
            universe,
            {instrument: replace(stock, bars=tuple(bars))},
        )

        report = run_walk_forward(
            history,
            config=replace(CONFIG, evaluation_sessions=1),
            strategy=_SignalStrategy(),
        )
        sample = report.samples[0]

        expected_mfe = (Decimal("300") / sample.entry_price - 1) * 100
        post_exit_high_mfe = (Decimal("400") / sample.entry_price - 1) * 100
        self.assertEqual(sample.exit_reason, "hard_stop")
        self.assertEqual(sample.mfe_pct, expected_mfe)
        self.assertLess(sample.mfe_pct, post_exit_high_mfe)

    def test_tail_horizon_excludes_early_stop_and_survivor_consistently(self):
        survivor = run_walk_forward(
            _history(), config=CONFIG, strategy=_SignalStrategy()
        )
        early_stop = run_walk_forward(
            _history(ambiguous_at=229),
            config=CONFIG,
            strategy=_SignalStrategy(),
        )

        self.assertEqual(len(early_stop.samples), len(survivor.samples))
        final_date = _history()[Market.US][0].primary.bars[-1].session_date
        self.assertTrue(all(
            sample.entry_date < final_date
            for sample in early_stop.samples + survivor.samples
        ))

    def test_stock_calendar_gap_uses_first_bar_strictly_after_decision(self):
        history = _history()
        bundle, universe, stocks = history[Market.US]
        instrument, stock = next(iter(stocks.items()))
        bars = stock.bars[:220] + stock.bars[221:]
        history[Market.US] = (
            bundle,
            universe,
            {instrument: replace(stock, bars=bars)},
        )
        strategy = _SignalStrategy()

        report = run_walk_forward(
            history,
            config=replace(CONFIG, evaluation_sessions=4),
            strategy=strategy,
        )

        decision_date = bundle.primary.bars[219].session_date
        expected_entry = next(
            bar for bar in bars if bar.session_date > decision_date
        )
        self.assertTrue(all(
            observed <= decision for decision, observed in strategy.observed
        ))
        missing_session = bundle.primary.bars[220].session_date
        self.assertNotIn(
            missing_session,
            {decision for decision, _ in strategy.observed},
        )
        self.assertEqual(report.samples[0].entry_date, expected_entry.session_date)

    def test_report_groups_all_dimensions_and_small_samples_cannot_tune(self):
        report = run_walk_forward(
            _history(markets=(Market.KR, Market.US)),
            config=CONFIG,
            strategy=_SignalStrategy(),
        )
        keys = {
            (item.market, item.regime, item.strategy_id, item.trigger_type)
            for item in report.segments
        }
        self.assertTrue(any(key[0] is Market.KR and key[3] is TriggerType.BREAKOUT for key in keys))
        self.assertTrue(any(key[0] is Market.US and key[3] is TriggerType.OVERSOLD_REBOUND for key in keys))
        self.assertTrue(all(not item.policy_change_allowed for item in report.segments))
        self.assertTrue(all(item.status == "insufficient_sample" for item in report.segments))
        self.assertTrue(all(sample.mfe_pct >= 0 for sample in report.samples))
        self.assertTrue(all(sample.mae_pct <= 0 for sample in report.samples))
        self.assertTrue(all(sample.holding_sessions == 2 for sample in report.samples))
        self.assertTrue(all(
            item.mean_holding_sessions == Decimal("2")
            for item in report.segments
        ))
        by_symbol = {}
        for sample in report.samples:
            by_symbol.setdefault((sample.market, sample.symbol), []).append(sample)
        for samples in by_symbol.values():
            ordered = sorted(samples, key=lambda item: item.entry_date)
            self.assertTrue(all(
                current.entry_date > previous.exit_date
                for previous, current in zip(ordered, ordered[1:])
            ))

    def test_policy_comparison_is_deterministic_and_never_mutates_production_policy(self):
        original = policy_for(Regime.STRONG_BEAR)
        flat = RegimePolicy(
            frozenset(TriggerType), Decimal("0"), Decimal("0"), Decimal("1"),
            Decimal("7"), Decimal("1"), 10, Decimal("0"), Decimal("3"),
        )
        provider = lambda regime: flat

        first = run_walk_forward(_history(descending=True), config=CONFIG,
                                 strategy=_SignalStrategy(), policy_provider=provider)
        second = run_walk_forward(_history(descending=True), config=CONFIG,
                                  strategy=_SignalStrategy(), policy_provider=provider)

        self.assertEqual(first.comparison_deltas, second.comparison_deltas)
        self.assertEqual(policy_for(Regime.STRONG_BEAR), original)
        self.assertIsInstance(first.comparison_deltas, MappingProxyType)

    def test_comparison_clones_pristine_stateful_strategy_before_selected_run(self):
        wrapped_default = lambda regime: policy_for(regime)

        report = run_walk_forward(
            _history(),
            config=CONFIG,
            strategy=_CallSensitiveStrategy(),
            policy_provider=wrapped_default,
        )

        self.assertTrue(report.comparison_deltas)
        self.assertEqual(set(report.comparison_deltas.values()), {Decimal("0")})


if __name__ == "__main__":
    unittest.main()
