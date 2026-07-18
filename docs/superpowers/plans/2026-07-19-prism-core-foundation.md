# PRISM Core Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 재시작해도 주문·체결·보유가 이어지고, 기존 보유 청산을 신규 진입보다 먼저 처리하는 KR/US 공용 local paper 코어를 추가한다.

**Architecture:** 새 `prism_core` 패키지가 시장·주문 도메인, SQLite 원장, local paper broker, 1회 사이클을 소유한다. 기존 루트 파이프라인은 하위 호환 facade로 남기고 마지막 통합 작업에서 `classroom` 프로필만 새 코어로 연결한다. 브로커 체결을 포지션의 진실 원천으로 삼고, 주문 결과가 불명확하면 재주문하지 않는다.

**Tech Stack:** Python 3.10+, standard library `dataclasses`, `decimal`, `enum`, `sqlite3`, `unittest`, `asyncio`

## Global Constraints

- `python3 main.py`는 외부 키와 새 필수 패키지 없이 완주해야 한다.
- `run_screening`, `run_analysis`, `run_trading`, `run_feedback` 공개 시그니처를 바꾸지 않는다.
- 실거래 이중 게이트를 약화하지 않는다.
- `paper/live`에서 mock·stale·시장/통화 누락 주문은 fail-closed한다.
- SQLite에는 금액과 수량을 decimal 문자열로 저장해 USD 정밀도를 잃지 않는다.
- DB migration은 additive·idempotent하며 기존 `prism.db` 데이터를 삭제하지 않는다.
- 모든 테스트는 네트워크·자격정보 없이 실행한다.
- 각 작업은 TDD 순서와 Lore commit protocol을 따른다.

---

## File Map

- Create `prism_core/__init__.py`: 공용 타입 export
- Create `prism_core/domain.py`: KR/US 시장, 주문 의도, 상태, 포지션, 체결 모델과 검증
- Create `prism_core/ledger.py`: additive schema와 주문·체결·포지션 transaction
- Create `prism_core/paper_broker.py`: preview/submit/pending/fill/cancel/reconcile local broker
- Create `prism_core/cycle.py`: 청산 우선 1회 사이클과 중복 client order ID 방지
- Create `prism_core/classroom.py`: 토요일 수업용 3-cycle replay fixture
- Modify `runtime_config.py`: `classroom`과 `backtest` 프로필 인식
- Modify `main.py`: `classroom`일 때 새 replay를 실행하고 기존 mock 경로는 보존
- Modify `db.py`: 새 원장을 같은 `prism.db`에 초기화하는 단일 스키마 진입점 제공
- Create `tests/test_prism_core_domain.py`
- Create `tests/test_prism_core_ledger.py`
- Create `tests/test_prism_core_paper_broker.py`
- Create `tests/test_prism_core_cycle.py`
- Create `tests/test_classroom_profile.py`

### Task 1: KR/US 주문 도메인과 상태 전이

**Files:**
- Create: `prism_core/__init__.py`
- Create: `prism_core/domain.py`
- Test: `tests/test_prism_core_domain.py`

**Interfaces:**
- Consumes: 표준 라이브러리만 사용
- Produces: `Market`, `OrderSide`, `OrderType`, `OrderStatus`, `OrderIntent`, `OrderRecord`, `Fill`, `Position`, `validate_transition()`

- [ ] **Step 1: Write the failing domain tests**

```python
from decimal import Decimal
import unittest

from prism_core.domain import (
    Market, OrderIntent, OrderSide, OrderStatus, OrderType,
    validate_transition,
)


class PrismCoreDomainTest(unittest.TestCase):
    def test_us_order_requires_usd_and_keeps_decimal_price(self):
        order = OrderIntent(
            client_order_id="cycle-1:AAPL:BUY",
            market=Market.US,
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.5"),
            limit_price=Decimal("181.25"),
            currency="USD",
        )
        self.assertEqual(order.limit_price, Decimal("181.25"))

    def test_us_order_rejects_krw_currency(self):
        with self.assertRaisesRegex(ValueError, "US order currency must be USD"):
            OrderIntent(
                client_order_id="bad",
                market=Market.US,
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                limit_price=Decimal("180"),
                currency="KRW",
            )

    def test_kr_full_share_order_rejects_fractional_quantity(self):
        with self.assertRaisesRegex(ValueError, "KR quantity must be a whole number"):
            OrderIntent(
                client_order_id="bad-kr",
                market=Market.KR,
                symbol="005930",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1.5"),
                limit_price=Decimal("70000"),
                currency="KRW",
            )

    def test_unknown_can_only_move_to_reconciled_terminal_state(self):
        self.assertTrue(validate_transition(OrderStatus.UNKNOWN, OrderStatus.FILLED))
        self.assertTrue(validate_transition(OrderStatus.UNKNOWN, OrderStatus.REJECTED))
        self.assertFalse(validate_transition(OrderStatus.UNKNOWN, OrderStatus.SUBMITTED))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the domain test and confirm RED**

Run: `python3 -m unittest tests.test_prism_core_domain -v`

Expected: `ModuleNotFoundError: No module named 'prism_core'`.

- [ ] **Step 3: Implement the complete domain module**

```python
# prism_core/domain.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Market(str, Enum):
    KR = "KR"
    US = "US"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PREVIEWED = "PREVIEWED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"
    UNKNOWN = "UNKNOWN"


