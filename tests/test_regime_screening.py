from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from prism_core.domain import (
    Candidate,
    EntryContext,
    EntryDecision,
    Instrument,
    Market,
    Regime,
    RegimePolicy,
    TriggerType,
)
from prism_core.policy import gate_entry, policy_for
from prism_core.market_data import DailyBar, MarketSeries, UniverseMember
from prism_core.regime import PulseState, RegimeResult
from prism_core.screening import (
    OneilTrendStrategy,
    ScreeningStrategy,
    screen_candidates,
)


def candidate(**overrides):
    values = {
        "instrument": Instrument(
            symbol="AAPL",
            market=Market.US,
            exchange="NASDAQ",
            currency="USD",
            name="Apple",
            sector="Technology",
            lot_size=Decimal("0.001"),
            price_precision=2,
        ),
        "as_of": datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc),
        "trigger_type": TriggerType.BREAKOUT,
        "regime": Regime.STRONG_BULL,
        "feature_values": {"above_50_day": True, "setup": "cup"},
        "component_scores": {"trend": Decimal("4"), "volume": Decimal("4")},
        "final_score": Decimal("8"),
        "reference_price": Decimal("100"),
        "stop_price": Decimal("93"),
        "target_price": Decimal("114"),
        "risk_reward_ratio": Decimal("2"),
        "source": "fixture",
    }
    values.update(overrides)
    return Candidate(**values)


def policy():
    return RegimePolicy(
        active_triggers=frozenset({TriggerType.BREAKOUT}),
        minimum_candidate_score=Decimal("6"),
        minimum_analysis_score=Decimal("6"),
        minimum_risk_reward=Decimal("1.2"),
        maximum_stop_pct=Decimal("7"),
        account_risk_pct=Decimal("1"),
        maximum_slots=10,
        minimum_cash_pct=Decimal("10"),
        trailing_pct=Decimal("8"),
    )


AS_OF = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)


def instrument(symbol="AAPL"):
    return Instrument(
        symbol=symbol,
        market=Market.US,
        exchange="NASDAQ",
        currency="USD",
        name=symbol,
        sector="Technology",
        lot_size=Decimal("0.001"),
        price_precision=2,
    )


def series(symbol="AAPL", *, market=Market.US, currency="USD"):
    bars = tuple(
        DailyBar(
            session_date=date(2026, 5, 1) + timedelta(days=index),
            open=Decimal("100.00") + Decimal(index),
            high=Decimal("101.00") + Decimal(index),
            low=Decimal("99.00") + Decimal(index),
            close=Decimal("100.00") + Decimal(index),
            volume=Decimal("1000000") + Decimal(index),
        )
        for index in range(20)
    )
    return MarketSeries(
        market=market,
        symbol=symbol,
        currency=currency,
        price_precision=2,
        bars=bars,
        fetched_at=AS_OF,
        source="fixture",
        is_fixture=True,
    )


def regime_result(regime=Regime.STRONG_BULL, market=Market.US):
    return RegimeResult(
        market=market,
        as_of=AS_OF,
        regime=regime,
        confidence=Decimal("0.8"),
        pulse=PulseState.UPTREND,
        metrics={},
        reasons=("fixture",),
        source="fixture",
    )


def trend_instrument(symbol, market):
    is_kr = market is Market.KR
    return Instrument(
        symbol=symbol,
        market=market,
        exchange="XKRX" if is_kr else "NASDAQ",
        currency="KRW" if is_kr else "USD",
        name=symbol,
        sector="Technology",
        lot_size=Decimal("1") if is_kr else Decimal("0.001"),
        price_precision=0 if is_kr else 2,
    )


