# Market Regime + Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KR/US 시장 데이터를 같은 계약으로 검증하고, 결정론적 5단계 레짐이 활성 trigger·후보 점수·진입 안전 문턱을 실제로 바꾸는 stateful paper/classroom 파이프라인을 만든다.

**Architecture:** `prism_core.market_data`가 출처·시각·시장·OHLCV를 검증하고, 순수 함수인 `prism_core.regime`이 KR/US 레짐을 계산한다. `prism_core.screening`은 플러그형 trigger를 점수화하며 `prism_core.policy`가 레짐별 최소 점수·손익비·손절폭·위험률을 코드로 강제한다. 기존 `screening.run_screening() -> list[str]`는 상세 후보 API를 감싸는 facade로 유지하고, `TradingCycle.run()`의 주문·원장 계약은 변경하지 않는다.

**Tech Stack:** Python 3.10+ standard library (`dataclasses`, `decimal`, `enum`, `typing`, `datetime`, `zoneinfo`, `sqlite3`, `unittest`), optional `yfinance` adapter, SQLite schema migration, existing `prism_core` domain/ledger/paper broker/cycle.

## Global Constraints

- `python3 main.py`의 keyless mock 설치 경로와 기존 `run_screening(target_ticker=None, use_real=False) -> list[str]` 시그니처를 보존한다.
- `classroom`과 `backtest`는 네트워크·API 키 없이 고정 fixture로 결정론적으로 완주한다.
- `paper`와 `live`는 mock, stale, 시장 불일치, 통화 불일치, 유효하지 않은 가격을 fallback하지 않고 fail-closed 한다.
- KR 종목은 6자리 ASCII 코드·KRW·정수 가격/수량, US 종목은 대문자 ASCII 심볼·USD·`Decimal` 가격을 사용한다.
- 레짐·점수·진입 정책은 LLM이 변경하지 못하는 코드 계약이며, LLM 판단과 충돌하면 더 보수적인 값을 따른다.
- 새 필수 의존성을 추가하지 않는다. `yfinance`는 선택 adapter이고 import 실패가 mock/classroom을 깨뜨리지 않는다.
- 신규 주문 전에 기존 `TradingCycle`의 reconcile → high-water → exit → entry 순서와 UNKNOWN/중복 주문 차단을 그대로 사용한다.
- 원본 `prism-insight`의 임계값은 초기 기준일 뿐 수익 보장이 아니다. 합성 fixture와 walk-forward 결과는 교육용 검증 증거로만 표시한다.
- 테스트와 smoke는 임시 DB만 사용하며 루트 `prism.db`, 네트워크, 브로커 자격정보, live mutation을 사용하지 않는다.
- 변경은 Task별 Lore-format commit으로 남기고, 각 Task는 구현자 검토와 독립 spec/quality 검토를 통과해야 한다.

---

## File Map

- Create `prism_core/market_data.py`: 시장 데이터 도메인, freshness/provenance 검증, fixture 및 선택적 yfinance provider.
- Create `prism_core/regime.py`: KR/US 5단계 레짐 순수 계산과 Market Pulse 관찰값.
- Create `prism_core/policy.py`: 레짐별 trigger/점수/RR/손절/위험 정책의 단일 소스.
- Create `prism_core/screening.py`: 상세 후보 생성, trigger plugin 계약, 결정론적 정렬.
- Create `prism_core/market_pipeline.py`: data → regime → candidate → entry intent를 연결하되 주문 실행은 기존 `TradingCycle`에 위임.
- Create `prism_core/walk_forward.py`: 미래 데이터 누수 없는 시장×레짐×trigger 평가.
- Modify `prism_core/domain.py`: `Regime`, `TriggerType`, `Candidate`, `EntryDecision` 공용 불변 객체 추가.
- Modify `prism_core/ledger.py`: schema v5의 `market_regimes`/`candidates`/`entry_contexts`와 append/read API 추가.
- Modify `prism_core/__init__.py`: 안정된 공용 타입·함수만 export.
- Modify `screening.py`: legacy facade를 상세 스크리너에 연결하고 mock fallback 범위를 mock/real_data로 한정.
- Modify `runtime_config.py`: `screening_mode=fixture|real`의 profile 기본값과 paper/live fail-closed 경로 정규화.
- Modify `main.py`: classroom replay에 레짐별 후보/진입 증거를 포함하고 paper/live에서 provider preflight를 수행.
- Create `tests/test_market_data_provider.py`, `tests/test_market_regime.py`, `tests/test_regime_screening.py`, `tests/test_market_pipeline.py`, `tests/test_walk_forward.py`.
- Modify `tests/test_prism_core_ledger.py`, `tests/test_main_runtime_options.py`, `tests/test_prism_core_foundation_contract.py`.
- Modify `docs/architecture.md`, `docs/runtime-profiles.md`, `lecture/exercises/part3_실습가이드.md`, `lecture/exercises/part4_실습가이드.md` if present.

---

### Task 1: KR/US Market Data Contract and Fail-Closed Provider Boundary

**Files:**
- Create: `prism_core/market_data.py`
- Modify: `prism_core/domain.py`
- Modify: `prism_core/__init__.py`
- Test: `tests/test_market_data_provider.py`

**Interfaces:**
- Consumes: existing `Market`, `validate_market_contract()`.
- Produces: `DailyBar`, `MarketSeries`, `IndexBundle`, `UniverseMember`, `UniverseProvider`, `FixtureUniverseProvider`, `MarketDataProvider`, `FixtureMarketDataProvider`, `YFinanceMarketDataProvider`, `validate_series_for_profile()`.

- [ ] **Step 1: Write failing domain and provider tests**

