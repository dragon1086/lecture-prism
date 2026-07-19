from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import importlib
from typing import Any, Callable, Mapping, Protocol

from .domain import Instrument, Market


FIXTURE_AS_OF = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
_EXPECTED_CURRENCY = {Market.KR: "KRW", Market.US: "USD"}
_SUPPORTED_PROFILES = frozenset(
    {"mock", "classroom", "backtest", "real_data", "research", "paper", "live"}
)


class InvalidMarketData(ValueError):
    """A series violates its structural or market-specific contract."""


class MarketDataUnavailable(RuntimeError):
    """A provider cannot supply data safe for the requested profile."""


def _require_aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidMarketData(f"{name} must be a timezone-aware datetime")


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidMarketData(f"{name} is required")
    return value.strip()


@dataclass(frozen=True)
class DailyBar:
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.session_date, date) or isinstance(self.session_date, datetime):
            raise InvalidMarketData("session_date must be a date")
        for name in ("open", "high", "low", "close"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise InvalidMarketData(f"{name} must be finite and positive")
        if not isinstance(self.volume, Decimal) or not self.volume.is_finite() or self.volume < 0:
            raise InvalidMarketData("volume must be finite and non-negative")
        if not self.low <= self.open <= self.high or not self.low <= self.close <= self.high:
            raise InvalidMarketData("OHLC values must satisfy low <= open/close <= high")


@dataclass(frozen=True)
class MarketSeries:
    market: Market
    symbol: str
    currency: str
    price_precision: int
    bars: tuple[DailyBar, ...]
    fetched_at: datetime
    source: str
    is_fixture: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.market, Market):
            raise InvalidMarketData("market must be a Market")
        object.__setattr__(self, "symbol", _required_text(self.symbol, "symbol"))
        object.__setattr__(self, "source", _required_text(self.source, "source"))
        if not isinstance(self.currency, str):
            raise InvalidMarketData("currency is required")
        currency = self.currency.strip().upper()
        if currency != _EXPECTED_CURRENCY[self.market]:
            raise InvalidMarketData(f"{self.market.value} market data currency must be {_EXPECTED_CURRENCY[self.market]}")
        object.__setattr__(self, "currency", currency)
        if not isinstance(self.price_precision, int) or isinstance(
            self.price_precision, bool
        ) or self.price_precision < 0:
            raise InvalidMarketData(
                "price_precision must be a non-negative integer"
            )
        _require_aware(self.fetched_at, "fetched_at")
        if not isinstance(self.is_fixture, bool):
            raise InvalidMarketData("is_fixture must be a bool")
        if not isinstance(self.bars, tuple):
            raise InvalidMarketData("bars must be a tuple")
        normalized = []
        for bar in self.bars:
            if isinstance(bar, Mapping):
                try:
                    bar = DailyBar(**bar)
                except (TypeError, ValueError) as exc:
                    raise InvalidMarketData(f"invalid daily bar: {exc}") from exc
            if not isinstance(bar, DailyBar):
                raise InvalidMarketData("bars must contain DailyBar values")
            normalized.append(bar)
        bars = tuple(normalized)
        object.__setattr__(self, "bars", bars)
        if len(bars) < 20:
            raise InvalidMarketData("market series requires at least 20 bars")
        dates = tuple(bar.session_date for bar in bars)
        if any(left >= right for left, right in zip(dates, dates[1:])):
            raise InvalidMarketData("bar session dates must be strictly increasing and unique")
        for bar in bars:
            for name in ("open", "high", "low", "close"):
                value = getattr(bar, name)
                scaled = value.scaleb(self.price_precision)
                if scaled != scaled.to_integral_value():
                    if self.market is Market.KR and self.price_precision == 0:
                        raise InvalidMarketData(f"KR {name} must be a whole number")
                    raise InvalidMarketData(
                        f"{name} must align with price_precision {self.price_precision}"
                    )