def trend_series(selected, closes, volumes):
    quantum = Decimal("1") if selected.market is Market.KR else Decimal("0.01")
    bars = []
    for index, (close, volume) in enumerate(zip(closes, volumes)):
        close = Decimal(close).quantize(quantum)
        spread = Decimal("10") if selected.market is Market.KR else Decimal("0.10")
        bars.append(
            DailyBar(
                session_date=date(2025, 1, 1) + timedelta(days=index),
                open=close,
                high=close + spread,
                low=close - spread,
                close=close,
                volume=Decimal(volume),
            )
        )
    return MarketSeries(
        market=selected.market,
        symbol=selected.symbol,
        currency=selected.currency,
        price_precision=selected.price_precision,
        bars=tuple(bars),
        fetched_at=AS_OF,
        source="fixture",
        is_fixture=True,
    )


class InjectedStrategy:
    strategy_id = "test_strategy_v1"
    supported_triggers = frozenset({TriggerType.BREAKOUT})

    def __init__(self, output_instrument=None):
        self.output_instrument = output_instrument

    def evaluate(self, selected, stock_series, benchmark, regime):
        output = self.output_instrument or selected
        score = Decimal("8") if selected.symbol == "AAPL" else Decimal("7")
        return (
            candidate(
                instrument=output,
                as_of=regime.as_of,
                regime=regime.regime,
                final_score=score,
            ),
        )


class DuplicateCandidateStrategy(InjectedStrategy):
    def evaluate(self, selected, stock_series, benchmark, regime):
        result = super().evaluate(selected, stock_series, benchmark, regime)
        return result + result


class ScreeningPluginContractTest(unittest.TestCase):
    def test_rejects_duplicate_candidate_identity_deterministically(self):
        aapl = instrument()
        msft = instrument("MSFT")
        members = (
            UniverseMember(msft, "fixture", AS_OF.date()),
            UniverseMember(aapl, "fixture", AS_OF.date()),
        )
        messages = []
        for universe in (members, tuple(reversed(members))):
            with self.assertRaisesRegex(
                ValueError, "duplicate candidate identity"
            ) as raised:
                screen_candidates(
                    universe,
                    {aapl: series(), msft: series("MSFT")},
                    series("SPY"),
                    regime_result(),
                    strategy=DuplicateCandidateStrategy(),
                )
            messages.append(str(raised.exception))
        self.assertEqual(messages[0], messages[1])

    def test_rejects_malformed_strategy_contract(self):
        aapl = instrument()
        member = UniverseMember(aapl, "fixture", AS_OF.date())
        malformed = (
            ("strategy_id", " ", "strategy_id"),
            ("strategy_id", 7, "strategy_id"),
            ("supported_triggers", set({TriggerType.BREAKOUT}), "supported_triggers"),
            ("supported_triggers", frozenset(), "supported_triggers"),
            ("supported_triggers", frozenset({"breakout"}), "supported_triggers"),
            ("evaluate", None, "evaluate"),
        )
        for attribute, invalid_value, message in malformed:
            strategy = InjectedStrategy()
            setattr(strategy, attribute, invalid_value)
            with self.subTest(attribute=attribute, invalid_value=invalid_value):
                with self.assertRaisesRegex(ValueError, message):
                    screen_candidates(
                        (member,),
                        {aapl: series()},
                        series("SPY"),
                        regime_result(),
                        strategy=strategy,
                    )

    def test_injected_strategy_is_order_independent_and_sorted_by_score_then_symbol(self):
        aapl = instrument("AAPL")
        msft = instrument("MSFT")
        nvda = instrument("NVDA")
        forward = (
            UniverseMember(nvda, "fixture", AS_OF.date()),
            UniverseMember(msft, "fixture", AS_OF.date()),
            UniverseMember(aapl, "fixture", AS_OF.date()),
        )
        stock_series = {
            aapl: series("AAPL"),
            msft: series("MSFT"),
            nvda: series("NVDA"),
        }

        first = screen_candidates(
            forward,
            stock_series,
            series("SPY"),
            regime_result(),
            strategy=InjectedStrategy(),
        )
        second = screen_candidates(
            tuple(reversed(forward)),
            stock_series,
            series("SPY"),
            regime_result(),
            strategy=InjectedStrategy(),
        )

        self.assertIsInstance(InjectedStrategy(), ScreeningStrategy)
        self.assertEqual(first, second)
        self.assertEqual(
            tuple(value.instrument.symbol for value in first),
            ("AAPL", "MSFT", "NVDA"),
        )

    def test_rejects_input_series_market_currency_or_symbol_mismatch(self):
        aapl = instrument()
        member = UniverseMember(aapl, "fixture", AS_OF.date())
        mismatches = (
            series("AAPL", market=Market.KR, currency="KRW"),
            series("MSFT"),
        )
        for mismatched in mismatches:
            with self.subTest(series=mismatched):
                with self.assertRaisesRegex(ValueError, "series must match instrument"):
                    screen_candidates(
                        (member,),
                        {aapl: mismatched},
                        series("SPY"),
                        regime_result(),
                        strategy=InjectedStrategy(),
                    )

    def test_rejects_strategy_candidate_market_currency_or_symbol_mismatch(self):
        aapl = instrument()
        member = UniverseMember(aapl, "fixture", AS_OF.date())
        mismatched_outputs = (
            instrument("MSFT"),
            Instrument(
                symbol="005930",
                market=Market.KR,
                exchange="XKRX",
                currency="KRW",
                name="Samsung Electronics",
                sector="Technology",
                lot_size=Decimal("1"),
                price_precision=0,
            ),
        )
        for mismatched in mismatched_outputs:
            with self.subTest(instrument=mismatched):
                with self.assertRaisesRegex(ValueError, "candidate must match instrument"):
                    screen_candidates(
                        (member,),
                        {aapl: series()},
                        series("SPY"),
                        regime_result(),
                        strategy=InjectedStrategy(mismatched),
                    )