```python
class MarketDataProviderTest(unittest.TestCase):
    def test_kr_and_us_series_preserve_market_currency_and_decimal_contract(self):
        provider = FixtureMarketDataProvider.standard()
        kr = provider.index_bundle(Market.KR, as_of=FIXTURE_AS_OF)
        us = provider.index_bundle(Market.US, as_of=FIXTURE_AS_OF)
        self.assertEqual((kr.primary.market, kr.primary.currency), (Market.KR, "KRW"))
        self.assertEqual((us.primary.market, us.primary.currency), (Market.US, "USD"))
        self.assertTrue(all(bar.close == bar.close.to_integral_value() for bar in kr.primary.bars))
        self.assertTrue(all(bar.close.is_finite() and bar.close > 0 for bar in us.primary.bars))

    def test_paper_and_live_reject_fixture_stale_and_future_dated_data(self):
        series = FixtureMarketDataProvider.standard().index_bundle(
            Market.US, as_of=FIXTURE_AS_OF
        ).primary
        for profile in ("paper", "live"):
            with self.subTest(profile=profile), self.assertRaises(MarketDataUnavailable):
                validate_series_for_profile(series, profile, now=FIXTURE_AS_OF)

    def test_classroom_accepts_fixture_but_rejects_duplicate_or_unsorted_bars(self):
        series = FixtureMarketDataProvider.standard().index_bundle(
            Market.KR, as_of=FIXTURE_AS_OF
        ).primary
        validate_series_for_profile(series, "classroom", now=FIXTURE_AS_OF)
        with self.assertRaises(InvalidMarketData):
            MarketSeries(**{**asdict(series), "bars": (series.bars[1], series.bars[0])})

    def test_yfinance_import_failure_is_explicit_and_never_returns_fixture(self):
        provider = YFinanceMarketDataProvider(import_module=lambda _: (_ for _ in ()).throw(ImportError()))
        with self.assertRaises(MarketDataUnavailable):
            provider.index_bundle(Market.US, as_of=FIXTURE_AS_OF)
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python3 -m unittest tests.test_market_data_provider -v`

Expected: import failure because `prism_core.market_data` does not exist.

- [ ] **Step 3: Add immutable data objects and strict validation**

```python
@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: Market
    exchange: str
    currency: str
    name: str
    sector: str
    lot_size: Decimal
    price_precision: int

@dataclass(frozen=True)
class UniverseMember:
    instrument: Instrument
    source: str
    as_of: date

@dataclass(frozen=True)
class DailyBar:
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

@dataclass(frozen=True)
class MarketSeries:
    market: Market
    symbol: str
    currency: str
    bars: tuple[DailyBar, ...]
    fetched_at: datetime
    source: str
    is_fixture: bool = False

@dataclass(frozen=True)
class IndexBundle:
    primary: MarketSeries
    secondary: MarketSeries
    volatility: MarketSeries | None = None
    breadth_ratio: Decimal | None = None

class MarketDataProvider(Protocol):
    def index_bundle(self, market: Market, *, as_of: datetime) -> IndexBundle:
        pass
    def stock_series(self, instrument: Instrument, *, as_of: datetime) -> MarketSeries:
        pass

class UniverseProvider(Protocol):
    def members(self, market: Market, *, as_of: datetime) -> tuple[UniverseMember, ...]:
        pass

def validate_series_for_profile(series: MarketSeries, profile: str, *, now: datetime) -> None:
    if profile in {"paper", "live"} and series.is_fixture:
        raise MarketDataUnavailable("paper/live requires non-fixture market data")
    if series.fetched_at > now + timedelta(minutes=5):
        raise InvalidMarketData("market data is future-dated")
    if profile in {"paper", "live"} and now - series.fetched_at > timedelta(minutes=20):
        raise MarketDataUnavailable("paper/live market data is stale")
```

In `MarketSeries.__post_init__`, enforce one currency per market, strictly increasing unique session dates, at least 20 bars, finite positive OHLC, `low <= open/close <= high`, non-negative volume, and integral KR OHLC. `YFinanceMarketDataProvider` must lazy-import `yfinance`, convert numbers through `Decimal(str(value))`, and raise `MarketDataUnavailable` rather than substituting fixtures.

In `Instrument.__post_init__`, reuse `validate_market_contract()` for symbol/currency/lot size, require a non-empty exchange/name/sector, positive lot size, and `price_precision == 0` for KR. `FixtureUniverseProvider.members()` returns symbols in canonical `(market.value, symbol)` order and rejects duplicate instruments.

- [ ] **Step 4: Add deterministic KR/US fixture series and a curated universe**

Create `FixtureMarketDataProvider.standard()` with at least 220 sessions for KR KOSPI/KOSDAQ plus `005930`, `000660`, `035420`, and US S&P 500/Nasdaq/VIX plus `AAPL`, `MSFT`, `NVDA`. Generate the bars from fixed arithmetic sequences; never use `random`, current wall-clock time, or network data. The sequences must include one strong-bull, one sideways, and one strong-bear window used by later tests.

- [ ] **Step 5: Run focused and foundation regression tests**

Run: `python3 -m unittest tests.test_market_data_provider tests.test_prism_core_domain tests.test_prism_core_foundation_contract -v`

Expected: all pass; no external package is imported on the fixture path.

- [ ] **Step 6: Commit**

Commit intent: `시장 데이터의 출처와 신선도를 주문 정책보다 먼저 증명한다`

---

### Task 2: Pure Five-Regime Engine and Market Pulse Observation

**Files:**
- Create: `prism_core/regime.py`
- Modify: `prism_core/domain.py`
- Modify: `prism_core/__init__.py`
- Test: `tests/test_market_regime.py`

