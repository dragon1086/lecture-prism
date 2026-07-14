import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import db


class PipelineStoreTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._temp_dir.name) / "prism.db"

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._temp_dir.cleanup()

    def _fetch_delivery(self, sequence=None):
        with sqlite3.connect(db.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            if sequence is None:
                row = conn.execute("SELECT * FROM notification_deliveries").fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM notification_deliveries WHERE sequence = ?",
                    (sequence,),
                ).fetchone()
            return dict(row)

    def test_init_db_adds_pipeline_tables_idempotently(self):
        db.init_db()
        db.init_db()

        with sqlite3.connect(db.DB_PATH) as conn:
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        self.assertTrue(
            {"pipeline_runs", "pipeline_events", "notification_deliveries"}
            <= names
        )

    def test_pipeline_run_can_be_started_finished_and_read_as_latest(self):
        db.start_pipeline_run(
            {
                "run_id": "run-1",
                "started_at": "2026-07-15T00:00:00+00:00",
                "profile": "mock",
                "trade_state": "simulation",
                "data_source": "mock",
                "data_as_of": "2026-07-14",
                "market_status": "closed",
            }
        )

        started = db.get_latest_pipeline_run()
        self.assertEqual("run-1", started["run_id"])
        self.assertEqual("running", started["status"])

        db.finish_pipeline_run("run-1", "failed", failure_stage="analysis")

        finished = db.get_latest_pipeline_run()
        self.assertEqual("failed", finished["status"])
        self.assertEqual("analysis", finished["failure_stage"])
        self.assertIsNotNone(finished["completed_at"])

    def test_latest_pipeline_run_compares_mixed_offsets_chronologically(self):
        db.start_pipeline_run(
            {
                "run_id": "older-jst",
                "started_at": "2026-07-15T09:30:00+09:00",
                "profile": "mock",
                "trade_state": "simulation",
            }
        )
        db.start_pipeline_run(
            {
                "run_id": "newer-utc",
                "started_at": "2026-07-15T01:00:00+00:00",
                "profile": "mock",
                "trade_state": "simulation",
            }
        )

        latest = db.get_latest_pipeline_run()

        self.assertEqual("newer-utc", latest["run_id"])
        self.assertEqual("2026-07-15T01:00:00+00:00", latest["started_at"])

    def test_pipeline_events_are_ordered_and_details_are_redacted(self):
        webhook = "https://discord.com/api/webhooks/" + "123/private-value"
        db.start_pipeline_run(
            {"run_id": "run-1", "profile": "mock", "trade_state": "simulation"}
        )
        db.save_pipeline_event(
            {
                "run_id": "run-1",
                "sequence": 2,
                "event_type": "screening.completed",
            }
        )
        db.save_pipeline_event(
            {
                "run_id": "run-1",
                "sequence": 1,
                "event_type": "pipeline.started",
                "details": {
                    "candidate_count": 3,
                    "webhook_url": webhook,
                },
            }
        )

        rows = db.get_pipeline_events("run-1")

        self.assertEqual([1, 2], [row["sequence"] for row in rows])
        self.assertEqual("succeeded", rows[0]["status"])
        details = json.loads(rows[0]["details"])
        self.assertEqual(3, details["candidate_count"])
        self.assertEqual("[REDACTED]", details["webhook_url"])

    def test_notification_delivery_is_upserted_without_persisting_secrets(self):
        webhook = "https://discord.com/api/webhooks/" + "123/private-value"
        token = "123456789:" + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        db.start_pipeline_run(
            {"run_id": "run-1", "profile": "mock", "trade_state": "simulation"}
        )
        db.save_notification_delivery(
            {
                "run_id": "run-1",
                "sequence": 1,
                "channel": "discord",
                "status": "queued",
                "attempts": 0,
                "webhook_url": webhook,
                "bot_token": token,
            }
        )
        db.save_notification_delivery(
            {
                "run_id": "run-1",
                "sequence": 1,
                "channel": "discord",
                "status": "failed",
                "attempts": 2,
                "error": f"POST {webhook} failed with token={token}",
                "webhook_url": webhook,
                "bot_token": token,
            }
        )

        row = self._fetch_delivery()
        with sqlite3.connect(db.DB_PATH) as conn:
            columns = {
                column[1]
                for column in conn.execute(
                    "PRAGMA table_info(notification_deliveries)"
                ).fetchall()
            }

        self.assertEqual("failed", row["status"])
        self.assertEqual(2, row["attempts"])
        self.assertIn("[REDACTED]", row["error"])
        persisted = json.dumps(row, ensure_ascii=False)
        self.assertNotIn(webhook, persisted)
        self.assertNotIn(token, persisted)
        self.assertFalse({"webhook_url", "bot_token", "token"} & columns)

    def test_notification_delivery_redacts_json_shaped_error_string(self):
        secret = "sk-" + "synthetic-sensitive"
        db.save_notification_delivery(
            {
                "run_id": "run-json",
                "sequence": 2,
                "channel": "telegram",
                "status": "failed",
                "error": json.dumps({"token": secret, "message": "request failed"}),
            }
        )

        row = self._fetch_delivery(sequence=2)

        self.assertNotIn(secret, row["error"])
        self.assertEqual("[REDACTED]", json.loads(row["error"])["token"])

    def test_notification_delivery_redacts_mapping_error(self):
        secret = "sk-" + "synthetic-sensitive"
        db.save_notification_delivery(
            {
                "run_id": "run-mapping",
                "sequence": 3,
                "channel": "discord",
                "status": "failed",
                "error": {"api_key": secret, "message": "request failed"},
            }
        )

        row = self._fetch_delivery(sequence=3)

        self.assertNotIn(secret, row["error"])
        self.assertEqual("[REDACTED]", json.loads(row["error"])["api_key"])

    def test_notification_delivery_redacts_prefixed_json_without_losing_context(self):
        secret = "sk-" + "synthetic-sensitive"
        error = "request failed: " + json.dumps(
            {"token": secret}, separators=(",", ":")
        )
        db.save_notification_delivery(
            {
                "run_id": "run-prefixed-json",
                "sequence": 4,
                "channel": "telegram",
                "status": "failed",
                "error": error,
            }
        )

        row = self._fetch_delivery(sequence=4)

        self.assertNotIn(secret, row["error"])
        self.assertTrue(row["error"].startswith("request failed: "))
        self.assertIn('"token":"[REDACTED]"', row["error"])


if __name__ == "__main__":
    unittest.main()