class OneilTrendStrategyTest(unittest.TestCase):
    def test_screening_skips_short_stock_history_but_keeps_valid_member(self):
        aapl = trend_instrument("AAPL", Market.US)
        msft = trend_instrument("MSFT", Market.US)
        spy = trend_instrument("SPY", Market.US)
        stock_closes = [
            Decimal("100") + Decimal(index) / Decimal("10")
            for index in range(259)
        ] + [Decimal("140")]
        benchmark_closes = [
            Decimal("100") + Decimal(index) / Decimal("20")
            for index in range(260)
        ]
        valid_stock = trend_series(
            aapl, stock_closes, ["1000000"] * 259 + ["3000000"]
        )
        short_stock = trend_series(
            msft, stock_closes[:251], ["1000000"] * 251
        )
        benchmark = trend_series(spy, benchmark_closes, ["1000000"] * 260)

        results = screen_candidates(
            (
                UniverseMember(msft, "fixture", AS_OF.date()),
                UniverseMember(aapl, "fixture", AS_OF.date()),
            ),
            {msft: short_stock, aapl: valid_stock},
            benchmark,
            regime_result(),
            strategy=OneilTrendStrategy(),
        )

        self.assertTrue(results)
        self.assertEqual(
            {value.instrument.symbol for value in results}, {"AAPL"}
        )

    def test_screening_keeps_insufficient_benchmark_history_fatal(self):
        aapl = trend_instrument("AAPL", Market.US)
        spy = trend_instrument("SPY", Market.US)
        stock_closes = [Decimal("100") + Decimal(index) for index in range(252)]
        valid_stock = trend_series(aapl, stock_closes, ["1000000"] * 252)
        short_benchmark = trend_series(
            spy, stock_closes[:20], ["1000000"] * 20
        )

        with self.assertRaisesRegex(ValueError, "21 benchmark sessions"):
            screen_candidates(
                (UniverseMember(aapl, "fixture", AS_OF.date()),),
                {aapl: valid_stock},
                short_benchmark,
                regime_result(),
                strategy=OneilTrendStrategy(),
            )

    def test_us_breakout_calculates_features_once_and_emits_distinct_triggers(self):
        aapl = trend_instrument("AAPL", Market.US)
        spy = trend_instrument("SPY", Market.US)
        stock_closes = [Decimal("100") + Decimal(index) / Decimal("10") for index in range(259)] + [Decimal("140")]
        benchmark_closes = [Decimal("100") + Decimal(index) / Decimal("20") for index in range(260)]
        stock = trend_series(aapl, stock_closes, ["1000000"] * 259 + ["3000000"])
        benchmark = trend_series(spy, benchmark_closes, ["1000000"] * 260)

        results = OneilTrendStrategy().evaluate(
            aapl,
            stock,
            benchmark,
            regime_result(),
        )

        by_trigger = {value.trigger_type: value for value in results}
        self.assertIn(TriggerType.BREAKOUT, by_trigger)
        self.assertIn(TriggerType.VOLUME_SURGE, by_trigger)
        self.assertIn(TriggerType.RELATIVE_STRENGTH, by_trigger)
        self.assertEqual(len(by_trigger), len(results))
        features = by_trigger[TriggerType.BREAKOUT].feature_values
        self.assertEqual(features["volume_ratio"], Decimal("3"))
        self.assertGreater(features["price_vs_sma20_pct"], Decimal("0"))
        self.assertGreater(features["price_vs_sma50_pct"], Decimal("0"))
        self.assertEqual(features["high_52w_distance_pct"], Decimal("0"))
        self.assertGreater(features["relative_strength_pct"], Decimal("0"))
        self.assertGreater(features["momentum_pct"], Decimal("0"))
        self.assertGreaterEqual(features["volatility_pct"], Decimal("0"))
        self.assertEqual(features["pullback_depth_pct"], Decimal("0"))
        self.assertNotEqual(
            by_trigger[TriggerType.BREAKOUT].component_scores,
            by_trigger[TriggerType.VOLUME_SURGE].component_scores,
        )

    def test_kr_oversold_rebound_uses_whole_prices_and_a_distinct_trigger(self):
        samsung = trend_instrument("005930", Market.KR)
        kospi = trend_instrument("069500", Market.KR)
        rising = [Decimal("10000") + Decimal(index * 20) for index in range(240)]
        decline = [Decimal("14800") - Decimal(index * 100) for index in range(19)]
        stock_closes = rising + decline + [Decimal("13200")]
        benchmark_closes = [Decimal("10000") + Decimal(index * 5) for index in range(260)]
        stock = trend_series(samsung, stock_closes, ["1000000"] * 260)
        benchmark = trend_series(kospi, benchmark_closes, ["1000000"] * 260)

        results = OneilTrendStrategy().evaluate(
            samsung,
            stock,
            benchmark,
            regime_result(Regime.STRONG_BEAR, Market.KR),
        )

        rebound = next(
            value
            for value in results
            if value.trigger_type is TriggerType.OVERSOLD_REBOUND
        )
        self.assertEqual(rebound.instrument.market, Market.KR)
        self.assertEqual(rebound.reference_price, rebound.reference_price.to_integral_value())
        self.assertEqual(rebound.stop_price, rebound.stop_price.to_integral_value())
        self.assertEqual(rebound.target_price, rebound.target_price.to_integral_value())
        self.assertGreater(rebound.feature_values["pullback_depth_pct"], Decimal("8"))
        self.assertGreater(rebound.feature_values["latest_return_pct"], Decimal("0"))