**Interfaces:**
- Consumes: `IndexBundle`, `Market`, `DailyBar`.
- Produces: `Regime`, `PulseState`, `RegimeResult`, `classify_market_regime(bundle, as_of) -> RegimeResult`.

- [ ] **Step 1: Write table-driven boundary tests before implementation**

```python
class MarketRegimeTest(unittest.TestCase):
    def test_kr_and_us_fixture_windows_cover_all_five_regimes(self):
        provider = FixtureMarketDataProvider.standard()
        cases = [
            (Market.KR, KR_STRONG_BULL_AT, Regime.STRONG_BULL),
            (Market.KR, KR_MODERATE_BEAR_AT, Regime.MODERATE_BEAR),
            (Market.US, US_SIDEWAYS_AT, Regime.SIDEWAYS),
            (Market.US, US_MODERATE_BULL_AT, Regime.MODERATE_BULL),
            (Market.US, US_STRONG_BEAR_AT, Regime.STRONG_BEAR),
        ]
        for market, as_of, expected in cases:
            with self.subTest(market=market, as_of=as_of):
                result = classify_market_regime(provider.index_bundle(market, as_of=as_of), as_of=as_of)
                self.assertIs(result.regime, expected)
                self.assertGreaterEqual(result.confidence, Decimal("0"))
                self.assertLessEqual(result.confidence, Decimal("1"))

    def test_bear_market_bounce_below_primary_ma_never_becomes_bull(self):
        result = classify_market_regime(bear_rally_bundle(Market.US), as_of=FIXTURE_AS_OF)
        self.assertIn(result.regime, {Regime.SIDEWAYS, Regime.MODERATE_BEAR, Regime.STRONG_BEAR})

    def test_high_volatility_drawdown_can_only_downgrade_a_bull_label(self):
        result = classify_market_regime(high_vol_drawdown_bundle(), as_of=FIXTURE_AS_OF)
        self.assertIs(result.regime, Regime.SIDEWAYS)
        self.assertIn("high_vol_drawdown", result.reasons)

    def test_missing_primary_history_fails_instead_of_guessing_sideways(self):
        with self.assertRaises(InsufficientMarketHistory):
            classify_market_regime(short_bundle(19), as_of=FIXTURE_AS_OF)
```

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_market_regime -v`

Expected: missing `Regime` and classifier failures.

- [ ] **Step 3: Implement the public result contract and pure helpers**

```python
class Regime(str, Enum):
    STRONG_BULL = "strong_bull"
    MODERATE_BULL = "moderate_bull"
    SIDEWAYS = "sideways"
    MODERATE_BEAR = "moderate_bear"
    STRONG_BEAR = "strong_bear"

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
```

Implement `_sma`, `_return_pct`, `_realized_volatility`, `_drawdown`, `_distribution_days`, and `_breadth_state` using only `Decimal` and chronological bars. No helper may read environment variables, wall-clock time, DB, network, or LLM output.

- [ ] **Step 4: Implement explicit KR/US classification tables**

Use the primary long-term divider before short-term momentum:

```python
_REGIME_THRESHOLDS = {
    Market.KR: RegimeThresholds(primary_ma=120, secondary_ma=60, momentum_days=10,
                                strong_bull_return=Decimal("5"), strong_bear_return=Decimal("-5")),
    Market.US: RegimeThresholds(primary_ma=200, secondary_ma=50, momentum_days=20,
                                strong_bull_return=Decimal("3"), strong_bear_return=Decimal("-5")),
}
```

Above primary MA may yield strong/moderate bull or sideways; below primary MA may yield sideways/moderate/strong bear but never bull. US strong bull additionally requires VIX below 20; US strong bear requires VIX at least 20. A high-volatility drawdown override may only downgrade bull to sideways. Pulse is computed independently: 0–3 distribution days = UPTREND, 4–5 = UNDER_PRESSURE, 6+ or drawdown at least 8% = CORRECTION.

- [ ] **Step 5: Run boundary, determinism, and foundation suites**

Run the same classification twice and assert exact dataclass equality. Then run:

`python3 -m unittest tests.test_market_regime tests.test_market_data_provider tests.test_prism_core_domain -v`

Expected: all pass and every five-level branch is exercised for both markets across fixture/table cases.

- [ ] **Step 6: Commit**

Commit intent: `시장 레짐을 LLM 해석이 아닌 재현 가능한 시장 규칙으로 고정한다`

---

### Task 3: Regime-Aware Trigger Plugins, Candidate Ranking, and Conservative Entry Policy

**Files:**
- Create: `prism_core/policy.py`
- Create: `prism_core/screening.py`
- Modify: `prism_core/domain.py`
- Modify: `prism_core/__init__.py`
- Test: `tests/test_regime_screening.py`

**Interfaces:**
- Consumes: `MarketSeries`, `RegimeResult`, existing `OrderIntent`.
- Produces: `TriggerType`, `Candidate`, `RegimePolicy`, `ScreeningStrategy`, `OneilTrendStrategy`, `screen_candidates()`, `gate_entry()`.

- [ ] **Step 1: Lock the desired regime/strategy compatibility with failing tests**

```python
class RegimeScreeningTest(unittest.TestCase):
    def test_same_features_receive_different_policy_by_regime(self):
        bull = screen_one(AAPL_SERIES, regime(Regime.STRONG_BULL))
        bear = screen_one(AAPL_SERIES, regime(Regime.STRONG_BEAR))
        self.assertTrue(gate_entry(bull, analysis_score=8).allowed)
        self.assertFalse(gate_entry(bear, analysis_score=8).allowed)
        self.assertGreater(policy_for(Regime.STRONG_BEAR).minimum_risk_reward,
                           policy_for(Regime.STRONG_BULL).minimum_risk_reward)

    def test_weak_regime_disables_unconfirmed_breakout_but_keeps_confirmed_rebound_plugin(self):
        policy = policy_for(Regime.STRONG_BEAR)
        self.assertNotIn(TriggerType.BREAKOUT, policy.active_triggers)
        self.assertIn(TriggerType.OVERSOLD_REBOUND, policy.active_triggers)

    def test_llm_enter_cannot_override_quantitative_gate(self):
        candidate = candidate_with(score="7.9", rr="1.2", stop_pct="-7")
        decision = gate_entry(candidate, analysis_score=10, llm_enter=True,
                              policy=policy_for(Regime.STRONG_BEAR))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reasons, ("candidate_score_below_floor", "risk_reward_below_floor", "stop_too_wide"))

    def test_candidate_order_is_score_then_symbol_and_has_no_input_order_dependency(self):
        forward = screen_candidates(UNIVERSE, SERIES_BY_SYMBOL, BENCHMARK, BULL_RESULT,
                                    strategy=OneilTrendStrategy())
        reverse = screen_candidates(tuple(reversed(UNIVERSE)), SERIES_BY_SYMBOL,
                                    BENCHMARK, BULL_RESULT,
                                    strategy=OneilTrendStrategy())
        self.assertEqual(forward, reverse)