_TRANSITIONS = {
    OrderStatus.CREATED: {OrderStatus.PREVIEWED, OrderStatus.REJECTED},
    OrderStatus.PREVIEWED: {OrderStatus.SUBMITTED, OrderStatus.REJECTED},
    OrderStatus.SUBMITTED: {OrderStatus.ACCEPTED, OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.UNKNOWN},
    OrderStatus.ACCEPTED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.UNKNOWN},
    OrderStatus.PARTIALLY_FILLED: {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.UNKNOWN},
    OrderStatus.UNKNOWN: {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED},
    OrderStatus.FILLED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.CANCELED: set(),
}


def validate_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in _TRANSITIONS[current]


@dataclass(frozen=True)
class OrderIntent:
    client_order_id: str
    market: Market
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None
    currency: str
    strategy_id: str = "default_oneil"
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("client_order_id is required")
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        currency = self.currency.strip().upper()
        object.__setattr__(self, "currency", currency)
        if self.market is Market.KR:
            if currency != "KRW":
                raise ValueError("KR order currency must be KRW")
            if self.quantity != self.quantity.to_integral_value():
                raise ValueError("KR quantity must be a whole number")
        if self.market is Market.US and currency != "USD":
            raise ValueError("US order currency must be USD")
        if self.order_type is OrderType.LIMIT and (self.limit_price is None or self.limit_price <= 0):
            raise ValueError("limit order requires a positive limit_price")


@dataclass(frozen=True)
class OrderRecord:
    intent: OrderIntent
    status: OrderStatus
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Decimal | None = None


@dataclass(frozen=True)
class Fill:
    fill_id: str
    client_order_id: str
    market: Market
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    currency: str


@dataclass(frozen=True)
class Position:
    market: Market
    symbol: str
    quantity: Decimal
    average_price: Decimal
    currency: str
    high_since_entry: Decimal
    strategy_id: str
```

```python
# prism_core/__init__.py
from .domain import Fill, Market, OrderIntent, OrderRecord, OrderSide, OrderStatus, OrderType, Position

__all__ = ["Fill", "Market", "OrderIntent", "OrderRecord", "OrderSide", "OrderStatus", "OrderType", "Position"]
```

- [ ] **Step 4: Run the domain test and full baseline**

Run: `python3 -m unittest tests.test_prism_core_domain -v`

Expected: 4 tests pass.

Run: `python3 -m unittest discover -s tests -v`

Expected: existing 38 tests plus new domain tests pass.

- [ ] **Step 5: Commit the domain contract**

Commit intent: `시장과 통화를 추론하지 않는 주문 계약으로 실제 주문 오해를 막는다`

### Task 2: Additive SQLite order·fill·position ledger

**Files:**
- Create: `prism_core/ledger.py`
- Test: `tests/test_prism_core_ledger.py`

**Interfaces:**
- Consumes: Task 1 `OrderIntent`, `OrderStatus`, `Fill`, `Position`, `validate_transition()`
- Produces: `Ledger(path)`, `create_order()`, `transition_order()`, `record_fill()`, `get_order()`, `list_positions()`, `update_high_water()`, `count_realized_trades()`

- [ ] **Step 1: Write failing ledger transaction tests**

```python
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from prism_core.domain import Fill, Market, OrderIntent, OrderSide, OrderStatus, OrderType
from prism_core.ledger import Ledger


def buy_intent(order_id="run-1:AAPL:BUY"):
    return OrderIntent(order_id, Market.US, "AAPL", OrderSide.BUY, OrderType.LIMIT,
                       Decimal("2"), Decimal("180.25"), "USD")


class PrismCoreLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name) / "ledger.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_fill_creates_position_only_after_fill(self):
        intent = buy_intent()
        self.ledger.create_order(intent)
        self.ledger.transition_order(intent.client_order_id, OrderStatus.PREVIEWED)
        self.ledger.transition_order(intent.client_order_id, OrderStatus.SUBMITTED)
        self.assertEqual(self.ledger.list_positions(), [])

        self.ledger.record_fill(Fill("fill-1", intent.client_order_id, Market.US, "AAPL",
                                     OrderSide.BUY, Decimal("2"), Decimal("179.50"), "USD"))

        position = self.ledger.list_positions()[0]
        self.assertEqual(position.quantity, Decimal("2"))
        self.assertEqual(position.average_price, Decimal("179.50"))

    def test_duplicate_order_id_is_idempotent(self):
        intent = buy_intent()
        self.ledger.create_order(intent)
        self.ledger.create_order(intent)
        self.assertEqual(self.ledger.get_order(intent.client_order_id).status, OrderStatus.CREATED)

    def test_invalid_reverse_transition_is_rejected(self):
        intent = buy_intent()
        self.ledger.create_order(intent)
        self.ledger.transition_order(intent.client_order_id, OrderStatus.PREVIEWED)
        with self.assertRaisesRegex(ValueError, "invalid order transition"):
            self.ledger.transition_order(intent.client_order_id, OrderStatus.CREATED)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the ledger test and confirm RED**

Run: `python3 -m unittest tests.test_prism_core_ledger -v`

Expected: import failure for `prism_core.ledger`.

- [ ] **Step 3: Implement the ledger with one transaction per state change**

Implement the complete `prism_core/ledger.py`:

```python
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .domain import Fill, Market, OrderIntent, OrderRecord, OrderSide, OrderStatus, OrderType, Position, validate_transition


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
        finally:
            conn.close()

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> OrderRecord:
        intent = OrderIntent(
            client_order_id=row["client_order_id"], market=Market(row["market"]),
            symbol=row["symbol"], side=OrderSide(row["side"]),
            order_type=OrderType(row["order_type"]), quantity=Decimal(row["quantity"]),
            limit_price=Decimal(row["limit_price"]) if row["limit_price"] else None,
            currency=row["currency"], strategy_id=row["strategy_id"], reason=row["reason"],
        )
        return OrderRecord(
            intent=intent, status=OrderStatus(row["status"]),
            filled_quantity=Decimal(row["filled_quantity"]),
            average_fill_price=Decimal(row["average_fill_price"]) if row["average_fill_price"] else None,
        )

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        return Position(
            market=Market(row["market"]), symbol=row["symbol"],
            quantity=Decimal(row["quantity"]), average_price=Decimal(row["average_price"]),
            currency=row["currency"], high_since_entry=Decimal(row["high_since_entry"]),
            strategy_id=row["strategy_id"],
        )

    def create_order(self, intent: OrderIntent) -> OrderRecord:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO broker_orders "
                "(client_order_id,market,symbol,side,order_type,quantity,limit_price,currency,strategy_id,reason,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (intent.client_order_id, intent.market.value, intent.symbol, intent.side.value,
                 intent.order_type.value, str(intent.quantity),
                 str(intent.limit_price) if intent.limit_price is not None else None,
                 intent.currency, intent.strategy_id, intent.reason, OrderStatus.CREATED.value, now, now),
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
                "SELECT * FROM broker_orders WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
        if row is None:
            raise KeyError(client_order_id)
        return self._row_to_order(row)

    def transition_order(self, client_order_id: str, target: OrderStatus) -> OrderRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM broker_orders WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
            if row is None:
                raise KeyError(client_order_id)
            current = OrderStatus(row["status"])
            if current is target:
                return self.get_order(client_order_id)
            if not validate_transition(current, target):
                raise ValueError(f"invalid order transition: {current.value} -> {target.value}")
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
            rows = conn.execute("SELECT * FROM positions ORDER BY market,symbol").fetchall()
        return [self._row_to_position(row) for row in rows]

    def count_realized_trades(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM realized_trades").fetchone()[0])

    def update_high_water(self, market: Market, symbol: str, price: Decimal) -> Position:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE market=? AND symbol=?", (market.value, symbol)
            ).fetchone()
            if row is None:
                raise KeyError((market.value, symbol))
            high = max(Decimal(row["high_since_entry"]), price)
            conn.execute(
                "UPDATE positions SET high_since_entry=?,updated_at=? WHERE market=? AND symbol=?",
                (str(high), _now(), market.value, symbol),
            )
        return next(p for p in self.list_positions() if p.market is market and p.symbol == symbol)

    def record_fill(self, fill: Fill) -> Position | None:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            inserted = conn.execute(
                "INSERT OR IGNORE INTO fills (fill_id,client_order_id,market,symbol,side,quantity,price,currency,occurred_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (fill.fill_id, fill.client_order_id, fill.market.value, fill.symbol,
                 fill.side.value, str(fill.quantity), str(fill.price), fill.currency, _now()),
            )
            if not inserted.rowcount:
                conn.commit()
                positions = self.list_positions()
                return next((p for p in positions if p.market is fill.market and p.symbol == fill.symbol), None)
            order_row = conn.execute(
                "SELECT * FROM broker_orders WHERE client_order_id=?", (fill.client_order_id,)
            ).fetchone()
            if order_row is None:
                raise KeyError(fill.client_order_id)
            order = self._row_to_order(order_row)
            if (order.intent.market, order.intent.symbol, order.intent.side, order.intent.currency) != (
                fill.market, fill.symbol, fill.side, fill.currency
            ):
                raise ValueError("fill does not match order")
            cumulative = order.filled_quantity + fill.quantity
            if fill.quantity <= 0 or cumulative > order.intent.quantity:
                raise ValueError("fill quantity exceeds order quantity")
            position_row = conn.execute(
                "SELECT * FROM positions WHERE market=? AND symbol=?", (fill.market.value, fill.symbol)
            ).fetchone()
            now = _now()
            if fill.side is OrderSide.BUY:
                old_qty = Decimal(position_row["quantity"]) if position_row else Decimal("0")
                old_avg = Decimal(position_row["average_price"]) if position_row else Decimal("0")
                new_qty = old_qty + fill.quantity
                new_avg = ((old_qty * old_avg) + (fill.quantity * fill.price)) / new_qty
                old_high = Decimal(position_row["high_since_entry"]) if position_row else fill.price
                conn.execute(
                    "INSERT INTO positions (market,symbol,quantity,average_price,currency,high_since_entry,strategy_id,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(market,symbol) DO UPDATE SET "
                    "quantity=excluded.quantity,average_price=excluded.average_price,"
                    "high_since_entry=excluded.high_since_entry,strategy_id=excluded.strategy_id,updated_at=excluded.updated_at",
                    (fill.market.value, fill.symbol, str(new_qty), str(new_avg), fill.currency,
                     str(max(old_high, fill.price)), order.intent.strategy_id, now),
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
                    (fill.market.value, fill.symbol, str(fill.quantity), str(old_avg), str(fill.price),
                     str((fill.price - old_avg) * fill.quantity), fill.currency, position_row["strategy_id"], now),
                )
                if remaining == 0:
                    conn.execute("DELETE FROM positions WHERE market=? AND symbol=?", (fill.market.value, fill.symbol))
                else:
                    conn.execute(
                        "UPDATE positions SET quantity=?,updated_at=? WHERE market=? AND symbol=?",
                        (str(remaining), now, fill.market.value, fill.symbol),
                    )
            previous_cost = (order.average_fill_price or Decimal("0")) * order.filled_quantity
            average_fill = (previous_cost + fill.price * fill.quantity) / cumulative
            target = OrderStatus.FILLED if cumulative == order.intent.quantity else OrderStatus.PARTIALLY_FILLED
            if not validate_transition(order.status, target):
                raise ValueError(f"invalid order transition: {order.status.value} -> {target.value}")
            conn.execute(
                "UPDATE broker_orders SET status=?,filled_quantity=?,average_fill_price=?,updated_at=? WHERE client_order_id=?",
                (target.value, str(cumulative), str(average_fill), now, fill.client_order_id),
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
        return next((p for p in positions if p.market is fill.market and p.symbol == fill.symbol), None)
```

