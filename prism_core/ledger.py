from __future__ import annotations

import sqlite3
from contextlib import contextmanager
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
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
        return self.get_order(intent.client_order_id)

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
        with self._connect() as conn:
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

    def count_realized_trades(self) -> int:
        with self._connect() as conn:
            return int(
                conn.execute("SELECT COUNT(*) FROM realized_trades").fetchone()[0]
            )

    def update_high_water(
        self, market: Market, symbol: str, price: Decimal
    ) -> Position:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE market=? AND symbol=?",
                (market.value, symbol),
            ).fetchone()
            if row is None:
                raise KeyError((market.value, symbol))
            high = max(Decimal(row["high_since_entry"]), price)
            conn.execute(
                "UPDATE positions SET high_since_entry=?,updated_at=? WHERE market=? AND symbol=?",
                (str(high), _now(), market.value, symbol),
            )
        return next(
            position
            for position in self.list_positions()
            if position.market is market and position.symbol == symbol
        )

    def record_fill(self, fill: Fill) -> Position | None:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            inserted = conn.execute(
                "INSERT OR IGNORE INTO fills (fill_id,client_order_id,market,symbol,side,quantity,price,currency,occurred_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    fill.fill_id,
                    fill.client_order_id,
                    fill.market.value,
                    fill.symbol,
                    fill.side.value,
                    str(fill.quantity),
                    str(fill.price),
                    fill.currency,
                    _now(),
                ),
            )
            if not inserted.rowcount:
                conn.commit()
                positions = self.list_positions()
                return next(
                    (
                        position
                        for position in positions
                        if position.market is fill.market
                        and position.symbol == fill.symbol
                    ),
                    None,
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
            ) != (fill.market, fill.symbol, fill.side, fill.currency):
                raise ValueError("fill does not match order")

            cumulative = order.filled_quantity + fill.quantity
            if fill.quantity <= 0 or cumulative > order.intent.quantity:
                raise ValueError("fill quantity exceeds order quantity")

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
                        fill.currency,
                        str(max(old_high, fill.price)),
                        order.intent.strategy_id,
                        now,
                    ),
                )
            else:
                if position_row is None:
                    raise ValueError("cannot sell a missing position")
                old_qty = Decimal(position_row["quantity"])
                old_avg = Decimal(position_row["average_price"])
                if fill.quantity > old_qty:
                    raise ValueError("sell quantity exceeds position")
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
                        fill.currency,
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
            if not validate_transition(order.status, target):
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
