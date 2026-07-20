from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .domain import (
    Candidate,
    EntryContext,
    Fill,
    Instrument,
    Market,
    OrderIntent,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionEntryConflict,
    PositionFillConflict,
    Regime,
    TriggerType,
    validate_market_contract,
    validate_transition,
)
from .regime import PulseState, RegimeResult
from .policy import policy_for

CURRENT_SCHEMA_VERSION = 6


class IncompatibleLedgerSchema(RuntimeError):
    """The database cannot safely satisfy the owned ledger contract."""


_VERSION_ONE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS prism_core_meta "
    "(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS broker_orders (
    client_order_id TEXT PRIMARY KEY, market TEXT NOT NULL, symbol TEXT NOT NULL,
    side TEXT NOT NULL, order_type TEXT NOT NULL, quantity TEXT NOT NULL,
    limit_price TEXT, currency TEXT NOT NULL, strategy_id TEXT NOT NULL,
    reason TEXT NOT NULL, status TEXT NOT NULL,
    filled_quantity TEXT NOT NULL DEFAULT '0', average_fill_price TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
)
""",
    """CREATE TABLE IF NOT EXISTS order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, client_order_id TEXT NOT NULL,
    status TEXT NOT NULL, occurred_at TEXT NOT NULL,
    UNIQUE(client_order_id, status)
)""",
    """CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY, client_order_id TEXT NOT NULL, market TEXT NOT NULL,
    symbol TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL,
    price TEXT NOT NULL, currency TEXT NOT NULL, occurred_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS positions (
    market TEXT NOT NULL, symbol TEXT NOT NULL, quantity TEXT NOT NULL,
    average_price TEXT NOT NULL, currency TEXT NOT NULL,
    high_since_entry TEXT NOT NULL, strategy_id TEXT NOT NULL,
    updated_at TEXT NOT NULL, PRIMARY KEY(market, symbol)
)""",
    """CREATE TABLE IF NOT EXISTS realized_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, market TEXT NOT NULL,
    symbol TEXT NOT NULL, quantity TEXT NOT NULL, entry_price TEXT NOT NULL,
    exit_price TEXT NOT NULL, pnl_amount TEXT NOT NULL, currency TEXT NOT NULL,
    strategy_id TEXT NOT NULL, closed_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS classroom_replays (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE, strategy_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL, owner_token TEXT, lease_expires_at REAL,
    realized_trades INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT
)""",
)

_VERSION_FIVE_SCHEMA = (
    """CREATE TABLE market_regimes (
    run_id TEXT NOT NULL, market TEXT NOT NULL, as_of TEXT NOT NULL,
    regime TEXT NOT NULL, confidence TEXT NOT NULL, pulse TEXT NOT NULL,
    metrics_json TEXT NOT NULL, reasons_json TEXT NOT NULL, source TEXT NOT NULL,
    PRIMARY KEY(run_id, market)
)""",
    """CREATE TABLE candidates (
    run_id TEXT NOT NULL, rank INTEGER NOT NULL, market TEXT NOT NULL,
    symbol TEXT NOT NULL, exchange TEXT NOT NULL, currency TEXT NOT NULL,
    name TEXT NOT NULL, sector TEXT NOT NULL, lot_size TEXT NOT NULL,
    price_precision INTEGER NOT NULL,
    as_of TEXT NOT NULL, trigger_type TEXT NOT NULL,
    regime TEXT NOT NULL, feature_values_json TEXT NOT NULL,
    component_scores_json TEXT NOT NULL, final_score TEXT NOT NULL,
    reference_price TEXT NOT NULL, stop_price TEXT NOT NULL,
    target_price TEXT NOT NULL, risk_reward_ratio TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY(run_id, market, symbol, trigger_type),
    UNIQUE(run_id, market, rank)
)""",
    """CREATE TABLE entry_contexts (
    client_order_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
    market TEXT NOT NULL, symbol TEXT NOT NULL, strategy_id TEXT NOT NULL,
    regime TEXT NOT NULL, trigger_type TEXT NOT NULL,
    stop_price TEXT NOT NULL, target_price TEXT NOT NULL,
    risk_reward_ratio TEXT NOT NULL, trailing_pct TEXT NOT NULL,
    source TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(run_id, market, symbol, trigger_type)
)""",
)

_VERSION_SIX_SCHEMA = (
    """CREATE TABLE market_calendar_cache (
    market TEXT NOT NULL, broker_mode TEXT NOT NULL,
    trade_date TEXT NOT NULL, is_open INTEGER NOT NULL,
    source TEXT NOT NULL, checked_at TEXT NOT NULL,
    PRIMARY KEY(market, broker_mode, trade_date)
)""",
    """CREATE UNIQUE INDEX uq_broker_orders_broker_identity
    ON broker_orders(
        broker, broker_mode, broker_order_date, broker_org_no, broker_order_no
    )""",
    """CREATE INDEX ix_broker_orders_pending_recovery
    ON broker_orders(
        broker, broker_mode, status, updated_at, client_order_id
    )""",
)

_VERSION_ONE_COLUMNS = {
    "prism_core_meta": {"key", "value"},
    "broker_orders": {
        "client_order_id", "market", "symbol", "side", "order_type",
        "quantity", "limit_price", "currency", "strategy_id", "reason",
        "status", "filled_quantity", "average_fill_price", "created_at",
        "updated_at",
    },
    "order_events": {"id", "client_order_id", "status", "occurred_at"},
    "fills": {
        "fill_id", "client_order_id", "market", "symbol", "side",
        "quantity", "price", "currency", "occurred_at",
    },
    "positions": {
        "market", "symbol", "quantity", "average_price", "currency",
        "high_since_entry", "strategy_id", "updated_at",
    },
    "realized_trades": {
        "id", "market", "symbol", "quantity", "entry_price", "exit_price",
        "pnl_amount", "currency", "strategy_id", "closed_at",
    },
    "classroom_replays": {
        "sequence", "session_id", "strategy_id", "status", "owner_token",
        "lease_expires_at", "realized_trades", "created_at", "updated_at",
        "completed_at",
    },
}
_VERSION_TWO_COLUMNS = {
    **_VERSION_ONE_COLUMNS,
    "classroom_replays": _VERSION_ONE_COLUMNS["classroom_replays"]
    | {"phase"},
}
_VERSION_THREE_COLUMNS = {
    **_VERSION_TWO_COLUMNS,
    "realized_trades": _VERSION_ONE_COLUMNS["realized_trades"]
    | {"exit_client_order_id", "exit_fill_id"},
    "classroom_replays": _VERSION_TWO_COLUMNS["classroom_replays"]
    | {"phase", "abort_reason", "aborted_at"},
}
_VERSION_FOUR_COLUMNS = {
    **_VERSION_THREE_COLUMNS,
    "positions": _VERSION_ONE_COLUMNS["positions"] | {"entry_client_order_id"},
}
_VERSION_FIVE_COLUMNS = {
    **_VERSION_FOUR_COLUMNS,
    "market_regimes": {
        "run_id", "market", "as_of", "regime", "confidence", "pulse",
        "metrics_json", "reasons_json", "source",
    },
    "candidates": {
        "run_id", "rank", "market", "symbol", "exchange", "currency",
        "name", "sector", "lot_size", "price_precision", "as_of", "trigger_type",
        "regime", "feature_values_json", "component_scores_json",
        "final_score", "reference_price", "stop_price", "target_price",
        "risk_reward_ratio", "source",
    },
    "entry_contexts": {
        "client_order_id", "run_id", "market", "symbol", "strategy_id",
        "regime", "trigger_type", "stop_price", "target_price",
        "risk_reward_ratio", "trailing_pct", "source", "created_at",
    },
}
_CURRENT_COLUMNS = {
    **_VERSION_FIVE_COLUMNS,
    "broker_orders": _VERSION_FIVE_COLUMNS["broker_orders"]
    | {
        "broker",
        "broker_mode",
        "broker_order_date",
        "broker_org_no",
        "broker_order_no",
        "remaining_quantity",
    },
    "market_calendar_cache": {
        "market",
        "broker_mode",
        "trade_date",
        "is_open",
        "source",
        "checked_at",
    },
}
_SCHEMA_COLUMNS_BY_VERSION = {
    1: _VERSION_ONE_COLUMNS,
    2: _VERSION_TWO_COLUMNS,
    3: _VERSION_THREE_COLUMNS,
    4: _VERSION_FOUR_COLUMNS,
    5: _VERSION_FIVE_COLUMNS,
    6: _CURRENT_COLUMNS,
}
_PRIMARY_KEYS = {
    "prism_core_meta": ("key",),
    "broker_orders": ("client_order_id",),
    "order_events": ("id",),
    "fills": ("fill_id",),
    "positions": ("market", "symbol"),
    "realized_trades": ("id",),
    "classroom_replays": ("sequence",),
    "market_regimes": ("run_id", "market"),
    "candidates": ("run_id", "market", "symbol", "trigger_type"),
    "entry_contexts": ("client_order_id",),
    "market_calendar_cache": ("market", "broker_mode", "trade_date"),
}
_REQUIRED_UNIQUE_KEYS = {
    "broker_orders": {
        (
            "broker",
            "broker_mode",
            "broker_order_date",
            "broker_org_no",
            "broker_order_no",
        )
    },
    "order_events": {("client_order_id", "status")},
    "classroom_replays": {("session_id",), ("strategy_id",)},
    "candidates": {("run_id", "market", "rank")},
    "entry_contexts": {("run_id", "market", "symbol", "trigger_type")},
}
_REQUIRED_INDEX_KEYS = {
    "broker_orders": {
        (
            "broker",
            "broker_mode",
            "status",
            "updated_at",
            "client_order_id",
        )
    }
}


def _text_contract(
    columns: set[str],
    *,
    nullable: set[str] = frozenset(),
    types: dict[str, str] | None = None,
    defaults: dict[str, str] | None = None,
) -> dict[str, tuple[str, bool, str | None]]:
    types = types or {}
    defaults = defaults or {}
    return {
        name: (
            types.get(name, "TEXT"),
            name not in nullable,
            defaults.get(name),
        )
        for name in columns
    }


_COLUMN_CONTRACTS = {
    "prism_core_meta": _text_contract(
        _CURRENT_COLUMNS["prism_core_meta"], nullable={"key"}
    ),
    "broker_orders": _text_contract(
        _CURRENT_COLUMNS["broker_orders"],
        nullable={
            "client_order_id",
            "limit_price",
            "average_fill_price",
            "broker_order_date",
            "broker_org_no",
            "broker_order_no",
        },
        defaults={
            "filled_quantity": "'0'",
            "broker": "'paper'",
            "broker_mode": "'simulation'",
            "remaining_quantity": "'0'",
        },
    ),
    "order_events": _text_contract(
        _CURRENT_COLUMNS["order_events"],
        nullable={"id"},
        types={"id": "INTEGER"},
    ),
    "fills": _text_contract(
        _CURRENT_COLUMNS["fills"], nullable={"fill_id"}
    ),
    "positions": _text_contract(
        _CURRENT_COLUMNS["positions"],
        nullable={"entry_client_order_id"},
    ),
    "realized_trades": _text_contract(
        _CURRENT_COLUMNS["realized_trades"],
        nullable={"id", "exit_client_order_id", "exit_fill_id"},
        types={"id": "INTEGER"},
    ),
    "classroom_replays": _text_contract(
        _CURRENT_COLUMNS["classroom_replays"],
        nullable={
            "sequence",
            "owner_token",
            "lease_expires_at",
            "completed_at",
            "abort_reason",
            "aborted_at",
        },
        types={
            "sequence": "INTEGER",
            "lease_expires_at": "REAL",
            "phase": "INTEGER",
            "realized_trades": "INTEGER",
        },
        defaults={"phase": "1", "realized_trades": "0"},
    ),
    "market_regimes": _text_contract(_CURRENT_COLUMNS["market_regimes"]),
    "candidates": _text_contract(
        _CURRENT_COLUMNS["candidates"],
        types={"rank": "INTEGER", "price_precision": "INTEGER"},
    ),
    "entry_contexts": _text_contract(
        _CURRENT_COLUMNS["entry_contexts"], nullable={"client_order_id"}
    ),
    "market_calendar_cache": _text_contract(
        _CURRENT_COLUMNS["market_calendar_cache"],
        types={"is_open": "INTEGER"},
    ),
}

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


def _validated_trade_date(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("trade_date must be YYYYMMDD")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("trade_date must be a valid YYYYMMDD date") from exc
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError("trade_date must be a valid YYYYMMDD date")
    return value


def _validated_checked_at(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("checked_at must be an aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("checked_at must be an aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("checked_at must be an aware ISO timestamp")
    return parsed.astimezone(timezone.utc).isoformat()


_DECIMAL_JSON_TAG = "__prism_decimal__"


def _encode_typed_json(values) -> str:
    encoded = {
        key: {_DECIMAL_JSON_TAG: str(value)}
        if isinstance(value, Decimal)
        else value
        for key, value in dict(values).items()
    }
    return json.dumps(encoded, sort_keys=True, separators=(",", ":"))


def _decode_typed_json(payload: str) -> dict:
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("typed JSON must contain an object")
    values = {}
    for key, value in decoded.items():
        if isinstance(value, dict):
            if set(value) != {_DECIMAL_JSON_TAG} or not isinstance(
                value[_DECIMAL_JSON_TAG], str
            ):
                raise ValueError("malformed or unknown typed JSON tag")
            decimal_value = Decimal(value[_DECIMAL_JSON_TAG])
            if not decimal_value.is_finite():
                raise ValueError("tagged Decimal must be finite")
            value = decimal_value
        elif isinstance(value, list):
            raise ValueError("malformed or unknown typed JSON value")
        values[key] = value
    return values


def _sql_has_unquoted_keyword(sql: str, keyword: str) -> bool:
    """Find a DDL keyword while ignoring SQLite quotes and comments."""

    target = keyword.upper()
    index = 0
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""
        if char == "-" and next_char == "-":
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline < 0 else newline + 1
            continue
        if char == "/" and next_char == "*":
            closing = sql.find("*/", index + 2)
            index = len(sql) if closing < 0 else closing + 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            while index < len(sql):
                if sql[index] != quote:
                    index += 1
                    continue
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                index += 1
                break
            continue
        if char == "[":
            closing = sql.find("]", index + 1)
            index = len(sql) if closing < 0 else closing + 1
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < len(sql) and (
                sql[end].isalnum() or sql[end] in {"_", "$"}
            ):
                end += 1
            if sql[index:end].upper() == target:
                return True
            index = end
            continue
        index += 1
    return False


@dataclass(frozen=True)
class ClassroomReplayClaim:
    sequence: int
    session_id: str
    strategy_id: str
    owner_token: str
    phase: int
    targets: frozenset[tuple[Market, str]] = frozenset()
    cleanup_strategies: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BrokerOrderState:
    order: OrderRecord
    broker: str
    broker_mode: str
    broker_order_date: str | None
    broker_org_no: str | None
    broker_order_no: str | None
    remaining_quantity: Decimal

    @property
    def status(self) -> OrderStatus:
        return self.order.status

    @property
    def filled_quantity(self) -> Decimal:
        return self.order.filled_quantity

    @property
    def average_fill_price(self) -> Decimal | None:
        return self.order.average_fill_price


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {
            row[1]
            for row in conn.execute(
                f'PRAGMA table_xinfo("{table}")'
            ).fetchall()
        }

    @staticmethod
    def _primary_key(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return tuple(
            row[1]
            for row in sorted(rows, key=lambda item: item[5])
            if row[5]
        )

    @staticmethod
    def _validate_unique_keys(
        conn: sqlite3.Connection,
        table: str,
        required: set[tuple[str, ...]],
    ) -> None:
        valid = set()
        for row in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
            name = row[1]
            is_unique = bool(row[2])
            origin = row[3]
            is_partial = bool(row[4])
            if not is_unique or origin == "pk":
                continue
            key_rows = [
                item
                for item in conn.execute(
                    "SELECT * FROM pragma_index_xinfo(?)",
                    (name,),
                ).fetchall()
                if item[5]
            ]
            has_expression = any(
                item[1] < 0 or item[2] is None for item in key_rows
            )
            columns = tuple(item[2] for item in key_rows)
            if is_partial:
                raise IncompatibleLedgerSchema(
                    f"{table} has partial UNIQUE index {name}: {columns!r}"
                )
            if has_expression:
                raise IncompatibleLedgerSchema(
                    f"{table} has expression UNIQUE index {name}"
                )
            if any(str(item[4]).upper() != "BINARY" for item in key_rows):
                raise IncompatibleLedgerSchema(
                    f"{table} has non-BINARY collation in UNIQUE index "
                    f"{name}"
                )
            if columns not in required:
                raise IncompatibleLedgerSchema(
                    f"{table} has unexpected UNIQUE key: {columns!r}"
                )
            valid.add(columns)
        missing = required - valid
        if missing:
            raise IncompatibleLedgerSchema(
                f"{table} missing required full UNIQUE keys: "
                f"{sorted(missing)!r}"
            )

    @staticmethod
    def _validate_required_indexes(
        conn: sqlite3.Connection,
        table: str,
        required: set[tuple[str, ...]],
    ) -> None:
        if not required:
            return
        valid: set[tuple[str, ...]] = set()
        for row in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
            name = row[1]
            if bool(row[2]) or bool(row[4]):
                continue
            key_rows = [
                item
                for item in conn.execute(
                    "SELECT * FROM pragma_index_xinfo(?)", (name,)
                ).fetchall()
                if item[5]
            ]
            if any(item[1] < 0 or item[2] is None for item in key_rows):
                continue
            if any(str(item[4]).upper() != "BINARY" for item in key_rows):
                continue
            valid.add(tuple(item[2] for item in key_rows))
        missing = required - valid
        if missing:
            raise IncompatibleLedgerSchema(
                f"{table} missing required index keys: {sorted(missing)!r}"
            )

    @staticmethod
    def _validate_primary_key_index(
        conn: sqlite3.Connection,
        table: str,
        expected: tuple[str, ...],
        columns: dict[str, sqlite3.Row | tuple],
    ) -> None:
        indexes = [
            row
            for row in conn.execute(
                f'PRAGMA index_list("{table}")'
            ).fetchall()
            if row[3] == "pk"
        ]
        is_integer_rowid = (
            len(expected) == 1
            and str(columns[expected[0]][2]).upper() == "INTEGER"
        )
        if is_integer_rowid:
            if indexes:
                raise IncompatibleLedgerSchema(
                    f"{table} must use an INTEGER rowid PRIMARY KEY"
                )
            table_sql_row = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            table_sql = table_sql_row[0] if table_sql_row else ""
            if (
                not _sql_has_unquoted_keyword(table_sql, "AUTOINCREMENT")
                or _sql_has_unquoted_keyword(table_sql, "CONFLICT")
            ):
                raise IncompatibleLedgerSchema(
                    f"{table} has noncanonical INTEGER PRIMARY KEY semantics"
                )
            return
        if not indexes:
            raise IncompatibleLedgerSchema(
                f"{table} is missing its PRIMARY KEY backing index"
            )
        if len(indexes) != 1:
            raise IncompatibleLedgerSchema(
                f"{table} has incompatible PRIMARY KEY indexes"
            )
        index = indexes[0]
        name = index[1]
        if not bool(index[2]) or bool(index[4]):
            raise IncompatibleLedgerSchema(
                f"{table} has incompatible PRIMARY KEY index {name}"
            )
        key_rows = [
            row
            for row in conn.execute(
                "SELECT * FROM pragma_index_xinfo(?)",
                (name,),
            ).fetchall()
            if row[5]
        ]
        if any(row[1] < 0 or row[2] is None for row in key_rows):
            raise IncompatibleLedgerSchema(
                f"{table} has expression PRIMARY KEY index {name}"
            )
        actual = tuple(row[2] for row in key_rows)
        if actual != expected:
            raise IncompatibleLedgerSchema(
                f"{table} has incompatible PRIMARY KEY index columns: "
                f"{actual!r}"
            )
        for row in key_rows:
            column = row[2]
            if (
                str(columns[column][2]).upper() == "TEXT"
                and str(row[4]).upper() != "BINARY"
            ):
                raise IncompatibleLedgerSchema(
                    f"{table} has non-BINARY collation in PRIMARY KEY "
                    f"index {name}"
                )

    @classmethod
    def _validate_schema(
        cls,
        conn: sqlite3.Connection,
        required_columns: dict[str, set[str]],
        *,
        allowed_columns: dict[str, set[str]] | None = None,
    ) -> None:
        """Certify the versioned owned-table surface before public use.

        SQLite exposes generated columns and triggers directly, but not every
        column-level constraint as structured metadata. Unknown columns are
        therefore rejected rather than guessed safe. Non-unique indexes stay
        outside the write contract and remain permitted.
        """
        for table, required in required_columns.items():
            table_sql_row = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            table_sql = table_sql_row[0] if table_sql_row else ""
            if _sql_has_unquoted_keyword(table_sql, "CHECK"):
                raise IncompatibleLedgerSchema(
                    f"{table} has an unexpected CHECK constraint"
                )
            triggers = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger' AND tbl_name=? ORDER BY name",
                    (table,),
                ).fetchall()
            ]
            if triggers:
                raise IncompatibleLedgerSchema(
                    f"{table} has unexpected triggers: {triggers!r}"
                )
            rows = conn.execute(f'PRAGMA table_xinfo("{table}")').fetchall()
            by_name = {row[1]: row for row in rows}
            actual = set(by_name)
            allowed = (
                required
                if allowed_columns is None
                else allowed_columns[table]
            )
            missing = sorted(required - actual)
            if missing:
                raise IncompatibleLedgerSchema(
                    f"{table} missing required columns: {', '.join(missing)}"
                )
            unknown = sorted(actual - allowed)
            if unknown:
                raise IncompatibleLedgerSchema(
                    f"{table} has unknown columns: {', '.join(unknown)}"
                )
            for column in sorted(required):
                row = by_name[column]
                if int(row[6]) != 0:
                    raise IncompatibleLedgerSchema(
                        f"{table}.{column} has unexpected generated semantics"
                    )
                expected_type, expected_not_null, expected_default = (
                    _COLUMN_CONTRACTS[table][column]
                )
                actual_type = str(row[2]).upper()
                if actual_type != expected_type:
                    raise IncompatibleLedgerSchema(
                        f"{table}.{column} has incompatible type: "
                        f"expected {expected_type}, got {actual_type or '<empty>'}"
                    )
                if bool(row[3]) is not expected_not_null:
                    requirement = "NOT NULL" if expected_not_null else "nullable"
                    raise IncompatibleLedgerSchema(
                        f"{table}.{column} has incompatible NOT NULL shape: "
                        f"expected {requirement}"
                    )
                if row[4] != expected_default:
                    raise IncompatibleLedgerSchema(
                        f"{table}.{column} has incompatible default: "
                        f"expected {expected_default!r}, got {row[4]!r}"
                    )
            primary_key = cls._primary_key(conn, table)
            if primary_key != _PRIMARY_KEYS[table]:
                raise IncompatibleLedgerSchema(
                    f"{table} has incompatible primary key: {primary_key!r}"
                )
            cls._validate_primary_key_index(
                conn,
                table,
                _PRIMARY_KEYS[table],
                by_name,
            )
            required_unique = {
                key
                for key in _REQUIRED_UNIQUE_KEYS.get(table, set())
                if set(key) <= allowed
            }
            cls._validate_unique_keys(conn, table, required_unique)
            required_indexes = {
                key
                for key in _REQUIRED_INDEX_KEYS.get(table, set())
                if set(key) <= allowed
            }
            cls._validate_required_indexes(
                conn, table, required_indexes
            )

    @classmethod
    def _add_column(
        cls, conn: sqlite3.Connection, table: str, definition: str
    ) -> bool:
        column = definition.split()[0]
        if column not in cls._table_columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
            return True
        return False

    @classmethod
    def _run_migration(
        cls, conn: sqlite3.Connection, target_version: int
    ) -> None:
        if target_version == 1:
            for statement in _VERSION_ONE_SCHEMA:
                conn.execute(statement)
            cls._validate_schema(conn, _VERSION_ONE_COLUMNS)
            return
        if target_version == 2:
            phase_added = cls._add_column(
                conn,
                "classroom_replays",
                "phase INTEGER NOT NULL DEFAULT 1",
            )
            if phase_added:
                conn.execute(
                    "UPDATE classroom_replays SET phase=3 "
                    "WHERE status='INCOMPLETE' AND EXISTS ("
                    "SELECT 1 FROM broker_orders "
                    "WHERE broker_orders.strategy_id="
                    "classroom_replays.strategy_id "
                    "AND broker_orders.side='SELL')"
                )
            return
        if target_version == 3:
            cls._add_column(conn, "classroom_replays", "abort_reason TEXT")
            cls._add_column(conn, "classroom_replays", "aborted_at TEXT")
            cls._add_column(
                conn, "realized_trades", "exit_client_order_id TEXT"
            )
            cls._add_column(conn, "realized_trades", "exit_fill_id TEXT")
            return
        if target_version == 4:
            cls._add_column(
                conn, "positions", "entry_client_order_id TEXT"
            )
            return
        if target_version == 5:
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('market_regimes','candidates','entry_contexts')"
                ).fetchall()
            }
            if existing:
                raise IncompatibleLedgerSchema(
                    "partial or premature v5 provenance tables: "
                    f"{sorted(existing)!r}"
                )
            for statement in _VERSION_FIVE_SCHEMA:
                conn.execute(statement)
            return
        if target_version == 6:
            existing = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='market_calendar_cache'"
            ).fetchone()
            if existing is not None:
                raise IncompatibleLedgerSchema(
                    "partial or premature v6 market calendar table"
                )
            cls._add_column(
                conn,
                "broker_orders",
                "broker TEXT NOT NULL DEFAULT 'paper'",
            )
            cls._add_column(
                conn,
                "broker_orders",
                "broker_mode TEXT NOT NULL DEFAULT 'simulation'",
            )
            cls._add_column(conn, "broker_orders", "broker_order_date TEXT")
            cls._add_column(conn, "broker_orders", "broker_org_no TEXT")
            cls._add_column(conn, "broker_orders", "broker_order_no TEXT")
            cls._add_column(
                conn,
                "broker_orders",
                "remaining_quantity TEXT NOT NULL DEFAULT '0'",
            )
            for client_order_id, quantity, filled_quantity in conn.execute(
                "SELECT client_order_id,quantity,filled_quantity "
                "FROM broker_orders"
            ).fetchall():
                try:
                    requested = Decimal(quantity)
                    filled = Decimal(filled_quantity)
                except Exception as exc:
                    raise IncompatibleLedgerSchema(
                        f"invalid order quantity during v6 migration: "
                        f"{client_order_id}"
                    ) from exc
                remaining = requested - filled
                if (
                    not requested.is_finite()
                    or not filled.is_finite()
                    or requested <= 0
                    or filled < 0
                    or remaining < 0
                ):
                    raise IncompatibleLedgerSchema(
                        f"invalid order quantity during v6 migration: "
                        f"{client_order_id}"
                    )
                conn.execute(
                    "UPDATE broker_orders SET remaining_quantity=? "
                    "WHERE client_order_id=?",
                    (str(remaining), client_order_id),
                )
            for statement in _VERSION_SIX_SCHEMA:
                conn.execute(statement)
            return
        raise AssertionError(f"unknown schema migration: {target_version}")

    def _initialize_schema(self) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_VERSION_ONE_SCHEMA[0])
            self._validate_schema(
                conn, {"prism_core_meta": _VERSION_ONE_COLUMNS["prism_core_meta"]}
            )
            conn.execute(
                "INSERT OR IGNORE INTO prism_core_meta (key,value) "
                "VALUES ('schema_version','0')"
            )
            raw_version = conn.execute(
                "SELECT value FROM prism_core_meta WHERE key='schema_version'"
            ).fetchone()[0]
            try:
                version = int(raw_version)
            except (TypeError, ValueError) as exc:
                raise IncompatibleLedgerSchema(
                    f"invalid ledger schema_version: {raw_version!r}"
                ) from exc
            if version < 0 or version > CURRENT_SCHEMA_VERSION:
                raise IncompatibleLedgerSchema(
                    f"unsupported ledger schema_version: {version}"
                )
            if version:
                if version == CURRENT_SCHEMA_VERSION:
                    self._validate_schema(
                        conn,
                        _VERSION_ONE_COLUMNS,
                        allowed_columns=_CURRENT_COLUMNS,
                    )
                else:
                    self._validate_schema(
                        conn, _SCHEMA_COLUMNS_BY_VERSION[version]
                    )
            for target in range(version + 1, CURRENT_SCHEMA_VERSION + 1):
                self._run_migration(conn, target)
                conn.execute(
                    "UPDATE prism_core_meta SET value=? "
                    "WHERE key='schema_version'",
                    (str(target),),
                )
                self._validate_schema(
                    conn, _SCHEMA_COLUMNS_BY_VERSION[target]
                )
            if version == CURRENT_SCHEMA_VERSION:
                # Older course builds sometimes stamped the current version
                # before every modeled additive column existed. Repair only
                # known migrations after the base/unknown/trigger/key safety
                # preflight; final validation still requires the exact v5 set.
                for target in range(2, 5):
                    self._run_migration(conn, target)
            self._validate_schema(conn, _CURRENT_COLUMNS)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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

    @staticmethod
    def _regime_metrics_json(result: RegimeResult) -> str:
        return _encode_typed_json(result.metrics)

    def record_market_regime(self, run_id: str, result: RegimeResult) -> None:
        row = self._market_regime_row(run_id, result)
        with self._connect(immediate=True) as conn:
            self._record_market_regime_row(conn, row)

    def _market_regime_row(self, run_id: str, result: RegimeResult) -> tuple:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id is required")
        if not isinstance(result, RegimeResult):
            raise ValueError("result must be a RegimeResult")
        normalized = RegimeResult(
            market=result.market,
            as_of=result.as_of,
            regime=result.regime,
            confidence=result.confidence,
            pulse=result.pulse,
            metrics=result.metrics,
            reasons=result.reasons,
            source=result.source,
        )
        row = (
            run_id.strip(),
            normalized.market.value,
            normalized.as_of.isoformat(),
            normalized.regime.value,
            str(normalized.confidence),
            normalized.pulse.value,
            self._regime_metrics_json(normalized),
            json.dumps(
                normalized.reasons,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            normalized.source,
        )
        return row

    @staticmethod
    def _record_market_regime_row(conn, row) -> None:
        existing = conn.execute(
            "SELECT run_id,market,as_of,regime,confidence,pulse,"
            "metrics_json,reasons_json,source FROM market_regimes "
            "WHERE run_id=? AND market=?",
            row[:2],
        ).fetchone()
        if existing is not None:
            if tuple(existing) == row:
                return
            raise ValueError(f"market regime collision: {row[0]}:{row[1]}")
        conn.execute(
            "INSERT INTO market_regimes "
            "(run_id,market,as_of,regime,confidence,pulse,metrics_json,"
            "reasons_json,source) VALUES (?,?,?,?,?,?,?,?,?)",
            row,
        )

    def get_market_regime(
        self, run_id: str, market: Market
    ) -> RegimeResult | None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id is required")
        if not isinstance(market, Market):
            raise ValueError("market must be a Market")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_regimes WHERE run_id=? AND market=?",
                (run_id.strip(), market.value),
            ).fetchone()
        if row is None:
            return None
        try:
            metrics = _decode_typed_json(row["metrics_json"])
            reasons = json.loads(row["reasons_json"])
            if not isinstance(reasons, list):
                raise ValueError("reasons_json must contain an array")
            return RegimeResult(
                market=Market(row["market"]),
                as_of=datetime.fromisoformat(row["as_of"]),
                regime=Regime(row["regime"]),
                confidence=Decimal(row["confidence"]),
                pulse=PulseState(row["pulse"]),
                metrics=metrics,
                reasons=tuple(reasons),
                source=row["source"],
            )
        except Exception as exc:
            raise ValueError("corrupt stored market regime") from exc

    @staticmethod
    def _candidate_json(values) -> str:
        return _encode_typed_json(values)

    def record_candidates(self, run_id: str, candidates) -> None:
        rows = self._candidate_rows(run_id, candidates)
        with self._connect(immediate=True) as conn:
            self._record_candidate_rows(conn, rows)

    def _candidate_rows(self, run_id: str, candidates) -> list[tuple]:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id is required")
        run_id = run_id.strip()
        candidates = tuple(candidates)
        ranks = Counter()
        rows = []
        identities = set()
        for candidate in candidates:
            if not isinstance(candidate, Candidate):
                raise ValueError("candidates must contain Candidate values")
            normalized = Candidate(
                instrument=Instrument(
                    symbol=candidate.instrument.symbol,
                    market=candidate.instrument.market,
                    exchange=candidate.instrument.exchange,
                    currency=candidate.instrument.currency,
                    name=candidate.instrument.name,
                    sector=candidate.instrument.sector,
                    lot_size=candidate.instrument.lot_size,
                    price_precision=candidate.instrument.price_precision,
                ),
                as_of=candidate.as_of,
                trigger_type=candidate.trigger_type,
                regime=candidate.regime,
                feature_values=candidate.feature_values,
                component_scores=candidate.component_scores,
                final_score=candidate.final_score,
                reference_price=candidate.reference_price,
                stop_price=candidate.stop_price,
                target_price=candidate.target_price,
                risk_reward_ratio=candidate.risk_reward_ratio,
                source=candidate.source,
            )
            instrument = normalized.instrument
            ranks[instrument.market] += 1
            identity = (
                run_id,
                instrument.market.value,
                instrument.symbol,
                normalized.trigger_type.value,
            )
            if identity in identities:
                raise ValueError(f"candidate collision: {identity!r}")
            identities.add(identity)
            rows.append((
                run_id,
                ranks[instrument.market],
                instrument.market.value,
                instrument.symbol,
                instrument.exchange,
                instrument.currency,
                instrument.name,
                instrument.sector,
                str(instrument.lot_size),
                instrument.price_precision,
                normalized.as_of.isoformat(),
                normalized.trigger_type.value,
                normalized.regime.value,
                self._candidate_json(normalized.feature_values),
                self._candidate_json(normalized.component_scores),
                str(normalized.final_score),
                str(normalized.reference_price),
                str(normalized.stop_price),
                str(normalized.target_price),
                str(normalized.risk_reward_ratio),
                normalized.source,
            ))
        return rows

    @staticmethod
    def _record_candidate_rows(conn, rows) -> None:
        pending = []
        for row in rows:
            existing = conn.execute(
                    "SELECT run_id,rank,market,symbol,exchange,currency,name,sector,"
                    "lot_size,price_precision,as_of,trigger_type,regime,"
                    "feature_values_json,component_scores_json,final_score,"
                    "reference_price,stop_price,target_price,risk_reward_ratio,source "
                    "FROM candidates WHERE run_id=? AND market=? AND symbol=? "
                    "AND trigger_type=?",
                    (row[0], row[2], row[3], row[11]),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != row:
                    raise ValueError(
                        f"candidate collision: {row[0]}:{row[2]}:{row[3]}"
                    )
                continue
            occupied_rank = conn.execute(
                "SELECT symbol,trigger_type FROM candidates "
                "WHERE run_id=? AND market=? AND rank=?",
                (row[0], row[2], row[1]),
            ).fetchone()
            if occupied_rank is not None:
                raise ValueError(
                    f"candidate collision: {row[0]}:{row[2]}:rank-{row[1]}"
                )
            pending.append(row)
        conn.executemany(
            "INSERT INTO candidates (run_id,rank,market,symbol,exchange,"
            "currency,name,sector,lot_size,price_precision,as_of,trigger_type,"
            "regime,feature_values_json,component_scores_json,final_score,"
            "reference_price,stop_price,target_price,risk_reward_ratio,source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            pending,
        )

    def list_candidates(
        self, run_id: str, market: Market | None = None
    ) -> list[Candidate]:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id is required")
        if market is not None and not isinstance(market, Market):
            raise ValueError("market must be a Market")
        parameters = [run_id.strip()]
        where = "run_id=?"
        if market is not None:
            where += " AND market=?"
            parameters.append(market.value)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM candidates WHERE {where} ORDER BY rank,rowid",
                parameters,
            ).fetchall()
        results = []
        for row in rows:
            try:
                features = _decode_typed_json(row["feature_values_json"])
                components = _decode_typed_json(row["component_scores_json"])
                results.append(Candidate(
                    instrument=Instrument(
                        symbol=row["symbol"],
                        market=Market(row["market"]),
                        exchange=row["exchange"],
                        currency=row["currency"],
                        name=row["name"],
                        sector=row["sector"],
                        lot_size=Decimal(row["lot_size"]),
                        price_precision=row["price_precision"],
                    ),
                    as_of=datetime.fromisoformat(row["as_of"]),
                    trigger_type=TriggerType(row["trigger_type"]),
                    regime=Regime(row["regime"]),
                    feature_values=features,
                    component_scores=components,
                    final_score=Decimal(row["final_score"]),
                    reference_price=Decimal(row["reference_price"]),
                    stop_price=Decimal(row["stop_price"]),
                    target_price=Decimal(row["target_price"]),
                    risk_reward_ratio=Decimal(row["risk_reward_ratio"]),
                    source=row["source"],
                ))
            except Exception as exc:
                raise ValueError("corrupt stored candidate") from exc
        return results

    def _validated_entry_reference(self, context: EntryContext) -> Candidate:
        expected_id = (
            f"{context.run_id}:{context.candidate.instrument.market.value}:"
            f"{context.candidate.instrument.symbol}:BUY"
        )
        if context.client_order_id != expected_id:
            raise ValueError("entry context client_order_id mismatch")
        candidates = self.list_candidates(
            context.run_id, context.candidate.instrument.market
        )
        referenced = next(
            (
                candidate
                for candidate in candidates
                if candidate.instrument.symbol
                == context.candidate.instrument.symbol
                and candidate.trigger_type is context.candidate.trigger_type
            ),
            None,
        )
        if referenced is None:
            raise ValueError("entry context candidate mismatch")
        self._validate_entry_context_against_candidate(context, referenced)
        return referenced

    @staticmethod
    def _validate_entry_context_against_candidate(
        context: EntryContext, referenced: Candidate
    ) -> None:
        expected_id = (
            f"{context.run_id}:{referenced.instrument.market.value}:"
            f"{referenced.instrument.symbol}:BUY"
        )
        if context.client_order_id != expected_id:
            raise ValueError("entry context client_order_id mismatch")
        if referenced != context.candidate:
            raise ValueError("entry context candidate mismatch")
        if context.strategy_id != referenced.source:
            raise ValueError("entry context strategy_id mismatch")
        if context.policy != policy_for(referenced.regime):
            raise ValueError("entry context policy mismatch")

    def record_entry_context(self, context: EntryContext) -> None:
        if not isinstance(context, EntryContext):
            raise ValueError("context must be an EntryContext")
        referenced = self._validated_entry_reference(context)
        row = self._entry_context_row(context, referenced)
        with self._connect(immediate=True) as conn:
            self._record_entry_context_row(conn, row)

    @staticmethod
    def _entry_context_row(context: EntryContext, referenced: Candidate) -> tuple:
        return (
            context.client_order_id,
            context.run_id,
            referenced.instrument.market.value,
            referenced.instrument.symbol,
            context.strategy_id,
            referenced.regime.value,
            referenced.trigger_type.value,
            str(referenced.stop_price),
            str(referenced.target_price),
            str(referenced.risk_reward_ratio),
            str(context.policy.trailing_pct),
            referenced.source,
        )

    @staticmethod
    def _record_entry_context_row(conn, row) -> None:
        existing = conn.execute(
                "SELECT client_order_id,run_id,market,symbol,strategy_id,regime,"
                "trigger_type,stop_price,target_price,risk_reward_ratio,"
                "trailing_pct,source FROM entry_contexts WHERE client_order_id=? "
                "OR (run_id=? AND market=? AND symbol=? AND trigger_type=?)",
                (row[0], row[1], row[2], row[3], row[6]),
        ).fetchone()
        if existing is not None:
            if tuple(existing) == row:
                return
            raise ValueError(f"entry context collision: {row[0]}")
        conn.execute(
            "INSERT INTO entry_contexts (client_order_id,run_id,market,symbol,"
            "strategy_id,regime,trigger_type,stop_price,target_price,"
            "risk_reward_ratio,trailing_pct,source,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row + (_now(),),
        )

    def get_entry_context(self, client_order_id: str) -> EntryContext | None:
        if not isinstance(client_order_id, str) or not client_order_id.strip():
            raise ValueError("client_order_id is required")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM entry_contexts WHERE client_order_id=?",
                (client_order_id.strip(),),
            ).fetchone()
        if row is None:
            return None
        try:
            created_at = datetime.fromisoformat(row["created_at"])
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("created_at must be timezone-aware")
            market = Market(row["market"])
            trigger = TriggerType(row["trigger_type"])
            referenced = next(
                (
                    candidate
                    for candidate in self.list_candidates(row["run_id"], market)
                    if candidate.instrument.symbol == row["symbol"]
                    and candidate.trigger_type is trigger
                ),
                None,
            )
            if referenced is None:
                raise ValueError("entry context candidate is missing")
            policy = policy_for(referenced.regime)
            context = EntryContext(
                client_order_id=row["client_order_id"],
                run_id=row["run_id"],
                candidate=referenced,
                strategy_id=row["strategy_id"],
                policy=policy,
            )
            if (
                context.client_order_id
                != f"{context.run_id}:{market.value}:{row['symbol']}:BUY"
                or row["strategy_id"] != referenced.source
                or row["source"] != referenced.source
                or Regime(row["regime"]) is not referenced.regime
                or Decimal(row["stop_price"]) != referenced.stop_price
                or Decimal(row["target_price"]) != referenced.target_price
                or Decimal(row["risk_reward_ratio"])
                != referenced.risk_reward_ratio
                or Decimal(row["trailing_pct"]) != policy.trailing_pct
            ):
                raise ValueError("entry context does not match candidate")
            return context
        except Exception as exc:
            raise ValueError("corrupt stored entry context") from exc

    def record_market_preparation(
        self,
        run_id: str,
        regimes: tuple[RegimeResult, ...],
        candidates: tuple[Candidate, ...],
        entry_contexts: tuple[EntryContext, ...],
    ) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id is required")
        if not all(type(values) is tuple for values in (
            regimes, candidates, entry_contexts
        )):
            raise ValueError("market preparation inputs must be exact tuples")
        run_id = run_id.strip()

        regime_rows = []
        regime_by_market = {}
        for result in regimes:
            row = self._market_regime_row(run_id, result)
            if result.market in regime_by_market:
                raise ValueError("duplicate market regime")
            regime_by_market[result.market] = result
            regime_rows.append(row)

        candidate_rows = self._candidate_rows(run_id, candidates)
        candidate_by_identity = {}
        for selected in candidates:
            supplied_regime = regime_by_market.get(selected.instrument.market)
            if supplied_regime is None or supplied_regime.regime is not selected.regime:
                raise ValueError("candidate has no matching supplied market regime")
            identity = (
                selected.instrument.market,
                selected.instrument.symbol,
                selected.trigger_type,
            )
            if identity in candidate_by_identity:
                raise ValueError("duplicate candidate identity")
            candidate_by_identity[identity] = selected

        context_rows = []
        context_ids = set()
        for context in entry_contexts:
            if not isinstance(context, EntryContext):
                raise ValueError("entry_contexts must contain EntryContext values")
            if context.run_id != run_id:
                raise ValueError("entry context run_id mismatch")
            if context.client_order_id in context_ids:
                raise ValueError("duplicate entry context client_order_id")
            context_ids.add(context.client_order_id)
            identity = (
                context.candidate.instrument.market,
                context.candidate.instrument.symbol,
                context.candidate.trigger_type,
            )
            referenced = candidate_by_identity.get(identity)
            if referenced is None:
                raise ValueError("entry context references unsupplied candidate")
            self._validate_entry_context_against_candidate(context, referenced)
            context_rows.append(self._entry_context_row(context, referenced))

        with self._connect(immediate=True) as conn:
            for row in regime_rows:
                self._record_market_regime_row(conn, row)
            self._record_candidate_rows(conn, candidate_rows)
            for row in context_rows:
                self._record_entry_context_row(conn, row)

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
            "quantity,filled_quantity,remaining_quantity,currency "
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
            remaining_quantity = Decimal(order["remaining_quantity"])
            fill_quantities = [Decimal(fill["quantity"]) for fill in fills]
        except Exception:
            return True
        if any(quantity <= 0 for quantity in fill_quantities):
            return True
        if sum(fill_quantities, Decimal("0")) != filled_quantity:
            return True
        if (
            remaining_quantity < 0
            or filled_quantity + remaining_quantity != order_quantity
        ):
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

    @classmethod
    def _row_to_broker_order_state(
        cls, row: sqlite3.Row
    ) -> BrokerOrderState:
        return BrokerOrderState(
            order=cls._row_to_order(row),
            broker=row["broker"],
            broker_mode=row["broker_mode"],
            broker_order_date=row["broker_order_date"],
            broker_org_no=row["broker_org_no"],
            broker_order_no=row["broker_order_no"],
            remaining_quantity=Decimal(row["remaining_quantity"]),
        )

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        market = Market(row["market"])
        quantity = Decimal(row["quantity"])
        average_price = Decimal(row["average_price"])
        high_since_entry = Decimal(row["high_since_entry"])
        validate_market_contract(
            market,
            row["symbol"],
            currency=row["currency"],
            quantity=quantity,
            price=average_price,
            price_name="average_price",
        )
        validate_market_contract(
            market,
            row["symbol"],
            price=high_since_entry,
            price_name="high_since_entry",
        )
        if quantity <= 0:
            raise ValueError("persisted position quantity must be positive")
        if average_price <= 0:
            raise ValueError(
                "persisted position average_price must be positive"
            )
        if high_since_entry <= 0:
            raise ValueError(
                "persisted position high_since_entry must be positive"
            )
        if high_since_entry < average_price:
            raise ValueError(
                "persisted position high_since_entry cannot be below "
                "average_price"
            )
        return Position(
            market=market,
            symbol=row["symbol"],
            quantity=quantity,
            average_price=average_price,
            currency=row["currency"],
            high_since_entry=high_since_entry,
            strategy_id=row["strategy_id"],
            entry_client_order_id=row["entry_client_order_id"],
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
        validate_market_contract(
            fill.market,
            fill.symbol,
            quantity=fill.quantity,
            price=fill.price,
            quantity_name="fill quantity",
            price_name="fill price",
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
        if not isinstance(intent, OrderIntent):
            raise ValueError("intent must be an OrderIntent")
        intent.__post_init__()
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO broker_orders "
                "(client_order_id,market,symbol,side,order_type,quantity,limit_price,currency,strategy_id,reason,status,remaining_quantity,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    str(intent.quantity),
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

    @staticmethod
    def _normalized_broker_value(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        return value.strip().lower()

    def save_broker_order(
        self,
        intent: OrderIntent,
        *,
        broker: str,
        broker_mode: str,
    ) -> BrokerOrderState:
        if not isinstance(intent, OrderIntent):
            raise ValueError("intent must be an OrderIntent")
        intent.__post_init__()
        normalized_broker = self._normalized_broker_value(broker, "broker")
        normalized_mode = self._normalized_broker_value(
            broker_mode, "broker_mode"
        )
        now = _now()
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO broker_orders "
                "(client_order_id,market,symbol,side,order_type,quantity,"
                "limit_price,currency,strategy_id,reason,status,"
                "remaining_quantity,broker,broker_mode,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    str(intent.quantity),
                    normalized_broker,
                    normalized_mode,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (intent.client_order_id,),
            ).fetchone()
            if row is None or not self._order_payload_matches(row, intent):
                raise ValueError(f"order id collision: {intent.client_order_id}")
            if (
                row["broker"] != normalized_broker
                or row["broker_mode"] != normalized_mode
            ):
                raise ValueError(
                    f"order broker collision: {intent.client_order_id}"
                )
            if cursor.rowcount:
                conn.execute(
                    "INSERT INTO order_events "
                    "(client_order_id,status,occurred_at) VALUES (?,?,?)",
                    (
                        intent.client_order_id,
                        OrderStatus.CREATED.value,
                        now,
                    ),
                )
            state = self._row_to_broker_order_state(row)
        return state

    def get_broker_order_state(
        self, client_order_id: str
    ) -> BrokerOrderState:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
        if row is None:
            raise KeyError(client_order_id)
        return self._row_to_broker_order_state(row)

    def admit_broker_order(
        self,
        intent: OrderIntent,
        *,
        broker: str,
        broker_mode: str,
    ) -> tuple[BrokerOrderState | None, BrokerOrderState | None]:
        """Atomically admit one order or return the unresolved blocker.

        An identity-less UNKNOWN blocks the whole broker account because its
        symbol/order identity cannot be proven after a lost POST response.
        Other unresolved orders block another order for the same symbol.
        """
        if not isinstance(intent, OrderIntent):
            raise ValueError("intent must be an OrderIntent")
        intent.__post_init__()
        normalized_broker = self._normalized_broker_value(broker, "broker")
        normalized_mode = self._normalized_broker_value(
            broker_mode, "broker_mode"
        )
        placeholders = ",".join("?" for _ in _UNRESOLVED_ORDER_STATUSES)
        with self._connect(immediate=True) as conn:
            blocker = conn.execute(
                "SELECT * FROM broker_orders WHERE broker=? AND broker_mode=? "
                f"AND status IN ({placeholders}) AND ("
                "(status=? AND broker_order_no IS NULL) OR "
                "(market=? AND symbol=?)) "
                "ORDER BY updated_at,client_order_id LIMIT 1",
                (
                    normalized_broker,
                    normalized_mode,
                    *(status.value for status in _UNRESOLVED_ORDER_STATUSES),
                    OrderStatus.UNKNOWN.value,
                    intent.market.value,
                    intent.symbol,
                ),
            ).fetchone()
            if blocker is not None:
                return None, self._row_to_broker_order_state(blocker)

            now = _now()
            conn.execute(
                "INSERT INTO broker_orders "
                "(client_order_id,market,symbol,side,order_type,quantity,"
                "limit_price,currency,strategy_id,reason,status,"
                "remaining_quantity,broker,broker_mode,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    str(intent.quantity),
                    normalized_broker,
                    normalized_mode,
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
            return self._row_to_broker_order_state(created), None

    def bind_broker_identity(
        self,
        client_order_id: str,
        *,
        broker_order_date: str,
        broker_org_no: str,
        broker_order_no: str,
    ) -> BrokerOrderState:
        values = {
            "broker_order_date": broker_order_date,
            "broker_org_no": broker_org_no,
            "broker_order_no": broker_order_no,
        }
        normalized: dict[str, str] = {}
        for name, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
            normalized[name] = value.strip()
        normalized["broker_order_date"] = _validated_trade_date(
            normalized["broker_order_date"]
        )
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
            if row is None:
                raise KeyError(client_order_id)
            current = (
                row["broker_order_date"],
                row["broker_org_no"],
                row["broker_order_no"],
            )
            requested = (
                normalized["broker_order_date"],
                normalized["broker_org_no"],
                normalized["broker_order_no"],
            )
            if current == requested:
                return self._row_to_broker_order_state(row)
            if any(value is not None for value in current):
                raise ValueError(
                    f"broker identity is already bound: {client_order_id}"
                )
            try:
                conn.execute(
                    "UPDATE broker_orders SET broker_order_date=?,"
                    "broker_org_no=?,broker_order_no=?,updated_at=? "
                    "WHERE client_order_id=?",
                    (*requested, _now(), client_order_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("broker order identity collision") from exc
            updated = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
            return self._row_to_broker_order_state(updated)

    def update_broker_order(
        self,
        client_order_id: str,
        *,
        status: OrderStatus,
        filled_quantity: Decimal,
        remaining_quantity: Decimal,
        average_fill_price: Decimal | None,
    ) -> BrokerOrderState:
        if not isinstance(status, OrderStatus):
            raise ValueError("status must be an OrderStatus")
        for name, value in (
            ("filled_quantity", filled_quantity),
            ("remaining_quantity", remaining_quantity),
        ):
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value < 0
            ):
                raise ValueError(f"{name} must be a finite non-negative Decimal")
        if filled_quantity == 0:
            if average_fill_price is not None:
                raise ValueError(
                    "average_fill_price must be None when nothing is filled"
                )
        elif (
            not isinstance(average_fill_price, Decimal)
            or not average_fill_price.is_finite()
            or average_fill_price <= 0
        ):
            raise ValueError(
                "average_fill_price must be positive when quantity is filled"
            )
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
            if row is None:
                raise KeyError(client_order_id)
            requested = Decimal(row["quantity"])
            if filled_quantity + remaining_quantity != requested:
                raise ValueError(
                    "filled_quantity + remaining_quantity must equal requested quantity"
                )
            if status is OrderStatus.FILLED and (
                filled_quantity != requested or remaining_quantity != 0
            ):
                raise ValueError(
                    "FILLED requires the full requested quantity and zero remaining"
                )
            if status is OrderStatus.PARTIALLY_FILLED and not (
                0 < filled_quantity < requested and remaining_quantity > 0
            ):
                raise ValueError(
                    "PARTIALLY_FILLED requires both filled and remaining quantity"
                )
            if status in {
                OrderStatus.CREATED,
                OrderStatus.PREVIEWED,
                OrderStatus.SUBMITTED,
                OrderStatus.ACCEPTED,
                OrderStatus.REJECTED,
            } and filled_quantity != 0:
                raise ValueError(f"{status.value} cannot contain filled quantity")
            if status is OrderStatus.CANCELED and remaining_quantity <= 0:
                raise ValueError("CANCELED requires an unfilled remaining quantity")
            current_status = OrderStatus(row["status"])
            current_filled = Decimal(row["filled_quantity"])
            current_remaining = Decimal(row["remaining_quantity"])
            if filled_quantity < current_filled:
                raise ValueError("filled_quantity cannot decrease")
            if remaining_quantity > current_remaining:
                raise ValueError("remaining_quantity cannot increase")
            if current_status is not status and not validate_transition(
                current_status, status
            ):
                raise ValueError(
                    f"invalid order transition: {current_status.value} -> "
                    f"{status.value}"
                )
            now = _now()
            conn.execute(
                "UPDATE broker_orders SET status=?,filled_quantity=?,"
                "remaining_quantity=?,average_fill_price=?,updated_at=? "
                "WHERE client_order_id=?",
                (
                    status.value,
                    str(filled_quantity),
                    str(remaining_quantity),
                    (
                        str(average_fill_price)
                        if average_fill_price is not None
                        else None
                    ),
                    now,
                    client_order_id,
                ),
            )
            if current_status is not status:
                conn.execute(
                    "INSERT OR IGNORE INTO order_events "
                    "(client_order_id,status,occurred_at) VALUES (?,?,?)",
                    (client_order_id, status.value, now),
                )
            updated = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
            return self._row_to_broker_order_state(updated)

    def get_pending_broker_orders(
        self,
        *,
        broker: str,
        broker_mode: str,
    ) -> list[BrokerOrderState]:
        normalized_broker = self._normalized_broker_value(broker, "broker")
        normalized_mode = self._normalized_broker_value(
            broker_mode, "broker_mode"
        )
        placeholders = ",".join("?" for _ in _UNRESOLVED_ORDER_STATUSES)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM broker_orders WHERE broker=? AND broker_mode=? "
                f"AND status IN ({placeholders}) "
                "ORDER BY updated_at,client_order_id",
                (
                    normalized_broker,
                    normalized_mode,
                    *(status.value for status in _UNRESOLVED_ORDER_STATUSES),
                ),
            ).fetchall()
        return [self._row_to_broker_order_state(row) for row in rows]

    def save_market_day(
        self,
        market: Market,
        trade_date: str,
        *,
        is_open: bool,
        source: str,
        broker_mode: str = "paper",
        checked_at: str | None = None,
    ) -> dict:
        if not isinstance(market, Market):
            raise ValueError("market must be a Market")
        normalized_date = _validated_trade_date(trade_date)
        if type(is_open) is not bool:
            raise ValueError("is_open must be a bool")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source is required")
        mode = self._normalized_broker_value(broker_mode, "broker_mode")
        timestamp = _validated_checked_at(checked_at or _now())
        with self._connect(immediate=True) as conn:
            conn.execute(
                "INSERT INTO market_calendar_cache "
                "(market,broker_mode,trade_date,is_open,source,checked_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(market,broker_mode,trade_date) "
                "DO UPDATE SET is_open=excluded.is_open,source=excluded.source,"
                "checked_at=excluded.checked_at "
                "WHERE excluded.checked_at > market_calendar_cache.checked_at",
                (
                    market.value,
                    mode,
                    normalized_date,
                    int(is_open),
                    source.strip(),
                    timestamp,
                ),
            )
        return self.get_market_day(
            market, normalized_date, broker_mode=mode
        )

    def get_market_day(
        self,
        market: Market,
        trade_date: str,
        *,
        broker_mode: str = "paper",
    ) -> dict | None:
        if not isinstance(market, Market):
            raise ValueError("market must be a Market")
        normalized_date = _validated_trade_date(trade_date)
        mode = self._normalized_broker_value(broker_mode, "broker_mode")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_calendar_cache "
                "WHERE market=? AND broker_mode=? AND trade_date=?",
                (market.value, mode, normalized_date),
            ).fetchone()
        if row is None:
            return None
        if row["is_open"] not in {0, 1}:
            raise ValueError("persisted is_open must be 0 or 1")
        return {
            "market": row["market"],
            "broker_mode": row["broker_mode"],
            "trade_date": row["trade_date"],
            "is_open": bool(row["is_open"]),
            "source": row["source"],
            "checked_at": row["checked_at"],
        }

    def create_order_if_admissible(
        self, intent: OrderIntent
    ) -> OrderRecord | None:
        if not isinstance(intent, OrderIntent):
            raise ValueError("intent must be an OrderIntent")
        intent.__post_init__()
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
                "(client_order_id,market,symbol,side,order_type,quantity,limit_price,currency,strategy_id,reason,status,remaining_quantity,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    str(intent.quantity),
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
                "(client_order_id,market,symbol,side,order_type,quantity,limit_price,currency,strategy_id,reason,status,remaining_quantity,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    str(intent.quantity),
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
        validate_market_contract(market, symbol, price=price)
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
            position = (
                self._row_to_position(position_row)
                if position_row is not None
                else None
            )
            if fill.side is OrderSide.BUY and position is not None:
                entry_client_order_id = position.entry_client_order_id
                if entry_client_order_id is None:
                    raise PositionEntryConflict(
                        "position entry ownership is unknown; BUY fill rejected"
                    )
                if entry_client_order_id != fill.client_order_id:
                    raise PositionEntryConflict(
                        "BUY fill does not continue the position entry order"
                    )
                if order.intent.strategy_id != position.strategy_id:
                    raise PositionEntryConflict(
                        "BUY fill strategy does not own the position entry order"
                    )
            if fill.side is OrderSide.SELL:
                if position is None:
                    raise PositionFillConflict(
                        fill.market, fill.symbol, "missing"
                    )
                if order.intent.strategy_id != position.strategy_id:
                    raise PositionFillConflict(
                        fill.market, fill.symbol, "strategy_changed"
                    )
                if fill.quantity > position.quantity:
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
                old_qty = position.quantity if position else Decimal("0")
                old_avg = (
                    position.average_price if position else Decimal("0")
                )
                new_qty = old_qty + fill.quantity
                new_avg = (
                    (old_qty * old_avg) + (fill.quantity * fill.price)
                ) / new_qty
                old_high = position.high_since_entry if position else fill.price
                conn.execute(
                    "INSERT INTO positions (market,symbol,quantity,average_price,currency,high_since_entry,strategy_id,entry_client_order_id,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(market,symbol) DO UPDATE SET "
                    "quantity=excluded.quantity,average_price=excluded.average_price,"
                    "high_since_entry=excluded.high_since_entry,updated_at=excluded.updated_at",
                    (
                        fill.market.value,
                        fill.symbol,
                        str(new_qty),
                        str(new_avg),
                        normalized_currency,
                        str(max(old_high, fill.price)),
                        order.intent.strategy_id,
                        fill.client_order_id,
                        now,
                    ),
                )
            else:
                old_qty = position.quantity
                old_avg = position.average_price
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
                        position.strategy_id,
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
                "UPDATE broker_orders SET status=?,filled_quantity=?,"
                "remaining_quantity=?,average_fill_price=?,updated_at=? "
                "WHERE client_order_id=?",
                (
                    target.value,
                    str(cumulative),
                    str(order.intent.quantity - cumulative),
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
