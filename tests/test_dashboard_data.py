from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import db
import main
import trading


class DashboardSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._temp_dir.name) / "prism.db"

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._temp_dir.cleanup()

    @staticmethod
    def _start_run(
        run_id: str,
        *,
        started_at: str = "2026-07-15T00:00:00+00:00",
        profile: str = "paper",
        trade_state: str = "simulation",
        data_source: str = "yfinance",
        data_as_of: str = "2026-07-14",
        market_status: str = "closed",
    ) -> None:
        db.start_pipeline_run(
            {
                "run_id": run_id,
                "started_at": started_at,
                "profile": profile,
                "trade_state": trade_state,
                "data_source": data_source,
                "data_as_of": data_as_of,
                "market_status": market_status,
            }
        )

    @staticmethod
    def _order(
        run_id: str,
        request_id: str,
        status: str,
        *,
        requested_qty: int = 5,
        filled_qty: int = 0,
        requested_price: int = 100,
        avg_fill_price: float | None = None,
        side: str = "BUY",
        message: str = "",
    ) -> dict:
        return {
            "run_id": run_id,
            "broker": "kis",
            "mode": "paper",
            "client_request_id": request_id,
            "order_date": "2026-07-15",
            "org_no": "private-org",
            "order_no": f"order-{request_id}",
            "ticker": "005930",
            "side": side,
            "status": status,
            "requested_qty": requested_qty,
            "filled_qty": filled_qty,
            "remaining_qty": requested_qty - filled_qty,
            "requested_price": requested_price,
            "avg_fill_price": avg_fill_price,
            "message": message,
        }

    def test_empty_snapshot_is_truthful_and_does_not_invent_cash(self):
        snapshot = db.get_dashboard_snapshot()

        self.assertIsNone(snapshot["run"])
        for key in (
            "events", "deliveries", "orders", "positions", "analyses", "lessons"
        ):
            self.assertEqual([], snapshot[key])
        self.assertEqual(
            {
                "source": "selected_run_fills",
                "limitations": "현금과 계좌 평가액은 저장하지 않아 표시하지 않습니다.",
                "cash": None,
                "cash_known": False,
                "position_count": 0,
                "known_position_value": 0,
            },
            snapshot["portfolio"],
        )

    def test_latest_snapshot_is_one_run_story_with_provenance(self):
        self._start_run("older", started_at="2026-07-14T00:00:00+00:00")
        self._start_run(
            "selected",
            started_at="2026-07-15T00:00:00+00:00",
            profile="real_data",
            data_source="yfinance",
            data_as_of="2026-07-11",
        )
        for run_id, ticker in (("older", "000660"), ("selected", "005930")):
            db.save_pipeline_event(
                {
                    "run_id": run_id,
                    "sequence": 1,
                    "event_type": "analysis.completed",
                    "ticker": ticker,
                    "details": {"candidate_count": 1},
                }
            )
            db.save_analysis(
                {
                    "run_id": run_id,
                    "ticker": ticker,
                    "recommendation": "BUY",
                    "buy_score": 7,
                    "rationale": "테스트 판단",
                }
            )
            db.save_lesson(ticker, "BUY", "테스트 교훈", run_id=run_id)

        snapshot = db.get_dashboard_snapshot("latest")

        self.assertEqual("selected", snapshot["run"]["run_id"])
        self.assertEqual("real_data", snapshot["run"]["profile"])
        self.assertEqual("yfinance", snapshot["run"]["data_source"])
        self.assertEqual("2026-07-11", snapshot["run"]["data_as_of"])
        self.assertEqual(["005930"], [row["ticker"] for row in snapshot["analyses"]])
        self.assertEqual(["005930"], [row["ticker"] for row in snapshot["lessons"]])
        self.assertTrue(
            all(
                row["run_id"] == "selected"
                for key in ("events", "analyses", "lessons")
                for row in snapshot[key]
            )
        )

    def test_failed_run_decodes_safe_details_and_redacts_xss_and_secrets(self):
        secret = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        self._start_run("failed-run")
        db.save_pipeline_event(
            {
                "run_id": "failed-run",
                "sequence": 2,
                "event_type": "pipeline.failed",
                "status": "failed",
                "summary": "<script>alert('x')</script>",
                "details": {
                    "failure_stage": "analysis",
                    "bot_token": secret,
                    "safe_note": "<img src=x onerror=alert(1)>",
                },
            }
        )
        db.save_pipeline_event(
            {
                "run_id": "failed-run",
                "sequence": 1,
                "event_type": "pipeline.started",
            }
        )
        db.finish_pipeline_run("failed-run", "failed", failure_stage="analysis")

        snapshot = db.get_dashboard_snapshot("failed-run")
        serialized = json.dumps(snapshot, ensure_ascii=False)

        self.assertEqual("failed", snapshot["run"]["status"])
        self.assertEqual("analysis", snapshot["run"]["failure_stage"])
        self.assertEqual([1, 2], [event["sequence"] for event in snapshot["events"]])
        self.assertIsInstance(snapshot["events"][1]["details"], dict)
        self.assertEqual(
            "[REDACTED]", snapshot["events"][1]["details"]["bot_token"]
        )
        self.assertNotIn(secret, serialized)
        self.assertNotIn("<script>", serialized)
        self.assertNotIn("<img", serialized)

    def test_order_states_stay_distinct_and_only_filled_quantity_is_a_position(self):
        self._start_run("run-orders", trade_state="paper")
        orders = [
            self._order("run-orders", "accepted", "accepted"),
            self._order(
                "run-orders", "partial", "partial_fill", filled_qty=2,
                avg_fill_price=100,
            ),
            self._order(
                "run-orders", "filled", "filled", requested_qty=3,
                filled_qty=3, requested_price=110, avg_fill_price=110,
            ),
            self._order(
                "run-orders", "blocked", "blocked",
                message="<script>bad</script> token=private-value",
            ),
        ]
        for order in orders:
            db.save_broker_order(order)

        snapshot = db.get_dashboard_snapshot("run-orders")

        self.assertEqual(
            ["accepted", "partial_fill", "filled", "blocked"],
            [order["status"] for order in snapshot["orders"]],
        )
        self.assertEqual(
            {
                "run_id", "broker", "mode", "order_date", "order_no", "ticker",
                "side", "status", "requested_qty", "filled_qty", "remaining_qty",
                "requested_price", "avg_fill_price", "message", "created_at",
                "updated_at",
            },
            set(snapshot["orders"][0]),
        )
        self.assertNotIn("private-org", json.dumps(snapshot, ensure_ascii=False))
        self.assertEqual(
            [
                {
                    "run_id": "run-orders",
                    "ticker": "005930",
                    "quantity": 5,
                    "average_price": 106.0,
                    "source": "broker_fills",
                    "mode": "paper",
                }
            ],
            snapshot["positions"],
        )
        self.assertEqual(530.0, snapshot["portfolio"]["known_position_value"])

    def test_blocked_order_never_becomes_a_position(self):
        self._start_run("run-blocked", trade_state="paper")
        db.save_broker_order(self._order("run-blocked", "blocked", "blocked"))

        snapshot = db.get_dashboard_snapshot("run-blocked")

        self.assertEqual([], snapshot["positions"])
        self.assertEqual("blocked", snapshot["orders"][0]["status"])

    def test_completed_simulation_trades_create_only_selected_run_position(self):
        self._start_run("run-sim")
        self._start_run("other", started_at="2026-07-14T00:00:00+00:00")
        db.save_trade(
            {
                "run_id": "run-sim", "ticker": "035420", "action": "BUY",
                "executed_price": 100, "quantity": 4, "mode": "simulation",
            }
        )
        db.save_trade(
            {
                "run_id": "run-sim", "ticker": "035420", "action": "SELL",
                "executed_price": 120, "quantity": 1, "mode": "simulation",
            }
        )
        db.save_trade(
            {
                "run_id": "run-sim", "ticker": "035420", "action": "BUY",
                "executed_price": 100, "quantity": 99, "mode": "kis_demo",
            }
        )
        db.save_trade(
            {
                "run_id": "other", "ticker": "035420", "action": "BUY",
                "executed_price": 100, "quantity": 100, "mode": "simulation",
            }
        )

        snapshot = db.get_dashboard_snapshot("run-sim")

        self.assertEqual(
            [
                {
                    "run_id": "run-sim",
                    "ticker": "035420",
                    "quantity": 3,
                    "average_price": 100.0,
                    "source": "simulation_trades",
                    "mode": "simulation",
                }
            ],
            snapshot["positions"],
        )

    def test_deliveries_analyses_and_lessons_are_safe_allowlisted_rows(self):
        secret = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        self._start_run("run-safe")
        db.save_notification_delivery(
            {
                "run_id": "run-safe",
                "sequence": 4,
                "channel": "telegram",
                "status": "failed",
                "attempts": 2,
                "error": f"<b>실패</b> token={secret}",
            }
        )
        db.save_analysis(
            {
                "run_id": "run-safe",
                "ticker": "005930",
                "recommendation": "BUY",
                "buy_score": 8,
                "rationale": "<script>분석</script>",
                "technical_summary": f"돌파 token={secret}",
            }
        )
        db.save_lesson(
            "005930", "BUY", "<img src=x onerror=bad> 교훈", run_id="run-safe"
        )

        snapshot = db.get_dashboard_snapshot("run-safe")
        serialized = json.dumps(snapshot, ensure_ascii=False)

        self.assertEqual(
            {
                "run_id", "sequence", "channel", "status", "attempts",
                "queued_at", "completed_at", "error",
            },
            set(snapshot["deliveries"][0]),
        )
        self.assertEqual(
            {
                "run_id", "timestamp", "ticker", "recommendation", "score",
                "reason", "risk", "sections",
            },
            set(snapshot["analyses"][0]),
        )
        self.assertIsInstance(snapshot["analyses"][0]["sections"], dict)
        self.assertEqual(
            {
                "run_id", "timestamp", "ticker", "action", "lesson", "tier",
                "error_type",
            },
            set(snapshot["lessons"][0]),
        )
        self.assertNotIn(secret, serialized)
        self.assertNotIn("<script>", serialized)
        self.assertNotIn("<img", serialized)

    def test_run_id_migration_is_additive_and_idempotent(self):
        with sqlite3.connect(db.DB_PATH) as conn:
            conn.executescript(
                """
                CREATE TABLE trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    price INTEGER,
                    quantity INTEGER,
                    mode TEXT DEFAULT 'simulation',
                    reason TEXT
                );
                CREATE TABLE analysis_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    score INTEGER,
                    reason TEXT,
                    risk TEXT
                );
                CREATE TABLE feedback_lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    tier TEXT DEFAULT 'short',
                    error_type TEXT DEFAULT 'JUDGMENT'
                );
                CREATE TABLE broker_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    client_request_id TEXT NOT NULL,
                    order_date TEXT NOT NULL,
                    org_no TEXT,
                    order_no TEXT,
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_qty INTEGER NOT NULL,
                    filled_qty INTEGER NOT NULL DEFAULT 0,
                    remaining_qty INTEGER NOT NULL,
                    requested_price INTEGER,
                    avg_fill_price REAL,
                    message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(broker, mode, client_request_id)
                );
                INSERT INTO trade_history
                    (timestamp, ticker, action, price, quantity, mode)
                VALUES ('2026-07-14T00:00:00', '005930', 'BUY', 70000, 1, 'simulation');
                """
            )

        db.init_db()
        db.init_db()

        with sqlite3.connect(db.DB_PATH) as conn:
            for table in (
                "broker_orders", "analysis_decisions", "trade_history",
                "feedback_lessons",
            ):
                columns = {
                    row[1] for row in conn.execute(f"PRAGMA table_info({table})")
                }
                self.assertIn("run_id", columns)
            preserved = conn.execute(
                "SELECT ticker, quantity, run_id FROM trade_history"
            ).fetchone()
            self.assertEqual(("005930", 1, None), preserved)


class RunIdPropagationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._temp_dir.name) / "prism.db"

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._temp_dir.cleanup()

    async def test_main_propagates_run_id_to_analysis_trade_and_lesson(self):
        analysis = {
            "ticker": "005930",
            "recommendation": "BUY",
            "decision": "매수",
            "buy_score": 8,
            "target_price": 120_000,
            "rationale": "거래량 증가",
            "data_source": "yfinance",
            "data_as_of": "2026-07-11",
        }
        trade = {
            "ticker": "005930",
            "action": "BUY",
            "price": 100,
            "quantity": 2,
            "executed": True,
            "executed_price": 100,
            "mode": "simulation",
        }

        with patch(
            "screening.run_screening", new=AsyncMock(return_value=["005930"])
        ), patch(
            "analysis.run_analysis", new=AsyncMock(return_value=analysis)
        ), patch(
            "report_writer.write_reports", return_value=[]
        ), patch(
            "trading.run_trading", new=AsyncMock(return_value=[trade])
        ):
            await main.run_pipeline()

        snapshot = db.get_dashboard_snapshot("latest")
        run_id = snapshot["run"]["run_id"]
        self.assertEqual([run_id], [row["run_id"] for row in snapshot["analyses"]])
        self.assertEqual([run_id], [row["run_id"] for row in snapshot["lessons"]])
        self.assertEqual(run_id, snapshot["positions"][0]["run_id"])

    def test_trading_decision_preserves_optional_run_id(self):
        decision = trading._decide_position(
            {
                "run_id": "run-trading",
                "ticker": "005930",
                "buy_score": 8,
                "current_price": 70_000,
            },
            {"slots_used": 0, "cash": 10_000_000},
        )

        self.assertEqual("run-trading", decision["run_id"])