class RegimeDomainContractTest(unittest.TestCase):
    def test_trigger_type_contract_is_exact(self):
        self.assertEqual(
            tuple(trigger.value for trigger in TriggerType),
            (
                "breakout",
                "pullback",
                "volume_surge",
                "relative_strength",
                "oversold_rebound",
            ),
        )

    def test_candidate_copies_mutable_inputs_into_immutable_mappings(self):
        features = {"volume_ratio": Decimal("1.8")}
        components = {"volume": Decimal("8")}
        value = candidate(feature_values=features, component_scores=components)

        features["volume_ratio"] = Decimal("99")
        components["volume"] = Decimal("0")

        self.assertEqual(value.feature_values["volume_ratio"], Decimal("1.8"))
        self.assertEqual(value.component_scores["volume"], Decimal("8"))
        with self.assertRaises(TypeError):
            value.feature_values["new"] = True
        with self.assertRaises(FrozenInstanceError):
            value.final_score = Decimal("9")

    def test_candidate_validates_price_geometry_and_stored_risk_reward(self):
        invalid = (
            ({"stop_price": Decimal("100")}, "stop_price must be below reference_price"),
            ({"target_price": Decimal("100")}, "target_price must be above reference_price"),
            ({"risk_reward_ratio": Decimal("1.98")}, "risk_reward_ratio must match prices"),
        )
        for overrides, message in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, message):
                    candidate(**overrides)

    def test_candidate_rejects_scores_above_ten(self):
        with self.assertRaisesRegex(ValueError, "final_score.*10"):
            candidate(final_score=Decimal("10.01"))

    def test_candidate_prices_must_match_instrument_precision(self):
        for field_name in ("reference_price", "stop_price", "target_price"):
            with self.subTest(field_name=field_name):
                values = {
                    "reference_price": Decimal("100.00"),
                    "stop_price": Decimal("93.00"),
                    "target_price": Decimal("114.00"),
                }
                values[field_name] += Decimal("0.001")
                with self.assertRaisesRegex(
                    ValueError, f"{field_name}.*price_precision"
                ):
                    candidate(**values)

    def test_policy_decision_and_entry_context_are_frozen(self):
        selected_policy = policy()
        selected_candidate = candidate()
        decision = EntryDecision(
            candidate=selected_candidate,
            allowed=True,
            analysis_score=Decimal("8"),
            reasons=(),
            policy=selected_policy,
        )
        context = EntryContext(
            client_order_id="cycle-1:AAPL:BUY",
            run_id="cycle-1",
            candidate=selected_candidate,
            strategy_id="oneil_trend_v1",
            policy=selected_policy,
        )

        with self.assertRaises(FrozenInstanceError):
            decision.allowed = False
        with self.assertRaises(FrozenInstanceError):
            context.run_id = "cycle-2"


