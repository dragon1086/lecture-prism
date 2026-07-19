from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .domain import (
    Fill,
    Market,
    OrderIntent,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionFillConflict,
    validate_transition,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS prism_core_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO prism_core_meta (key, value) VALUES ('schema_version', '1');
CREATE TABLE IF NOT EXISTS broker_orders (
    client_order_id TEXT PRIMARY KEY, market TEXT NOT NULL, symbol TEXT NOT NULL,
    side TEXT NOT NULL, order_type TEXT NOT NULL, quantity TEXT NOT NULL,
    limit_price TEXT, currency TEXT NOT NULL, strategy_id TEXT NOT NULL,
    reason TEXT NOT NULL, status TEXT NOT NULL,
    filled_quantity TEXT NOT NULL DEFAULT '0', average_fill_price TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, client_order_id TEXT NOT NULL,
    status TEXT NOT NULL, occurred_at TEXT NOT NULL,
    -- First observation of each status; fills is the per-execution audit log.
    UNIQUE(client_order_id, status)
);
CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY, client_order_id TEXT NOT NULL, market TEXT NOT NULL,
    symbol TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL,
    price TEXT NOT NULL, currency TEXT NOT NULL, occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    market TEXT NOT NULL, symbol TEXT NOT NULL, quantity TEXT NOT NULL,
    average_price TEXT NOT NULL, currency TEXT NOT NULL,
    high_since_entry TEXT NOT NULL, strategy_id TEXT NOT NULL,
    updated_at TEXT NOT NULL, PRIMARY KEY(market, symbol)
);
CREATE TABLE IF NOT EXISTS realized_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, market TEXT NOT NULL,
    symbol TEXT NOT NULL, quantity TEXT NOT NULL, entry_price TEXT NOT NULL,
    exit_price TEXT NOT NULL, pnl_amount TEXT NOT NULL, currency TEXT NOT NULL,
    strategy_id TEXT NOT NULL, closed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS classroom_replays (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE, strategy_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL, owner_token TEXT, lease_expires_at REAL,
    phase INTEGER NOT NULL DEFAULT 1,
    realized_trades INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT
);
"""

_UNRESOLVED_ORDER_STATUSES = (
    OrderStatus.CREATED,
    OrderStatus.PREVIEWED,
    OrderStatus.SUBMITTED,
    OrderStatus.ACCEPTED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.UNKNOWN,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ClassroomReplayClaim:
    sequence: int
    session_id: str
    strategy_id: str
    owner_token: str
    phase: int


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(classroom_replays)"
                ).fetchall()
            }
            if "phase" not in columns:
                conn.execute(
                    "ALTER TABLE classroom_replays "
                    "ADD COLUMN phase INTEGER NOT NULL DEFAULT 1"
                )
                conn.execute(
                    "UPDATE classroom_replays SET phase=3 "
                    "WHERE status='INCOMPLETE' AND EXISTS ("
                    "SELECT 1 FROM broker_orders "
                    "WHERE broker_orders.strategy_id="
                    "classroom_replays.strategy_id "
                    "AND broker_orders.side='SELL')"
                )

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def cycle_fence(self):
        lock_path = Path(f"{self.path}.cycle-lock")
        conn = sqlite3.connect(lock_path, timeout=0)
        try:
            try:
                conn.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError:
                conn.close()
                yield False
                return
            try:
                yield True
            finally:
                conn.rollback()
        finally:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                pass

    @contextmanager
    def classroom_replay_fence(self, *, wait_seconds: float):
        """Serialize complete classroom replay invocations across processes."""

        if wait_seconds < 0:
            raise ValueError("wait_seconds cannot be negative")
        lock_path = Path(f"{self.path}.classroom-replay-lock")
        conn = sqlite3.connect(lock_path, timeout=wait_seconds)
        try:
            try:
                conn.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError:
                conn.close()
                yield False
                return
            try:
                yield True
            finally:
                conn.rollback()
        finally:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                pass

    def claim_classroom_replay(
        self,
        owner_token: str,
        *,
        lease_seconds: float,
        now: float | None = None,
    ) -> ClassroomReplayClaim | None:
        """Claim the sole incomplete replay or allocate its next sequence."""

        if not isinstance(owner_token, str) or not owner_token.strip():
            raise ValueError("owner_token is required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        claimed_at = time.time() if now is None else float(now)
        lease_expires_at = claimed_at + lease_seconds
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM classroom_replays "
                "WHERE status='INCOMPLETE' ORDER BY sequence LIMIT 1"
            ).fetchone()
            if row is not None:
                active_owner = row["owner_token"]
                active_until = row["lease_expires_at"]
                if (
                    active_owner is not None
                    and active_until is not None
                    and float(active_until) > claimed_at
                ):
                    return None
                cursor = conn.execute(
                    "UPDATE classroom_replays "
                    "SET owner_token=?,lease_expires_at=?,updated_at=? "
                    "WHERE sequence=? AND status='INCOMPLETE' "
                    "AND (owner_token IS NULL OR lease_expires_at IS NULL "
                    "OR lease_expires_at<=?)",
                    (
                        owner_token,
                        lease_expires_at,
                        _now(),
                        row["sequence"],
                        claimed_at,
                    ),
                )
                if not cursor.rowcount:
                    return None
                sequence = int(row["sequence"])
                session_id = row["session_id"]
                strategy_id = row["strategy_id"]
                phase = int(row["phase"])
            else:
                sequence = int(
                    conn.execute(
                        "SELECT COALESCE(MAX(sequence),0)+1 "
                        "FROM classroom_replays"
                    ).fetchone()[0]
                )
                session_id = f"classroom-{sequence:06d}"
                strategy_id = f"classroom-replay:{session_id}"
                phase = 1
                timestamp = _now()
                conn.execute(
                    "INSERT INTO classroom_replays "
                    "(sequence,session_id,strategy_id,status,owner_token,"
                    "lease_expires_at,created_at,updated_at) "
                    "VALUES (?,?,?,'INCOMPLETE',?,?,?,?)",
                    (
                        sequence,
                        session_id,
                        strategy_id,
                        owner_token,
                        lease_expires_at,
                        timestamp,
                        timestamp,
                    ),
                )
        return ClassroomReplayClaim(
            sequence, session_id, strategy_id, owner_token, phase
        )

    def renew_classroom_replay(
        self,
        claim: ClassroomReplayClaim,
        *,
        lease_seconds: float,
        now: float | None = None,
    ) -> None:
        renewed_at = time.time() if now is None else float(now)
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                "UPDATE classroom_replays "
                "SET lease_expires_at=?,updated_at=? "
                "WHERE sequence=? AND status='INCOMPLETE' AND owner_token=?",
                (
                    renewed_at + lease_seconds,
                    _now(),
                    claim.sequence,
                    claim.owner_token,
                ),
            )
            if not cursor.rowcount:
                raise RuntimeError("classroom replay lease lost")

    def release_classroom_replay(self, claim: ClassroomReplayClaim) -> None:
        with self._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE classroom_replays "
                "SET owner_token=NULL,lease_expires_at=NULL,updated_at=? "
                "WHERE sequence=? AND status='INCOMPLETE' AND owner_token=?",
                (_now(), claim.sequence, claim.owner_token),
            )

    def advance_classroom_replay_phase(
        self,
        claim: ClassroomReplayClaim,
        *,
        expected_phase: int,
        next_phase: int,
    ) -> ClassroomReplayClaim:
        if next_phase != expected_phase + 1:
            raise ValueError("classroom replay phase must advance by one")
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                "UPDATE classroom_replays SET phase=?,updated_at=? "
                "WHERE sequence=? AND status='INCOMPLETE' "
                "AND owner_token=? AND phase=?",
                (
                    next_phase,
                    _now(),
                    claim.sequence,
                    claim.owner_token,
                    expected_phase,
                ),
            )
            if not cursor.rowcount:
                raise RuntimeError("classroom replay phase or lease lost")
        return replace(claim, phase=next_phase)

    def complete_classroom_replay(
        self,
        claim: ClassroomReplayClaim,
        *,
        expected_trades: tuple[
            tuple[Market, str, Decimal, Decimal, str], ...
        ],
    ) -> dict:
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM classroom_replays WHERE sequence=?",
                (claim.sequence,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "INCOMPLETE"
                or row["owner_token"] != claim.owner_token
                or int(row["phase"]) != 4
            ):
                raise RuntimeError("classroom replay lease lost")
            trade_rows = conn.execute(
                "SELECT market,symbol,quantity,exit_price,currency "
                "FROM realized_trades WHERE strategy_id=?",
                (claim.strategy_id,),
            ).fetchall()
            actual_trades = sorted(
                (
                    trade["market"],
                    trade["symbol"],
                    Decimal(trade["quantity"]),
                    Decimal(trade["exit_price"]),
                    trade["currency"],
                )
                for trade in trade_rows
            )
            prescribed_trades = sorted(
                (
                    market.value,
                    symbol,
                    quantity,
                    exit_price,
                    currency,
                )
                for market, symbol, quantity, exit_price, currency in expected_trades
            )
            realized = len(actual_trades)
            positions = int(
                conn.execute(
                    "SELECT COUNT(*) FROM positions WHERE strategy_id=?",
                    (claim.strategy_id,),
                ).fetchone()[0]
            )
            if actual_trades != prescribed_trades:
                raise RuntimeError("classroom replay trade contract mismatch")
            if positions != 0:
                raise RuntimeError(
                    "classroom replay incomplete: "
                    f"realized={realized}, positions={positions}"
                )
            completed_at = _now()
            conn.execute(
                "UPDATE classroom_replays SET status='COMPLETED',"
                "owner_token=NULL,lease_expires_at=NULL,realized_trades=?,"
                "updated_at=?,completed_at=? WHERE sequence=?",
                (
                    realized,
                    completed_at,
                    completed_at,
                    claim.sequence,
                ),
            )
        return {
            "session": claim.session_id,
            "final_positions": positions,
            "realized_trades": realized,
        }

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> OrderRecord:
        intent = OrderIntent(
            client_order_id=row["client_order_id"],
            market=Market(row["market"]),
            symbol=row["symbol"],
            side=OrderSide(row["side"]),
            order_type=OrderType(row["order_type"]),
            quantity=Decimal(row["quantity"]),
            limit_price=Decimal(row["limit_price"]) if row["limit_price"] else None,
            currency=row["currency"],
            strategy_id=row["strategy_id"],
            reason=row["reason"],
        )
        return OrderRecord(
            intent=intent,
            status=OrderStatus(row["status"]),
            filled_quantity=Decimal(row["filled_quantity"]),
            average_fill_price=(
                Decimal(row["average_fill_price"])
                if row["average_fill_price"]
                else None
            ),
        )

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        return Position(
            market=Market(row["market"]),
            symbol=row["symbol"],
            quantity=Decimal(row["quantity"]),
            average_price=Decimal(row["average_price"]),
            currency=row["currency"],
            high_since_entry=Decimal(row["high_since_entry"]),
            strategy_id=row["strategy_id"],
        )

    @staticmethod
    def _order_payload_matches(row: sqlite3.Row, intent: OrderIntent) -> bool:
        stored_limit = (
            Decimal(row["limit_price"]) if row["limit_price"] is not None else None
        )
        return (
            row["client_order_id"] == intent.client_order_id
            and row["market"] == intent.market.value
            and row["symbol"] == intent.symbol
            and row["side"] == intent.side.value
            and row["order_type"] == intent.order_type.value
            and Decimal(row["quantity"]) == intent.quantity
            and stored_limit == intent.limit_price
            and row["currency"] == intent.currency
            and row["strategy_id"] == intent.strategy_id
            and row["reason"] == intent.reason
        )

    @staticmethod
    def _validate_fill(fill: Fill) -> str:
        for name in ("fill_id", "client_order_id", "symbol"):
            value = getattr(fill, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"fill {name} is required")
        if not isinstance(fill.market, Market):
            raise ValueError("fill market must be a Market")
        if not isinstance(fill.side, OrderSide):
            raise ValueError("fill side must be an OrderSide")
        for name in ("quantity", "price"):
            value = getattr(fill, name)
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value <= 0
            ):
                raise ValueError(f"fill {name} must be a finite positive Decimal")
        if fill.market is Market.KR:
            for name in ("quantity", "price"):
                value = getattr(fill, name)
                if value != value.to_integral_value():
                    raise ValueError(
                        f"KR fill {name} must be a whole number"
                    )
        if not isinstance(fill.currency, str):
            raise ValueError("fill currency is required")
        currency = fill.currency.strip().upper()
        expected_currency = "KRW" if fill.market is Market.KR else "USD"
        if currency != expected_currency:
            raise ValueError(
                f"{fill.market.value} fill currency must be {expected_currency}"
            )
        return currency

    @staticmethod
    def _fill_payload_matches(
        row: sqlite3.Row, fill: Fill, normalized_currency: str
    ) -> bool:
        return (
            row["fill_id"] == fill.fill_id
            and row["client_order_id"] == fill.client_order_id
            and row["market"] == fill.market.value
            and row["symbol"] == fill.symbol
            and row["side"] == fill.side.value
            and Decimal(row["quantity"]) == fill.quantity
            and Decimal(row["price"]) == fill.price
            and row["currency"] == normalized_currency
        )

    def create_order(self, intent: OrderIntent) -> OrderRecord:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO broker_orders "
                "(client_order_id,market,symbol,side,order_type,quantity,limit_price,currency,strategy_id,reason,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    intent.client_order_id,
                    intent.market.value,
                    intent.symbol,
                    intent.side.value,
                    intent.order_type.value,
                    str(intent.quantity),
                    str(intent.limit_price) if intent.limit_price is not None else None,
                    intent.currency,
                    intent.strategy_id,
                    intent.reason,
                    OrderStatus.CREATED.value,
                    now,
                    now,
                ),
            )
            if cursor.rowcount:
                conn.execute(
                    "INSERT INTO order_events (client_order_id,status,occurred_at) VALUES (?,?,?)",
                    (intent.client_order_id, OrderStatus.CREATED.value, now),
                )
            else:
                row = conn.execute(
                    "SELECT * FROM broker_orders WHERE client_order_id=?",
                    (intent.client_order_id,),
                ).fetchone()
                if row is None or not self._order_payload_matches(row, intent):
                    raise ValueError(
                        f"order id collision: {intent.client_order_id}"
                    )
        return self.get_order(intent.client_order_id)

    def create_order_if_admissible(
        self, intent: OrderIntent
    ) -> OrderRecord | None:
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (intent.client_order_id,),
            ).fetchone()
            if existing is not None:
                if not self._order_payload_matches(existing, intent):
                    raise ValueError(
                        f"order id collision: {intent.client_order_id}"
                    )
                status = OrderStatus(existing["status"])
                if status is OrderStatus.UNKNOWN:
                    return None
                if status in _UNRESOLVED_ORDER_STATUSES:
                    placeholders = ",".join(
                        "?" for _ in _UNRESOLVED_ORDER_STATUSES
                    )
                    other = conn.execute(
                        "SELECT 1 FROM broker_orders "
                        f"WHERE market=? AND symbol=? AND client_order_id<>? "
                        f"AND status IN ({placeholders}) LIMIT 1",
                        (
                            intent.market.value,
                            intent.symbol,
                            intent.client_order_id,
                            *(
                                item.value
                                for item in _UNRESOLVED_ORDER_STATUSES
                            ),
                        ),
                    ).fetchone()
                    if other is not None:
                        return None
                return self._row_to_order(existing)

            position = conn.execute(
                "SELECT 1 FROM positions WHERE market=? AND symbol=?",
                (intent.market.value, intent.symbol),
            ).fetchone()
            if intent.side is OrderSide.BUY and position is not None:
                return None
            if intent.side is OrderSide.SELL and position is None:
                return None

            placeholders = ",".join(
                "?" for _ in _UNRESOLVED_ORDER_STATUSES
            )
            unresolved = conn.execute(
                "SELECT 1 FROM broker_orders "
                f"WHERE market=? AND symbol=? AND status IN ({placeholders}) "
                "LIMIT 1",
                (
                    intent.market.value,
                    intent.symbol,
                    *(item.value for item in _UNRESOLVED_ORDER_STATUSES),
                ),
            ).fetchone()
            if unresolved is not None:
                return None

            now = _now()
            conn.execute(
                "INSERT INTO broker_orders "
                "(client_order_id,market,symbol,side,order_type,quantity,limit_price,currency,strategy_id,reason,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    intent.client_order_id,
                    intent.market.value,
                    intent.symbol,
                    intent.side.value,
                    intent.order_type.value,
                    str(intent.quantity),
                    (
                        str(intent.limit_price)
                        if intent.limit_price is not None
                        else None
                    ),
                    intent.currency,
                    intent.strategy_id,
                    intent.reason,
                    OrderStatus.CREATED.value,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO order_events "
                "(client_order_id,status,occurred_at) VALUES (?,?,?)",
                (
                    intent.client_order_id,
                    OrderStatus.CREATED.value,
                    now,
                ),
            )
            created = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (intent.client_order_id,),
            ).fetchone()
            return self._row_to_order(created)

    def create_or_resume_exit(
        self,
        run_id: str,
        market: Market,
        symbol: str,
        reason: str,
    ) -> tuple[OrderRecord | None, str | None]:
        placeholders = ",".join("?" for _ in _UNRESOLVED_ORDER_STATUSES)
        with self._connect(immediate=True) as conn:
            position_row = conn.execute(
                "SELECT * FROM positions WHERE market=? AND symbol=?",
                (market.value, symbol),
            ).fetchone()
            if position_row is None:
                return None, None

            unresolved = conn.execute(
                "SELECT * FROM broker_orders "
                f"WHERE market=? AND symbol=? AND status IN ({placeholders}) "
                "ORDER BY created_at,client_order_id",
                (
                    market.value,
                    symbol,
                    *(status.value for status in _UNRESOLVED_ORDER_STATUSES),
                ),
            ).fetchall()
            buy_rows = [
                row for row in unresolved if OrderSide(row["side"]) is OrderSide.BUY
            ]
            if buy_rows:
                reason_code = (
                    "unknown_buy_order"
                    if any(
                        OrderStatus(row["status"]) is OrderStatus.UNKNOWN
                        for row in buy_rows
                    )
                    else "unresolved_buy_order"
                )
                return None, reason_code

            sell_rows = [
                row
                for row in unresolved
                if OrderSide(row["side"]) is OrderSide.SELL
            ]
            if any(
                OrderStatus(row["status"]) is OrderStatus.UNKNOWN
                for row in sell_rows
            ):
                return None, "unknown_exit_order"
            if len(sell_rows) > 1:
                return None, "multiple_exit_orders"
            if sell_rows:
                return self._row_to_order(sell_rows[0]), None

            base_id = f"{run_id}:{market.value}:{symbol}:SELL"
            client_order_id = base_id
            suffix = 1
            while conn.execute(
                "SELECT 1 FROM broker_orders WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone() is not None:
                suffix += 1
                client_order_id = f"{base_id}:{suffix}"

            intent = OrderIntent(
                client_order_id=client_order_id,
                market=market,
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal(position_row["quantity"]),
                limit_price=None,
                currency=position_row["currency"],
                strategy_id=position_row["strategy_id"],
                reason=reason,
            )
            now = _now()
            conn.execute(
                "INSERT INTO broker_orders "
                "(client_order_id,market,symbol,side,order_type,quantity,limit_price,currency,strategy_id,reason,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    intent.client_order_id,
                    intent.market.value,
                    intent.symbol,
                    intent.side.value,
                    intent.order_type.value,
                    str(intent.quantity),
                    None,
                    intent.currency,
                    intent.strategy_id,
                    intent.reason,
                    OrderStatus.CREATED.value,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO order_events "
                "(client_order_id,status,occurred_at) VALUES (?,?,?)",
                (
                    intent.client_order_id,
                    OrderStatus.CREATED.value,
                    now,
                ),
            )
            created = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (intent.client_order_id,),
            ).fetchone()
            return self._row_to_order(created), None

    def get_order(self, client_order_id: str) -> OrderRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
        if row is None:
            raise KeyError(client_order_id)
        return self._row_to_order(row)

    def transition_order(
        self, client_order_id: str, target: OrderStatus
    ) -> OrderRecord:
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
            if row is None:
                raise KeyError(client_order_id)
            current = OrderStatus(row["status"])
            if current is target:
                return self._row_to_order(row)
            if not validate_transition(current, target):
                raise ValueError(
                    f"invalid order transition: {current.value} -> {target.value}"
                )
            now = _now()
            conn.execute(
                "UPDATE broker_orders SET status=?, updated_at=? WHERE client_order_id=?",
                (target.value, now, client_order_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO order_events (client_order_id,status,occurred_at) VALUES (?,?,?)",
                (client_order_id, target.value, now),
            )
        return self.get_order(client_order_id)

    def list_positions(self) -> list[Position]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions ORDER BY market,symbol"
            ).fetchall()
        return [self._row_to_position(row) for row in rows]

    def has_unresolved_order(self, market: Market, symbol: str) -> bool:
        if not isinstance(market, Market):
            raise ValueError("market must be a Market")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        placeholders = ",".join("?" for _ in _UNRESOLVED_ORDER_STATUSES)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM broker_orders "
                f"WHERE market=? AND symbol=? AND status IN ({placeholders}) "
                "LIMIT 1",
                (
                    market.value,
                    symbol,
                    *(status.value for status in _UNRESOLVED_ORDER_STATUSES),
                ),
            ).fetchone()
        return row is not None

    def list_unresolved_orders(
        self, market: Market, symbol: str
    ) -> list[OrderRecord]:
        placeholders = ",".join("?" for _ in _UNRESOLVED_ORDER_STATUSES)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM broker_orders "
                f"WHERE market=? AND symbol=? AND status IN ({placeholders}) "
                "ORDER BY created_at,client_order_id",
                (
                    market.value,
                    symbol,
                    *(status.value for status in _UNRESOLVED_ORDER_STATUSES),
                ),
            ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def count_realized_trades(self, strategy_id: str | None = None) -> int:
        with self._connect() as conn:
            if strategy_id is not None:
                return int(
                    conn.execute(
                        "SELECT COUNT(*) FROM realized_trades "
                        "WHERE strategy_id=?",
                        (strategy_id,),
                    ).fetchone()[0]
                )
            return int(
                conn.execute("SELECT COUNT(*) FROM realized_trades").fetchone()[0]
            )

    def count_positions(self, strategy_id: str | None = None) -> int:
        with self._connect() as conn:
            if strategy_id is not None:
                return int(
                    conn.execute(
                        "SELECT COUNT(*) FROM positions WHERE strategy_id=?",
                        (strategy_id,),
                    ).fetchone()[0]
                )
            return int(conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0])

    def update_high_water(
        self, market: Market, symbol: str, price: Decimal
    ) -> Position:
        if not isinstance(market, Market):
            raise ValueError("market must be a Market")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        if (
            not isinstance(price, Decimal)
            or not price.is_finite()
            or price <= 0
        ):
            raise ValueError("price must be a finite positive Decimal")
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE market=? AND symbol=?",
                (market.value, symbol),
            ).fetchone()
            if row is None:
                raise KeyError((market.value, symbol))
            high = max(Decimal(row["high_since_entry"]), price)
            if high != Decimal(row["high_since_entry"]):
                conn.execute(
                    "UPDATE positions SET high_since_entry=?,updated_at=? WHERE market=? AND symbol=?",
                    (str(high), _now(), market.value, symbol),
                )
                row = conn.execute(
                    "SELECT * FROM positions WHERE market=? AND symbol=?",
                    (market.value, symbol),
                ).fetchone()
            return self._row_to_position(row)

    def record_fill(
        self,
        fill: Fill,
        *,
        allowed_statuses: frozenset[OrderStatus] | None = None,
    ) -> Position | None:
        normalized_currency = self._validate_fill(fill)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing_fill = conn.execute(
                "SELECT * FROM fills WHERE fill_id=?", (fill.fill_id,)
            ).fetchone()
            if existing_fill is not None:
                if not self._fill_payload_matches(
                    existing_fill, fill, normalized_currency
                ):
                    raise ValueError(f"fill id collision: {fill.fill_id}")
                position_row = conn.execute(
                    "SELECT * FROM positions WHERE market=? AND symbol=?",
                    (fill.market.value, fill.symbol),
                ).fetchone()
                conn.commit()
                return (
                    self._row_to_position(position_row)
                    if position_row is not None
                    else None
                )

            order_row = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (fill.client_order_id,),
            ).fetchone()
            if order_row is None:
                raise KeyError(fill.client_order_id)
            order = self._row_to_order(order_row)
            if (
                order.intent.market,
                order.intent.symbol,
                order.intent.side,
                order.intent.currency,
            ) != (fill.market, fill.symbol, fill.side, normalized_currency):
                raise ValueError("fill does not match order")
            if (
                allowed_statuses is not None
                and order.status not in allowed_statuses
            ):
                raise ValueError(
                    f"order cannot be filled from {order.status.value}"
                )
            if order.intent.order_type is OrderType.LIMIT:
                limit_price = order.intent.limit_price
                if (
                    order.intent.side is OrderSide.BUY
                    and fill.price > limit_price
                ):
                    raise ValueError("BUY fill price exceeds limit")
                if (
                    order.intent.side is OrderSide.SELL
                    and fill.price < limit_price
                ):
                    raise ValueError("SELL fill price below limit")

            cumulative = order.filled_quantity + fill.quantity
            if fill.quantity <= 0 or cumulative > order.intent.quantity:
                raise ValueError("fill quantity exceeds order quantity")

            conn.execute(
                "INSERT INTO fills (fill_id,client_order_id,market,symbol,side,quantity,price,currency,occurred_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    fill.fill_id,
                    fill.client_order_id,
                    fill.market.value,
                    fill.symbol,
                    fill.side.value,
                    str(fill.quantity),
                    str(fill.price),
                    normalized_currency,
                    _now(),
                ),
            )

            position_row = conn.execute(
                "SELECT * FROM positions WHERE market=? AND symbol=?",
                (fill.market.value, fill.symbol),
            ).fetchone()
            now = _now()
            if fill.side is OrderSide.BUY:
                old_qty = (
                    Decimal(position_row["quantity"])
                    if position_row
                    else Decimal("0")
                )
                old_avg = (
                    Decimal(position_row["average_price"])
                    if position_row
                    else Decimal("0")
                )
                new_qty = old_qty + fill.quantity
                new_avg = (
                    (old_qty * old_avg) + (fill.quantity * fill.price)
                ) / new_qty
                old_high = (
                    Decimal(position_row["high_since_entry"])
                    if position_row
                    else fill.price
                )
                conn.execute(
                    "INSERT INTO positions (market,symbol,quantity,average_price,currency,high_since_entry,strategy_id,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(market,symbol) DO UPDATE SET "
                    "quantity=excluded.quantity,average_price=excluded.average_price,"
                    "high_since_entry=excluded.high_since_entry,strategy_id=excluded.strategy_id,updated_at=excluded.updated_at",
                    (
                        fill.market.value,
                        fill.symbol,
                        str(new_qty),
                        str(new_avg),
                        normalized_currency,
                        str(max(old_high, fill.price)),
                        order.intent.strategy_id,
                        now,
                    ),
                )
            else:
                if position_row is None:
                    raise PositionFillConflict(
                        fill.market, fill.symbol, "missing"
                    )
                old_qty = Decimal(position_row["quantity"])
                old_avg = Decimal(position_row["average_price"])
                if fill.quantity > old_qty:
                    raise PositionFillConflict(
                        fill.market, fill.symbol, "quantity_changed"
                    )
                remaining = old_qty - fill.quantity
                conn.execute(
                    "INSERT INTO realized_trades (market,symbol,quantity,entry_price,exit_price,pnl_amount,currency,strategy_id,closed_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        fill.market.value,
                        fill.symbol,
                        str(fill.quantity),
                        str(old_avg),
                        str(fill.price),
                        str((fill.price - old_avg) * fill.quantity),
                        normalized_currency,
                        position_row["strategy_id"],
                        now,
                    ),
                )
                if remaining == 0:
                    conn.execute(
                        "DELETE FROM positions WHERE market=? AND symbol=?",
                        (fill.market.value, fill.symbol),
                    )
                else:
                    conn.execute(
                        "UPDATE positions SET quantity=?,updated_at=? WHERE market=? AND symbol=?",
                        (str(remaining), now, fill.market.value, fill.symbol),
                    )

            previous_cost = (
                order.average_fill_price or Decimal("0")
            ) * order.filled_quantity
            average_fill = (
                previous_cost + fill.price * fill.quantity
            ) / cumulative
            target = (
                OrderStatus.FILLED
                if cumulative == order.intent.quantity
                else OrderStatus.PARTIALLY_FILLED
            )
            if order.status is not target and not validate_transition(
                order.status, target
            ):
                raise ValueError(
                    f"invalid order transition: {order.status.value} -> {target.value}"
                )
            conn.execute(
                "UPDATE broker_orders SET status=?,filled_quantity=?,average_fill_price=?,updated_at=? WHERE client_order_id=?",
                (
                    target.value,
                    str(cumulative),
                    str(average_fill),
                    now,
                    fill.client_order_id,
                ),
            )
            if order.status is not target:
                conn.execute(
                    "INSERT OR IGNORE INTO order_events (client_order_id,status,occurred_at) VALUES (?,?,?)",
                    (fill.client_order_id, target.value, now),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        positions = self.list_positions()
        return next(
            (
                position
                for position in positions
                if position.market is fill.market and position.symbol == fill.symbol
            ),
            None,
        )