- [ ] **Step 4: Run ledger tests and verify persisted restart state**

Run: `python3 -m unittest tests.test_prism_core_ledger -v`

Expected: all ledger tests pass.

Add a restart assertion by constructing a second `Ledger` with the same path and verifying the AAPL position remains.

- [ ] **Step 5: Commit the ledger**

Commit intent: `체결 전에는 보유를 만들지 않는 원장으로 계좌 상태 왜곡을 막는다`

### Task 3: Local paper broker with preview, pending, fill, cancel, unknown

**Files:**
- Create: `prism_core/paper_broker.py`
- Test: `tests/test_prism_core_paper_broker.py`

**Interfaces:**
- Consumes: `Ledger`, `OrderIntent`, `OrderRecord`, `Fill`, `OrderStatus`
- Produces: `PaperBroker.preview_order()`, `submit_order()`, `fill_order()`, `cancel_order()`, `get_positions()`, `reconcile()`

- [ ] **Step 1: Write failing paper broker tests**

```python
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from prism_core.domain import Market, OrderIntent, OrderSide, OrderStatus, OrderType
from prism_core.ledger import Ledger
from prism_core.paper_broker import PaperBroker


class PaperBrokerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.broker = PaperBroker(Ledger(Path(self.tmp.name) / "paper.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def _order(self):
        return OrderIntent("cycle-1:005930:BUY", Market.KR, "005930", OrderSide.BUY,
                           OrderType.LIMIT, Decimal("3"), Decimal("70000"), "KRW")

    def test_submit_is_accepted_not_filled(self):
        record = self.broker.submit_order(self._order())
        self.assertEqual(record.status, OrderStatus.ACCEPTED)
        self.assertEqual(self.broker.get_positions(), [])

    def test_explicit_fill_creates_position(self):
        order = self._order()
        self.broker.submit_order(order)
        record = self.broker.fill_order(order.client_order_id, Decimal("3"), Decimal("69900"))
        self.assertEqual(record.status, OrderStatus.FILLED)
        self.assertEqual(self.broker.get_positions()[0].quantity, Decimal("3"))

    def test_duplicate_submit_does_not_create_second_order(self):
        first = self.broker.submit_order(self._order())
        second = self.broker.submit_order(self._order())
        self.assertEqual(first, second)

    def test_cancel_accepted_order(self):
        order = self._order()
        self.broker.submit_order(order)
        self.assertEqual(self.broker.cancel_order(order.client_order_id).status, OrderStatus.CANCELED)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run paper broker tests and confirm RED**

Run: `python3 -m unittest tests.test_prism_core_paper_broker -v`

Expected: import failure for `prism_core.paper_broker`.

- [ ] **Step 3: Implement the paper broker**

`PaperBroker.submit_order()` must call `create_order()`, then CREATED→PREVIEWED→SUBMITTED→ACCEPTED. If the order already exists it returns the persisted record without another transition. `fill_order()` creates a deterministic fill ID from client order ID plus current filled quantity, and `cancel_order()` only permits ACCEPTED or PARTIALLY_FILLED.

```python
from __future__ import annotations