```

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_regime_screening -v`

Expected: missing policy/screening API failures.

- [ ] **Step 3: Define immutable candidate and policy contracts**

```python
class TriggerType(str, Enum):
    BREAKOUT = "breakout"
    PULLBACK = "pullback"
    VOLUME_SURGE = "volume_surge"
    RELATIVE_STRENGTH = "relative_strength"
    OVERSOLD_REBOUND = "oversold_rebound"

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

@dataclass(frozen=True)
class EntryDecision:
    candidate: Candidate
    allowed: bool
    analysis_score: Decimal
    reasons: tuple[str, ...]
    policy: RegimePolicy

@dataclass(frozen=True)
class EntryContext:
    client_order_id: str
    run_id: str
    candidate: Candidate
    strategy_id: str
    policy: RegimePolicy

def gate_entry(candidate: Candidate, *, analysis_score: Decimal | int,
               llm_enter: bool | None = None,
               policy: RegimePolicy | None = None) -> EntryDecision:
    pass
```

Candidate mappings must be copied to immutable `MappingProxyType` values in `__post_init__`; all prices/scores must be finite and positive where applicable; stop must be below reference, target above reference, and stored risk/reward must equal the price-derived value within `0.01`.

- [ ] **Step 4: Implement the table-driven policy and plugin protocol**

```python
class ScreeningStrategy(Protocol):
    strategy_id: str
    supported_triggers: frozenset[TriggerType]
    def evaluate(self, instrument: Instrument, series: MarketSeries,
                 benchmark: MarketSeries, regime: RegimeResult) -> tuple[Candidate, ...]:
        pass

def screen_candidates(universe: tuple[UniverseMember, ...],
                      series_by_instrument: Mapping[Instrument, MarketSeries],
                      benchmark: MarketSeries, regime: RegimeResult, *,
                      strategy: ScreeningStrategy) -> tuple[Candidate, ...]:
    pass

def D(value: str) -> Decimal:
    return Decimal(value)

_POLICIES = {
    Regime.STRONG_BULL: RegimePolicy(frozenset({TriggerType.BREAKOUT, TriggerType.PULLBACK, TriggerType.VOLUME_SURGE, TriggerType.RELATIVE_STRENGTH}), D("6.0"), D("6"), D("1.2"), D("7"), D("1.0"), 10, D("10"), D("8")),
    Regime.MODERATE_BULL: RegimePolicy(frozenset({TriggerType.BREAKOUT, TriggerType.PULLBACK, TriggerType.VOLUME_SURGE, TriggerType.RELATIVE_STRENGTH}), D("6.5"), D("6"), D("1.3"), D("7"), D("0.8"), 8, D("20"), D("8")),
    Regime.SIDEWAYS: RegimePolicy(frozenset({TriggerType.PULLBACK, TriggerType.VOLUME_SURGE, TriggerType.OVERSOLD_REBOUND}), D("7.0"), D("7"), D("1.5"), D("6"), D("0.6"), 6, D("35"), D("5")),
    Regime.MODERATE_BEAR: RegimePolicy(frozenset({TriggerType.OVERSOLD_REBOUND, TriggerType.RELATIVE_STRENGTH}), D("8.0"), D("8"), D("1.8"), D("5"), D("0.4"), 3, D("55"), D("5")),
    Regime.STRONG_BEAR: RegimePolicy(frozenset({TriggerType.OVERSOLD_REBOUND}), D("9.0"), D("9"), D("2.0"), D("5"), D("0.25"), 1, D("75"), D("5")),
}
```

The exact table is the initial teaching policy; tests must assert the monotonic safety invariants (bear never lowers thresholds or increases exposure) rather than only duplicate every literal.

- [ ] **Step 5: Implement `OneilTrendStrategy` and conservative gate semantics**

Calculate volume ratio, 20/50-day position, 52-week high distance, relative strength versus benchmark, momentum, volatility, and pullback depth. Each trigger returns its own component scores; do not merge distinct triggers into an unexplained single score. `gate_entry()` returns every failed reason in deterministic order and applies `max(policy.minimum_analysis_score, configured_strategy_floor)`; `llm_enter=False` may veto, while `llm_enter=True` never bypasses quantitative failure.

- [ ] **Step 6: Verify plugin isolation and both-market contracts**

Add a test-only strategy implementing `ScreeningStrategy`; prove it can be injected without editing the core screener and cannot emit a mismatched market/currency/symbol candidate. Run:

`python3 -m unittest tests.test_regime_screening tests.test_market_regime tests.test_prism_core_domain -v`

