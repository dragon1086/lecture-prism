from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from prism_core import (
    DailyBar,
    IndexBundle,
    InsufficientMarketHistory,
    Market,
    MarketSeries,
    PulseState,
    Regime,
    RegimeResult,
    classify_market_regime,
)
from prism_core.regime import (
    _breadth_state,
    _distribution_days,
    _drawdown,
    _pulse_state,
    _realized_volatility,
    _return_pct,
    _sma,
)


FIXED_AS_OF = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)


def bars(
    closes: tuple[str, ...], volumes: tuple[str, ...] | None = None
) -> tuple[DailyBar, ...]:
    if volumes is None:
        volumes = tuple("100" for _ in closes)
    start = date(2026, 1, 1)
    result = []
    for index, (close_text, volume_text) in enumerate(zip(closes, volumes)):
        close = Decimal(close_text)
        result.append(
            DailyBar(
                session_date=start + timedelta(days=index),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal(volume_text),
            )
        )
    return tuple(result)


def market_series(
    market: Market,
    symbol: str,
    closes: tuple[Decimal, ...],
    *,
    volumes: tuple[Decimal, ...] | None = None,
) -> MarketSeries:
    if volumes is None:
        volumes = tuple(Decimal(1_000_000 + index) for index in range(len(closes)))
    start = date(2025, 1, 1)
    daily_bars = tuple(
        DailyBar(
            session_date=start + timedelta(days=index),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=volume,
        )
        for index, (close, volume) in enumerate(zip(closes, volumes))
    )
    return MarketSeries(
        market=market,
        symbol=symbol,
        currency="KRW" if market is Market.KR else "USD",
        price_precision=2,
        bars=daily_bars,
        fetched_at=FIXED_AS_OF,
        source="fixture:regime-test",
        is_fixture=True,
    )


def kr_bundle(tail: tuple[str, ...], *, history: int = 120) -> IndexBundle:
    closes = tuple(Decimal("100") for _ in range(history)) + tuple(
        Decimal(value) for value in tail
    )
    return IndexBundle(
        primary=market_series(Market.KR, "KOSPI", closes),
        secondary=market_series(Market.KR, "KOSDAQ", closes),
        breadth_ratio=Decimal("0.55"),
    )


def linear_tail(start: str, step: str, *, periods: int = 20) -> tuple[Decimal, ...]:
    origin = Decimal(start)
    increment = Decimal(step)
    return tuple(origin + increment * index for index in range(periods + 1))


def us_bundle(tail: tuple[Decimal, ...], *, vix: str) -> IndexBundle:
    closes = tuple(Decimal("100") for _ in range(200)) + tail
    return IndexBundle(
        primary=market_series(Market.US, "SPX", closes),
        secondary=market_series(Market.US, "NASDAQ", closes),
        volatility=market_series(
            Market.US,
            "VIX",
            tuple(Decimal(vix) for _ in range(20)),
        ),
        breadth_ratio=Decimal("0.55"),
    )


class MarketRegimeContractTest(unittest.TestCase):
    def test_public_result_contract_uses_stable_values_and_is_frozen(self):
        self.assertEqual(
            [regime.value for regime in Regime],
            [
                "strong_bull",
                "moderate_bull",
                "sideways",
                "moderate_bear",
                "strong_bear",
            ],
        )
        self.assertEqual(
            [pulse.value for pulse in PulseState],
            ["UPTREND", "UNDER_PRESSURE", "CORRECTION"],
        )

        result = RegimeResult(
            market=Market.US,
            as_of=FIXED_AS_OF,
            regime=Regime.MODERATE_BULL,
            confidence=Decimal("0.75"),
            pulse=PulseState.UPTREND,
            metrics={"close": Decimal("100")},
            reasons=("above_primary_ma",),
            source="fixture:test",
        )

        with self.assertRaises((AttributeError, TypeError)):
            result.regime = Regime.SIDEWAYS

        with self.assertRaises(TypeError):
            result.metrics["close"] = Decimal("101")

    def test_result_rejects_mutable_or_mistyped_metric_entries(self):
        invalid_metrics = (
            {"mutable": []},
            {"boolean": True},
            {1: "non-string key"},
        )

        for metrics in invalid_metrics:
            with self.subTest(metrics=metrics), self.assertRaises(ValueError):
                RegimeResult(
                    market=Market.US,
                    as_of=FIXED_AS_OF,
                    regime=Regime.SIDEWAYS,
                    confidence=Decimal("0.60"),
                    pulse=PulseState.UPTREND,
                    metrics=metrics,
                    reasons=("contract_test",),
                    source="fixture:test",
                )


