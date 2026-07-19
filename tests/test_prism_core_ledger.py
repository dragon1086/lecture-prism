from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from prism_core.domain import (
    Fill,
    Market,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionFillConflict,
)
from prism_core.ledger import Ledger


def buy_intent(
    order_id="run-1:AAPL:BUY",
    quantity=Decimal("2"),
    price=Decimal("180.25"),
):
    return OrderIntent(
        order_id,
        Market.US,
        "AAPL",
        OrderSide.BUY,
        OrderType.LIMIT,
        quantity,
        price,
        "USD",
    )


def sell_intent(order_id="run-1:AAPL:SELL", quantity=Decimal("2")):
    return OrderIntent(
        order_id,
        Market.US,
        "AAPL",
        OrderSide.SELL,
        OrderType.MARKET,
        quantity,
        None,
        "USD",
    )


def kr_buy_intent(order_id="run-1:005930:BUY"):
    return OrderIntent(
        order_id,
        Market.KR,
        "005930",
        OrderSide.BUY,
        OrderType.LIMIT,
        Decimal("2"),
        Decimal("70000"),
        "KRW",
    )


class _CursorAfterFetch:
    def __init__(self, cursor, ready, release):
        self._cursor = cursor
        self._ready = ready
        self._release = release

    def fetchone(self):
        row = self._cursor.fetchone()
        self._cursor.fetchall()
        self._ready.set()
        if not self._release.wait(2):
            raise TimeoutError("concurrency test did not release stale read")
        return row

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _InterleavingConnection:
    def __init__(self, connection, select_prefix, ready, release):
        self._connection = connection
        self._select_prefix = select_prefix
        self._ready = ready
        self._release = release

    def execute(self, sql, parameters=()):
        normalized = " ".join(sql.upper().split())
        if normalized == "BEGIN IMMEDIATE":
            self._ready.set()
        cursor = self._connection.execute(sql, parameters)
        if normalized.startswith(self._select_prefix):
            return _CursorAfterFetch(cursor, self._ready, self._release)
        return cursor

    @property
    def row_factory(self):
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._connection.row_factory = value

    def __getattr__(self, name):
        return getattr(self._connection, name)


class PrismCoreLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.db"
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def _advance(self, intent, accepted=False):
        self.ledger.create_order(intent)
        self.ledger.transition_order(intent.client_order_id, OrderStatus.PREVIEWED)
        self.ledger.transition_order(intent.client_order_id, OrderStatus.SUBMITTED)
        if accepted:
            self.ledger.transition_order(intent.client_order_id, OrderStatus.ACCEPTED)

    def _fill(self, fill_id, intent, quantity, price, **overrides):
        values = {
            "client_order_id": intent.client_order_id,
            "market": intent.market,
            "symbol": intent.symbol,
            "side": intent.side,
            "quantity": quantity,
            "price": price,
            "currency": intent.currency,
        }
        values.update(overrides)
        return Fill(fill_id=fill_id, **values)

    def _table_count(self, table):
        with sqlite3.connect(self.path) as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def _open_position(self, quantity=Decimal("5"), price=Decimal("100.00")):
        intent = buy_intent("seed:AAPL:BUY", quantity, price)
        self._advance(intent)
        self.ledger.record_fill(self._fill("seed-fill", intent, quantity, price))
        return intent

    def test_fill_creates_position_only_after_fill_and_survives_restart(self):
        intent = buy_intent()
        self._advance(intent)
        self.assertEqual(self.ledger.list_positions(), [])

        self.ledger.record_fill(
            self._fill("fill-1", intent, Decimal("2"), Decimal("179.50"))
        )

        position = self.ledger.list_positions()[0]
        self.assertEqual(position.quantity, Decimal("2"))
        self.assertEqual(position.average_price, Decimal("179.50"))
        self.assertEqual(Ledger(self.path).list_positions(), [position])

    def test_three_nonterminal_buy_fills_then_full_fill_update_aggregate(self):
        intent = buy_intent(quantity=Decimal("4"))
        self._advance(intent, accepted=True)

        for index, price in enumerate(
            (
                Decimal("179.10"),
                Decimal("179.20"),
                Decimal("179.30"),
                Decimal("179.40"),
            ),
            start=1,
        ):
            self.ledger.record_fill(
                self._fill(f"buy-fill-{index}", intent, Decimal("1"), price)
            )
            if index <= 3:
                self.assertEqual(
                    self.ledger.get_order(intent.client_order_id).status,
                    OrderStatus.PARTIALLY_FILLED,
                )

        order = self.ledger.get_order(intent.client_order_id)
        position = self.ledger.list_positions()[0]
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.filled_quantity, Decimal("4"))
        self.assertEqual(order.average_fill_price, Decimal("179.25"))
        self.assertEqual(position.quantity, Decimal("4"))
        self.assertEqual(position.average_price, Decimal("179.25"))
        self.assertEqual(Ledger(self.path).list_positions(), [position])

    def test_three_nonterminal_sell_fills_then_full_fill_realize_each_fill(self):
        self._open_position(quantity=Decimal("6"))
        intent = sell_intent(quantity=Decimal("4"))
        self._advance(intent, accepted=True)

        for index, price in enumerate(
            (
                Decimal("110.00"),
                Decimal("112.00"),
                Decimal("114.00"),
                Decimal("116.00"),
            ),
            start=1,
        ):
            self.ledger.record_fill(
                self._fill(f"sell-fill-{index}", intent, Decimal("1"), price)
            )
            if index <= 3:
                self.assertEqual(
                    self.ledger.get_order(intent.client_order_id).status,
                    OrderStatus.PARTIALLY_FILLED,
                )

        order = self.ledger.get_order(intent.client_order_id)
        position = self.ledger.list_positions()[0]
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.average_fill_price, Decimal("113.00"))
        self.assertEqual(position.quantity, Decimal("2"))
        self.assertEqual(position.average_price, Decimal("100.00"))
        self.assertEqual(self.ledger.count_realized_trades(), 4)
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT quantity,entry_price,exit_price,pnl_amount "
                "FROM realized_trades ORDER BY id"
            ).fetchall()
        self.assertEqual(
            [[Decimal(value) for value in row] for row in rows],
            [
                [Decimal("1"), Decimal("100.00"), Decimal("110.00"), Decimal("10.00")],
                [Decimal("1"), Decimal("100.00"), Decimal("112.00"), Decimal("12.00")],
                [Decimal("1"), Decimal("100.00"), Decimal("114.00"), Decimal("14.00")],
                [Decimal("1"), Decimal("100.00"), Decimal("116.00"), Decimal("16.00")],
            ],
        )

    def test_full_sell_removes_position_and_records_realized_trade(self):
        self._open_position(quantity=Decimal("2"))
        intent = sell_intent(quantity=Decimal("2"))
        self._advance(intent)

        result = self.ledger.record_fill(
            self._fill("full-sell", intent, Decimal("2"), Decimal("110.00"))
        )

        self.assertIsNone(result)
        self.assertEqual(self.ledger.list_positions(), [])
        self.assertEqual(self.ledger.count_realized_trades(), 1)

    def test_foreign_strategy_sell_fill_rolls_back_all_mutation(self):
        self._open_position(quantity=Decimal("2"))
        intent = OrderIntent(
            "foreign:AAPL:SELL",
            Market.US,
            "AAPL",
            OrderSide.SELL,
            OrderType.MARKET,
            Decimal("2"),
            None,
            "USD",
            strategy_id="foreign_strategy",
        )
        self._advance(intent, accepted=True)

        with self.assertRaisesRegex(PositionFillConflict, "strategy"):
            self.ledger.record_fill(
                self._fill(
                    "foreign-sell-fill",
                    intent,
                    Decimal("2"),
                    Decimal("110.00"),
                )
            )

        order = self.ledger.get_order(intent.client_order_id)
        position = self.ledger.list_positions()[0]
        self.assertEqual(order.status, OrderStatus.ACCEPTED)
        self.assertEqual(order.filled_quantity, Decimal("0"))
        self.assertEqual(position.quantity, Decimal("2"))
        self.assertEqual(position.strategy_id, "default_oneil")
        self.assertEqual(self._table_count("fills"), 1)
        self.assertEqual(self.ledger.count_realized_trades(), 0)

    def test_sell_trade_records_closing_order_and_fill_provenance(self):
        self._open_position(quantity=Decimal("2"))
        intent = sell_intent(quantity=Decimal("2"))
        self._advance(intent, accepted=True)
        fill = self._fill(
            "owned-sell-fill",
            intent,
            Decimal("2"),
            Decimal("110.00"),
        )

        self.ledger.record_fill(fill)

        with sqlite3.connect(self.path) as conn:
            provenance = conn.execute(
                "SELECT exit_client_order_id,exit_fill_id "
                "FROM realized_trades"
            ).fetchone()
        self.assertEqual(
            provenance,
            (intent.client_order_id, fill.fill_id),
        )

    def test_sell_exceeding_position_rolls_back_fill_order_and_realized_trade(self):
        self._open_position(quantity=Decimal("2"))
        intent = sell_intent(quantity=Decimal("3"))
        self._advance(intent)

        with self.assertRaisesRegex(
            PositionFillConflict, "sell quantity exceeds position"
        ):
            self.ledger.record_fill(
                self._fill("oversell", intent, Decimal("3"), Decimal("110.00"))
            )

        order = self.ledger.get_order(intent.client_order_id)
        self.assertEqual(order.status, OrderStatus.SUBMITTED)
        self.assertEqual(order.filled_quantity, Decimal("0"))
        self.assertEqual(self.ledger.list_positions()[0].quantity, Decimal("2"))
        self.assertEqual(self._table_count("fills"), 1)
        self.assertEqual(self.ledger.count_realized_trades(), 0)

    def test_duplicate_order_id_requires_same_normalized_payload(self):
        intent = buy_intent()
        self.ledger.create_order(intent)
        normalized_retry = buy_intent(quantity=Decimal("2.0"), price=Decimal("180.250"))

        self.ledger.create_order(normalized_retry)

        self.assertEqual(self._table_count("broker_orders"), 1)
        self.assertEqual(self._table_count("order_events"), 1)

    def test_conflicting_order_id_is_rejected_without_changing_original(self):
        intent = buy_intent()
        original = self.ledger.create_order(intent)
        collisions = {
            "market and currency": OrderIntent(
                intent.client_order_id,
                Market.KR,
                "005930",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("2"),
                Decimal("180.25"),
                "KRW",
            ),
            "symbol": OrderIntent(
                intent.client_order_id,
                Market.US,
                "MSFT",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("2"),
                Decimal("180.25"),
                "USD",
            ),
            "side": sell_intent(intent.client_order_id),
            "order type and limit": OrderIntent(
                intent.client_order_id,
                Market.US,
                "AAPL",
                OrderSide.BUY,
                OrderType.MARKET,
                Decimal("2"),
                None,
                "USD",
            ),
            "quantity": buy_intent(quantity=Decimal("3")),
            "limit price": buy_intent(price=Decimal("181.25")),
            "strategy": OrderIntent(
                intent.client_order_id,
                Market.US,
                "AAPL",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("2"),
                Decimal("180.25"),
                "USD",
                strategy_id="other",
            ),
            "reason": OrderIntent(
                intent.client_order_id,
                Market.US,
                "AAPL",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("2"),
                Decimal("180.25"),
                "USD",
                reason="different",
            ),
        }

        for label, collision in collisions.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "order id collision"):
                    self.ledger.create_order(collision)

        self.assertEqual(self.ledger.get_order(intent.client_order_id), original)
        self.assertEqual(self._table_count("broker_orders"), 1)
        self.assertEqual(self._table_count("order_events"), 1)

    def test_duplicate_fill_is_idempotent_only_for_same_normalized_payload(self):
        intent = buy_intent(quantity=Decimal("3"))
        self._advance(intent, accepted=True)
        fill = self._fill(
            "fill-1", intent, Decimal("1.0"), Decimal("179.500"), currency="usd"
        )

        first = self.ledger.record_fill(fill)
        replay = self.ledger.record_fill(
            self._fill("fill-1", intent, Decimal("1.00"), Decimal("179.50"))
        )

        self.assertEqual(replay, first)
        self.assertEqual(self._table_count("fills"), 1)
        self.assertEqual(self.ledger.list_positions()[0].quantity, Decimal("1.0"))
        self.assertEqual(self.ledger.get_order(intent.client_order_id).filled_quantity, Decimal("1.0"))

    def test_conflicting_fill_id_is_rejected_without_changing_state(self):
        intent = buy_intent(quantity=Decimal("3"))
        self._advance(intent, accepted=True)
        self.ledger.record_fill(
            self._fill("fill-1", intent, Decimal("1"), Decimal("179.50"))
        )
        before_order = self.ledger.get_order(intent.client_order_id)
        before_position = self.ledger.list_positions()[0]

        collisions = {
            "order id": {"client_order_id": "another-order"},
            "market and currency": {
                "market": Market.KR,
                "currency": "KRW",
                "price": Decimal("180"),
            },
            "symbol": {"symbol": "MSFT"},
            "side": {"side": OrderSide.SELL},
            "quantity": {"quantity": Decimal("1.5")},
            "price": {"price": Decimal("180.50")},
        }
        for label, changes in collisions.items():
            with self.subTest(label=label):
                quantity = changes.get("quantity", Decimal("1"))
                price = changes.get("price", Decimal("179.50"))
                identity_changes = {
                    key: value
                    for key, value in changes.items()
                    if key not in {"quantity", "price"}
                }
                with self.assertRaisesRegex(ValueError, "fill id collision"):
                    self.ledger.record_fill(
                        self._fill(
                            "fill-1",
                            intent,
                            quantity,
                            price,
                            **identity_changes,
                        )
                    )

        self.assertEqual(self.ledger.get_order(intent.client_order_id), before_order)
        self.assertEqual(self.ledger.list_positions(), [before_position])
        self.assertEqual(self._table_count("fills"), 1)

    def test_mismatched_fill_rolls_back_insert_and_all_aggregates(self):
        intent = buy_intent()
        self._advance(intent)

        with self.assertRaisesRegex(ValueError, "fill does not match order"):
            self.ledger.record_fill(
                self._fill("bad-fill", intent, Decimal("2"), Decimal("179.50"), symbol="MSFT")
            )

        order = self.ledger.get_order(intent.client_order_id)
        self.assertEqual(order.status, OrderStatus.SUBMITTED)
        self.assertEqual(order.filled_quantity, Decimal("0"))
        self.assertEqual(self.ledger.list_positions(), [])
        self.assertEqual(self._table_count("fills"), 0)
        self.assertEqual(self.ledger.count_realized_trades(), 0)

    def test_fill_boundary_rejects_malformed_values_without_writes(self):
        intent = buy_intent()
        self._advance(intent)
        valid = {
            "fill_id": "fill-1",
            "client_order_id": intent.client_order_id,
            "market": Market.US,
            "symbol": "AAPL",
            "side": OrderSide.BUY,
            "quantity": Decimal("2"),
            "price": Decimal("179.50"),
            "currency": "USD",
        }
        invalid = {
            "empty fill id": {"fill_id": " "},
            "empty order id": {"client_order_id": ""},
            "empty symbol": {"symbol": " "},
            "market enum": {"market": "US"},
            "side enum": {"side": "BUY"},
            "quantity type": {"quantity": 2},
            "zero quantity": {"quantity": Decimal("0")},
            "nan quantity": {"quantity": Decimal("NaN")},
            "price type": {"price": 179.5},
            "negative price": {"price": Decimal("-1")},
            "infinite price": {"price": Decimal("Infinity")},
            "market currency": {"currency": "KRW"},
        }

        for label, changes in invalid.items():
            with self.subTest(label=label):
                values = {**valid, **changes}
                with self.assertRaises(ValueError):
                    self.ledger.record_fill(Fill(**values))
                self.assertEqual(self._table_count("fills"), 0)
                self.assertEqual(self.ledger.list_positions(), [])
                self.assertEqual(
                    self.ledger.get_order(intent.client_order_id).status,
                    OrderStatus.SUBMITTED,
                )

    def test_kr_fill_rejects_fractional_quantity_without_writes(self):
        intent = kr_buy_intent()
        self._advance(intent, accepted=True)
        before_order = self.ledger.get_order(intent.client_order_id)

        with self.assertRaisesRegex(
            ValueError, "KR fill quantity must be a whole number"
        ):
            self.ledger.record_fill(
                self._fill(
                    "fractional-kr-quantity",
                    intent,
                    Decimal("0.5"),
                    Decimal("69999"),
                )
            )

        self.assertEqual(self._table_count("fills"), 0)
        self.assertEqual(
            self.ledger.get_order(intent.client_order_id), before_order
        )
        self.assertEqual(self.ledger.list_positions(), [])
        self.assertEqual(self.ledger.count_realized_trades(), 0)

    def test_kr_fill_rejects_fractional_price_without_writes(self):
        intent = kr_buy_intent()
        self._advance(intent, accepted=True)
        before_order = self.ledger.get_order(intent.client_order_id)

        with self.assertRaisesRegex(
            ValueError, "KR fill price must be a whole number"
        ):
            self.ledger.record_fill(
                self._fill(
                    "fractional-kr-price",
                    intent,
                    Decimal("2"),
                    Decimal("69999.5"),
                )
            )

        self.assertEqual(self._table_count("fills"), 0)
        self.assertEqual(
            self.ledger.get_order(intent.client_order_id), before_order
        )
        self.assertEqual(self.ledger.list_positions(), [])
        self.assertEqual(self.ledger.count_realized_trades(), 0)

    def test_decimal_columns_are_text_and_round_trip_exactly(self):
        intent = buy_intent(
            quantity=Decimal("1.2500"), price=Decimal("180.2500")
        )
        self._advance(intent)
        self.ledger.record_fill(
            self._fill(
                "fractional-fill",
                intent,
                Decimal("1.2500"),
                Decimal("179.1250"),
            )
        )

        restarted = Ledger(self.path)
        order = restarted.get_order(intent.client_order_id)
        position = restarted.list_positions()[0]
        self.assertEqual(order.intent.quantity, Decimal("1.2500"))
        self.assertEqual(order.intent.limit_price, Decimal("180.2500"))
        self.assertEqual(order.filled_quantity, Decimal("1.2500"))
        self.assertEqual(order.average_fill_price, Decimal("179.1250"))
        self.assertEqual(position.quantity, Decimal("1.2500"))
        self.assertEqual(position.average_price, Decimal("179.1250"))
        with sqlite3.connect(self.path) as conn:
            order_types = conn.execute(
                "SELECT typeof(quantity),typeof(limit_price),typeof(filled_quantity),"
                "typeof(average_fill_price) FROM broker_orders"
            ).fetchone()
            fill_types = conn.execute(
                "SELECT typeof(quantity),typeof(price) FROM fills"
            ).fetchone()
            position_types = conn.execute(
                "SELECT typeof(quantity),typeof(average_price),typeof(high_since_entry) "
                "FROM positions"
            ).fetchone()
        self.assertEqual(order_types, ("text", "text", "text", "text"))
        self.assertEqual(fill_types, ("text", "text"))
        self.assertEqual(position_types, ("text", "text", "text"))

    def test_schema_reinitialization_preserves_legacy_rows(self):
        legacy_path = Path(self.tmp.name) / "legacy.db"
        with sqlite3.connect(legacy_path) as conn:
            conn.execute("CREATE TABLE trade_history (id INTEGER PRIMARY KEY, note TEXT)")
            conn.execute("INSERT INTO trade_history (note) VALUES ('keep me')")

        Ledger(legacy_path)
        Ledger(legacy_path)

        with sqlite3.connect(legacy_path) as conn:
            self.assertEqual(
                conn.execute("SELECT note FROM trade_history").fetchall(),
                [("keep me",)],
            )
            self.assertEqual(
                conn.execute(
                    "SELECT value FROM prism_core_meta WHERE key='schema_version'"
                ).fetchone(),
                ("1",),
            )

    def test_order_events_record_first_status_observation_and_fills_audit_each_execution(self):
        intent = buy_intent(quantity=Decimal("3"))
        self._advance(intent, accepted=True)
        for index in range(3):
            self.ledger.record_fill(
                self._fill(
                    f"fill-{index}", intent, Decimal("1"), Decimal("179.50")
                )
            )

        with sqlite3.connect(self.path) as conn:
            partial_events = conn.execute(
                "SELECT COUNT(*) FROM order_events "
                "WHERE client_order_id=? AND status=?",
                (intent.client_order_id, OrderStatus.PARTIALLY_FILLED.value),
            ).fetchone()[0]
            fills = conn.execute(
                "SELECT COUNT(*) FROM fills WHERE client_order_id=?",
                (intent.client_order_id,),
            ).fetchone()[0]
        self.assertEqual(partial_events, 1)
        self.assertEqual(fills, 3)

    def test_invalid_reverse_transition_is_rejected(self):
        intent = buy_intent()
        self.ledger.create_order(intent)
        self.ledger.transition_order(intent.client_order_id, OrderStatus.PREVIEWED)
        with self.assertRaisesRegex(ValueError, "invalid order transition"):
            self.ledger.transition_order(intent.client_order_id, OrderStatus.CREATED)

    def test_terminal_fill_cannot_be_overwritten_by_stale_cancel(self):
        intent = buy_intent()
        self._advance(intent, accepted=True)
        writer = sqlite3.connect(self.path)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "UPDATE broker_orders SET status=? WHERE client_order_id=?",
            (OrderStatus.FILLED.value, intent.client_order_id),
        )

        result = self._run_interleaved_writer(
            writer,
            "SELECT * FROM BROKER_ORDERS",
            lambda: self.ledger.transition_order(
                intent.client_order_id, OrderStatus.CANCELED
            ),
        )

        self.assertIsInstance(result.get("error"), ValueError)
        self.assertRegex(str(result["error"]), "invalid order transition")
        self.assertEqual(
            self.ledger.get_order(intent.client_order_id).status,
            OrderStatus.FILLED,
        )

    def test_high_water_update_is_monotonic_across_two_connections(self):
        self._open_position(price=Decimal("100.00"))
        writer = sqlite3.connect(self.path)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "UPDATE positions SET high_since_entry='120.00' "
            "WHERE market='US' AND symbol='AAPL'"
        )

        result = self._run_interleaved_writer(
            writer,
            "SELECT * FROM POSITIONS",
            lambda: self.ledger.update_high_water(
                Market.US, "AAPL", Decimal("110.00")
            ),
        )

        self.assertNotIn("error", result)
        self.assertEqual(result["value"].high_since_entry, Decimal("120.00"))
        self.assertEqual(
            self.ledger.list_positions()[0].high_since_entry, Decimal("120.00")
        )

    def test_high_water_never_moves_lower(self):
        self._open_position(price=Decimal("100.00"))
        raised = self.ledger.update_high_water(
            Market.US, "AAPL", Decimal("120.00")
        )
        lowered = self.ledger.update_high_water(
            Market.US, "AAPL", Decimal("110.00")
        )
        self.assertEqual(raised.high_since_entry, Decimal("120.00"))
        self.assertEqual(lowered.high_since_entry, Decimal("120.00"))

    def test_unresolved_order_query_includes_unknown_and_excludes_terminal(self):
        intent = buy_intent("unresolved:AAPL:BUY")
        self._advance(intent, accepted=True)

        self.assertTrue(self.ledger.has_unresolved_order(Market.US, "AAPL"))
        self.ledger.transition_order(
            intent.client_order_id, OrderStatus.UNKNOWN
        )
        self.assertTrue(self.ledger.has_unresolved_order(Market.US, "AAPL"))
        self.ledger.transition_order(
            intent.client_order_id, OrderStatus.CANCELED
        )
        self.assertFalse(self.ledger.has_unresolved_order(Market.US, "AAPL"))

    def test_concurrent_entry_admission_creates_only_one_symbol_order(self):
        intents = (
            buy_intent("concurrent-1:AAPL:BUY"),
            buy_intent("concurrent-2:AAPL:BUY"),
        )
        ready = threading.Barrier(2)
        results = []
        errors = []

        def admit(intent):
            try:
                ready.wait(2)
                results.append(
                    Ledger(self.path).create_order_if_admissible(intent)
                )
            except Exception as exc:
                errors.append(exc)

        workers = [
            threading.Thread(target=admit, args=(intent,))
            for intent in intents
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)

        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self._table_count("broker_orders"), 1)

    def _run_interleaved_writer(self, writer, select_prefix, operation):
        ready = threading.Event()
        release = threading.Event()
        result = {}
        real_connect = sqlite3.connect

        def connect(path, *args, **kwargs):
            connection = real_connect(path, *args, **kwargs)
            if threading.current_thread().name == "ledger-race-worker":
                return _InterleavingConnection(
                    connection, select_prefix, ready, release
                )
            return connection

        def run():
            try:
                result["value"] = operation()
            except Exception as exc:
                result["error"] = exc

        try:
            with patch("prism_core.ledger.sqlite3.connect", side_effect=connect):
                thread = threading.Thread(target=run, name="ledger-race-worker")
                thread.start()
                self.assertTrue(ready.wait(2), "second connection did not reach read/lock")
                writer.commit()
                release.set()
                thread.join(2)
                self.assertFalse(thread.is_alive(), "second connection did not finish")
        finally:
            writer.close()
            release.set()
        return result


if __name__ == "__main__":
    unittest.main()