@dataclass(frozen=True)
class IndexBundle:
    primary: MarketSeries
    secondary: MarketSeries
    volatility: MarketSeries | None = None
    breadth_ratio: Decimal | None = None

    def __post_init__(self) -> None:
        series = (self.primary, self.secondary) + ((self.volatility,) if self.volatility else ())
        if not all(isinstance(item, MarketSeries) for item in series):
            raise InvalidMarketData("index bundle values must be MarketSeries")
        if any(item.market is not self.primary.market for item in series):
            raise InvalidMarketData("index bundle markets must match")
        if any(item.currency != self.primary.currency for item in series):
            raise InvalidMarketData("index bundle currencies must match")
        if self.breadth_ratio is not None and (
            not isinstance(self.breadth_ratio, Decimal)
            or not self.breadth_ratio.is_finite()
            or not Decimal("0") <= self.breadth_ratio <= Decimal("1")
        ):
            raise InvalidMarketData("breadth_ratio must be a finite Decimal from 0 to 1")


@dataclass(frozen=True)
class UniverseMember:
    instrument: Instrument
    source: str
    as_of: date

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise InvalidMarketData("instrument must be an Instrument")
        object.__setattr__(self, "source", _required_text(self.source, "source"))
        if not isinstance(self.as_of, date) or isinstance(self.as_of, datetime):
            raise InvalidMarketData("as_of must be a date")


class MarketDataProvider(Protocol):
    def index_bundle(self, market: Market, *, as_of: datetime) -> IndexBundle: ...
    def stock_series(self, instrument: Instrument, *, as_of: datetime) -> MarketSeries: ...


class UniverseProvider(Protocol):
    def members(self, market: Market, *, as_of: datetime) -> tuple[UniverseMember, ...]: ...


def validate_series_for_profile(series: MarketSeries, profile: str, *, now: datetime) -> None:
    if profile not in _SUPPORTED_PROFILES:
        raise ValueError(f"unsupported profile: {profile}")
    _require_aware(now, "now")
    if profile in {"paper", "live"} and series.is_fixture:
        raise MarketDataUnavailable("paper/live requires non-fixture market data")
    if series.fetched_at > now + timedelta(minutes=5):
        raise InvalidMarketData("market data is future-dated")
    if profile in {"paper", "live"}:
        if now - series.fetched_at > timedelta(minutes=20):
            raise MarketDataUnavailable("paper/live market data is stale")
        latest_session = series.bars[-1].session_date
        now_utc_date = now.astimezone(timezone.utc).date()
        if _weekdays_after(latest_session, now_utc_date) > 1:
            raise MarketDataUnavailable(
                "paper/live latest observation is stale"
            )


def _weekdays_after(latest_session: date, current_date: date) -> int:
    """Count expected weekday sessions after the latest observed session."""

    if current_date <= latest_session:
        return 0
    count = 0
    cursor = latest_session + timedelta(days=1)
    while cursor <= current_date:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


@dataclass(frozen=True)
class FixtureUniverseProvider:
    universe: tuple[UniverseMember, ...]

    def __post_init__(self) -> None:
        if type(self.universe) is not tuple:
            raise InvalidMarketData("universe must be a tuple")
        seen = set()
        for member in self.universe:
            if not isinstance(member, UniverseMember):
                raise InvalidMarketData("universe must contain UniverseMember values")
            key = (member.instrument.market, member.instrument.symbol)
            if key in seen:
                raise InvalidMarketData(f"duplicate universe instrument: {key[0].value}:{key[1]}")
            seen.add(key)

    @classmethod
    def standard(cls) -> "FixtureUniverseProvider":
        rows = (
            ("005930", Market.KR, "XKRX", "KRW", "Samsung Electronics", "Technology", 0),
            ("000660", Market.KR, "XKRX", "KRW", "SK Hynix", "Technology", 0),
            ("035420", Market.KR, "XKRX", "KRW", "NAVER", "Communication Services", 0),
            ("AAPL", Market.US, "XNAS", "USD", "Apple", "Technology", 2),
            ("MSFT", Market.US, "XNAS", "USD", "Microsoft", "Technology", 2),
            ("NVDA", Market.US, "XNAS", "USD", "NVIDIA", "Technology", 2),
        )
        return cls(tuple(UniverseMember(Instrument(symbol, market, exchange, currency, name, sector, Decimal("1"), precision), "fixture:v1", FIXTURE_AS_OF.date()) for symbol, market, exchange, currency, name, sector, precision in rows))

    def members(self, market: Market, *, as_of: datetime) -> tuple[UniverseMember, ...]:
        if not isinstance(market, Market):
            raise InvalidMarketData("market must be a Market")
        _require_aware(as_of, "as_of")
        return tuple(sorted((replace(member, as_of=as_of.date()) for member in self.universe if member.instrument.market is market), key=lambda member: (member.instrument.market.value, member.instrument.symbol)))