Expected: all pass.

- [ ] **Step 7: Commit**

Commit intent: `스크리닝 전략과 매수 문턱이 같은 레짐 정책을 공유하게 한다`

---

### Task 4: Persist Regime, Candidate, and Entry-Order Provenance in Schema v5

**Files:**
- Modify: `prism_core/ledger.py`
- Modify: `prism_core/__init__.py`
- Modify: `tests/test_prism_core_ledger.py`
- Test: `tests/test_market_pipeline.py`

**Interfaces:**
- Consumes: `RegimeResult`, `Candidate`, `EntryContext`, existing `Ledger`.
- Produces: `Ledger.record_market_regime(run_id, result)`, `Ledger.record_candidates(run_id, candidates)`, `Ledger.record_entry_context(context)`, atomic `Ledger.record_market_preparation(run_id, regimes, candidates, entry_contexts)`, `Ledger.get_market_regime(run_id, market)`, `Ledger.list_candidates(run_id, market=None)`, `Ledger.get_entry_context(client_order_id)`.

- [ ] **Step 1: Write schema/migration/round-trip tests first**

```python
def test_v4_to_v5_migration_preserves_orders_and_adds_regime_candidate_tables(self):
    seed_v4_ledger(self.path)
    before = sqlite_rows(self.path, "broker_orders")
    ledger = Ledger(self.path)
    self.assertEqual(before, sqlite_rows(self.path, "broker_orders"))
    self.assertEqual(schema_version(self.path), 5)
    ledger.record_market_regime("run-1", STRONG_BULL_RESULT)
    ledger.record_candidates("run-1", (AAPL_CANDIDATE,))
    ledger.record_entry_context(AAPL_ENTRY_CONTEXT)
    self.assertEqual(ledger.get_market_regime("run-1", Market.US), STRONG_BULL_RESULT)
    self.assertEqual(ledger.list_candidates("run-1"), [AAPL_CANDIDATE])
    self.assertEqual(ledger.get_entry_context("run-1:US:AAPL:BUY"), AAPL_ENTRY_CONTEXT)

def test_same_run_market_regime_retry_is_idempotent_but_collision_fails(self):
    ledger.record_market_regime("run-1", result(Regime.SIDEWAYS))
    ledger.record_market_regime("run-1", result(Regime.SIDEWAYS))
    with self.assertRaises(ValueError, msg="market regime collision"):
        ledger.record_market_regime("run-1", result(Regime.STRONG_BULL))
```

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_prism_core_ledger.LedgerSchemaTest tests.test_market_pipeline.MarketProvenanceTest -v`

Expected: schema version/API failures.

- [ ] **Step 3: Add ordered transactional v5 migration**

```sql
CREATE TABLE market_regimes (
  run_id TEXT NOT NULL, market TEXT NOT NULL, as_of TEXT NOT NULL,
  regime TEXT NOT NULL, confidence TEXT NOT NULL, pulse TEXT NOT NULL,
  metrics_json TEXT NOT NULL, reasons_json TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY(run_id, market)
);
CREATE TABLE candidates (
  run_id TEXT NOT NULL, rank INTEGER NOT NULL, market TEXT NOT NULL,
  symbol TEXT NOT NULL, as_of TEXT NOT NULL, trigger_type TEXT NOT NULL,
  regime TEXT NOT NULL, feature_values_json TEXT NOT NULL,
  component_scores_json TEXT NOT NULL, final_score TEXT NOT NULL,
  reference_price TEXT NOT NULL, stop_price TEXT NOT NULL,
  target_price TEXT NOT NULL, risk_reward_ratio TEXT NOT NULL,
  source TEXT NOT NULL,
  PRIMARY KEY(run_id, market, symbol, trigger_type),
  UNIQUE(run_id, market, rank)
);
CREATE TABLE entry_contexts (
  client_order_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
  market TEXT NOT NULL, symbol TEXT NOT NULL, strategy_id TEXT NOT NULL,
  regime TEXT NOT NULL, trigger_type TEXT NOT NULL,
  stop_price TEXT NOT NULL, target_price TEXT NOT NULL,
  risk_reward_ratio TEXT NOT NULL, trailing_pct TEXT NOT NULL,
  source TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(run_id, market, symbol, trigger_type)
);
```

Use canonical JSON (`sort_keys=True`, compact separators), ISO timestamps with timezone, and decimal strings. Extend the strict schema validator from the foundation fix as an exact versioned contract: no unknown columns, generated/CHECK/trigger semantics, non-BINARY text keys, noncanonical INTEGER primary keys, partial/expression indexes, or unmodeled UNIQUE constraints. Add v5 columns/tables only through the explicit ordered migration. A failed migration must roll back meta version and every new table.

- [ ] **Step 4: Implement idempotent append/read APIs with semantic collision checks**

Do not use `INSERT OR REPLACE`. Identical retries return normally; same identity with different regime, rank, score, price, trigger, or source raises a precise collision before mutation. Reconstruct through domain constructors so corrupt enum, JSON, Decimal, market, or price relationships fail closed.

`record_market_preparation()` validates the complete tuple first, opens one `BEGIN IMMEDIATE` transaction, inserts every regime, candidate, and entry context with the same semantic collision rules, and rolls back the entire preparation if any row conflicts. `entry_contexts.client_order_id` must equal the generated `OrderIntent.client_order_id`; market, symbol, strategy, stop, target, and trigger must match the referenced candidate exactly.

- [ ] **Step 5: Run concurrent initialization and corruption tests**

Cover two threads opening a v4 ledger, partially-created v5 tables, partial UNIQUE impostors, any unknown column (including nullable/defaulted), modeled-column generated/CHECK semantics, owned-table triggers, malformed candidate JSON, and a stored candidate whose symbol/currency violates its market. Use only `tempfile.TemporaryDirectory()`.

- [ ] **Step 6: Run the full ledger/foundation suite**

Run: `python3 -m unittest tests.test_prism_core_ledger tests.test_prism_core_paper_broker tests.test_prism_core_cycle tests.test_classroom_profile -v`

Expected: all pass with no root DB mutation.

- [ ] **Step 7: Commit**

Commit intent: `매수 후보가 어떤 시장 판단에서 나왔는지 재시작 뒤에도 증명한다`

---

### Task 5: Market Pipeline Integration and Legacy Facade

**Files:**
- Create: `prism_core/market_pipeline.py`
- Modify: `prism_core/cycle.py`
- Modify: `screening.py`
- Modify: `runtime_config.py`
- Modify: `main.py`
- Modify: `prism_core/classroom.py`
- Modify: `tests/test_main_runtime_options.py`
- Modify: `tests/test_classroom_profile.py`
- Modify: `tests/test_prism_core_cycle.py`
- Test: `tests/test_market_pipeline.py`

**Interfaces:**
- Consumes: provider, regime classifier, screening strategy, policy gate, ledger, existing `TradingCycle.run(run_id, entry_intents, auto_fill=False)`.
- Produces: additive `TradingCycle.run_staged(run_id, entry_supplier, exit_policy_provider=None, auto_fill=False)`, `MarketPipeline.prepare_entries() -> MarketPreparation`, `run_detailed_screening() -> list[Candidate]`; existing `TradingCycle.run()` and root `run_screening()` remain compatible.

- [ ] **Step 1: Write end-to-end preparation and fail-closed tests**

```python
class MarketPipelineTest(unittest.TestCase):
    def test_classroom_kr_us_cycle_persists_regime_candidate_and_filled_entry(self):
        result = run_fixture_market_cycle(temp_db, as_of=FIXTURE_AS_OF, auto_fill=True)
        self.assertEqual({r.market for r in result.regimes}, {Market.KR, Market.US})
        self.assertTrue(result.candidates)
        self.assertEqual(result.cycle.event_order[-1], "ENTRY")
        self.assertTrue(Ledger(temp_db).list_positions())

    def test_exit_still_precedes_regime_screening_and_new_entry(self):
        result = run_second_cycle_with_trailing_exit(temp_db)
        self.assertLess(result.event_order.index("EXIT"), result.event_order.index("SCREEN"))
        self.assertLess(result.event_order.index("SCREEN"), result.event_order.index("ENTRY"))

    def test_live_weak_regime_tightens_trailing_and_target_while_bull_holds_winner(self):
        weak = run_exit_policy_case(live_regime=Regime.SIDEWAYS, quote=Decimal("115"))
        bull = run_exit_policy_case(live_regime=Regime.STRONG_BULL, quote=Decimal("115"))
        self.assertEqual(weak.exit_reason, "weak_regime_target")
        self.assertIsNone(bull.exit_reason)

    def test_scenario_stop_precedes_absolute_stop_and_regime_trailing(self):
        result = run_exit_policy_case(live_regime=Regime.STRONG_BULL,
                                      quote=Decimal("94"), scenario_stop=Decimal("95"))
        self.assertEqual(result.exit_reason, "scenario_stop")

    def test_paper_and_live_do_not_call_screening_or_broker_after_provider_failure(self):
        provider = RaisingProvider(MarketDataUnavailable("stale"))
        broker = SpyBroker()
        with self.assertRaises(MarketDataUnavailable):
            MarketPipeline(provider=provider, broker=broker, profile="paper").run("run-1")
        self.assertEqual(broker.mutations, [])

    def test_legacy_facade_returns_symbols_and_mock_main_still_completes(self):
        symbols = asyncio.run(run_screening(use_real=False))
        self.assertTrue(all(isinstance(symbol, str) for symbol in symbols))
