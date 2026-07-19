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
                replay_columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(classroom_replays)"
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

    def test_init_db_migrates_accepted_legacy_exit_to_phase_three(self):
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
                db.init_db()

            with sqlite3.connect(path) as conn:
                phase = conn.execute(
                    "SELECT phase FROM classroom_replays"
                ).fetchone()[0]

            self.assertEqual(phase, 3)


if __name__ == "__main__":
    unittest.main()