def _business_sessions(end: date, count: int) -> tuple[date, ...]:
    sessions = []
    current = end
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current)
        current -= timedelta(days=1)
    return tuple(reversed(sessions))


def _fixture_close(index: int, base: Decimal, step: Decimal) -> Decimal:
    if index < 80:
        return base + step * index
    bull_end = base + step * Decimal("79")
    if index < 160:
        return bull_end + step * Decimal((index % 5) - 2)
    if index < 240:
        return bull_end - step * Decimal("1.4") * Decimal(index - 159)
    bear_end = bull_end - step * Decimal("1.4") * Decimal("80")
    if index < 280:
        return bear_end + step * Decimal("0.7") * Decimal(index - 239)
    moderate_end = bear_end + step * Decimal("0.7") * Decimal("40")
    return moderate_end - step * Decimal("1.6") * Decimal(index - 279)


def _fixture_bars(
    market: Market,
    *,
    base: Decimal,
    step: Decimal,
    invert_for_volatility: bool = False,
) -> tuple[DailyBar, ...]:
    def normalized_close(index: int) -> Decimal:
        close = _fixture_close(index, base, step)
        if invert_for_volatility:
            close = Decimal("35") - (close - base) / Decimal("10")
        quantum = Decimal("1") if market is Market.KR else Decimal("0.01")
        return close.quantize(quantum)

    bars = []
    previous = normalized_close(0)
    for index, session_date in enumerate(
        _business_sessions(FIXTURE_AS_OF.date(), 320)
    ):
        close = normalized_close(index)
        if market is Market.KR:
            open_price = previous
            spread = max(Decimal("1"), abs(step).quantize(Decimal("1")))
        else:
            open_price = previous
            spread = max(Decimal("0.10"), abs(step)).quantize(Decimal("0.01"))
        low = min(open_price, close) - spread
        high = max(open_price, close) + spread
        bars.append(
            DailyBar(
                session_date=session_date,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=Decimal(1_000_000 + index * 2_500 + (index % 7) * 10_000),
            )
        )
        previous = close
    return tuple(bars)


def _fixture_series(
    market: Market,
    symbol: str,
    *,
    base: Decimal,
    step: Decimal,
    price_precision: int,
    invert_for_volatility: bool = False,
) -> MarketSeries:
    return MarketSeries(
        market=market,
        symbol=symbol,
        currency=_EXPECTED_CURRENCY[market],
        price_precision=price_precision,
        bars=_fixture_bars(
            market,
            base=base,
            step=step,
            invert_for_volatility=invert_for_volatility,
        ),
        fetched_at=FIXTURE_AS_OF,
        source="fixture:v1",
        is_fixture=True,
    )


def _slice_fixture_series(series: MarketSeries, as_of: datetime) -> MarketSeries:
    bars = tuple(bar for bar in series.bars if bar.session_date <= as_of.date())
    if len(bars) < 20:
        raise MarketDataUnavailable(
            f"fixture history for {series.symbol} has fewer than 20 sessions at {as_of.date()}"
        )
    return replace(series, bars=bars, fetched_at=min(series.fetched_at, as_of))