```

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_market_pipeline tests.test_main_runtime_options -v`

Expected: pipeline API/integration failures.

- [ ] **Step 3: Add a lazy entry-supplier hook without changing existing cycle callers**

Add `TradingCycle.run_staged(run_id, entry_supplier, *, exit_policy_provider=None, auto_fill=False)`. Under the existing single `cycle_fence`, it performs reconcile, portfolio-wide high-water observation, exit decisions/cancellation/liquidation, then calls `entry_supplier()` exactly once and evaluates the returned intents against the initial-position exclusion set. `TradingCycle.run()` delegates to `run_staged(..., lambda: entry_intents, exit_policy_provider=None, ...)`, preserving the foundation's default 7% hard stop and 8% trailing behavior. If the supplier raises, completed exits remain truthful, no entry order is created, and the cycle result records `entry_preparation_failed`; UNKNOWN and no-same-cycle re-entry semantics remain unchanged.

For the market pipeline, `exit_policy_provider(position)` loads the immutable `EntryContext` through the position's `entry_client_order_id` and combines it with the fresh, read-only regime preflight. Evaluate exits in this order: persisted scenario stop, absolute 7% hard stop, losing-position primary moving-average break when available, live-regime trailing after 5% activation, weak-regime target, then optional strategy exit plugin. Missing/corrupt entry context blocks adaptive trailing/target but never weakens the absolute hard stop. Bull regimes use their wider trailing and treat target as a milestone; sideways/bear use their tighter trailing and target as an exit.

Write direct tests proving supplier invocation occurs after an exit fill, is skipped when the cycle fence is unavailable, is called once, and cannot re-enter a symbol held at cycle start even if it exited earlier in the same cycle.

- [ ] **Step 4: Implement preparation without duplicating broker logic**