class RegimePolicyTest(unittest.TestCase):
    def test_policy_table_has_exact_initial_teaching_rows(self):
        expected = {
            Regime.STRONG_BULL: (
                frozenset(
                    {
                        TriggerType.BREAKOUT,
                        TriggerType.PULLBACK,
                        TriggerType.VOLUME_SURGE,
                        TriggerType.RELATIVE_STRENGTH,
                    }
                ),
                "6.0", "6", "1.2", "7", "1.0", 10, "10", "8",
            ),
            Regime.MODERATE_BULL: (
                frozenset(
                    {
                        TriggerType.BREAKOUT,
                        TriggerType.PULLBACK,
                        TriggerType.VOLUME_SURGE,
                        TriggerType.RELATIVE_STRENGTH,
                    }
                ),
                "6.5", "6", "1.3", "7", "0.8", 8, "20", "8",
            ),
            Regime.SIDEWAYS: (
                frozenset(
                    {
                        TriggerType.PULLBACK,
                        TriggerType.VOLUME_SURGE,
                        TriggerType.OVERSOLD_REBOUND,
                    }
                ),
                "7.0", "7", "1.5", "6", "0.6", 6, "35", "5",
            ),
            Regime.MODERATE_BEAR: (
                frozenset(
                    {
                        TriggerType.OVERSOLD_REBOUND,
                        TriggerType.RELATIVE_STRENGTH,
                    }
                ),
                "8.0", "8", "1.8", "5", "0.4", 3, "55", "5",
            ),
            Regime.STRONG_BEAR: (
                frozenset({TriggerType.OVERSOLD_REBOUND}),
                "9.0", "9", "2.0", "5", "0.25", 1, "75", "5",
            ),
        }
        for regime, row in expected.items():
            with self.subTest(regime=regime):
                selected = policy_for(regime)
                self.assertEqual(
                    (
                        selected.active_triggers,
                        selected.minimum_candidate_score,
                        selected.minimum_analysis_score,
                        selected.minimum_risk_reward,
                        selected.maximum_stop_pct,
                        selected.account_risk_pct,
                        selected.maximum_slots,
                        selected.minimum_cash_pct,
                        selected.trailing_pct,
                    ),
                    (row[0], *(Decimal(value) for value in row[1:6]), row[6], *(Decimal(value) for value in row[7:])),
                )

    def test_bear_policies_never_lower_safety_or_raise_exposure(self):
        ordered = tuple(policy_for(regime) for regime in Regime)
        for safer, stricter in zip(ordered, ordered[1:]):
            self.assertGreaterEqual(
                stricter.minimum_candidate_score,
                safer.minimum_candidate_score,
            )
            self.assertGreaterEqual(
                stricter.minimum_analysis_score,
                safer.minimum_analysis_score,
            )
            self.assertGreaterEqual(
                stricter.minimum_risk_reward,
                safer.minimum_risk_reward,
            )
            self.assertLessEqual(stricter.maximum_stop_pct, safer.maximum_stop_pct)
            self.assertLessEqual(stricter.account_risk_pct, safer.account_risk_pct)
            self.assertLessEqual(stricter.maximum_slots, safer.maximum_slots)
            self.assertGreaterEqual(stricter.minimum_cash_pct, safer.minimum_cash_pct)

    def test_llm_enter_cannot_override_quantitative_gate(self):
        selected_candidate = candidate(
            trigger_type=TriggerType.OVERSOLD_REBOUND,
            regime=Regime.STRONG_BEAR,
            final_score=Decimal("7.9"),
            target_price=Decimal("108.4"),
            risk_reward_ratio=Decimal("1.2"),
        )

        decision = gate_entry(
            selected_candidate,
            analysis_score=10,
            llm_enter=True,
            policy=policy_for(Regime.STRONG_BEAR),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.reasons,
            (
                "candidate_score_below_floor",
                "risk_reward_below_floor",
                "stop_too_wide",
            ),
        )

    def test_gate_reports_all_failures_in_stable_order_and_llm_may_only_veto(self):
        selected_candidate = candidate()
        weak_policy = RegimePolicy(
            active_triggers=frozenset({TriggerType.OVERSOLD_REBOUND}),
            minimum_candidate_score=Decimal("9"),
            minimum_analysis_score=Decimal("4"),
            minimum_risk_reward=Decimal("3"),
            maximum_stop_pct=Decimal("5"),
            account_risk_pct=Decimal("0.5"),
            maximum_slots=2,
            minimum_cash_pct=Decimal("50"),
            trailing_pct=Decimal("5"),
        )
        decision = gate_entry(
            selected_candidate,
            analysis_score=5,
            llm_enter=False,
            policy=weak_policy,
        )
        self.assertEqual(
            decision.reasons,
            (
                "trigger_not_active",
                "candidate_score_below_floor",
                "analysis_score_below_floor",
                "risk_reward_below_floor",
                "stop_too_wide",
                "llm_veto",
            ),
        )

        approved = gate_entry(selected_candidate, analysis_score=8, llm_enter=True)
        vetoed = gate_entry(selected_candidate, analysis_score=8, llm_enter=False)
        self.assertTrue(approved.allowed)
        self.assertEqual(vetoed.reasons, ("llm_veto",))

    def test_gate_rejects_ambiguous_runtime_score_and_llm_types(self):
        with self.assertRaisesRegex(ValueError, "analysis_score"):
            gate_entry(candidate(), analysis_score=True)
        with self.assertRaisesRegex(ValueError, "llm_enter"):
            gate_entry(candidate(), analysis_score=8, llm_enter="yes")


if __name__ == "__main__":
    unittest.main()
