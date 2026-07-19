from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import db


class DatabaseCoreSchemaTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