```python
@dataclass(frozen=True)
class MarketPreparation:
    run_id: str
    regimes: tuple[RegimeResult, ...]
    candidates: tuple[Candidate, ...]
    decisions: tuple[EntryDecision, ...]
    entry_contexts: tuple[EntryContext, ...]
    entry_intents: tuple[OrderIntent, ...]

class MarketPipeline:
    def prepare_entries(self, run_id: str, *, as_of: datetime) -> MarketPreparation:
        regimes: list[RegimeResult] = []
        candidates: list[Candidate] = []
        decisions: list[EntryDecision] = []
        contexts: list[EntryContext] = []
        intents: list[OrderIntent] = []
        for market in (Market.KR, Market.US):
            bundle = self.provider.index_bundle(market, as_of=as_of)
            for series in (bundle.primary, bundle.secondary, bundle.volatility):
                if series is not None:
                    validate_series_for_profile(series, self.profile, now=as_of)
            regime = classify_market_regime(bundle, as_of=as_of)
            universe = tuple(self.universe_provider.members(market, as_of=as_of))
            stock_series = {
                member.instrument: self.provider.stock_series(member.instrument, as_of=as_of)
                for member in universe
            }
            for series in stock_series.values():
                validate_series_for_profile(series, self.profile, now=as_of)
            selected = screen_candidates(
                universe, stock_series, bundle.primary, regime, strategy=self.strategy
            )
            regimes.append(regime)
            candidates.extend(selected)
            for candidate in selected:
                decision = gate_entry(
                    candidate,
                    analysis_score=self.analysis_score(candidate),
                    llm_enter=self.llm_enter(candidate),
                    policy=policy_for(regime.regime),
                )
                decisions.append(decision)
                if decision.allowed:
                    intent, context = self.entry_planner.to_order(run_id, decision)
                    intents.append(intent)
                    contexts.append(context)
        self.ledger.record_market_preparation(
            run_id, tuple(regimes), tuple(candidates), tuple(contexts)
        )
        return MarketPreparation(run_id, tuple(regimes), tuple(candidates),
                                 tuple(decisions), tuple(contexts), tuple(intents))

    def run(self, run_id: str, *, as_of: datetime,
            auto_fill: bool = False) -> MarketCycleResult:
        snapshot = self.load_and_validate_snapshot(as_of=as_of)
        prepared_box: list[MarketPreparation] = []

        def supply_entries() -> list[OrderIntent]:
            prepared = self.prepare_entries(run_id, as_of=as_of, snapshot=snapshot)
            prepared_box.append(prepared)
            return list(prepared.entry_intents)

        cycle = TradingCycle(self.broker, snapshot.quotes).run_staged(
            run_id, supply_entries,
            exit_policy_provider=self.exit_policy_provider(snapshot),
            auto_fill=auto_fill
        )
        prepared = prepared_box[0] if prepared_box else MarketPreparation.empty(run_id)
        return MarketCycleResult(prepared=prepared, cycle=cycle)
```

`load_and_validate_snapshot()` fetches and validates both market bundles, every held-position quote, and every screened stock series before the cycle's first broker mutation. It computes an immutable live regime map as a read-only exit-safety input. The lazy supplier runs only after exits, reuses that exact map for candidate screening, then atomically persists regime/candidate/context evidence and constructs orders; it must not refetch or reclassify mid-cycle. `record_market_preparation()` is the atomic wrapper around the Task 4 append APIs. Construct `OrderIntent` only from allowed `EntryDecision`s. Position sizing is `floor(account_equity * account_risk_pct / (reference_price - stop_price))`, clamped by cash/slot limits and KR lot-size/integrality.

- [ ] **Step 5: Preserve the legacy root facade by profile**

`run_screening(target_ticker=...)` validates the symbol and returns exactly that symbol for mock/real_data analysis compatibility. `use_real=False` retains the tiny legacy demo. `run_detailed_screening()` is used by classroom/backtest/paper/live. `paper/live` must call `YFinanceMarketDataProvider` or an explicitly injected provider and surface a blocked preflight; it must never log “demo fallback”.

- [ ] **Step 6: Extend classroom replay with regime-dependent evidence**

Keep the existing three-cycle entry/hold/trailing-exit sequence and add a preparation phase whose fixed KR/US windows cause different policies. The summary must include `run_id`, each market's regime, candidate symbol/trigger/score, rejected reasons, order IDs, fills, and realized exits. Existing session ownership, restart, quarantine, and no-same-cycle re-entry tests remain unchanged.

- [ ] **Step 7: Run keyless, hostile ambient, and safety-gate verification**

Run mock and classroom through temporary DB injection. Set hostile ambient variables requesting live broker and prove `classroom` still scopes to fixture + paper broker. Patch broker factory and live adapter methods to raise if called. Do not execute the raw live CLI.

- [ ] **Step 8: Run full tests and commit**

Run: `python3 -m unittest discover -s tests -v`

Expected: all pass.

Commit intent: `레짐 판단과 후보 선별을 기존 exit-first paper 사이클에 연결한다`

---

### Task 6: Leakage-Safe Walk-Forward Evidence and Course Documentation

**Files:**
- Create: `prism_core/walk_forward.py`
- Create: `tests/test_walk_forward.py`
- Modify: `docs/architecture.md`
- Modify: `docs/runtime-profiles.md`
- Modify: `lecture/exercises/part3_실습가이드.md`
- Modify: `lecture/exercises/part4_실습가이드.md` if present
- Modify: `tests/test_prism_core_foundation_contract.py`

**Interfaces:**
- Consumes: historical fixture/provider series, classifier, strategy, policy.
- Produces: `WalkForwardConfig`, `TradeSample`, `SegmentMetrics`, `WalkForwardReport`, `run_walk_forward()`.

