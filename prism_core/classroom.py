"""Deterministic, offline state-transition replay for classroom use."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import secrets
import time

from .cycle import CycleResult, TradingCycle
from .domain import Market, OrderIntent, OrderSide, OrderType
from .ledger import ClassroomReplayClaim, Ledger
from .paper_broker import PaperBroker


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
        return {
            "cycles": 3,
            **persisted,
            "markets": [Market.KR.value, Market.US.value],
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