class MarketRegimeHelperTest(unittest.TestCase):
    def test_decimal_price_helpers_have_explicit_percentage_semantics(self):
        rising = bars(("100", "110", "121"))
        falling = bars(("100", "120", "90"))

        self.assertEqual(_sma(rising, 2), Decimal("115.5"))
        self.assertEqual(_return_pct(rising, 2), Decimal("21.00"))
        self.assertEqual(_realized_volatility(rising, 2), Decimal("0"))
        self.assertEqual(_drawdown(falling, 3), Decimal("25.00"))

    def test_distribution_days_require_a_lower_close_and_higher_volume(self):
        observations = bars(
            ("100", "99", "100", "98"),
            ("100", "110", "120", "130"),
        )

        self.assertEqual(_distribution_days(observations, 3), 2)

    def test_breadth_state_is_explicit_when_observation_is_missing(self):
        self.assertEqual(_breadth_state(None), "unavailable")
        self.assertEqual(_breadth_state(Decimal("0.44")), "weak")
        self.assertEqual(_breadth_state(Decimal("0.50")), "neutral")
        self.assertEqual(_breadth_state(Decimal("0.56")), "broad")

    def test_helpers_fail_closed_when_the_requested_window_is_missing(self):
        with self.assertRaises(InsufficientMarketHistory):
            _sma(bars(("100",)), 2)


class MarketPulseBoundaryTest(unittest.TestCase):
    def test_distribution_day_boundaries_map_to_pulse_states(self):
        cases = (
            (0, PulseState.UPTREND),
            (3, PulseState.UPTREND),
            (4, PulseState.UNDER_PRESSURE),
            (5, PulseState.UNDER_PRESSURE),
            (6, PulseState.CORRECTION),
        )

        for distribution_days, expected in cases:
            with self.subTest(distribution_days=distribution_days):
                self.assertIs(
                    _pulse_state(distribution_days, Decimal("0")), expected
                )

    def test_eight_percent_drawdown_is_a_correction(self):
        self.assertIs(
            _pulse_state(0, Decimal("7.99")), PulseState.UPTREND
        )
        self.assertIs(
            _pulse_state(0, Decimal("8")), PulseState.CORRECTION
        )


class MarketRegimeSafetyTest(unittest.TestCase):
    def test_bear_market_bounce_below_primary_ma_never_becomes_bull(self):
        history = tuple(Decimal("120") for _ in range(200))
        rally = linear_tail("90", "0.5")
        closes = history + rally
        bundle = IndexBundle(
            primary=market_series(Market.US, "SPX", closes),
            secondary=market_series(Market.US, "NASDAQ", closes),
            volatility=market_series(
                Market.US,
                "VIX",
                tuple(Decimal("19.99") for _ in range(20)),
            ),
            breadth_ratio=Decimal("0.55"),
        )

        result = classify_market_regime(bundle, as_of=FIXED_AS_OF)

        self.assertIn(
            result.regime,
            {Regime.SIDEWAYS, Regime.MODERATE_BEAR, Regime.STRONG_BEAR},
        )

    def test_high_volatility_drawdown_only_downgrades_bull(self):
        bull_tail = (
            Decimal("100"),
            Decimal("120"),
        ) + tuple(Decimal("110") for _ in range(19))
        downgraded = classify_market_regime(
            us_bundle(bull_tail, vix="30"), as_of=FIXED_AS_OF
        )
        bear = classify_market_regime(
            us_bundle(linear_tail("100", "-0.25"), vix="30"),
            as_of=FIXED_AS_OF,
        )

        self.assertIs(downgraded.regime, Regime.SIDEWAYS)
        self.assertIn("high_vol_drawdown", downgraded.reasons)
        self.assertIs(bear.regime, Regime.STRONG_BEAR)
        self.assertNotIn("high_vol_drawdown", bear.reasons)

    def test_classification_is_exactly_deterministic(self):
        bundle = us_bundle(linear_tail("100", "0.15"), vix="19.99")

        first = classify_market_regime(bundle, as_of=FIXED_AS_OF)
        second = classify_market_regime(bundle, as_of=FIXED_AS_OF)

        self.assertEqual(first, second)


