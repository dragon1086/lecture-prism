import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import db


def _order(**overrides):
    value = {
        "broker": "kis",
        "mode": "paper",
        "client_request_id": "request-1",
        "order_date": "2026-07-15",
        "org_no": None,
        "order_no": None,
        "ticker": "005930",
        "side": "BUY",
        "status": "submitting",
        "requested_qty": 5,
        "filled_qty": 0,
        "remaining_qty": 5,
        "requested_price": 70000,
        "avg_fill_price": None,
    }
    value.update(overrides)
    return value


class KISOrderStoreTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._temp_dir.name) / "prism.db"

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._temp_dir.cleanup()

    def _all_orders(self):
        with sqlite3.connect(db.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM broker_orders")]

    def test_migration_adds_tables_and_pending_index_idempotently(self):
        db.init_db()
        db.init_db()

        with sqlite3.connect(db.DB_PATH) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(broker_orders)")
            }

        self.assertTrue({"broker_orders", "market_calendar_cache"} <= tables)
        self.assertIn("idx_broker_orders_pending", indexes)
        self.assertIn("idx_broker_orders_broker_identity", indexes)
        self.assertFalse(
            {"account_no", "app_key", "app_secret", "access_token", "raw_response"}
            & columns
        )

    def test_client_request_id_deduplicates_before_acceptance(self):
        first = db.save_broker_order(_order())
        accepted = db.save_broker_order(
            _order(status="accepted", org_no="01", order_no="100")
        )

        rows = self._all_orders()
        self.assertEqual(first["id"], accepted["id"])
        self.assertEqual(1, len(rows))
        self.assertEqual("accepted", rows[0]["status"])
        self.assertEqual("100", rows[0]["order_no"])

    def test_broker_identity_deduplicates_accepted_records(self):
        first = db.save_broker_order(
            _order(status="accepted", org_no="01", order_no="100")
        )
        duplicate = db.save_broker_order(
            _order(
                client_request_id="recovery-request",
                status="unfilled",
                org_no="01",
                order_no="100",
            )
        )

        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(1, len(self._all_orders()))
        self.assertEqual("unfilled", duplicate["status"])

    def test_order_progress_persists_fill_quantities_and_average_price(self):
        db.save_broker_order(
            _order(status="accepted", org_no="01", order_no="100")
        )

        partial = db.update_broker_order(
            _order(
                status="partial_fill",
                org_no="01",
                order_no="100",
                filled_qty=2,
                remaining_qty=3,
                avg_fill_price=70100,
            )
        )
        filled = db.update_broker_order(
            _order(
                status="filled",
                org_no="01",
                order_no="100",
                filled_qty=5,
                remaining_qty=0,
                avg_fill_price=70200,
            )
        )

        self.assertEqual("partial_fill", partial["status"])
        self.assertEqual(2, partial["filled_qty"])
        self.assertEqual(3, partial["remaining_qty"])
        self.assertEqual(70100, partial["avg_fill_price"])
        self.assertEqual("filled", filled["status"])
        self.assertEqual(5, filled["filled_qty"])
        self.assertEqual(0, filled["remaining_qty"])

    def test_order_state_cannot_regress_from_filled_to_accepted(self):
        db.save_broker_order(
            _order(
                status="filled",
                org_no="01",
                order_no="100",
                filled_qty=5,
                remaining_qty=0,
                avg_fill_price=70200,
            )
        )

        with self.assertRaises(ValueError):
            db.update_broker_order(
                _order(status="accepted", org_no="01", order_no="100")
            )

    def test_cancelled_and_rejected_are_terminal(self):
        db.save_broker_order(
            _order(status="accepted", org_no="01", order_no="100")
        )
        db.update_broker_order(
            _order(status="cancel_requested", org_no="01", order_no="100")
        )
        cancelled = db.update_broker_order(
            _order(status="cancelled", org_no="01", order_no="100")
        )
        self.assertEqual("cancelled", cancelled["status"])
        with self.assertRaises(ValueError):
            db.update_broker_order(
                _order(status="partial_fill", org_no="01", order_no="100")
            )

        db.save_broker_order(
            _order(client_request_id="request-2", status="rejected")
        )
        with self.assertRaises(ValueError):
            db.update_broker_order(
                _order(client_request_id="request-2", status="accepted")
            )

    def test_pending_recovery_excludes_terminal_orders(self):
        pending_statuses = [
            "submitting",
            "accepted",
            "unknown",
            "unfilled",
            "partial_fill",
            "cancel_requested",
        ]
        for index, status in enumerate(pending_statuses):
            db.save_broker_order(
                _order(client_request_id=f"pending-{index}", status=status)
            )
        for index, status in enumerate(("filled", "cancelled", "rejected")):
            db.save_broker_order(
                _order(
                    client_request_id=f"terminal-{index}",
                    status=status,
                    filled_qty=5 if status == "filled" else 0,
                    remaining_qty=0 if status in {"filled", "cancelled"} else 5,
                )
            )

        rows = db.get_pending_broker_orders(broker="kis", mode="paper")

        self.assertEqual(set(pending_statuses), {row["status"] for row in rows})

    def test_order_store_ignores_raw_credentials_and_sanitizes_message(self):
        secret = "sk-" + "synthetic-sensitive-value"
        saved = db.save_broker_order(
            _order(
                message=f"request failed token={secret}",
                app_secret=secret,
                access_token=secret,
                raw_response={"token": secret},
            )
        )

        persisted = json.dumps(saved, ensure_ascii=False)
        self.assertNotIn(secret, persisted)
        self.assertIn("[REDACTED]", saved["message"])

    def test_market_day_cache_upserts_and_reads_by_broker_market_date(self):
        db.save_market_day(
            {
                "broker": "kis",
                "market": "KRX",
                "business_date": "2026-07-15",
                "is_open": True,
                "source": "KIS",
            }
        )
        db.save_market_day(
            {
                "broker": "kis",
                "market": "KRX",
                "business_date": "2026-07-15",
                "is_open": False,
                "source": "manual-correction",
            }
        )

        saved = db.get_market_day("kis", "KRX", "2026-07-15")

        self.assertFalse(saved["is_open"])
        self.assertEqual("manual-correction", saved["source"])
        self.assertIsNone(db.get_market_day("kis", "KRX", "2026-07-16"))


if __name__ == "__main__":
    unittest.main()