from decimal import Decimal

from .domain import Fill, OrderIntent, OrderRecord, OrderStatus, Position
from .ledger import Ledger


class PaperBroker:
    name = "paper"
    mode = "paper"

    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def preview_order(self, intent: OrderIntent) -> OrderIntent:
        return intent

    def submit_order(self, intent: OrderIntent) -> OrderRecord:
        try:
            record = self.ledger.get_order(intent.client_order_id)
        except KeyError:
            record = self.ledger.create_order(intent)
        next_status = {
            OrderStatus.CREATED: OrderStatus.PREVIEWED,
            OrderStatus.PREVIEWED: OrderStatus.SUBMITTED,
            OrderStatus.SUBMITTED: OrderStatus.ACCEPTED,
        }
        while record.status in next_status:
            record = self.ledger.transition_order(intent.client_order_id, next_status[record.status])
        return record

    def fill_order(self, client_order_id: str, quantity: Decimal,
                   price: Decimal) -> OrderRecord:
        record = self.ledger.get_order(client_order_id)
        if record.status not in {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.UNKNOWN}:
            raise ValueError(f"order cannot be filled from {record.status.value}")
        new_cumulative = record.filled_quantity + quantity
        fill = Fill(
            fill_id=f"{client_order_id}:{new_cumulative}",
            client_order_id=client_order_id,
            market=record.intent.market,
            symbol=record.intent.symbol,
            side=record.intent.side,
            quantity=quantity,
            price=price,
            currency=record.intent.currency,
        )
        self.ledger.record_fill(fill)
        return self.ledger.get_order(client_order_id)

    def cancel_order(self, client_order_id: str) -> OrderRecord:
        record = self.ledger.get_order(client_order_id)
        if record.status not in {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError(f"order cannot be canceled from {record.status.value}")
        return self.ledger.transition_order(client_order_id, OrderStatus.CANCELED)

    def mark_unknown(self, client_order_id: str) -> OrderRecord:
        return self.ledger.transition_order(client_order_id, OrderStatus.UNKNOWN)

    def get_positions(self) -> list[Position]:
        return self.ledger.list_positions()

    def reconcile(self) -> list[Position]:
        return self.get_positions()
```

- [ ] **Step 4: Run broker tests and baseline**

Run: `python3 -m unittest tests.test_prism_core_paper_broker -v`

Expected: 4 tests pass.

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the paper broker**

Commit intent: `주문 접수와 체결을 분리해 수업과 운영에서 같은 상태를 보게 한다`

### Task 4: Exit-first restartable trading cycle

**Files:**
- Create: `prism_core/cycle.py`
- Test: `tests/test_prism_core_cycle.py`

**Interfaces:**
- Consumes: `PaperBroker`, `Position`, `OrderIntent`, quote mapping, exit policy
- Produces: `TradingCycle.run(run_id, entry_intents) -> CycleResult`

- [ ] **Step 1: Write the failing three-cycle restart E2E test**

```python
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from prism_core.cycle import TradingCycle
from prism_core.domain import Market, OrderIntent, OrderSide, OrderType
from prism_core.ledger import Ledger
from prism_core.paper_broker import PaperBroker


class TradingCycleTest(unittest.TestCase):
    def test_restart_entry_hold_exit_and_realized_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cycle.db"
            broker1 = PaperBroker(Ledger(path))
            entry = OrderIntent("run-1:AAPL:BUY", Market.US, "AAPL", OrderSide.BUY,
                                OrderType.LIMIT, Decimal("2"), Decimal("180"), "USD")
            cycle1 = TradingCycle(broker1, {(Market.US, "AAPL"): Decimal("180")})
            result1 = cycle1.run("run-1", [entry], auto_fill=True)
            self.assertEqual(result1.entry_orders[0].status.value, "FILLED")

            broker2 = PaperBroker(Ledger(path))
            cycle2 = TradingCycle(broker2, {(Market.US, "AAPL"): Decimal("195")})
            result2 = cycle2.run("run-2", [], auto_fill=True)
            self.assertEqual(result2.exit_orders, [])
            self.assertEqual(broker2.get_positions()[0].high_since_entry, Decimal("195"))

            broker3 = PaperBroker(Ledger(path))
            cycle3 = TradingCycle(broker3, {(Market.US, "AAPL"): Decimal("175")})
            result3 = cycle3.run("run-3", [], auto_fill=True)
            self.assertEqual(result3.exit_orders[0].intent.side, OrderSide.SELL)
            self.assertEqual(broker3.get_positions(), [])

    def test_exit_orders_are_processed_before_new_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = PaperBroker(Ledger(Path(tmp) / "ordering.db"))
            seed = OrderIntent("seed:AAPL:BUY", Market.US, "AAPL", OrderSide.BUY,
                               OrderType.LIMIT, Decimal("1"), Decimal("180"), "USD")
            broker.submit_order(seed)
            broker.fill_order(seed.client_order_id, Decimal("1"), Decimal("180"))
            new_entry = OrderIntent("run-2:MSFT:BUY", Market.US, "MSFT", OrderSide.BUY,
                                    OrderType.LIMIT, Decimal("1"), Decimal("300"), "USD")
            cycle = TradingCycle(
                broker,
                {(Market.US, "AAPL"): Decimal("160"), (Market.US, "MSFT"): Decimal("300")},
            )

            result = cycle.run("run-2", [new_entry], auto_fill=True)

            self.assertEqual(result.event_order, ["RECONCILE", "EXIT", "ENTRY"])
            self.assertEqual(result.exit_orders[0].intent.symbol, "AAPL")
            self.assertEqual(result.entry_orders[0].intent.symbol, "MSFT")
```

The second test seeds one filled position, supplies an exit-triggering quote and one new BUY intent, then asserts `CycleResult.event_order` starts with `RECONCILE`, `EXIT`, `ENTRY` in that order.

- [ ] **Step 2: Run the cycle E2E and confirm RED**

Run: `python3 -m unittest tests.test_prism_core_cycle -v`

Expected: import failure for `prism_core.cycle`.

- [ ] **Step 3: Implement the cycle**

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .domain import Market, OrderIntent, OrderRecord, OrderSide, OrderStatus, OrderType
from .paper_broker import PaperBroker


@dataclass(frozen=True)
class CycleResult:
    run_id: str
    exit_orders: list[OrderRecord]
    entry_orders: list[OrderRecord]
    event_order: list[str]


class TradingCycle:
    def __init__(self, broker: PaperBroker,
                 quotes: dict[tuple[Market, str], Decimal]):
        self.broker = broker
        self.quotes = quotes

    def run(self, run_id: str, entry_intents: list[OrderIntent],
            *, auto_fill: bool = False) -> CycleResult:
        event_order = ["RECONCILE"]
        exit_intents: list[OrderIntent] = []
        for position in self.broker.reconcile():
            key = (position.market, position.symbol)
            quote = self.quotes.get(key)
            if quote is None:
                continue
            position = self.broker.ledger.update_high_water(position.market, position.symbol, quote)
            stop_hit = quote <= position.average_price * Decimal("0.93")
            trail_armed = position.high_since_entry >= position.average_price * Decimal("1.05")
            trail_hit = quote <= position.high_since_entry * Decimal("0.92")
            if stop_hit or (trail_armed and trail_hit):
                exit_intents.append(OrderIntent(
                    client_order_id=f"{run_id}:{position.market.value}:{position.symbol}:SELL",
                    market=position.market,
                    symbol=position.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=position.quantity,
                    limit_price=quote,
                    currency=position.currency,
                    strategy_id=position.strategy_id,
                    reason="stop" if stop_hit else "trailing_stop",
                ))

        exit_orders: list[OrderRecord] = []
        if exit_intents:
            event_order.append("EXIT")
        for intent in exit_intents:
            record = self.broker.submit_order(intent)
            if auto_fill and record.status is not OrderStatus.FILLED:
                remaining = intent.quantity - record.filled_quantity
                record = self.broker.fill_order(
                    intent.client_order_id, remaining, self.quotes[(intent.market, intent.symbol)]
                )
            exit_orders.append(record)

        current_keys = {(p.market, p.symbol) for p in self.broker.reconcile()}
        eligible_entries = [
            intent for intent in entry_intents
            if (intent.market, intent.symbol) in self.quotes
            and (intent.market, intent.symbol) not in current_keys
        ]
        entry_orders: list[OrderRecord] = []
        if eligible_entries:
            event_order.append("ENTRY")
        for intent in eligible_entries:
            record = self.broker.submit_order(intent)
            if auto_fill and record.status is not OrderStatus.FILLED:
                remaining = intent.quantity - record.filled_quantity
                record = self.broker.fill_order(
                    intent.client_order_id, remaining, self.quotes[(intent.market, intent.symbol)]
                )
            entry_orders.append(record)

        return CycleResult(
            run_id=run_id,
            exit_orders=exit_orders,
            entry_orders=entry_orders,
            event_order=event_order,
        )
```

Exit client IDs are deterministic: `f"{run_id}:{market.value}:{symbol}:SELL"`. Entry IDs come from the supplied intent. Missing quote blocks that symbol without using a default price. A SELL quantity always equals the reconciled position quantity.

- [ ] **Step 4: Run the restart E2E and full suite**

Run: `python3 -m unittest tests.test_prism_core_cycle -v`

Expected: restart and ordering tests pass.

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests pass with no network access.

- [ ] **Step 5: Commit the cycle**

Commit intent: `재시작과 청산 우선 순서를 고정해 신규 매수만 반복하는 파이프라인을 끝낸다`

### Task 5: Classroom profile and existing pipeline compatibility

**Files:**
- Create: `prism_core/classroom.py`
- Modify: `runtime_config.py`
- Modify: `main.py`
- Modify: `db.py`
- Test: `tests/test_classroom_profile.py`
- Modify: `tests/test_main_runtime_options.py`

**Interfaces:**
- Consumes: `TradingCycle`, `PaperBroker`, `Ledger`
- Produces: `run_classroom_replay(db_path: Path) -> dict`, `LECTURE_PROFILE=classroom`, existing `main.run_pipeline()` compatibility

- [ ] **Step 1: Write failing classroom profile tests**

```python
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from prism_core.classroom import run_classroom_replay
from runtime_config import load_runtime_config


class ClassroomProfileTest(unittest.TestCase):
    def test_classroom_replay_finishes_entry_hold_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_classroom_replay(Path(tmp) / "classroom.db")
        self.assertEqual(result["cycles"], 3)
        self.assertEqual(result["final_positions"], 0)
        self.assertEqual(result["realized_trades"], 2)
        self.assertEqual(result["markets"], ["KR", "US"])

    def test_classroom_runtime_never_selects_live_broker(self):
        with mock.patch.dict("os.environ", {"LECTURE_PROFILE": "classroom"}, clear=False):
            cfg = load_runtime_config()
        self.assertEqual(cfg.profile, "classroom")
        self.assertEqual(cfg.trade_mode, "simulation")
        self.assertEqual(cfg.data_mode, "mock")
```

- [ ] **Step 2: Run the classroom tests and confirm RED**

Run: `python3 -m unittest tests.test_classroom_profile -v`

Expected: missing module/profile failure.

- [ ] **Step 3: Implement deterministic KR/US replay**

Implement `prism_core/classroom.py` so it creates one KR and one US BUY in cycle 1, updates both high-water marks in cycle 2, and triggers trailing exits in cycle 3. It uses the supplied DB path, returns only secret-free counts, and performs no network or environment lookup.

```python
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .cycle import TradingCycle
from .domain import Market, OrderIntent, OrderSide, OrderType
from .ledger import Ledger
from .paper_broker import PaperBroker


def run_classroom_replay(db_path: Path) -> dict:
    ledger = Ledger(db_path)
    broker = PaperBroker(ledger)
    session = uuid4().hex[:12]
    realized_before = ledger.count_realized_trades()
    entries = [
        OrderIntent(f"{session}-1:KR:005930:BUY", Market.KR, "005930", OrderSide.BUY,
                    OrderType.LIMIT, Decimal("1"), Decimal("70000"), "KRW"),
        OrderIntent(f"{session}-1:US:AAPL:BUY", Market.US, "AAPL", OrderSide.BUY,
                    OrderType.LIMIT, Decimal("1"), Decimal("180"), "USD"),
    ]
    TradingCycle(
        broker,
        {(Market.KR, "005930"): Decimal("70000"), (Market.US, "AAPL"): Decimal("180")},
    ).run(f"{session}-1", entries, auto_fill=True)
    TradingCycle(
        PaperBroker(Ledger(db_path)),
        {(Market.KR, "005930"): Decimal("76000"), (Market.US, "AAPL"): Decimal("195")},
    ).run(f"{session}-2", [], auto_fill=True)
    final_broker = PaperBroker(Ledger(db_path))
    TradingCycle(
        final_broker,
        {(Market.KR, "005930"): Decimal("69000"), (Market.US, "AAPL"): Decimal("175")},
    ).run(f"{session}-3", [], auto_fill=True)
    return {
        "cycles": 3,
        "final_positions": len(final_broker.get_positions()),
        "realized_trades": final_broker.ledger.count_realized_trades() - realized_before,
        "markets": [Market.KR.value, Market.US.value],
    }
```

Add these profile defaults:

```python
"classroom": {
    "data_mode": "mock",
    "screening_mode": "mock",
    "llm_mode": "mock",
    "report_mode": "lite",
    "research_tools": "",
    "trade_mode": "simulation",
},
"backtest": {
    "data_mode": "mock",
    "screening_mode": "mock",
    "llm_mode": "mock",
    "report_mode": "lite",
    "research_tools": "",
    "trade_mode": "simulation",
},
```

Add aliases `"class": "classroom"`, `"replay": "classroom"`, and `"walk_forward": "backtest"` to `_PROFILE_ALIASES`.

At the start of `main.run_pipeline()` after `cfg = load_runtime_config()`, add:

```python
    if cfg.profile == "classroom":
        from db import DB_PATH
        from prism_core.classroom import run_classroom_replay

        summary = await asyncio.to_thread(run_classroom_replay, DB_PATH)
        log.info("classroom replay 완료: %s", summary)
        return summary
```

At the end of `db.init_db()`, outside the legacy `_connect()` block, initialize the additive ledger:

```python
    from prism_core.ledger import Ledger

    Ledger(DB_PATH)
```

In `main.run_pipeline()`, branch only when `cfg.profile == "classroom"`: call the replay using the normal `db.DB_PATH`, log the three-cycle summary, and return it. All existing mock behavior remains unchanged.

In `db.init_db()`, instantiate `Ledger(DB_PATH)` after the legacy schema migration so `db.py` remains the one public schema initializer.

- [ ] **Step 4: Verify classroom and legacy demo paths**

Run: `LECTURE_PROFILE=classroom python3 main.py`

Expected: KR/US three-cycle replay completes with zero final positions and two realized trades.

Run: `python3 main.py`

Expected: existing keyless 4-stage demo still completes.

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 5: Commit classroom integration**

Commit intent: `휴장일에도 실제 상태 전이를 재현해 강의 결과가 시장 시간에 좌우되지 않게 한다`

### Task 6: Foundation verification and documentation contract

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/runtime-profiles.md`
- Modify: `lecture/exercises/part3_실습가이드.md`
- Test: `tests/test_prism_core_foundation_contract.py`

**Interfaces:**
- Consumes: Tasks 1–5 public interfaces
- Produces: architecture/course documentation that describes actual connected paths only

- [ ] **Step 1: Add a failing documentation contract test**

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PrismCoreFoundationContractTest(unittest.TestCase):
    def test_runtime_docs_distinguish_classroom_paper_and_live(self):
        text = (ROOT / "docs/runtime-profiles.md").read_text(encoding="utf-8")
        for phrase in ("classroom", "청산", "미체결", "paper/live에서는 mock"):
            self.assertIn(phrase, text)

    def test_part3_uses_agent_prompt_not_required_terminal_commands(self):
        text = (ROOT / "lecture/exercises/part3_실습가이드.md").read_text(encoding="utf-8")
        self.assertIn("classroom 전체 사이클", text)
        self.assertIn("미체결 → 체결 → 청산", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the contract test and confirm RED**

Run: `python3 -m unittest tests.test_prism_core_foundation_contract -v`

Expected: missing classroom wording failures.

- [ ] **Step 3: Update docs to match implemented reality**

Document:

- mock installation path versus classroom state replay
- order acceptance versus fill
- restart persistence and exit-first ordering
- KR/US currency safety
- paper/live data fail-closed target remains pending until market-provider slice
- coding-agent prompts for running classroom replay and explaining the dashboard evidence

Do not claim KIS or Toss completion in this foundation slice.

- [ ] **Step 4: Run all foundation evidence**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests pass.

Run: `python3 main.py`

Expected: legacy keyless demo completes.

Run: `LECTURE_PROFILE=classroom python3 main.py`

Expected: classroom replay completes.

Run: `python3 trading.py --live`

Expected: `live_blocked` and no broker mutation.

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m compileall main.py db.py runtime_config.py prism_core`

Expected: compilation succeeds.

Run: `git status --short` and `git diff --cached --name-only`

Expected: no DB, reports, tokens, local Toss session, or secret files staged.

- [ ] **Step 5: Commit the verified foundation**

Commit intent: `실행 증거와 강의 설명을 상태형 paper 코어의 실제 동작에 맞춘다`

---

## Follow-on Plans

After this plan passes, create and execute these separate plans in order:

1. `2026-07-19-market-regime-screening.md`
2. `2026-07-19-evidence-oauth.md`
3. `2026-07-19-kis-operations-course.md`
4. `2026-07-19-toss-wts-adapter.md`

Each follow-on plan must preserve the domain, ledger, and cycle interfaces defined here unless a failing compatibility test proves a change is necessary.
