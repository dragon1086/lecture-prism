from pathlib import Path
from decimal import Decimal
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

import db
from prism_core import Market, OrderIntent, OrderSide, OrderType
from prism_core.ledger import IncompatibleLedgerSchema, Ledger
from prism_core.paper_broker import PaperBroker


class DatabaseCoreSchemaTest(unittest.TestCase):
    @staticmethod
    def _schema_snapshot(path, table):
        with sqlite3.connect(path) as conn:
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0]
            rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
            indexes = conn.execute(
                "SELECT name,sql FROM sqlite_master "
                "WHERE type='index' AND tbl_name=? ORDER BY name",
                (table,),
            ).fetchall()
        return sql, rows, indexes

    def test_init_db_adds_core_ledger_without_breaking_legacy_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "combined.db"
            with mock.patch.object(db, "DB_PATH", path):
                db.init_db()
                db.init_db()

            with sqlite3.connect(path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                replay_columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(classroom_replays)"
                    ).fetchall()
                }
                trade_columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(realized_trades)"
                    ).fetchall()
                }
                position_columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(positions)"
                    ).fetchall()
                }

        self.assertTrue(
            {
                "trade_history",
                "analysis_decisions",
                "feedback_lessons",
                "broker_orders",
                "fills",
                "positions",
                "realized_trades",
                "classroom_replays",
            }.issubset(tables)
        )
        self.assertIn("phase", replay_columns)
        self.assertIn("abort_reason", replay_columns)
        self.assertIn("aborted_at", replay_columns)
        self.assertIn("exit_client_order_id", trade_columns)
        self.assertIn("exit_fill_id", trade_columns)
        self.assertIn("entry_client_order_id", position_columns)

    def test_init_db_adds_nullable_exit_provenance_without_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "combined.db"
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE TABLE realized_trades ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "market TEXT NOT NULL,symbol TEXT NOT NULL,"
                    "quantity TEXT NOT NULL,entry_price TEXT NOT NULL,"
                    "exit_price TEXT NOT NULL,pnl_amount TEXT NOT NULL,"
                    "currency TEXT NOT NULL,strategy_id TEXT NOT NULL,"
                    "closed_at TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO realized_trades "
                    "(market,symbol,quantity,entry_price,exit_price,"
                    "pnl_amount,currency,strategy_id,closed_at) "
                    "VALUES ('US','AAPL','1','100','110','10','USD',"
                    "'legacy','old')"
                )

            Ledger(path)
            Ledger(path)

            with sqlite3.connect(path) as conn:
                columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(realized_trades)"
                    ).fetchall()
                }
                self.assertTrue(
                    {"exit_client_order_id", "exit_fill_id"}.issubset(columns)
                )
                provenance = conn.execute(
                    "SELECT exit_client_order_id,exit_fill_id "
                    "FROM realized_trades WHERE strategy_id='legacy'"
                ).fetchone()

            self.assertEqual(provenance, (None, None))

    def test_init_db_adds_replay_phase_to_existing_core_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "combined.db"
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE TABLE classroom_replays ("
                    "sequence INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "session_id TEXT NOT NULL UNIQUE,"
                    "strategy_id TEXT NOT NULL UNIQUE,"
                    "status TEXT NOT NULL,owner_token TEXT,"
                    "lease_expires_at REAL,"
                    "realized_trades INTEGER NOT NULL DEFAULT 0,"
                    "created_at TEXT NOT NULL,updated_at TEXT NOT NULL,"
                    "completed_at TEXT)"
                )

            with mock.patch.object(db, "DB_PATH", path):
                db.init_db()

            with sqlite3.connect(path) as conn:
                phase = conn.execute(
                    "SELECT name,dflt_value FROM pragma_table_info(?) "
                    "WHERE name='phase'",
                    ("classroom_replays",),
                ).fetchone()

            self.assertEqual(phase, ("phase", "1"))

    def test_init_db_rejects_populated_incompatible_core_table_transactionally(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "combined.db"
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE TABLE classroom_replays ("
                    "sequence INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "session_id TEXT NOT NULL UNIQUE,"
                    "strategy_id TEXT NOT NULL UNIQUE,"
                    "status TEXT NOT NULL,owner_token TEXT,"
                    "lease_expires_at REAL,"
                    "realized_trades INTEGER NOT NULL DEFAULT 0,"
                    "created_at TEXT NOT NULL,updated_at TEXT NOT NULL,"
                    "completed_at TEXT)"
                )
                conn.execute(
                    "CREATE TABLE broker_orders ("
                    "client_order_id TEXT PRIMARY KEY,"
                    "strategy_id TEXT NOT NULL,side TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO classroom_replays "
                    "(session_id,strategy_id,status,created_at,updated_at) "
                    "VALUES (?,?, 'INCOMPLETE','now','now')",
                    (
                        "classroom-000001",
                        "classroom-replay:classroom-000001",
                    ),
                )
                conn.execute(
                    "INSERT INTO broker_orders VALUES (?,?,?)",
                    (
                        "classroom-000001-3:KR:005930:SELL",
                        "classroom-replay:classroom-000001",
                        "SELL",
                    ),
                )

            with mock.patch.object(db, "DB_PATH", path):
                with self.assertRaisesRegex(
                    IncompatibleLedgerSchema,
                    "broker_orders.*missing required columns",
                ):
                    db.init_db()

            with sqlite3.connect(path) as conn:
                replay_columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(classroom_replays)"
                    ).fetchall()
                }
                order = conn.execute(
                    "SELECT client_order_id,strategy_id,side FROM broker_orders"
                ).fetchone()

            self.assertNotIn("phase", replay_columns)
            self.assertEqual(
                order,
                (
                    "classroom-000001-3:KR:005930:SELL",
                    "classroom-replay:classroom-000001",
                    "SELL",
                ),
            )

    def test_current_schema_with_wrong_column_metadata_is_rejected(self):
        variants = (
            (
                "type",
                "quantity INTEGER NOT NULL",
                "filled_quantity TEXT NOT NULL DEFAULT '0'",
                "broker_orders.quantity.*type",
            ),
            (
                "not-null",
                "quantity TEXT",
                "filled_quantity TEXT NOT NULL DEFAULT '0'",
                "broker_orders.quantity.*NOT NULL",
            ),
            (
                "default",
                "quantity TEXT NOT NULL",
                "filled_quantity TEXT NOT NULL",
                "broker_orders.filled_quantity.*default",
            ),
        )
        for label, quantity_column, filled_column, message in variants:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"wrong-{label}.db"
                Ledger(path)
                with sqlite3.connect(path) as conn:
                    conn.execute("ALTER TABLE broker_orders RENAME TO old_orders")
                    conn.execute(
                        "CREATE TABLE broker_orders ("
                        "client_order_id TEXT PRIMARY KEY,market TEXT NOT NULL,"
                        "symbol TEXT NOT NULL,side TEXT NOT NULL,"
                        f"order_type TEXT NOT NULL,{quantity_column},"
                        "limit_price TEXT,currency TEXT NOT NULL,"
                        "strategy_id TEXT NOT NULL,reason TEXT NOT NULL,"
                        f"status TEXT NOT NULL,{filled_column},"
                        "average_fill_price TEXT,created_at TEXT NOT NULL,"
                        "updated_at TEXT NOT NULL)"
                    )
                    conn.execute("DROP TABLE old_orders")

                with self.assertRaisesRegex(
                    IncompatibleLedgerSchema, message
                ):
                    Ledger(path)

    def test_unknown_required_column_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "extra-required.db"
            Ledger(path)
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "ALTER TABLE positions ADD COLUMN rogue TEXT NOT NULL"
                )
                conn.execute(
                    "INSERT INTO positions "
                    "(market,symbol,quantity,average_price,currency,"
                    "high_since_entry,strategy_id,entry_client_order_id,"
                    "updated_at,rogue) VALUES "
                    "('US','AAPL','1','100','USD','100','owner',"
                    "'entry:AAPL:BUY','old','keep')"
                )
            before = self._schema_snapshot(path, "positions")

            with self.assertRaisesRegex(
                IncompatibleLedgerSchema,
                "positions.rogue.*unknown NOT NULL.*usable default",
            ):
                Ledger(path)

            self.assertEqual(self._schema_snapshot(path, "positions"), before)

    def test_unknown_required_column_with_unsafe_expression_default_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unsafe-default.db"
            ledger = Ledger(path)
            ledger.create_order(
                OrderIntent(
                    "existing:AAPL:BUY",
                    Market.US,
                    "AAPL",
                    OrderSide.BUY,
                    OrderType.MARKET,
                    Decimal("1"),
                    None,
                    "USD",
                )
            )
            with sqlite3.connect(path) as conn:
                conn.execute("ALTER TABLE broker_orders RENAME TO old_orders")
                conn.execute(
                    "CREATE TABLE broker_orders ("
                    "client_order_id TEXT PRIMARY KEY,market TEXT NOT NULL,"
                    "symbol TEXT NOT NULL,side TEXT NOT NULL,"
                    "order_type TEXT NOT NULL,quantity TEXT NOT NULL,"
                    "limit_price TEXT,currency TEXT NOT NULL,"
                    "strategy_id TEXT NOT NULL,reason TEXT NOT NULL,"
                    "status TEXT NOT NULL,"
                    "filled_quantity TEXT NOT NULL DEFAULT '0',"
                    "average_fill_price TEXT,created_at TEXT NOT NULL,"
                    "updated_at TEXT NOT NULL,"
                    "rogue TEXT NOT NULL DEFAULT (1/0))"
                )
                conn.execute(
                    "INSERT INTO broker_orders "
                    "SELECT *, 'keep' FROM old_orders"
                )
                conn.execute("DROP TABLE old_orders")
            before = self._schema_snapshot(path, "broker_orders")

            with self.assertRaisesRegex(
                IncompatibleLedgerSchema,
                "broker_orders.rogue.*without a usable default",
            ):
                Ledger(path)

            self.assertEqual(
                self._schema_snapshot(path, "broker_orders"), before
            )

    def test_unexpected_semantic_unique_index_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "extra-unique.db"
            ledger = Ledger(path)
            ledger.create_order(
                OrderIntent(
                    "existing:AAPL:BUY",
                    Market.US,
                    "AAPL",
                    OrderSide.BUY,
                    OrderType.MARKET,
                    Decimal("1"),
                    None,
                    "USD",
                )
            )
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE UNIQUE INDEX rogue_unique_symbol "
                    "ON broker_orders(symbol)"
                )
            before = self._schema_snapshot(path, "broker_orders")

            with self.assertRaisesRegex(
                IncompatibleLedgerSchema,
                "broker_orders.*unexpected UNIQUE.*symbol",
            ):
                Ledger(path)

            self.assertEqual(
                self._schema_snapshot(path, "broker_orders"), before
            )

    def test_partial_unique_impostor_does_not_satisfy_required_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partial-unique.db"
            ledger = Ledger(path)
            intent = OrderIntent(
                "existing:AAPL:BUY",
                Market.US,
                "AAPL",
                OrderSide.BUY,
                OrderType.MARKET,
                Decimal("1"),
                None,
                "USD",
            )
            ledger.create_order(intent)
            with sqlite3.connect(path) as conn:
                conn.execute("ALTER TABLE order_events RENAME TO old_events")
                conn.execute(
                    "CREATE TABLE order_events ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "client_order_id TEXT NOT NULL,status TEXT NOT NULL,"
                    "occurred_at TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO order_events "
                    "(id,client_order_id,status,occurred_at) "
                    "SELECT id,client_order_id,status,occurred_at "
                    "FROM old_events"
                )
                conn.execute("DROP TABLE old_events")
                conn.execute(
                    "CREATE UNIQUE INDEX partial_event_identity "
                    "ON order_events(client_order_id,status) "
                    "WHERE status='CREATED'"
                )
            before = self._schema_snapshot(path, "order_events")

            with self.assertRaisesRegex(
                IncompatibleLedgerSchema,
                "order_events.*partial.*UNIQUE",
            ):
                Ledger(path)

            self.assertEqual(
                self._schema_snapshot(path, "order_events"), before
            )

    def test_nocase_unique_impostor_does_not_satisfy_required_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nocase-unique.db"
            ledger = Ledger(path)
            ledger.create_order(
                OrderIntent(
                    "Case",
                    Market.US,
                    "AAPL",
                    OrderSide.BUY,
                    OrderType.MARKET,
                    Decimal("1"),
                    None,
                    "USD",
                )
            )
            with sqlite3.connect(path) as conn:
                conn.execute("ALTER TABLE order_events RENAME TO old_events")
                conn.execute(
                    "CREATE TABLE order_events ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "client_order_id TEXT NOT NULL,status TEXT NOT NULL,"
                    "occurred_at TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO order_events "
                    "(id,client_order_id,status,occurred_at) "
                    "SELECT id,client_order_id,status,occurred_at "
                    "FROM old_events"
                )
                conn.execute("DROP TABLE old_events")
                conn.execute(
                    "CREATE UNIQUE INDEX nocase_event_identity ON order_events("
                    "client_order_id COLLATE NOCASE,status)"
                )
            before = self._schema_snapshot(path, "order_events")

            with self.assertRaisesRegex(
                IncompatibleLedgerSchema,
                "order_events.*non-BINARY.*UNIQUE",
            ):
                Ledger(path)

            self.assertEqual(
                self._schema_snapshot(path, "order_events"), before
            )

    def test_expression_unique_impostor_does_not_satisfy_required_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "expression-unique.db"
            Ledger(path)
            with sqlite3.connect(path) as conn:
                conn.execute("ALTER TABLE order_events RENAME TO old_events")
                conn.execute(
                    "CREATE TABLE order_events ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "client_order_id TEXT NOT NULL,status TEXT NOT NULL,"
                    "occurred_at TEXT NOT NULL)"
                )
                conn.execute("DROP TABLE old_events")
                conn.execute(
                    "CREATE UNIQUE INDEX expression_event_identity "
                    "ON order_events(lower(client_order_id),status)"
                )
            before = self._schema_snapshot(path, "order_events")

            with self.assertRaisesRegex(
                IncompatibleLedgerSchema,
                "order_events.*expression UNIQUE",
            ):
                Ledger(path)

            self.assertEqual(
                self._schema_snapshot(path, "order_events"), before
            )

    def test_nullable_extra_column_and_nonunique_index_are_write_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "harmless-additions.db"
            Ledger(path)
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "ALTER TABLE broker_orders ADD COLUMN classroom_note TEXT"
                )
                conn.execute(
                    "ALTER TABLE broker_orders ADD COLUMN classroom_tag "
                    "TEXT NOT NULL DEFAULT 'safe'"
                )
                conn.execute(
                    "CREATE INDEX ix_broker_orders_symbol "
                    "ON broker_orders(symbol)"
                )

            broker = PaperBroker(Ledger(path))
            intent = OrderIntent(
                "safe-extra:AAPL:BUY",
                Market.US,
                "AAPL",
                OrderSide.BUY,
                OrderType.MARKET,
                Decimal("1"),
                None,
                "USD",
            )
            broker.submit_order(intent)
            filled = broker.fill_order(
                intent.client_order_id,
                "safe-fill",
                Decimal("1"),
                Decimal("100"),
            )

            self.assertEqual(filled.intent, intent)
            self.assertEqual(broker.get_positions()[0].quantity, Decimal("1"))
            with sqlite3.connect(path) as conn:
                self.assertEqual(
                    conn.execute(
                        "SELECT classroom_note,classroom_tag FROM broker_orders"
                    ).fetchone(),
                    (None, "safe"),
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT \"unique\" FROM pragma_index_list('broker_orders') "
                        "WHERE name='ix_broker_orders_symbol'"
                    ).fetchone(),
                    (0,),
                )

    def test_valid_version_one_schema_migrates_and_reopens_for_order_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old-core.db"
            Ledger(path)
            with sqlite3.connect(path) as conn:
                for table, columns in (
                    ("positions", ("entry_client_order_id",)),
                    ("realized_trades", ("exit_fill_id", "exit_client_order_id")),
                    ("classroom_replays", ("aborted_at", "abort_reason", "phase")),
                ):
                    for column in columns:
                        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
                conn.execute(
                    "UPDATE prism_core_meta SET value='1' WHERE key='schema_version'"
                )

            migrated = Ledger(path)
            migrated.create_order(
                OrderIntent(
                    "migration:AAPL:BUY",
                    Market.US,
                    "AAPL",
                    OrderSide.BUY,
                    OrderType.MARKET,
                    Decimal("1"),
                    None,
                    "USD",
                )
            )
            reopened = Ledger(path)
            self.assertEqual(
                reopened.get_order("migration:AAPL:BUY").intent.symbol, "AAPL"
            )
            claim = reopened.claim_classroom_replay("owner", lease_seconds=30)
            self.assertEqual(claim.phase, 1)
            with sqlite3.connect(path) as conn:
                version = conn.execute(
                    "SELECT value FROM prism_core_meta WHERE key='schema_version'"
                ).fetchone()[0]
            self.assertEqual(version, "4")

    def test_current_course_shell_database_shape_is_preserved_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "course-shell.db"
            with sqlite3.connect(path) as conn:
                conn.executescript(db._SCHEMA)
                conn.execute(
                    "INSERT INTO trade_history "
                    "(timestamp,ticker,action,price,quantity,mode,reason) "
                    "VALUES ('old','005930','PASS',70000,0,'simulation','keep')"
                )
                conn.execute(
                    "INSERT INTO analysis_decisions "
                    "(timestamp,ticker,recommendation,score,reason,risk,sections) "
                    "VALUES ('old','005930','HOLD',5,'keep','low',NULL)"
                )
                conn.execute(
                    "INSERT INTO feedback_lessons "
                    "(timestamp,ticker,action,lesson,tier,error_type) "
                    "VALUES ('old','005930','PASS','keep','short','JUDGMENT')"
                )

            Ledger(path)
            Ledger(path)

            with sqlite3.connect(path) as conn:
                self.assertEqual(
                    conn.execute("SELECT reason FROM trade_history").fetchall(),
                    [("keep",)],
                )
                self.assertEqual(
                    conn.execute("SELECT reason FROM analysis_decisions").fetchall(),
                    [("keep",)],
                )
                self.assertEqual(
                    conn.execute("SELECT lesson FROM feedback_lessons").fetchall(),
                    [("keep",)],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT value FROM prism_core_meta WHERE key='schema_version'"
                    ).fetchone(),
                    ("4",),
                )

    def test_concurrent_empty_database_initialization_is_serialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "concurrent.db"
            barrier = threading.Barrier(4)
            errors = []

            def initialize():
                barrier.wait()
                try:
                    Ledger(path)
                except Exception as exc:
                    errors.append(exc)

            workers = [threading.Thread(target=initialize) for _ in range(4)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(5)

            self.assertEqual(errors, [])
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            with sqlite3.connect(path) as conn:
                self.assertEqual(
                    conn.execute(
                        "SELECT value FROM prism_core_meta WHERE key='schema_version'"
                    ).fetchone(),
                    ("4",),
                )


if __name__ == "__main__":
    unittest.main()