@dataclass(frozen=True)
class FixtureMarketDataProvider:
    bundles: Mapping[Market, IndexBundle]
    stocks: Mapping[tuple[Market, str], MarketSeries]

    @classmethod
    def standard(cls) -> "FixtureMarketDataProvider":
        bundles = {
            Market.KR: IndexBundle(
                primary=_fixture_series(
                    Market.KR,
                    "KOSPI",
                    base=Decimal("2200"),
                    step=Decimal("8"),
                    price_precision=2,
                ),
                secondary=_fixture_series(
                    Market.KR,
                    "KOSDAQ",
                    base=Decimal("700"),
                    step=Decimal("3"),
                    price_precision=2,
                ),
                breadth_ratio=Decimal("0.48"),
            ),
            Market.US: IndexBundle(
                primary=_fixture_series(
                    Market.US,
                    "SP500",
                    base=Decimal("3800"),
                    step=Decimal("12"),
                    price_precision=2,
                ),
                secondary=_fixture_series(
                    Market.US,
                    "NASDAQ",
                    base=Decimal("11000"),
                    step=Decimal("35"),
                    price_precision=2,
                ),
                volatility=_fixture_series(
                    Market.US,
                    "VIX",
                    base=Decimal("100"),
                    step=Decimal("1"),
                    price_precision=2,
                    invert_for_volatility=True,
                ),
                breadth_ratio=Decimal("0.52"),
            ),
        }
        stock_rows = (
            (Market.KR, "005930", Decimal("55000"), Decimal("180"), 0),
            (Market.KR, "000660", Decimal("90000"), Decimal("250"), 0),
            (Market.KR, "035420", Decimal("180000"), Decimal("400"), 0),
            (Market.US, "AAPL", Decimal("130"), Decimal("0.45"), 2),
            (Market.US, "MSFT", Decimal("240"), Decimal("0.70"), 2),
            (Market.US, "NVDA", Decimal("80"), Decimal("0.35"), 2),
        )
        stocks = {
            (market, symbol): _fixture_series(
                market,
                symbol,
                base=base,
                step=step,
                price_precision=price_precision,
            )
            for market, symbol, base, step, price_precision in stock_rows
        }
        return cls(bundles=bundles, stocks=stocks)

    def index_bundle(self, market: Market, *, as_of: datetime) -> IndexBundle:
        if not isinstance(market, Market):
            raise InvalidMarketData("market must be a Market")
        _require_aware(as_of, "as_of")
        try:
            bundle = self.bundles[market]
        except KeyError as exc:
            raise MarketDataUnavailable(
                f"no fixture index bundle for {market.value}"
            ) from exc
        return IndexBundle(
            primary=_slice_fixture_series(bundle.primary, as_of),
            secondary=_slice_fixture_series(bundle.secondary, as_of),
            volatility=(
                _slice_fixture_series(bundle.volatility, as_of)
                if bundle.volatility is not None
                else None
            ),
            breadth_ratio=bundle.breadth_ratio,
        )

    def stock_series(
        self, instrument: Instrument, *, as_of: datetime
    ) -> MarketSeries:
        if not isinstance(instrument, Instrument):
            raise InvalidMarketData("instrument must be an Instrument")
        _require_aware(as_of, "as_of")
        try:
            series = self.stocks[(instrument.market, instrument.symbol)]
        except KeyError as exc:
            raise MarketDataUnavailable(
                f"no fixture stock series for {instrument.market.value}:{instrument.symbol}"
            ) from exc
        if series.currency != instrument.currency:
            raise InvalidMarketData("instrument and series currencies must match")
        return _slice_fixture_series(series, as_of)


