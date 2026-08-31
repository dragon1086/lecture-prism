from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import sys
import unittest

from prism_core.domain import Instrument, Market, Position
from prism_core.market_data import (
    FIXTURE_AS_OF,
    DailyBar,
    FixtureMarketDataProvider,
    FixtureUniverseProvider,
    InvalidMarketData,
    MarketDataUnavailable,
    MarketSeries,
    UniverseMember,
    YFinanceMarketDataProvider,
    validate_series_for_profile,
)


class _FakeHistory:
    def __init__(self, rows):
        self._rows = tuple(rows)
        self.empty = not self._rows

    def iterrows(self):
        return iter(self._rows)


class _FakeTicker:
    def __init__(self, module, symbol):
        self._module = module
        self._symbol = symbol

    def history(self, **kwargs):
        self._module.history_calls.append((self._symbol, kwargs))
        return self._module.histories[self._symbol]


class _FakeYFinance:
    def __init__(self, histories):
        self.histories = histories
        self.ticker_calls = []
        self.history_calls = []

    def Ticker(self, symbol):
        self.ticker_calls.append(symbol)
        return _FakeTicker(self, symbol)


def _fake_history(*, count=225, integral=False):
    start = FIXTURE_AS_OF - timedelta(days=300)
    rows = []
    for index in range(count):
        session = start + timedelta(days=index)
        close = Decimal("100") + Decimal(index)
        if not integral:
            close += Decimal("0.25")
        rows.append(
            (
                session,
                {
                    "Open": close - (Decimal("1") if integral else Decimal("0.20")),
                    "High": close + (Decimal("2") if integral else Decimal("0.50")),
                    "Low": close - (Decimal("2") if integral else Decimal("0.50")),
                    "Close": close,
                    "Volume": Decimal(1_000_000 + index),
                },
            )
        )
    return _FakeHistory(rows)


def _fake_float_tail_history(*, count=225):
    start = FIXTURE_AS_OF - timedelta(days=300)
    rows = []
    for index in range(count):
        close = 100.23999786376953 + index
        rows.append(
            (
                start + timedelta(days=index),
                {
                    "Open": close - 0.11,
                    "High": close + 0.21,
                    "Low": close - 0.29,
                    "Close": close,
                    "Volume": 1_000_000.0 + index,
                },
            )
        )
    return _FakeHistory(rows)