class KoreanMarketRegimeTest(unittest.TestCase):
    def test_kr_table_covers_all_five_regimes_at_return_boundaries(self):
        cases = (
            (
                ("100", "100.5", "101", "101.5", "102", "102.5", "103", "103.5", "104", "104.5", "105"),
                Regime.STRONG_BULL,
            ),
            (
                ("100", "100.2", "100.4", "100.6", "100.8", "101", "101.2", "101.4", "101.6", "101.8", "102"),
                Regime.MODERATE_BULL,
            ),
            (
                ("103", "102.8", "102.6", "102.4", "102.2", "102", "101.8", "101.6", "101.4", "101.2", "101"),
                Regime.SIDEWAYS,
            ),
            (
                ("100", "99.8", "99.6", "99.4", "99.2", "99", "98.8", "98.6", "98.4", "98.2", "98"),
                Regime.MODERATE_BEAR,
            ),
            (
                ("100", "99.5", "99", "98.5", "98", "97.5", "97", "96.5", "96", "95.5", "95"),
                Regime.STRONG_BEAR,
            ),
        )

        for tail, expected in cases:
            with self.subTest(expected=expected):
                result = classify_market_regime(
                    kr_bundle(tail), as_of=FIXED_AS_OF
                )
                self.assertIs(result.regime, expected)
                self.assertEqual(result.metrics["primary_ma_period"], 120)
                self.assertEqual(result.metrics["secondary_ma_period"], 60)
                self.assertGreaterEqual(result.confidence, Decimal("0"))
                self.assertLessEqual(result.confidence, Decimal("1"))

    def test_kr_missing_120_session_history_fails_closed(self):
        with self.assertRaises(InsufficientMarketHistory):
            classify_market_regime(
                kr_bundle((), history=119), as_of=FIXED_AS_OF
            )


class UnitedStatesMarketRegimeTest(unittest.TestCase):
    def test_us_table_covers_all_five_regimes_with_200_50_20_windows(self):
        cases = (
            (linear_tail("100", "0.15"), "19.99", Regime.STRONG_BULL),
            (linear_tail("100", "0.10"), "19.99", Regime.MODERATE_BULL),
            (linear_tail("103", "-0.10"), "19.99", Regime.SIDEWAYS),
            (linear_tail("100", "-0.10"), "20", Regime.MODERATE_BEAR),
            (linear_tail("100", "-0.25"), "20", Regime.STRONG_BEAR),
        )

        for tail, vix, expected in cases:
            with self.subTest(expected=expected):
                result = classify_market_regime(
                    us_bundle(tail, vix=vix), as_of=FIXED_AS_OF
                )
                self.assertIs(result.regime, expected)
                self.assertEqual(result.metrics["primary_ma_period"], 200)
                self.assertEqual(result.metrics["secondary_ma_period"], 50)
                self.assertEqual(result.metrics["momentum_days"], 20)

    def test_us_strong_bull_requires_vix_strictly_below_20(self):
        bullish_tail = linear_tail("100", "0.15")

        below_20 = classify_market_regime(
            us_bundle(bullish_tail, vix="19.99"), as_of=FIXED_AS_OF
        )
        at_20 = classify_market_regime(
            us_bundle(bullish_tail, vix="20"), as_of=FIXED_AS_OF
        )

        self.assertIs(below_20.regime, Regime.STRONG_BULL)
        self.assertIs(at_20.regime, Regime.MODERATE_BULL)

    def test_us_strong_bear_requires_vix_at_least_20(self):
        bearish_tail = linear_tail("100", "-0.25")

        below_20 = classify_market_regime(
            us_bundle(bearish_tail, vix="19.99"), as_of=FIXED_AS_OF
        )
        at_20 = classify_market_regime(
            us_bundle(bearish_tail, vix="20"), as_of=FIXED_AS_OF
        )

        self.assertIs(below_20.regime, Regime.MODERATE_BEAR)
        self.assertIs(at_20.regime, Regime.STRONG_BEAR)


if __name__ == "__main__":
    unittest.main()