class YFinanceMarketDataProvider:
    def __init__(
        self,
        *,
        import_module: Callable[[str], Any] = importlib.import_module,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._import_module = import_module
        self._clock = clock

    def _module(self) -> Any:
        try:
            return self._import_module("yfinance")
        except (ImportError, ModuleNotFoundError) as exc:
            raise MarketDataUnavailable(
                "yfinance is unavailable; install the optional dependency for real market data"
            ) from exc

    def _fetch_time(self) -> datetime:
        fetched_at = self._clock()
        _require_aware(fetched_at, "clock result")
        if fetched_at.utcoffset() != timedelta(0):
            raise InvalidMarketData("clock must return a UTC datetime")
        return fetched_at

    def index_bundle(self, market: Market, *, as_of: datetime) -> IndexBundle:
        if not isinstance(market, Market):
            raise InvalidMarketData("market must be a Market")
        _require_aware(as_of, "as_of")
        fetched_at = self._fetch_time()
        symbols = {
            Market.KR: (("KOSPI", "^KS11"), ("KOSDAQ", "^KQ11"), None),
            Market.US: (
                ("SP500", "^GSPC"),
                ("NASDAQ", "^IXIC"),
                ("VIX", "^VIX"),
            ),
        }
        primary, secondary, volatility = symbols[market]
        return IndexBundle(
            primary=self._load_series(
                market=market,
                symbol=primary[0],
                provider_symbol=primary[1],
                as_of=as_of,
                fetched_at=fetched_at,
                price_precision=2,
            ),
            secondary=self._load_series(
                market=market,
                symbol=secondary[0],
                provider_symbol=secondary[1],
                as_of=as_of,
                fetched_at=fetched_at,
                price_precision=2,
            ),
            volatility=(
                self._load_series(
                    market=market,
                    symbol=volatility[0],
                    provider_symbol=volatility[1],
                    as_of=as_of,
                    fetched_at=fetched_at,
                    price_precision=2,
                )
                if volatility is not None
                else None
            ),
        )

    def stock_series(self, instrument: Instrument, *, as_of: datetime) -> MarketSeries:
        if not isinstance(instrument, Instrument):
            raise InvalidMarketData("instrument must be an Instrument")
        _require_aware(as_of, "as_of")
        provider_symbol = instrument.symbol
        if instrument.market is Market.KR:
            if instrument.exchange == "XKRX":
                provider_symbol += ".KS"
            elif instrument.exchange in {"XKOS", "KOSDAQ"}:
                provider_symbol += ".KQ"
            else:
                raise MarketDataUnavailable(
                    f"unsupported KR exchange for yfinance: {instrument.exchange}"
                )
        fetched_at = self._fetch_time()
        return self._load_series(
            market=instrument.market,
            symbol=instrument.symbol,
            provider_symbol=provider_symbol,
            as_of=as_of,
            fetched_at=fetched_at,
            price_precision=instrument.price_precision,
        )

    def _load_series(
        self,
        *,
        market: Market,
        symbol: str,
        provider_symbol: str,
        as_of: datetime,
        fetched_at: datetime,
        price_precision: int,
    ) -> MarketSeries:
        yf = self._module()
        try:
            history = yf.Ticker(provider_symbol).history(
                start=as_of.date() - timedelta(days=731),
                end=as_of.date() + timedelta(days=1),
                interval="1d",
                auto_adjust=False,
            )
            if getattr(history, "empty", False):
                raise MarketDataUnavailable(
                    f"yfinance returned empty history for {provider_symbol}"
                )
            bars = []
            for timestamp, row in history.iterrows():
                if isinstance(timestamp, datetime):
                    session_date = timestamp.date()
                elif isinstance(timestamp, date):
                    session_date = timestamp
                elif hasattr(timestamp, "to_pydatetime"):
                    session_date = timestamp.to_pydatetime().date()
                else:
                    raise InvalidMarketData("yfinance history index must contain dates")
                if session_date > as_of.date():
                    continue
                prices = {
                    name: Decimal(str(row[name]))
                    for name in ("Open", "High", "Low", "Close")
                }
                if price_precision > 0:
                    quantum = Decimal(1).scaleb(-price_precision)
                    prices = {
                        name: value.quantize(quantum, rounding=ROUND_HALF_UP)
                        for name, value in prices.items()
                    }
                bars.append(
                    DailyBar(
                        session_date=session_date,
                        open=prices["Open"],
                        high=prices["High"],
                        low=prices["Low"],
                        close=prices["Close"],
                        volume=Decimal(str(row["Volume"])),
                    )
                )
            return MarketSeries(
                market=market,
                symbol=symbol,
                currency=_EXPECTED_CURRENCY[market],
                price_precision=price_precision,
                bars=tuple(bars),
                fetched_at=fetched_at,
                source="yfinance",
                is_fixture=False,
            )
        except MarketDataUnavailable:
            raise
        except Exception as exc:
            raise MarketDataUnavailable(
                f"yfinance could not provide valid history for {provider_symbol}"
            ) from exc
