from __future__ import annotations

import sqlite3
import time
from collections import Counter
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
    strategy_id TEXT NOT NULL, closed_at TEXT NOT NULL,
    exit_client_order_id TEXT, exit_fill_id TEXT
);
CREATE TABLE IF NOT EXISTS classroom_replays (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE, strategy_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL, owner_token TEXT, lease_expires_at REAL,
    phase INTEGER NOT NULL DEFAULT 1,
    realized_trades INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT,
    abort_reason TEXT, aborted_at TEXT
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
_TERMINAL_ORDER_STATUSES = frozenset(
    {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED}
)
_CLEANUP_ELIGIBLE_ABORT_REASONS = (
    "noncanonical_realized_trade",
    "noncanonical_trade_provenance",
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
    targets: frozenset[tuple[Market, str]] = frozenset()
    cleanup_strategies: frozenset[str] = frozenset()


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
            if "abort_reason" not in columns:
                conn.execute(
                    "ALTER TABLE classroom_replays "
                    "ADD COLUMN abort_reason TEXT"
                )
            if "aborted_at" not in columns:
                conn.execute(
                    "ALTER TABLE classroom_replays "
                    "ADD COLUMN aborted_at TEXT"
                )
            trade_columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(realized_trades)"
                ).fetchall()
            }
            if "exit_client_order_id" not in trade_columns:
                conn.execute(
                    "ALTER TABLE realized_trades "
                    "ADD COLUMN exit_client_order_id TEXT"
                )
            if "exit_fill_id" not in trade_columns:
                conn.execute(
                    "ALTER TABLE realized_trades ADD COLUMN exit_fill_id TEXT"
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
        targets: frozenset[tuple[Market, str]] = frozenset(),
        expected_trades: tuple[
            tuple[Market, str, Decimal, Decimal, str], ...
        ] = (),
    ) -> ClassroomReplayClaim | None:
        """Claim the sole incomplete replay or allocate its next sequence."""

        if not isinstance(owner_token, str) or not owner_token.strip():
            raise ValueError("owner_token is required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        claimed_at = time.time() if now is None else float(now)
        lease_expires_at = claimed_at + lease_seconds
        with self._connect(immediate=True) as conn:
            claimed_existing = False
            while True:
                row = conn.execute(
                    "SELECT * FROM classroom_replays "
                    "WHERE status='INCOMPLETE' ORDER BY sequence LIMIT 1"
                ).fetchone()
                if row is None:
                    break

                active_owner = row["owner_token"]
                active_until = row["lease_expires_at"]
                if (
                    active_owner is not None
                    and active_until is not None
                    and float(active_until) > claimed_at
                ):
                    return None

                actual_trades = self._classroom_trade_contract(
                    conn, row["strategy_id"]
                )
                if expected_trades and self._has_noncanonical_trade(
                    actual_trades, expected_trades
                ):
                    self._abort_classroom_replay(
                        conn,
                        row["sequence"],
                        "noncanonical_realized_trade",
                        len(actual_trades),
                    )
                    continue

                phase = int(row["phase"])
                if (
                    expected_trades
                    and phase == 4
                    and Counter(actual_trades) != Counter(
                        self._normalize_expected_trades(expected_trades)
                    )
                ):
                    phase = self._rederive_classroom_phase(
                        conn, row["strategy_id"]
                    )
                cleanup_strategies = self._aborted_position_strategies(
                    conn, targets
                )
                order_history_reason = self._assert_replay_order_contract(
                    conn,
                    targets,
                    session_id=row["session_id"],
                    strategy_id=row["strategy_id"],
                    phase=phase,
                    cleanup_strategies=cleanup_strategies,
                )
                if order_history_reason is not None:
                    self._abort_classroom_replay(
                        conn,
                        row["sequence"],
                        order_history_reason,
                        len(actual_trades),
                    )
                    continue

                cursor = conn.execute(
                    "UPDATE classroom_replays "
                    "SET owner_token=?,lease_expires_at=?,phase=?,updated_at=? "
                    "WHERE sequence=? AND status='INCOMPLETE' "
                    "AND (owner_token IS NULL OR lease_expires_at IS NULL "
                    "OR lease_expires_at<=?)",
                    (
                        owner_token,
                        lease_expires_at,
                        phase,
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
                claimed_existing = True
                break

            if not claimed_existing:
                cleanup_strategies = self._aborted_position_strategies(
                    conn, targets
                )
                self._assert_replay_order_contract(
                    conn,
                    targets,
                    cleanup_strategies=cleanup_strategies,
                )
                while True:
                    sequence = int(
                        conn.execute(
                            "SELECT COALESCE(MAX(sequence),0)+1 "
                            "FROM classroom_replays"
                        ).fetchone()[0]
                    )
                    session_id = f"classroom-{sequence:06d}"
                    strategy_id = f"classroom-replay:{session_id}"
                    occupied, namespace_trades = self._namespace_occupied(
                        conn, session_id, strategy_id
                    )
                    if not occupied:
                        break
                    timestamp = _now()
                    conn.execute(
                        "INSERT INTO classroom_replays "
                        "(sequence,session_id,strategy_id,status,phase,"
                        "realized_trades,created_at,updated_at,abort_reason,"
                        "aborted_at) VALUES (?,?,?,'ABORTED',1,?,?,?,?,?)",
                        (
                            sequence,
                            session_id,
                            strategy_id,
                            namespace_trades,
                            timestamp,
                            timestamp,
                            "namespace_collision",
                            timestamp,
                        ),
                    )
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
            sequence,
            session_id,
            strategy_id,
            owner_token,
            phase,
            targets,
            cleanup_strategies,
        )

    @staticmethod
    def _abort_classroom_replay(
        conn: sqlite3.Connection,
        sequence: int,
        reason: str,
        realized_trades: int,
    ) -> None:
        aborted_at = _now()
        conn.execute(
            "UPDATE classroom_replays SET status='ABORTED',"
            "owner_token=NULL,lease_expires_at=NULL,realized_trades=?,"
            "abort_reason=?,aborted_at=?,updated_at=? WHERE sequence=? "
            "AND status='INCOMPLETE'",
            (
                realized_trades,
                reason,
                aborted_at,
                aborted_at,
                sequence,
            ),
        )

    @staticmethod
    def _namespace_occupied(
        conn: sqlite3.Connection, session_id: str, strategy_id: str
    ) -> tuple[bool, int]:
        order = conn.execute(
            "SELECT 1 FROM broker_orders WHERE strategy_id=? "
            "OR client_order_id LIKE ? LIMIT 1",
            (strategy_id, f"{session_id}-%"),
        ).fetchone()
        fill = conn.execute(
            "SELECT 1 FROM fills JOIN broker_orders USING(client_order_id) "
            "WHERE broker_orders.strategy_id=? "
            "OR broker_orders.client_order_id LIKE ? LIMIT 1",
            (strategy_id, f"{session_id}-%"),
        ).fetchone()
        position = conn.execute(
            "SELECT 1 FROM positions WHERE strategy_id=? LIMIT 1",
            (strategy_id,),
        ).fetchone()
        realized = int(
            conn.execute(
                "SELECT COUNT(*) FROM realized_trades WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()[0]
        )
        return any(item is not None for item in (order, fill, position)) or bool(
            realized
        ), realized

    @staticmethod
    def _normalize_expected_trades(
        expected_trades: tuple[
            tuple[Market, str, Decimal, Decimal, str], ...
        ],
    ) -> list[tuple[str, str, Decimal, Decimal, str]]:
        return [
            (market.value, symbol, quantity, exit_price, currency)
            for market, symbol, quantity, exit_price, currency in expected_trades
        ]

    @staticmethod
    def _classroom_trade_contract(
        conn: sqlite3.Connection, strategy_id: str
    ) -> list[tuple[str, str, Decimal, Decimal, str]]:
        rows = conn.execute(
            "SELECT market,symbol,quantity,exit_price,currency "
            "FROM realized_trades WHERE strategy_id=?",
            (strategy_id,),
        ).fetchall()
        return [
            (
                row["market"],
                row["symbol"],
                Decimal(row["quantity"]),
                Decimal(row["exit_price"]),
                row["currency"],
            )
            for row in rows
        ]

    @classmethod
    def _has_noncanonical_trade(
        cls,
        actual_trades: list[tuple[str, str, Decimal, Decimal, str]],
        expected_trades: tuple[
            tuple[Market, str, Decimal, Decimal, str], ...
        ],
    ) -> bool:
        actual = Counter(actual_trades)
        expected = Counter(cls._normalize_expected_trades(expected_trades))
        return any(count > expected[trade] for trade, count in actual.items())

    @staticmethod
    def _assert_replay_order_contract(
        conn: sqlite3.Connection,
        targets: frozenset[tuple[Market, str]],
        *,
        session_id: str | None = None,
        strategy_id: str | None = None,
        phase: int | None = None,
        cleanup_strategies: frozenset[str] = frozenset(),
    ) -> str | None:
        placeholders = ",".join("?" for _ in _UNRESOLVED_ORDER_STATUSES)
        for market, symbol in targets:
            params = (
                market.value,
                symbol,
                *(status.value for status in _UNRESOLVED_ORDER_STATUSES),
            )
            rows = conn.execute(
                "SELECT client_order_id,market,symbol,side,status,strategy_id "
                "FROM broker_orders "
                f"WHERE market=? AND symbol=? AND status IN ({placeholders})",
                params,
            ).fetchall()
            for order in rows:
                if OrderStatus(order["status"]) is OrderStatus.UNKNOWN:
                    raise RuntimeError(
                        "classroom replay blocked by UNKNOWN target order"
                    )
                if (
                    strategy_id is not None
                    and order["strategy_id"] == strategy_id
                ):
                    continue
                if order["strategy_id"] in cleanup_strategies:
                    cleanup = conn.execute(
                        "SELECT session_id FROM classroom_replays "
                        "WHERE strategy_id=? AND status='ABORTED'",
                        (order["strategy_id"],),
                    ).fetchone()
                    if (
                        cleanup is not None
                        and Ledger._is_canonical_replay_order(
                            order, cleanup["session_id"], 3
                        )
                    ):
                        continue
                raise RuntimeError(
                    "classroom replay blocked by unrelated unresolved "
                    "target order"
                )
        if strategy_id is None:
            return None
        history_reason = Ledger._replay_order_history_reason(
            conn, targets, session_id, strategy_id, phase
        )
        if history_reason is not None:
            return history_reason
        return Ledger._replay_trade_provenance_reason(
            conn, targets, session_id, strategy_id
        )

    @staticmethod
    def _replay_order_history_reason(
        conn: sqlite3.Connection,
        targets: frozenset[tuple[Market, str]],
        session_id: str | None,
        strategy_id: str,
        active_phase: int | None,
    ) -> str | None:
        namespace_pattern = f"{session_id}-%"
        rows = conn.execute(
            "SELECT client_order_id,market,symbol,side,status,strategy_id,"
            "quantity,filled_quantity,currency "
            "FROM broker_orders WHERE strategy_id=? "
            "OR client_order_id LIKE ? "
            "ORDER BY client_order_id",
            (strategy_id, namespace_pattern),
        ).fetchall()
        chains: dict[
            tuple[int, Market, str, OrderSide], list[tuple[int, sqlite3.Row]]
        ] = {}
        for order in rows:
            status = OrderStatus(order["status"])
            if status is OrderStatus.UNKNOWN:
                raise RuntimeError(
                    "classroom replay blocked by UNKNOWN target order"
                )
            identity = Ledger._replay_order_identity(
                order, targets, session_id
            )
            if identity is None:
                if status in _TERMINAL_ORDER_STATUSES:
                    return "noncanonical_order_history"
                raise RuntimeError(
                    "classroom replay blocked by noncanonical replay order"
                )
            fills = conn.execute(
                "SELECT fill_id,client_order_id,market,symbol,side,quantity,"
                "price,currency FROM fills WHERE client_order_id=? "
                "ORDER BY fill_id",
                (order["client_order_id"],),
            ).fetchall()
            if Ledger._order_fill_history_mismatch(order, fills):
                return "noncanonical_order_history"
            if order["strategy_id"] != strategy_id:
                if fills or status not in {
                    OrderStatus.CANCELED,
                    OrderStatus.REJECTED,
                }:
                    return "noncanonical_order_history"
            chain_key, retry_index = identity
            chains.setdefault(chain_key, []).append((retry_index, order))

        orphan = conn.execute(
            "SELECT 1 FROM fills "
            "LEFT JOIN broker_orders USING(client_order_id) "
            "WHERE fills.client_order_id LIKE ? "
            "AND broker_orders.client_order_id IS NULL LIMIT 1",
            (namespace_pattern,),
        ).fetchone()
        if orphan is not None:
            return "noncanonical_order_history"

        predecessor_statuses = {
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
        }
        for (order_phase, _, _, _), members in chains.items():
            members.sort(key=lambda item: item[0])
            indices = [retry_index for retry_index, _ in members]
            if indices != list(range(len(indices))):
                if any(
                    OrderStatus(order["status"])
                    not in _TERMINAL_ORDER_STATUSES
                    for _, order in members
                ):
                    raise RuntimeError(
                        "classroom replay blocked by invalid successor lineage"
                    )
                return "noncanonical_order_history"
            for _, predecessor in members[:-1]:
                predecessor_status = OrderStatus(predecessor["status"])
                if predecessor_status in predecessor_statuses:
                    continue
                if predecessor_status in _TERMINAL_ORDER_STATUSES:
                    return "noncanonical_order_history"
                raise RuntimeError(
                    "classroom replay blocked by invalid successor lineage"
                )
            highest_status = OrderStatus(members[-1][1]["status"])
            if (
                highest_status not in _TERMINAL_ORDER_STATUSES
                and order_phase != active_phase
            ):
                raise RuntimeError(
                    "classroom replay blocked by noncanonical replay order"
                )
        return None

    @staticmethod
    def _order_fill_history_mismatch(
        order: sqlite3.Row, fills: list[sqlite3.Row]
    ) -> bool:
        try:
            order_quantity = Decimal(order["quantity"])
            filled_quantity = Decimal(order["filled_quantity"])
            fill_quantities = [Decimal(fill["quantity"]) for fill in fills]
        except Exception:
            return True
        if any(quantity <= 0 for quantity in fill_quantities):
            return True
        if sum(fill_quantities, Decimal("0")) != filled_quantity:
            return True
        status = OrderStatus(order["status"])
        if status is OrderStatus.FILLED and filled_quantity != order_quantity:
            return True
        if status is OrderStatus.REJECTED and filled_quantity != 0:
            return True
        return any(
            (
                fill["client_order_id"],
                fill["market"],
                fill["symbol"],
                fill["side"],
                fill["currency"],
            )
            != (
                order["client_order_id"],
                order["market"],
                order["symbol"],
                order["side"],
                order["currency"],
            )
            for fill in fills
        )

    @staticmethod
    def _replay_trade_provenance_reason(
        conn: sqlite3.Connection,
        targets: frozenset[tuple[Market, str]],
        session_id: str | None,
        strategy_id: str,
    ) -> str | None:
        trades = conn.execute(
            "SELECT id,market,symbol,quantity,exit_price,currency,"
            "exit_client_order_id,exit_fill_id FROM realized_trades "
            "WHERE strategy_id=? ORDER BY id",
            (strategy_id,),
        ).fetchall()
        linked_fill_ids: set[str] = set()
        for trade in trades:
            order_id = trade["exit_client_order_id"]
            fill_id = trade["exit_fill_id"]
            if not order_id or not fill_id or fill_id in linked_fill_ids:
                return "noncanonical_trade_provenance"
            linked = conn.execute(
                "SELECT broker_orders.client_order_id,"
                "broker_orders.market,broker_orders.symbol,"
                "broker_orders.side,broker_orders.status,"
                "broker_orders.strategy_id,fills.fill_id,"
                "fills.quantity AS fill_quantity,"
                "fills.price AS fill_price,fills.currency AS fill_currency "
                "FROM broker_orders JOIN fills "
                "ON fills.client_order_id=broker_orders.client_order_id "
                "WHERE broker_orders.client_order_id=? AND fills.fill_id=?",
                (order_id, fill_id),
            ).fetchone()
            if linked is None:
                return "noncanonical_trade_provenance"
            identity = Ledger._replay_order_identity(
                linked, targets, session_id
            )
            if (
                linked["strategy_id"] != strategy_id
                or OrderStatus(linked["status"]) is not OrderStatus.FILLED
                or identity is None
                or identity[0][0] != 3
                or (
                    trade["market"],
                    trade["symbol"],
                    Decimal(trade["quantity"]),
                    Decimal(trade["exit_price"]),
                    trade["currency"],
                )
                != (
                    linked["market"],
                    linked["symbol"],
                    Decimal(linked["fill_quantity"]),
                    Decimal(linked["fill_price"]),
                    linked["fill_currency"],
                )
            ):
                return "noncanonical_trade_provenance"
            linked_fill_ids.add(fill_id)

        sell_fill_ids = {
            row["fill_id"]
            for row in conn.execute(
                "SELECT fills.fill_id FROM fills JOIN broker_orders "
                "USING(client_order_id) WHERE broker_orders.strategy_id=? "
                "AND broker_orders.side='SELL'",
                (strategy_id,),
            ).fetchall()
        }
        if linked_fill_ids != sell_fill_ids:
            return "noncanonical_trade_provenance"
        return None

    @staticmethod
    def _replay_order_identity(
        order: sqlite3.Row,
        targets: frozenset[tuple[Market, str]],
        session_id: str | None,
    ) -> tuple[tuple[int, Market, str, OrderSide], int] | None:
        if session_id is None:
            return None
        try:
            market = Market(order["market"])
            side = OrderSide(order["side"])
        except ValueError:
            return None
        symbol = order["symbol"]
        if (market, symbol) not in targets:
            return None
        phase = 1 if side is OrderSide.BUY else 3
        base_id = (
            f"{session_id}-{phase}:{market.value}:{symbol}:{side.value}"
        )
        client_order_id = order["client_order_id"]
        if client_order_id == base_id:
            return (phase, market, symbol, side), 0
        prefix = f"{base_id}:retry-"
        if not client_order_id.startswith(prefix):
            return None
        suffix = client_order_id[len(prefix) :]
        if not (
            suffix.isdigit()
            and suffix == str(int(suffix))
            and int(suffix) >= 1
        ):
            return None
        return (phase, market, symbol, side), int(suffix)

    @staticmethod
    def _is_canonical_replay_order(
        order: sqlite3.Row,
        session_id: str | None,
        phase: int | None,
    ) -> bool:
        if phase not in {1, 3}:
            return False
        targets = frozenset(
            {(Market(order["market"]), order["symbol"])}
        )
        identity = Ledger._replay_order_identity(order, targets, session_id)
        return identity is not None and identity[0][0] == phase

    @staticmethod
    def _select_replay_order_id(
        conn: sqlite3.Connection,
        base_id: str,
        *,
        retry_filled: bool = False,
    ) -> str:
        rows = conn.execute(
            "SELECT client_order_id,status FROM broker_orders "
            "WHERE client_order_id=? OR client_order_id LIKE ?",
            (base_id, f"{base_id}:retry-%"),
        ).fetchall()
        canonical: list[tuple[int, sqlite3.Row]] = []
        for row in rows:
            client_order_id = row["client_order_id"]
            if client_order_id == base_id:
                canonical.append((0, row))
                continue
            suffix = client_order_id.removeprefix(f"{base_id}:retry-")
            if (
                suffix.isdigit()
                and suffix == str(int(suffix))
                and int(suffix) >= 1
            ):
                canonical.append((int(suffix), row))
        if not canonical:
            return base_id
        retry_index, latest = max(canonical, key=lambda item: item[0])
        latest_status = OrderStatus(latest["status"])
        if latest_status in {
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
        } or (retry_filled and latest_status is OrderStatus.FILLED):
            return f"{base_id}:retry-{retry_index + 1}"
        return latest["client_order_id"]

    def select_replay_order_id(self, base_id: str) -> str:
        """Return the persisted base or deterministic ``:retry-N`` successor."""

        with self._connect() as conn:
            return self._select_replay_order_id(conn, base_id)

    @staticmethod
    def _aborted_position_strategies(
        conn: sqlite3.Connection,
        targets: frozenset[tuple[Market, str]],
    ) -> frozenset[str]:
        strategies: set[str] = set()
        reason_placeholders = ",".join(
            "?" for _ in _CLEANUP_ELIGIBLE_ABORT_REASONS
        )
        for market, symbol in targets:
            rows = conn.execute(
                "SELECT positions.strategy_id FROM positions "
                "JOIN classroom_replays ON "
                "classroom_replays.strategy_id=positions.strategy_id "
                "WHERE positions.market=? AND positions.symbol=? "
                "AND classroom_replays.status='ABORTED' "
                "AND classroom_replays.abort_reason "
                f"IN ({reason_placeholders})",
                (
                    market.value,
                    symbol,
                    *_CLEANUP_ELIGIBLE_ABORT_REASONS,
                ),
            ).fetchall()
            strategies.update(row["strategy_id"] for row in rows)
        return frozenset(strategies)

    @staticmethod
    def _rederive_classroom_phase(
        conn: sqlite3.Connection, strategy_id: str
    ) -> int:
        position = conn.execute(
            "SELECT 1 FROM positions WHERE strategy_id=? LIMIT 1",
            (strategy_id,),
        ).fetchone()
        placeholders = ",".join("?" for _ in _UNRESOLVED_ORDER_STATUSES)
        pending_sell = conn.execute(
            "SELECT 1 FROM broker_orders WHERE strategy_id=? AND side='SELL' "
            f"AND status IN ({placeholders}) LIMIT 1",
            (
                strategy_id,
                *(status.value for status in _UNRESOLVED_ORDER_STATUSES),
            ),
        ).fetchone()
        return 3 if position is not None or pending_sell is not None else 1

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
            history_reason = self._assert_replay_order_contract(
                conn,
                claim.targets,
                session_id=claim.session_id,
                strategy_id=claim.strategy_id,
                phase=expected_phase,
            )
            if history_reason is not None:
                mismatch = (
                    "trade provenance"
                    if history_reason == "noncanonical_trade_provenance"
                    else "order history"
                )
                raise RuntimeError(f"classroom replay {mismatch} mismatch")
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
            history_reason = self._assert_replay_order_contract(
                conn,
                claim.targets,
                session_id=claim.session_id,
                strategy_id=claim.strategy_id,
                phase=4,
            )
            if history_reason is not None:
                mismatch = (
                    "trade provenance"
                    if history_reason == "noncanonical_trade_provenance"
                    else "order history"
                )
                raise RuntimeError(f"classroom replay {mismatch} mismatch")
            actual_trades = sorted(
                self._classroom_trade_contract(conn, claim.strategy_id)
            )
            prescribed_trades = sorted(
                self._normalize_expected_trades(expected_trades)
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
            client_order_id = self._select_replay_order_id(
                conn, base_id, retry_filled=True
            )

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

            position_row = conn.execute(
                "SELECT * FROM positions WHERE market=? AND symbol=?",
                (fill.market.value, fill.symbol),
            ).fetchone()
            if fill.side is OrderSide.SELL:
                if position_row is None:
                    raise PositionFillConflict(
                        fill.market, fill.symbol, "missing"
                    )
                if order.intent.strategy_id != position_row["strategy_id"]:
                    raise PositionFillConflict(
                        fill.market, fill.symbol, "strategy_changed"
                    )
                if fill.quantity > Decimal(position_row["quantity"]):
                    raise PositionFillConflict(
                        fill.market, fill.symbol, "quantity_changed"
                    )

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
                old_qty = Decimal(position_row["quantity"])
                old_avg = Decimal(position_row["average_price"])
                remaining = old_qty - fill.quantity
                conn.execute(
                    "INSERT INTO realized_trades "
                    "(market,symbol,quantity,entry_price,exit_price,"
                    "pnl_amount,currency,strategy_id,closed_at,"
                    "exit_client_order_id,exit_fill_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
                        fill.client_order_id,
                        fill.fill_id,
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
