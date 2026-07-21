"""Deterministic, offline state-transition replay for classroom use."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from pathlib import Path
import secrets
import sqlite3
import time

from .cycle import CycleResult, TradingCycle
from .domain import Candidate, Market, OrderIntent, OrderSide, OrderType, TriggerType
from .ledger import ClassroomReplayClaim, Ledger
from .market_data import FixtureMarketDataProvider, FixtureUniverseProvider
from .market_pipeline import MarketPipeline
from .paper_broker import PaperBroker
from .policy import gate_entry, policy_for


_ENTRY_QUOTES = {
    (Market.KR, "005930"): Decimal("70000"),
    (Market.US, "AAPL"): Decimal("180"),
}
_HIGH_WATER_QUOTES = {
    (Market.KR, "005930"): Decimal("76000"),
    (Market.US, "AAPL"): Decimal("195"),
}
_TRAILING_EXIT_QUOTES = {
    (Market.KR, "005930"): Decimal("69000"),
    (Market.US, "AAPL"): Decimal("175"),
}
_REPLAY_LEASE_SECONDS = 60.0
_REPLAY_WAIT_SECONDS = 5.0
_REPLAY_POLL_SECONDS = 0.01
_TARGETS = frozenset(_ENTRY_QUOTES)
_EXPECTED_TRADES = (
    (Market.KR, "005930", Decimal("1"), Decimal("69000"), "KRW"),
    (Market.US, "AAPL", Decimal("1"), Decimal("175"), "USD"),
)
_PREPARATION_AS_OF = datetime(2026, 1, 13, 15, 0, tzinfo=timezone.utc)


class _ClassroomOversoldStrategy:
    strategy_id = "classroom_oversold_evidence_v1"
    supported_triggers = frozenset({TriggerType.OVERSOLD_REBOUND})

    def evaluate(self, instrument, series, benchmark, regime):
        reference = series.bars[-1].close
        quantum = Decimal("1").scaleb(-instrument.price_precision)
        stop = (reference * Decimal("0.95")).quantize(
            quantum, rounding=ROUND_CEILING
        )
        target = (reference + (reference - stop) * Decimal("2")).quantize(
            quantum, rounding=ROUND_HALF_UP
        )
        return (
            Candidate(
                instrument=instrument,
                as_of=regime.as_of,
                trigger_type=TriggerType.OVERSOLD_REBOUND,
                regime=regime.regime,
                feature_values={"classroom_fixture": True},
                component_scores={
                    "oversold": Decimal("6"),
                    "rebound": Decimal("4"),
                },
                final_score=Decimal("10"),
                reference_price=reference,
                stop_price=stop,
                target_price=target,
                risk_reward_ratio=(target - reference) / (reference - stop),
                source=self.strategy_id,
            ),
        )


class _PreparationBrokerView:
    """Expose the shared ledger while isolating evidence sizing from positions."""

    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def get_positions(self):
        return []


def _preparation_summary(ledger: Ledger, session_id: str) -> dict:
    run_id = f"{session_id}-preparation"
    stored_regimes = tuple(
        result
        for market in Market
        if (result := ledger.get_market_regime(run_id, market)) is not None
    )
    if stored_regimes and len(stored_regimes) != len(Market):
        raise RuntimeError("classroom preparation evidence is incomplete")

    if stored_regimes:
        regimes = stored_regimes
        candidates = tuple(ledger.list_candidates(run_id))
        decisions = tuple(
            gate_entry(
                candidate,
                analysis_score=Decimal("10"),
                policy=policy_for(candidate.regime),
            )
            for candidate in candidates
        )
        order_ids = tuple(
            f"{run_id}:{candidate.instrument.market.value}:"
            f"{candidate.instrument.symbol}:BUY"
            for candidate in candidates
            if ledger.get_entry_context(
                f"{run_id}:{candidate.instrument.market.value}:"
                f"{candidate.instrument.symbol}:BUY"
            )
            is not None
        )
    else:
        pipeline = MarketPipeline(
            provider=FixtureMarketDataProvider.standard(),
            universe_provider=FixtureUniverseProvider.standard(),
            broker=_PreparationBrokerView(ledger),
            ledger=ledger,
            profile="classroom",
            strategy=_ClassroomOversoldStrategy(),
        )
        prepared = pipeline.prepare_entries(run_id, as_of=_PREPARATION_AS_OF)
        regimes = prepared.regimes
        candidates = prepared.candidates
        decisions = prepared.decisions
        order_ids = tuple(
            context.client_order_id for context in prepared.entry_contexts
        )

    return {
        "run_id": run_id,
        "regimes": {
            result.market.value: result.regime.value for result in regimes
        },
        "candidates": [
            {
                "market": candidate.instrument.market.value,
                "symbol": candidate.instrument.symbol,
                "trigger": candidate.trigger_type.value,
                "score": str(candidate.final_score),
            }
            for candidate in candidates
        ],
        "rejected_reasons": [
            {
                "market": decision.candidate.instrument.market.value,
                "symbol": decision.candidate.instrument.symbol,
                "reasons": list(decision.reasons),
            }
            for decision in decisions
            if not decision.allowed
        ],
        "order_ids": list(order_ids),
    }


def _execution_evidence(ledger: Ledger, strategy_id: str) -> tuple[list, list]:
    with sqlite3.connect(ledger.path) as conn:
        fills = [
            {
                "fill_id": row[0],
                "client_order_id": row[1],
                "market": row[2],
                "symbol": row[3],
                "side": row[4],
                "price": row[5],
            }
            for row in conn.execute(
                "SELECT fills.fill_id,fills.client_order_id,fills.market,"
                "fills.symbol,fills.side,fills.price FROM fills "
                "JOIN broker_orders USING(client_order_id) "
                "WHERE broker_orders.strategy_id=? ORDER BY fills.fill_id",
                (strategy_id,),
            )
        ]
        realized_exits = [
            {
                "market": row[0],
                "symbol": row[1],
                "exit_client_order_id": row[2],
                "exit_fill_id": row[3],
            }
            for row in conn.execute(
                "SELECT market,symbol,exit_client_order_id,exit_fill_id "
                "FROM realized_trades WHERE strategy_id=? ORDER BY market,symbol",
                (strategy_id,),
            )
        ]
    return fills, realized_exits


def _entry_intents(
    session: str, strategy_id: str, ledger: Ledger
) -> list[OrderIntent]:
    kr_base = f"{session}-1:KR:005930:BUY"
    us_base = f"{session}-1:US:AAPL:BUY"
    return [
        OrderIntent(
            ledger.select_replay_order_id(kr_base),
            Market.KR,
            "005930",
            OrderSide.BUY,
            OrderType.LIMIT,
            Decimal("1"),
            _ENTRY_QUOTES[(Market.KR, "005930")],
            "KRW",
            strategy_id=strategy_id,
        ),
        OrderIntent(
            ledger.select_replay_order_id(us_base),
            Market.US,
            "AAPL",
            OrderSide.BUY,
            OrderType.LIMIT,
            Decimal("1"),
            _ENTRY_QUOTES[(Market.US, "AAPL")],
            "USD",
            strategy_id=strategy_id,
        ),
    ]


def _require_completed(result: CycleResult) -> None:
    if result.blocked:
        reasons = ",".join(block.reason for block in result.blocked)
        raise RuntimeError(f"classroom replay blocked: {reasons}")


def _claim_replay(ledger: Ledger, owner_token: str):
    deadline = time.monotonic() + _REPLAY_WAIT_SECONDS
    while True:
        claim = ledger.claim_classroom_replay(
            owner_token,
            lease_seconds=_REPLAY_LEASE_SECONDS,
            targets=_TARGETS,
            expected_trades=_EXPECTED_TRADES,
        )
        if claim is not None:
            return claim
        if time.monotonic() >= deadline:
            raise RuntimeError("classroom replay lease unavailable")
        time.sleep(_REPLAY_POLL_SECONDS)


def _assert_target_ownership(ledger: Ledger, strategy_id: str) -> None:
    conflicts = [
        position
        for position in ledger.list_positions()
        if (position.market, position.symbol) in _TARGETS
        and position.strategy_id != strategy_id
    ]
    if conflicts:
        raise RuntimeError("classroom replay blocked by unrelated position")


def _settle_aborted_positions(
    path: Path, ledger: Ledger, claim: ClassroomReplayClaim
) -> None:
    for strategy_id in claim.cleanup_strategies:
        quotes = {
            (position.market, position.symbol): _TRAILING_EXIT_QUOTES[
                (position.market, position.symbol)
            ]
            for position in ledger.list_positions()
            if position.strategy_id == strategy_id
            and (position.market, position.symbol) in _TARGETS
        }
        if not quotes:
            continue
        session_id = strategy_id.removeprefix("classroom-replay:")
        _require_completed(
            TradingCycle(PaperBroker(Ledger(path)), quotes).run(
                f"{session_id}-3", [], auto_fill=True
            )
        )


def _run_replay_under_fence(path: Path, ledger: Ledger) -> dict:
    owner_token = secrets.token_hex(16)
    claim = _claim_replay(ledger, owner_token)
    try:
        _settle_aborted_positions(path, ledger, claim)
        _assert_target_ownership(ledger, claim.strategy_id)
        preparation = _preparation_summary(ledger, claim.session_id)
        if claim.phase == 1:
            ledger.renew_classroom_replay(
                claim, lease_seconds=_REPLAY_LEASE_SECONDS
            )
            _require_completed(
                TradingCycle(PaperBroker(ledger), _ENTRY_QUOTES).run(
                    f"{claim.session_id}-1",
                    _entry_intents(
                        claim.session_id, claim.strategy_id, ledger
                    ),
                    auto_fill=True,
                )
            )
            _assert_target_ownership(ledger, claim.strategy_id)
            claim = ledger.advance_classroom_replay_phase(
                claim, expected_phase=1, next_phase=2
            )
        if claim.phase == 2:
            ledger.renew_classroom_replay(
                claim, lease_seconds=_REPLAY_LEASE_SECONDS
            )
            _require_completed(
                TradingCycle(
                    PaperBroker(Ledger(path)), _HIGH_WATER_QUOTES
                ).run(f"{claim.session_id}-2", [], auto_fill=True)
            )
            _assert_target_ownership(ledger, claim.strategy_id)
            claim = ledger.advance_classroom_replay_phase(
                claim, expected_phase=2, next_phase=3
            )
        if claim.phase == 3:
            ledger.renew_classroom_replay(
                claim, lease_seconds=_REPLAY_LEASE_SECONDS
            )
            _require_completed(
                TradingCycle(
                    PaperBroker(Ledger(path)), _TRAILING_EXIT_QUOTES
                ).run(f"{claim.session_id}-3", [], auto_fill=True)
            )
            _assert_target_ownership(ledger, claim.strategy_id)
            claim = ledger.advance_classroom_replay_phase(
                claim, expected_phase=3, next_phase=4
            )
        _assert_target_ownership(ledger, claim.strategy_id)
        persisted = ledger.complete_classroom_replay(
            claim, expected_trades=_EXPECTED_TRADES
        )
        fills, realized_exits = _execution_evidence(ledger, claim.strategy_id)
        return {
            "cycles": 3,
            **persisted,
            "markets": [Market.KR.value, Market.US.value],
            "preparation": preparation,
            "fills": fills,
            "realized_exits": realized_exits,
        }
    finally:
        ledger.release_classroom_replay(claim)


def run_classroom_replay(db_path: Path) -> dict:
    """Run BUY, high-water HOLD, and trailing-exit cycles on ``db_path``."""

    path = Path(db_path)
    ledger = Ledger(path)
    with ledger.classroom_replay_fence(
        wait_seconds=_REPLAY_WAIT_SECONDS
    ) as acquired:
        if not acquired:
            raise RuntimeError("classroom replay fence unavailable")
        return _run_replay_under_fence(path, ledger)
