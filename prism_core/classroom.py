"""Deterministic, offline state-transition replay for classroom use."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from .cycle import CycleResult, TradingCycle
from .domain import Market, OrderIntent, OrderSide, OrderType
from .ledger import Ledger
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


def _entry_intents(session: str) -> list[OrderIntent]:
    return [
        OrderIntent(
            f"{session}-1:KR:005930:BUY",
            Market.KR,
            "005930",
            OrderSide.BUY,
            OrderType.LIMIT,
            Decimal("1"),
            _ENTRY_QUOTES[(Market.KR, "005930")],
            "KRW",
            strategy_id="classroom_oneil",
        ),
        OrderIntent(
            f"{session}-1:US:AAPL:BUY",
            Market.US,
            "AAPL",
            OrderSide.BUY,
            OrderType.LIMIT,
            Decimal("1"),
            _ENTRY_QUOTES[(Market.US, "AAPL")],
            "USD",
            strategy_id="classroom_oneil",
        ),
    ]


def _require_completed(result: CycleResult) -> None:
    if result.blocked:
        reasons = ",".join(block.reason for block in result.blocked)
        raise RuntimeError(f"classroom replay blocked: {reasons}")


def run_classroom_replay(db_path: Path) -> dict:
    """Run BUY, high-water HOLD, and trailing-exit cycles on ``db_path``."""

    path = Path(db_path)
    ledger = Ledger(path)
    realized_before = ledger.count_realized_trades()
    session = f"classroom-{(realized_before // 2) + 1:06d}"

    _require_completed(
        TradingCycle(PaperBroker(ledger), _ENTRY_QUOTES).run(
            f"{session}-1", _entry_intents(session), auto_fill=True
        )
    )
    _require_completed(
        TradingCycle(
            PaperBroker(Ledger(path)), _HIGH_WATER_QUOTES
        ).run(f"{session}-2", [], auto_fill=True)
    )
    final_broker = PaperBroker(Ledger(path))
    _require_completed(
        TradingCycle(final_broker, _TRAILING_EXIT_QUOTES).run(
            f"{session}-3", [], auto_fill=True
        )
    )

    return {
        "cycles": 3,
        "final_positions": len(final_broker.get_positions()),
        "realized_trades": (
            final_broker.ledger.count_realized_trades() - realized_before
        ),
        "markets": [Market.KR.value, Market.US.value],
    }
