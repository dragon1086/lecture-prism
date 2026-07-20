from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import db
from prism_core.domain import (
    Market,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
)
from prism_core.ledger import Ledger


def _intent(client_order_id: str, *, symbol: str = "AAPL") -> OrderIntent:
    return OrderIntent(
        client_order_id=client_order_id,
        market=Market.US,
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        limit_price=Decimal("180.25"),
        currency="USD",
        strategy_id="kis-order-store-test",
        reason="persistence contract",
    )


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[1]
        for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def _seed_v5(path: Path) -> tuple:
    """Create a real legacy row, then expose the database as schema v5."""

    ledger = Ledger(path)
    ledger.create_order(_intent("legacy:AAPL:BUY"))
    with sqlite3.connect(path) as conn:
        before = conn.execute(
            "SELECT client_order_id,market,symbol,side,order_type,quantity,"
            "limit_price,currency,strategy_id,reason,status,filled_quantity,"
            "average_fill_price,created_at,updated_at FROM broker_orders"
        ).fetchone()
        conn.execute("DROP INDEX IF EXISTS uq_broker_orders_broker_identity")
        conn.execute("DROP INDEX IF EXISTS ix_broker_orders_pending_recovery")
        conn.execute("DROP TABLE IF EXISTS market_calendar_cache")
        columns = _columns(conn, "broker_orders")
        for column in (
            "remaining_quantity",
            "broker_order_no",
            "broker_org_no",
            "broker_order_date",
            "broker_mode",
            "broker",
        ):
            if column in columns:
                conn.execute(f'ALTER TABLE broker_orders DROP COLUMN "{column}"')
        conn.execute(
            "UPDATE prism_core_meta SET value='5' WHERE key='schema_version'"
        )
    return before


class KISOrderStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "kis-orders.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ledger(self) -> Ledger:
        return Ledger(self.path)

    @staticmethod
    def _advance_to_submitted(ledger: Ledger, client_order_id: str) -> None:
        ledger.transition_order(client_order_id, OrderStatus.PREVIEWED)
        ledger.transition_order(client_order_id, OrderStatus.SUBMITTED)

    def test_v5_to_v6_migration_is_idempotent_and_preserves_existing_order(self):
        before = _seed_v5(self.path)

        Ledger(self.path)
        Ledger(self.path)

        with sqlite3.connect(self.path) as conn:
            after = conn.execute(
                "SELECT client_order_id,market,symbol,side,order_type,quantity,"
                "limit_price,currency,strategy_id,reason,status,filled_quantity,"
                "average_fill_price,created_at,updated_at FROM broker_orders"
            ).fetchone()
            version = conn.execute(
                "SELECT value FROM prism_core_meta WHERE key='schema_version'"
            ).fetchone()[0]
            migrated = conn.execute(
                "SELECT broker,broker_mode,remaining_quantity "
                "FROM broker_orders WHERE client_order_id='legacy:AAPL:BUY'"
            ).fetchone()
            calendar_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='market_calendar_cache'"
            ).fetchone()
            pending_index = tuple(
                row[2]
                for row in conn.execute(
                    "SELECT * FROM pragma_index_xinfo(?)",
                    ("ix_broker_orders_pending_recovery",),
                ).fetchall()
                if row[5]
            )

        self.assertEqual(after, before)
        self.assertEqual(version, "6")
        self.assertEqual(migrated, ("paper", "simulation", "2"))
        self.assertIsNotNone(calendar_exists)
        self.assertEqual(
            pending_index,
            ("broker", "broker_mode", "status", "updated_at", "client_order_id"),
        )

        with sqlite3.connect(self.path) as conn:
            conn.execute("DROP INDEX ix_broker_orders_pending_recovery")
        with self.assertRaisesRegex(Exception, "missing required index"):
            Ledger(self.path)

    def test_orders_without_broker_identity_do_not_conflict(self):
        ledger = self._ledger()
        first = ledger.save_broker_order(
            _intent("request-1"), broker="kis", broker_mode="demo"
        )
        second = ledger.save_broker_order(
            _intent("request-2", symbol="MSFT"),
            broker="kis",
            broker_mode="demo",
        )

        self.assertIsNone(first.broker_order_no)
        self.assertIsNone(second.broker_order_no)

    def test_broker_identity_bind_is_idempotent_and_rejects_collision(self):
        ledger = self._ledger()
        ledger.save_broker_order(
            _intent("request-1"), broker="kis", broker_mode="demo"
        )
        ledger.save_broker_order(
            _intent("request-2", symbol="MSFT"),
            broker="kis",
            broker_mode="demo",
        )
        identity = {
            "broker_order_date": "20260720",
            "broker_org_no": "12345",
            "broker_order_no": "0000004321",
        }

        first = ledger.bind_broker_identity("request-1", **identity)
        repeated = ledger.bind_broker_identity("request-1", **identity)
        self.assertEqual(first, repeated)
        with self.assertRaises((ValueError, sqlite3.IntegrityError)):
            ledger.bind_broker_identity("request-2", **identity)

    def test_broker_identity_requires_all_nonblank_components(self):
        ledger = self._ledger()
        ledger.save_broker_order(
            _intent("request-1"), broker="kis", broker_mode="demo"
        )

        incomplete = (
            {"broker_order_date": "", "broker_org_no": "12345", "broker_order_no": "1"},
            {"broker_order_date": "20260231", "broker_org_no": "12345", "broker_order_no": "1"},
            {"broker_order_date": "20260720", "broker_org_no": "", "broker_order_no": "1"},
            {"broker_order_date": "20260720", "broker_org_no": "12345", "broker_order_no": ""},
        )
        for identity in incomplete:
            with self.subTest(identity=identity):
                with self.assertRaises(ValueError):
                    ledger.bind_broker_identity("request-1", **identity)

    def test_order_snapshot_progresses_accepted_partial_filled(self):
        ledger = self._ledger()
        ledger.save_broker_order(
            _intent("request-1"), broker="kis", broker_mode="demo"
        )
        self._advance_to_submitted(ledger, "request-1")

        accepted = ledger.update_broker_order(
            "request-1",
            status=OrderStatus.ACCEPTED,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("2"),
            average_fill_price=None,
        )
        partial = ledger.update_broker_order(
            "request-1",
            status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=Decimal("0.75"),
            remaining_quantity=Decimal("1.25"),
            average_fill_price=Decimal("180.20"),
        )
        filled = ledger.update_broker_order(
            "request-1",
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("2"),
            remaining_quantity=Decimal("0"),
            average_fill_price=Decimal("180.30"),
        )

        self.assertEqual(accepted.status, OrderStatus.ACCEPTED)
        self.assertEqual(partial.remaining_quantity, Decimal("1.25"))
        self.assertEqual(filled.filled_quantity, Decimal("2"))
        self.assertEqual(filled.remaining_quantity, Decimal("0"))

        with self.assertRaises(ValueError):
            ledger.update_broker_order(
                "request-1",
                status=OrderStatus.ACCEPTED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("2"),
                average_fill_price=None,
            )

    def test_order_snapshot_rejects_quantity_inconsistency_and_regression(self):
        ledger = self._ledger()
        ledger.save_broker_order(
            _intent("request-1"), broker="kis", broker_mode="demo"
        )
        self._advance_to_submitted(ledger, "request-1")
        ledger.update_broker_order(
            "request-1",
            status=OrderStatus.ACCEPTED,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("2"),
            average_fill_price=None,
        )
        ledger.update_broker_order(
            "request-1",
            status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=Decimal("1"),
            remaining_quantity=Decimal("1"),
            average_fill_price=Decimal("180.25"),
        )

        with self.assertRaises(ValueError):
            ledger.update_broker_order(
                "request-1",
                status=OrderStatus.PARTIALLY_FILLED,
                filled_quantity=Decimal("0.5"),
                remaining_quantity=Decimal("1.5"),
                average_fill_price=Decimal("180.25"),
            )
        with self.assertRaises(ValueError):
            ledger.update_broker_order(
                "request-1",
                status=OrderStatus.FILLED,
                filled_quantity=Decimal("1"),
                remaining_quantity=Decimal("1"),
                average_fill_price=Decimal("180.25"),
            )
        with self.assertRaises(ValueError):
            ledger.update_broker_order(
                "request-1",
                status=OrderStatus.PARTIALLY_FILLED,
                filled_quantity=Decimal("1"),
                remaining_quantity=Decimal("1.25"),
                average_fill_price=Decimal("180.25"),
            )

    def test_pending_query_is_scoped_and_includes_unknown_not_terminal(self):
        ledger = self._ledger()
        for order_id, mode in (
            ("demo-unknown", "demo"),
            ("demo-filled", "demo"),
            ("real-unknown", "real"),
        ):
            ledger.save_broker_order(
                _intent(order_id), broker="kis", broker_mode=mode
            )
            self._advance_to_submitted(ledger, order_id)

        ledger.update_broker_order(
            "demo-unknown",
            status=OrderStatus.UNKNOWN,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("2"),
            average_fill_price=None,
        )
        ledger.update_broker_order(
            "demo-filled",
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("2"),
            remaining_quantity=Decimal("0"),
            average_fill_price=Decimal("180.25"),
        )
        ledger.update_broker_order(
            "real-unknown",
            status=OrderStatus.UNKNOWN,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("2"),
            average_fill_price=None,
        )

        pending = ledger.get_pending_broker_orders(
            broker="kis", broker_mode="demo"
        )
        self.assertEqual(
            [item.order.intent.client_order_id for item in pending],
            ["demo-unknown"],
        )

    def test_market_day_upsert_read_and_boolean_validation(self):
        ledger = self._ledger()
        ledger.save_market_day(
            Market.KR,
            "20260720",
            is_open=False,
            source="kis",
            checked_at="2026-07-20T01:00:00.100000+00:00",
        )
        ledger.save_market_day(
            Market.KR,
            "20260720",
            is_open=True,
            source="kis-corrected",
            checked_at="2026-07-20T01:00:00.900000+00:00",
        )
        ledger.save_market_day(
            Market.KR,
            "20260720",
            is_open=False,
            source="kis-stale",
            checked_at="2026-07-20T01:00:00.500000+00:00",
        )

        result = ledger.get_market_day(Market.KR, "20260720")
        self.assertEqual(result["market"], "KR")
        self.assertEqual(result["trade_date"], "20260720")
        self.assertIs(result["is_open"], True)
        self.assertEqual(result["source"], "kis-corrected")
        self.assertEqual(
            result["checked_at"], "2026-07-20T01:00:00.900000+00:00"
        )
        with self.assertRaises(ValueError):
            ledger.save_market_day(
                Market.KR,
                "20260721",
                is_open=1,
                source="kis",
            )
        for invalid_date in ("20260230", "2026-07-20", ""):
            with self.subTest(invalid_date=invalid_date):
                with self.assertRaises(ValueError):
                    ledger.get_market_day(Market.KR, invalid_date)
        with self.assertRaises(ValueError):
            ledger.save_market_day(
                Market.KR,
                "20260721",
                is_open=True,
                source="kis",
                checked_at="not-a-timestamp",
            )

    def test_db_facade_uses_the_same_ledger_tables(self):
        with patch.object(db, "DB_PATH", self.path):
            state = db.save_broker_order(
                _intent("facade-order"), broker="kis", broker_mode="demo"
            )
            db.save_market_day(
                Market.KR,
                "20260720",
                is_open=True,
                source="kis",
                broker_mode="demo",
            )

            self.assertEqual(state.broker, "kis")
            self.assertEqual(
                db.get_pending_broker_orders(broker="kis", broker_mode="demo")[
                    0
                ].order.intent.client_order_id,
                "facade-order",
            )
            self.assertTrue(
                db.get_market_day(
                    Market.KR, "20260720", broker_mode="demo"
                )["is_open"]
            )
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM broker_orders "
                    "WHERE client_order_id='facade-order'"
                ).fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
