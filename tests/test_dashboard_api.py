from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import dashboard
import db


class DashboardAPITests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._temp_dir.name) / "prism.db"
        self._dashboard_had_db_path = hasattr(dashboard, "DB_PATH")
        self._dashboard_db_path = getattr(dashboard, "DB_PATH", None)
        dashboard.DB_PATH = db.DB_PATH

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        if self._dashboard_had_db_path:
            dashboard.DB_PATH = self._dashboard_db_path
        else:
            del dashboard.DB_PATH
        self._temp_dir.cleanup()

    def _client(self) -> TestClient:
        return TestClient(dashboard.app)

    @staticmethod
    def _seed_run(run_id: str = "run-ui") -> None:
        db.start_pipeline_run(
            {
                "run_id": run_id,
                "started_at": "2026-07-15T00:00:00+00:00",
                "profile": "paper",
                "trade_state": "paper",
                "data_source": "yfinance",
                "data_as_of": "2026-07-11",
                "market_status": "closed",
            }
        )
        db.save_pipeline_event(
            {
                "run_id": run_id,
                "sequence": 1,
                "event_type": "pipeline.started",
                "status": "succeeded",
                "summary": "파이프라인 시작",
            }
        )
        db.save_notification_delivery(
            {
                "run_id": run_id,
                "sequence": 1,
                "channel": "telegram",
                "status": "sent",
                "attempts": 1,
            }
        )
        db.save_analysis(
            {
                "run_id": run_id,
                "ticker": "005930",
                "recommendation": "BUY",
                "buy_score": 8,
                "rationale": "거래량 증가",
                "technical_summary": "20일선 돌파",
                "supply_summary": "수급 개선",
                "financial_summary": "재무 안정",
                "industry_summary": "반도체 회복",
                "news_summary": "신규 공급 계약",
                "market_condition": "휴장 · 최근 영업일 데이터",
            }
        )
        db.save_trade(
            {
                "run_id": run_id,
                "ticker": "005930",
                "action": "BUY",
                "executed_price": 70_000,
                "quantity": 2,
                "mode": "simulation",
            }
        )
        db.save_lesson(
            "005930", "BUY", "체결된 수량만 보유로 본다.", run_id=run_id
        )
        db.finish_pipeline_run(run_id, "succeeded")

    def test_lifespan_uses_canonical_schema_without_demo_seed(self):
        with self._client():
            pass

        with sqlite3.connect(db.DB_PATH) as connection:
            counts = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in (
                    "trade_history", "analysis_decisions", "feedback_lessons"
                )
            }

        self.assertEqual(
            {
                "trade_history": 0,
                "analysis_decisions": 0,
                "feedback_lessons": 0,
            },
            counts,
        )

    def test_api_dashboard_returns_selected_run_snapshot(self):
        self._seed_run()

        with self._client() as client:
            response = client.get("/api/dashboard", params={"run_id": "run-ui"})

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("run-ui", payload["run"]["run_id"])
        self.assertEqual("yfinance", payload["run"]["data_source"])
        self.assertEqual("2026-07-11", payload["run"]["data_as_of"])
        self.assertEqual([1], [event["sequence"] for event in payload["events"]])
        self.assertEqual("sent", payload["deliveries"][0]["status"])
        self.assertEqual(2, payload["positions"][0]["quantity"])
        self.assertEqual(6, len(payload["analyses"][0]["sections"]))

    def test_api_data_is_compatible_alias_for_run_scoped_snapshot(self):
        self._seed_run()

        with self._client() as client:
            canonical = client.get(
                "/api/dashboard", params={"run_id": "run-ui"}
            ).json()
            compatible = client.get(
                "/api/data", params={"run_id": "run-ui"}
            ).json()

        self.assertEqual(canonical, compatible)

    def test_unknown_run_is_an_honest_empty_state(self):
        with self._client() as client:
            response = client.get(
                "/api/dashboard", params={"run_id": "missing"}
            )

        self.assertEqual(200, response.status_code)
        payload = response.json()

        self.assertIsNone(payload["run"])
        self.assertEqual([], payload["positions"])
        self.assertIsNone(payload["portfolio"]["cash"])
        self.assertFalse(payload["portfolio"]["cash_known"])

    def test_page_is_local_accessible_responsive_and_polling_run_scoped(self):
        with self._client() as client:
            response = client.get("/")

        self.assertEqual(200, response.status_code)
        html = response.text
        for section_id in (
            "truth-bar",
            "pipeline-timeline",
            "notification-health",
            "order-truth",
            "portfolio",
            "analyses",
            "lessons",
            "empty-state",
        ):
            self.assertIn(f'id="{section_id}"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("prefers-reduced-motion", html)
        self.assertIn("@media (max-width:", html)
        self.assertIn("textContent", html)
        self.assertNotIn("innerHTML", html)
        self.assertIn("/api/dashboard", html)
        self.assertIn("run_id", html)
        self.assertIn("5000", html)
        self.assertNotIn("https://fonts", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("실시간 대시보드", html)

    def test_page_contains_plain_language_operational_states(self):
        with self._client() as client:
            html = client.get("/").text

        for label in (
            "주문 접수",
            "부분 체결",
            "체결",
            "차단",
            "Discord",
            "Telegram",
            "데이터 기준일",
            "현금 잔고를 추정하지 않습니다",
        ):
            self.assertIn(label, html)

    def test_api_and_page_do_not_embed_raw_xss_payload(self):
        self._seed_run("run-xss")
        db.save_pipeline_event(
            {
                "run_id": "run-xss",
                "sequence": 2,
                "event_type": "pipeline.failed",
                "status": "failed",
                "summary": "<script>alert(1)</script>",
                "details": {"safe_note": "<img src=x onerror=alert(1)>"},
            }
        )

        with self._client() as client:
            api_response = client.get(
                "/api/dashboard", params={"run_id": "run-xss"}
            )
            page_text = client.get("/").text

        self.assertEqual(200, api_response.status_code)
        api_text = json.dumps(api_response.json(), ensure_ascii=False)
        self.assertNotIn("<script>", api_text)
        self.assertNotIn("<img", api_text)
        self.assertNotIn("alert(1)", page_text)

    def test_server_binds_loopback_only(self):
        self.assertEqual("127.0.0.1", dashboard.DASHBOARD_HOST)

    def test_server_rejects_untrusted_host_header(self):
        with self._client() as client:
            response = client.get("/api/dashboard", headers={"Host": "attacker.example"})

        self.assertEqual(400, response.status_code)