class MarketDataProviderTest(unittest.TestCase):
    def test_task_one_public_api_is_exported_from_package(self):
        import prism_core

        public_names = (
            "Instrument",
            "DailyBar",
            "MarketSeries",
            "IndexBundle",
            "UniverseMember",
            "UniverseProvider",
            "FixtureUniverseProvider",
            "MarketDataProvider",
            "FixtureMarketDataProvider",
            "YFinanceMarketDataProvider",
            "InvalidMarketData",
            "MarketDataUnavailable",
            "validate_series_for_profile",
        )
        for name in public_names:
            with self.subTest(name=name):
                self.assertTrue(hasattr(prism_core, name), name)
                self.assertIn(name, prism_core.__all__)

    def test_kr_and_us_series_preserve_market_currency_and_decimal_contract(self):
        provider = FixtureMarketDataProvider.standard()

        kr = provider.index_bundle(Market.KR, as_of=FIXTURE_AS_OF)
        us = provider.index_bundle(Market.US, as_of=FIXTURE_AS_OF)

        self.assertEqual((kr.primary.market, kr.primary.currency), (Market.KR, "KRW"))
        self.assertEqual((us.primary.market, us.primary.currency), (Market.US, "USD"))
        self.assertEqual((kr.primary.price_precision, us.primary.price_precision), (2, 2))
        self.assertTrue(all(bar.close == bar.close.to_integral_value() for bar in kr.primary.bars))
        self.assertTrue(all(bar.close.is_finite() and bar.close > 0 for bar in us.primary.bars))

    def test_fixture_contains_long_index_and_stock_history_for_both_markets(self):
        provider = FixtureMarketDataProvider.standard()

        kr = provider.index_bundle(Market.KR, as_of=FIXTURE_AS_OF)
        us = provider.index_bundle(Market.US, as_of=FIXTURE_AS_OF)

        self.assertGreaterEqual(len(kr.primary.bars), 220)
        self.assertGreaterEqual(len(kr.secondary.bars), 220)
        self.assertIsNone(kr.volatility)
        self.assertGreaterEqual(len(us.primary.bars), 220)
        self.assertGreaterEqual(len(us.secondary.bars), 220)
        self.assertGreaterEqual(len(us.volatility.bars), 220)
        first_vix = us.volatility.bars[0]
        self.assertLess(abs(first_vix.open - first_vix.close), Decimal("5"))
        self.assertGreater(min(first_vix.open, first_vix.close), Decimal("0"))
        universe = FixtureUniverseProvider.standard()
        members = universe.members(
            Market.KR, as_of=FIXTURE_AS_OF
        ) + universe.members(Market.US, as_of=FIXTURE_AS_OF)
        self.assertEqual(
            {member.instrument.symbol for member in members},
            {"005930", "000660", "035420", "AAPL", "MSFT", "NVDA"},
        )
        for member in members:
            instrument = member.instrument
            series = provider.stock_series(instrument, as_of=FIXTURE_AS_OF)
            self.assertEqual((series.market, series.symbol), (instrument.market, instrument.symbol))
            self.assertEqual(series.price_precision, instrument.price_precision)
            self.assertGreaterEqual(len(series.bars), 220)

    def test_paper_and_live_reject_fixture_data(self):
        series = FixtureMarketDataProvider.standard().index_bundle(
            Market.US, as_of=FIXTURE_AS_OF
        ).primary

        for profile in ("paper", "live"):
            with self.subTest(profile=profile), self.assertRaisesRegex(
                MarketDataUnavailable, "non-fixture"
            ):
                validate_series_for_profile(series, profile, now=FIXTURE_AS_OF)

    def test_paper_and_live_reject_stale_non_fixture_data(self):
        fixture = FixtureMarketDataProvider.standard().index_bundle(
            Market.US, as_of=FIXTURE_AS_OF
        ).primary
        stale = replace(
            fixture,
            fetched_at=FIXTURE_AS_OF - timedelta(minutes=21),
            source="test-feed",
            is_fixture=False,
        )

        for profile in ("paper", "live"):
            with self.subTest(profile=profile), self.assertRaisesRegex(
                MarketDataUnavailable, "stale"
            ):
                validate_series_for_profile(stale, profile, now=FIXTURE_AS_OF)

    def test_paper_and_live_allow_one_expected_weekday_but_reject_two_missed_sessions(self):
        fixture = FixtureMarketDataProvider.standard().index_bundle(
            Market.US, as_of=FIXTURE_AS_OF
        ).primary
        cases = (
            (
                "friday_to_monday",
                date(2026, 6, 26),
                datetime(2026, 6, 29, 15, tzinfo=timezone.utc),
                False,
            ),
            (
                "friday_to_tuesday",
                date(2026, 6, 26),
                datetime(2026, 6, 30, 15, tzinfo=timezone.utc),
                True,
            ),
            (
                "monday_to_friday",
                date(2026, 6, 22),
                datetime(2026, 6, 26, 15, tzinfo=timezone.utc),
                True,
            ),
        )

        for profile in ("paper", "live"):
            for label, latest_date, now, should_reject in cases:
                delayed = replace(
                    fixture,
                    bars=tuple(
                        bar
                        for bar in fixture.bars
                        if bar.session_date <= latest_date
                    ),
                    fetched_at=now,
                    source="test-feed",
                    is_fixture=False,
                )
                with self.subTest(profile=profile, case=label):
                    if should_reject:
                        with self.assertRaisesRegex(
                            MarketDataUnavailable, "latest observation is stale"
                        ):
                            validate_series_for_profile(delayed, profile, now=now)
                    else:
                        validate_series_for_profile(delayed, profile, now=now)

    def test_future_dated_validation_orders_fixture_provenance_before_live_freshness(self):
        fixture = FixtureMarketDataProvider.standard().index_bundle(
            Market.US, as_of=FIXTURE_AS_OF
        ).primary
        future_fixture = replace(
            fixture,
            fetched_at=FIXTURE_AS_OF + timedelta(minutes=6),
        )

        for profile in ("classroom", "backtest"):
            with self.subTest(profile=profile), self.assertRaisesRegex(
                InvalidMarketData, "future-dated"
            ):
                validate_series_for_profile(
                    future_fixture, profile, now=FIXTURE_AS_OF
                )
        for profile in ("paper", "live"):
            with self.subTest(profile=profile), self.assertRaisesRegex(
                MarketDataUnavailable, "non-fixture"
            ):
                validate_series_for_profile(
                    future_fixture, profile, now=FIXTURE_AS_OF
                )

        future_non_fixture = replace(
            future_fixture,
            source="test-feed",
            is_fixture=False,
        )
        for profile in ("paper", "live"):
            with self.subTest(profile=profile, fixture=False), self.assertRaisesRegex(
                InvalidMarketData, "future-dated"
            ):
                validate_series_for_profile(
                    future_non_fixture, profile, now=FIXTURE_AS_OF
                )

    def test_classroom_accepts_fixture_but_rejects_duplicate_or_unsorted_bars(self):
        series = FixtureMarketDataProvider.standard().index_bundle(
            Market.KR, as_of=FIXTURE_AS_OF
        ).primary
        validate_series_for_profile(series, "classroom", now=FIXTURE_AS_OF)

        with self.assertRaisesRegex(InvalidMarketData, "strictly increasing"):
            MarketSeries(
                **{
                    **asdict(series),
                    "bars": (series.bars[1], series.bars[0], *series.bars[2:]),
                }
            )
        with self.assertRaisesRegex(InvalidMarketData, "strictly increasing"):
            MarketSeries(
                **{
                    **asdict(series),
                    "bars": (series.bars[0], series.bars[0], *series.bars[2:]),
                }
            )

    def test_market_series_rejects_currency_ohlc_volume_and_kr_fraction_violations(self):
        bars = tuple(
            DailyBar(
                session_date=date(2026, 1, day),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("105"),
                volume=Decimal("1000"),
            )
            for day in range(1, 21)
        )
        base = {
            "market": Market.KR,
            "symbol": "KOSPI",
            "currency": "KRW",
            "price_precision": 0,
            "bars": bars,
            "fetched_at": datetime(2026, 1, 20, tzinfo=timezone.utc),
            "source": "test-feed",
        }

        with self.assertRaisesRegex(InvalidMarketData, "currency"):
            MarketSeries(**{**base, "currency": "USD"})
        with self.assertRaisesRegex(InvalidMarketData, "whole number"):
            MarketSeries(
                **{
                    **base,
                    "bars": (
                        replace(bars[0], close=Decimal("105.5")),
                        *bars[1:],
                    ),
                }
            )
        for changes, message in (
            ({"high": Decimal("99")}, "OHLC"),
            ({"close": Decimal("NaN")}, "finite and positive"),
            ({"volume": Decimal("-1")}, "non-negative"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(InvalidMarketData, message):
                invalid_bar = replace(bars[0], **changes)
                MarketSeries(**{**base, "bars": (invalid_bar, *bars[1:])})

    def test_instrument_reuses_exact_market_contract_and_requires_metadata(self):
        valid = Instrument(
            "AAPL", Market.US, "XNAS", "usd", "Apple", "Technology", Decimal("1"), 2
        )
        self.assertEqual(valid.currency, "USD")

        invalid_cases = (
            ({"symbol": "aapl"}, "US symbol"),
            ({"currency": "KRW"}, "US order currency must be USD"),
            ({"exchange": ""}, "exchange"),
            ({"name": ""}, "name"),
            ({"sector": ""}, "sector"),
            ({"lot_size": Decimal("0")}, "lot_size must be positive"),
            ({"lot_size": Decimal("NaN")}, "lot_size must be a finite Decimal"),
        )
        defaults = asdict(valid)
        for changes, message in invalid_cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                Instrument(**{**defaults, **changes})
        with self.assertRaisesRegex(ValueError, "KR price_precision must be 0"):
            Instrument(
                "005930", Market.KR, "XKRX", "KRW", "Samsung", "Technology", Decimal("1"), 2
            )

    def test_fixture_universe_is_canonical_and_rejects_duplicates(self):
        provider = FixtureUniverseProvider.standard()
        members = provider.members(Market.US, as_of=FIXTURE_AS_OF)

        self.assertEqual(
            tuple(member.instrument.symbol for member in members),
            ("AAPL", "MSFT", "NVDA"),
        )
        duplicate = UniverseMember(
            members[0].instrument, "fixture", FIXTURE_AS_OF.date()
        )
        with self.assertRaisesRegex(InvalidMarketData, "duplicate"):
            FixtureUniverseProvider((duplicate, duplicate))
        with self.assertRaisesRegex(InvalidMarketData, "tuple"):
            FixtureUniverseProvider([duplicate])

    def test_yfinance_is_lazy_and_import_failure_never_returns_fixture(self):
        calls = []
        was_loaded = "yfinance" in sys.modules

        def fail_import(name):
            calls.append(name)
            raise ImportError("not installed")

        provider = YFinanceMarketDataProvider(import_module=fail_import)
        self.assertEqual(calls, [])

        with self.assertRaisesRegex(MarketDataUnavailable, "yfinance"):
            provider.index_bundle(Market.US, as_of=FIXTURE_AS_OF)
        self.assertEqual(calls, ["yfinance"])
        self.assertEqual("yfinance" in sys.modules, was_loaded)

    def test_yfinance_us_index_bundle_converts_all_indices_without_fixture_fallback(self):
        fake = _FakeYFinance(
            {
                "^GSPC": _fake_history(),
                "^IXIC": _fake_history(),
                "^VIX": _fake_history(),
            }
        )
        fetched_at = FIXTURE_AS_OF - timedelta(minutes=2)
        clock_calls = []

        def clock():
            clock_calls.append(None)
            return fetched_at

        provider = YFinanceMarketDataProvider(import_module=lambda _: fake, clock=clock)

        bundle = provider.index_bundle(Market.US, as_of=FIXTURE_AS_OF)

        self.assertEqual(fake.ticker_calls, ["^GSPC", "^IXIC", "^VIX"])
        expected_range = {
            "start": FIXTURE_AS_OF.date() - timedelta(days=731),
            "end": FIXTURE_AS_OF.date() + timedelta(days=1),
            "interval": "1d",
            "auto_adjust": False,
        }
        self.assertEqual(
            fake.history_calls,
            [
                ("^GSPC", expected_range),
                ("^IXIC", expected_range),
                ("^VIX", expected_range),
            ],
        )
        self.assertEqual(
            (bundle.primary.symbol, bundle.secondary.symbol, bundle.volatility.symbol),
            ("SP500", "NASDAQ", "VIX"),
        )
        for series in (bundle.primary, bundle.secondary, bundle.volatility):
            self.assertEqual((series.market, series.currency), (Market.US, "USD"))
            self.assertEqual(series.source, "yfinance")
            self.assertFalse(series.is_fixture)
            self.assertIsInstance(series.bars[0].close, Decimal)
            self.assertEqual(series.fetched_at, fetched_at)
        self.assertEqual(clock_calls, [None])

    def test_yfinance_stock_symbol_mapping_preserves_us_and_kr_price_contracts(self):
        fake = _FakeYFinance(
            {
                "AAPL": _fake_history(),
                "005930.KS": _fake_history(integral=True),
            }
        )
        provider = YFinanceMarketDataProvider(import_module=lambda _: fake)
        us = Instrument(
            "AAPL", Market.US, "XNAS", "USD", "Apple", "Technology", Decimal("1"), 2
        )
        kr = Instrument(
            "005930", Market.KR, "XKRX", "KRW", "Samsung", "Technology", Decimal("1"), 0
        )

        us_series = provider.stock_series(us, as_of=FIXTURE_AS_OF)
        kr_series = provider.stock_series(kr, as_of=FIXTURE_AS_OF)

        self.assertEqual(fake.ticker_calls, ["AAPL", "005930.KS"])
        expected_range = {
            "start": FIXTURE_AS_OF.date() - timedelta(days=731),
            "end": FIXTURE_AS_OF.date() + timedelta(days=1),
            "interval": "1d",
            "auto_adjust": False,
        }
        self.assertEqual(
            fake.history_calls,
            [("AAPL", expected_range), ("005930.KS", expected_range)],
        )
        self.assertEqual((us_series.symbol, us_series.currency), ("AAPL", "USD"))
        self.assertEqual((kr_series.symbol, kr_series.currency), ("005930", "KRW"))
        self.assertTrue(
            all(
                price == price.to_integral_value()
                for bar in kr_series.bars
                for price in (bar.open, bar.high, bar.low, bar.close)
            )
        )

    def test_yfinance_held_kr_position_resolves_ks_then_kq_without_context(self):
        fake = _FakeYFinance({"035420.KQ": _fake_history(integral=True)})
        provider = YFinanceMarketDataProvider(
            import_module=lambda _: fake,
            clock=lambda: FIXTURE_AS_OF,
        )
        position = Position(
            Market.KR,
            "035420",
            Decimal("1"),
            Decimal("200000"),
            "KRW",
            Decimal("210000"),
            "legacy",
            "legacy:KR:035420:BUY",
        )

        series = provider.held_position_series(position, as_of=FIXTURE_AS_OF)

        self.assertEqual(fake.ticker_calls, ["035420.KS", "035420.KQ"])
        self.assertEqual(
            (series.market, series.symbol, series.currency),
            (Market.KR, "035420", "KRW"),
        )

    def test_yfinance_kr_indices_allow_explicit_fractional_price_precision(self):
        fake = _FakeYFinance(
            {
                "^KS11": _fake_history(),
                "^KQ11": _fake_history(),
            }
        )
        provider = YFinanceMarketDataProvider(
            import_module=lambda _: fake,
            clock=lambda: FIXTURE_AS_OF,
        )

        bundle = provider.index_bundle(Market.KR, as_of=FIXTURE_AS_OF)

        self.assertIsNone(bundle.volatility)
        for series in (bundle.primary, bundle.secondary):
            self.assertEqual(series.price_precision, 2)
            self.assertTrue(
                any(bar.close != bar.close.to_integral_value() for bar in series.bars)
            )

    def test_yfinance_kr_stock_fractional_ohlc_fails_closed_at_instrument_precision(self):
        fake = _FakeYFinance({"005930.KS": _fake_history()})
        provider = YFinanceMarketDataProvider(
            import_module=lambda _: fake,
            clock=lambda: FIXTURE_AS_OF,
        )
        instrument = Instrument(
            "005930", Market.KR, "XKRX", "KRW", "Samsung", "Technology", Decimal("1"), 0
        )

        with self.assertRaises(MarketDataUnavailable):
            provider.stock_series(instrument, as_of=FIXTURE_AS_OF)

    def test_yfinance_quantizes_float_tails_to_declared_index_and_stock_precision(self):
        fake = _FakeYFinance(
            {
                symbol: _fake_float_tail_history()
                for symbol in (
                    "^GSPC",
                    "^IXIC",
                    "^VIX",
                    "^KS11",
                    "^KQ11",
                    "AAPL",
                )
            }
        )
        provider = YFinanceMarketDataProvider(
            import_module=lambda _: fake,
            clock=lambda: FIXTURE_AS_OF,
        )
        us_bundle = provider.index_bundle(Market.US, as_of=FIXTURE_AS_OF)
        kr_bundle = provider.index_bundle(Market.KR, as_of=FIXTURE_AS_OF)
        stock = provider.stock_series(
            Instrument(
                "AAPL",
                Market.US,
                "XNAS",
                "USD",
                "Apple",
                "Technology",
                Decimal("1"),
                2,
            ),
            as_of=FIXTURE_AS_OF,
        )

        series_values = (
            us_bundle.primary,
            us_bundle.secondary,
            us_bundle.volatility,
            kr_bundle.primary,
            kr_bundle.secondary,
            stock,
        )
        for series in series_values:
            self.assertEqual(series.price_precision, 2)
            first = series.bars[0]
            self.assertEqual(first.close, Decimal("100.24"))
            for bar in series.bars:
                for price in (bar.open, bar.high, bar.low, bar.close):
                    self.assertTrue(price.is_finite())
                    self.assertEqual(price, price.quantize(Decimal("0.01")))

    def test_yfinance_empty_or_short_history_fails_without_fixture_fallback(self):
        instrument = Instrument(
            "AAPL", Market.US, "XNAS", "USD", "Apple", "Technology", Decimal("1"), 2
        )
        for history in (_FakeHistory(()), _fake_history(count=19)):
            with self.subTest(count=len(history._rows)):
                fake = _FakeYFinance({"AAPL": history})
                provider = YFinanceMarketDataProvider(import_module=lambda _: fake)
                with self.assertRaises(MarketDataUnavailable):
                    provider.stock_series(instrument, as_of=FIXTURE_AS_OF)
                self.assertEqual(fake.ticker_calls, ["AAPL"])

    def test_yfinance_uses_injected_clock_but_cuts_bars_off_at_as_of(self):
        history = _fake_history(count=302)
        fake = _FakeYFinance({"AAPL": history})
        fetched_at = FIXTURE_AS_OF - timedelta(minutes=1)
        provider = YFinanceMarketDataProvider(
            import_module=lambda _: fake,
            clock=lambda: fetched_at,
        )
        instrument = Instrument(
            "AAPL", Market.US, "XNAS", "USD", "Apple", "Technology", Decimal("1"), 2
        )

        series = provider.stock_series(instrument, as_of=FIXTURE_AS_OF)

        self.assertEqual(series.fetched_at, fetched_at)
        self.assertEqual(series.bars[-1].session_date, FIXTURE_AS_OF.date())
        self.assertTrue(all(bar.session_date <= FIXTURE_AS_OF.date() for bar in series.bars))

    def test_unknown_profile_fails_closed(self):
        series = FixtureMarketDataProvider.standard().index_bundle(
            Market.US, as_of=FIXTURE_AS_OF
        ).primary
        with self.assertRaisesRegex(ValueError, "unsupported profile"):
            validate_series_for_profile(series, "production", now=FIXTURE_AS_OF)


if __name__ == "__main__":
    unittest.main()