- [ ] **Step 1: Write temporal-isolation and report-contract tests**

```python
class WalkForwardTest(unittest.TestCase):
    def test_decision_at_t_never_reads_bar_after_t(self):
        guarded = GuardedSeries(full_bars, forbidden_after=decision_date)
        run_walk_forward(guarded, config=CONFIG)
        self.assertEqual(guarded.future_reads, [])

    def test_report_groups_market_regime_strategy_and_trigger(self):
        report = run_walk_forward(FIXTURE_HISTORY, config=CONFIG)
        keys = {(m.market, m.regime, m.strategy_id, m.trigger_type) for m in report.segments}
        self.assertIn((Market.KR, Regime.STRONG_BULL, "default_oneil", TriggerType.BREAKOUT), keys)
        self.assertIn((Market.US, Regime.STRONG_BEAR, "default_oneil", TriggerType.OVERSOLD_REBOUND), keys)

    def test_tiny_samples_never_auto_tune_policy(self):
        report = run_walk_forward(SMALL_HISTORY, config=replace(CONFIG, minimum_samples=30))
        self.assertTrue(all(not item.policy_change_allowed for item in report.segments))
```

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_walk_forward -v`

Expected: missing walk-forward module/API.

- [ ] **Step 3: Implement chronological train/evaluate windows and conservative fills**

```python
HistoricalMarketData = Mapping[
    Market,
    tuple[IndexBundle, tuple[UniverseMember, ...], Mapping[Instrument, MarketSeries]],
]

@dataclass(frozen=True)
class WalkForwardConfig:
    warmup_sessions: int = 220
    evaluation_sessions: int = 63
    step_sessions: int = 21
    maximum_holding_sessions: int = 60
    slippage_bps: Decimal = Decimal("10")
    minimum_samples: int = 30

@dataclass(frozen=True)
class TradeSample:
    market: Market
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
    comparison_deltas: Mapping[tuple[Market, Regime, str, TriggerType], Decimal]

def run_walk_forward(history: HistoricalMarketData, *, config: WalkForwardConfig,
                     strategy: ScreeningStrategy = OneilTrendStrategy(),
                     policy_provider: Callable[[Regime], RegimePolicy] = policy_for
                     ) -> WalkForwardReport:
    pass
```

At session `t`, classifier and screener receive bars ending at `t`; entries fill no earlier than `t+1` open with adverse slippage. Stops win ties over targets on an ambiguous OHLC bar. Exit evaluation follows hard stop → trailing → weak-regime target → max-hold. Compute sample count, win rate, mean/median return, MFE, MAE, stop count, mean holding sessions, and maximum losing streak by market×regime×strategy×trigger. Never mutate production policy from a report.

- [ ] **Step 4: Add a policy compatibility comparison**

Run the same fixture history with `RegimeAwarePolicy` and a test-only `FlatPolicy`. The report must expose per-segment deltas, but tests assert reproducibility and risk invariants—not that regime-aware policy always earns more. Mark segments below `minimum_samples` as `insufficient_sample`.

- [ ] **Step 5: Update course documentation using coding-agent prompts**

Document:

- why regime and screening must be evaluated together;
- how the same candidate is admitted in bull and rejected in bear;
- order of provider validation → regime → screening → analysis gate → sizing → existing cycle;
- KR/US differences (120/60 versus 200/50 and VIX) without pretending identical data fields;
- profile behavior: mock fallback is allowed only in mock/real_data observation, paper/live fail closed;
- how a student asks the coding agent to run the classroom full cycle and explain regime/candidate/order/fill evidence;
- how Part 4 Track A replaces one `ScreeningStrategy` plugin while Tracks B/C/D preserve the core contracts;
- that walk-forward is evidence, not profit assurance, and live activation remains separately gated.

Student-facing docs must not require raw terminal command blocks. Put executable commands only in developer/test documents.

- [ ] **Step 6: Add relational documentation contract tests**

Assert that docs contain `strong_bull`, `strong_bear`, `KR 120/60`, `US 200/50`, `VIX`, `paper/live`, `fail-closed`, `미래 데이터`, and `수익 보장 아님`; also assert they do not claim KIS full lifecycle, Toss WTS, OAuth evidence, or dashboard integration complete in this slice.

- [ ] **Step 7: Run complete verification**

Run:

- `python3 -m unittest discover -s tests -v`
- keyless `main.run_pipeline()` mock smoke with a temporary `db.DB_PATH`
- classroom `main.run_pipeline()` smoke with a temporary `db.DB_PATH`
- paper/live provider-failure smoke with broker mutation mocks asserting zero calls
- `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m compileall main.py screening.py runtime_config.py prism_core`
- `git diff --check`
- `git status --short`
- staged filename and secret-pattern scan

Expected: all tests/smokes pass; no `prism.db`, reports, logs, replay locks, tokens, local paths, or credentials are staged.

- [ ] **Step 8: Commit**

Commit intent: `레짐과 전략의 궁합을 미래 누수 없는 강의 증거로 보여준다`

---

## Final Review Gate

Before starting `2026-07-19-evidence-oauth.md`:

- run an immutable merge-base-to-HEAD review package;
- obtain independent code/spec/security and architecture verdicts;
- fix all Critical/Important findings with one bounded fixer and re-review;
- confirm legacy mock, classroom KR/US replay, paper/live provider fail-closed, schema migration, cycle ownership, and walk-forward temporal isolation;
- record exact commands/results in `.superpowers/sdd/market-regime-screening-review.md`;
- keep lease-expiry subprocess fencing, OAuth process-global state, KIS lifecycle, Toss WTS, dashboard tables, and large Ledger extraction as explicit later plans unless a correctness failure makes one blocking.
