import asyncio
import argparse
from datetime import datetime, timezone
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import operations
import operations_runtime


class OperationsTest(unittest.TestCase):
    def test_holding_monitor_only_executes_exit_decisions(self):
        holdings = [
            {
                "ticker": "005930",
                "entry_price": 80_000,
                "quantity": 2,
                "high_since_entry": 82_000,
            }
        ]
        sell = {
            "action": "SELL",
            "ticker": "005930",
            "quantity": 2,
            "price": 72_000,
            "reason": "손절",
        }

        with mock.patch(
            "operations.trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
        ), mock.patch(
            "operations.trading._load_holding_prices",
            new=mock.AsyncMock(return_value={"005930": 72_000}),
        ), mock.patch(
            "operations.trading._persist_holding_highs",
            new=mock.AsyncMock(),
        ), mock.patch(
            "operations.trading.run_exit_check",
            new=mock.AsyncMock(return_value=[sell]),
        ), mock.patch(
            "operations.trading._execute_decision",
            new=mock.AsyncMock(return_value={**sell, "status": "filled"}),
        ), mock.patch(
            "feedback.run_feedback",
            new=mock.AsyncMock(),
        ) as run_feedback:
            results = asyncio.run(operations.run_holding_monitor(dry_run=True))

        self.assertEqual([row["action"] for row in results], ["SELL"])
        run_feedback.assert_awaited_once_with(results, [])

    def test_holding_monitor_broker_execution_blocks_missing_quote_without_data_source(self):
        holdings = [
            {
                "ticker": "005930",
                "entry_price": 80_000,
                "quantity": 2,
                "high_since_entry": 82_000,
            }
        ]

        with mock.patch(
            "operations.trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
        ), mock.patch(
            "brokers.factory.get_broker_adapter",
            return_value=object(),
        ), mock.patch(
            "data_source.fetch_stock_data",
            side_effect=AssertionError("broker monitor exits must not use data_source"),
        ), mock.patch(
            "feedback.run_feedback",
            new=mock.AsyncMock(),
        ) as run_feedback:
            results = asyncio.run(operations.run_holding_monitor(dry_run=False))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "blocked")
        self.assertEqual(results[0]["mode"], "broker_quote_unavailable")
        self.assertTrue(results[0]["operational_alert"])
        run_feedback.assert_awaited_once_with(results, [])

    def test_reconciliation_is_read_only_and_isolates_provider_failure(self):
        with mock.patch(
            "operations.trading.reconcile_pending_kis_orders",
            new=mock.AsyncMock(side_effect=RuntimeError("temporary outage")),
        ):
            result = asyncio.run(operations.run_order_reconciliation("kis"))

        self.assertEqual(result["broker"], "kis")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["orders"], [])

    def test_kiwoom_reconciliation_dispatches_read_only_reader_with_adapter_and_mode(self):
        adapter = object()
        orders = [{"client_order_id": "lecture-kiwoom-1", "status": "accepted"}]
        reader = mock.AsyncMock(return_value=orders)

        with mock.patch(
            "operations.trading.reconcile_pending_kiwoom_orders",
            new=reader,
        ), mock.patch(
            "brokers.factory.get_broker_adapter",
            return_value=adapter,
        ) as get_adapter, mock.patch(
            "operations.trading._selected_broker_mode",
            return_value="demo",
        ) as selected_mode:
            result = asyncio.run(operations.run_order_reconciliation("kiwoom"))

        self.assertEqual(result["broker"], "kiwoom")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["orders"], orders)
        get_adapter.assert_called_once_with("kiwoom")
        selected_mode.assert_called_once_with("kiwoom")
        reader.assert_awaited_once_with(adapter=adapter, mode="demo")

    def test_status_output_reports_operations_snapshot_without_secret_values(self):
        self.assertTrue(hasattr(operations, "print_status"))
        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            store.record_scheduler_status("running", pid=9876, heartbeat_at="2026-08-08T09:30:00+00:00")
            store.record_job_success("monitor", "2026-08-08T09:31:00+00:00")
            out = StringIO()

            operations.print_status(
                state_store=store,
                output=out,
                profile="live",
                execute_broker=True,
                env={
                    "LECTURE_ENABLE_LIVE_BROKER": "1",
                    "LECTURE_ALLOW_REAL_BROKER": "1",
                    "LECTURE_UNATTENDED_LIVE_ACK": operations_runtime.LIVE_BROKER_UNATTENDED_ACK,
                    "OPENAI_API_KEY": "sk-secret-operations-status",
                    "KIS_APP_SECRET": "kis-secret-operations-status",
                },
                unresolved_order_count=lambda: 2,
                last_data_timestamp=lambda: "2026-08-08T09:29:00+00:00",
                now=lambda: "2026-08-08T09:32:00+00:00",
            )

        text = out.getvalue()
        self.assertIn("profile: live", text)
        self.assertIn("account_mode: real", text)
        self.assertIn("scheduler_pid: 9876", text)
        self.assertIn("scheduler_heartbeat: 2026-08-08T09:30:00+00:00", text)
        self.assertIn("monitor: success", text)
        self.assertIn("unresolved_order_count: 2", text)
        self.assertIn("last_data_timestamp: 2026-08-08T09:29:00+00:00", text)
        self.assertIn("next_jobs:", text)
        self.assertNotIn("sk-secret-operations-status", text)
        self.assertNotIn("kis-secret-operations-status", text)
        self.assertNotIn(operations_runtime.LIVE_BROKER_UNATTENDED_ACK, text)

    def test_scheduled_batch_uses_policy_dry_run_without_mutating_profile_environment(self):
        job = operations.JobSpec(
            name="analysis",
            at="09:30",
            weekdays=(0,),
            command="batch",
        )
        policy = operations_runtime.resolve_execution_policy(
            "paper",
            execute_broker=True,
            env={"LECTURE_ENABLE_LIVE_BROKER": "1"},
        )
        before = os.environ.get("LECTURE_PROFILE")

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "operations.run_analysis_batch",
                new=mock.AsyncMock(return_value={"ok": True}),
            ) as batch:
                asyncio.run(
                    operations.run_scheduled_job(
                        job,
                        state_store=operations_runtime.OperationsStateStore(Path(tmp)),
                        active_jobs=set(),
                        policy=policy,
                        config=mock.Mock(profile="paper"),
                        now=lambda: datetime.fromisoformat(
                            "2026-08-03T09:30:00+09:00"
                        ),
                    )
                )

        batch.assert_awaited_once()
        self.assertFalse(batch.await_args.kwargs["dry_run"])
        self.assertEqual(os.environ.get("LECTURE_PROFILE"), before)

    def test_scheduled_execute_broker_keeps_non_operating_profiles_in_simulation(self):
        job = operations.JobSpec(
            name="monitor",
            at="09:35",
            weekdays=(0,),
            command="monitor",
        )
        policy = operations_runtime.resolve_execution_policy(
            "research",
            execute_broker=True,
            env={"LECTURE_ENABLE_LIVE_BROKER": "1"},
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "operations.run_holding_monitor",
                new=mock.AsyncMock(return_value=[]),
            ) as monitor:
                asyncio.run(
                    operations.run_scheduled_job(
                        job,
                        state_store=operations_runtime.OperationsStateStore(Path(tmp)),
                        active_jobs=set(),
                        policy=policy,
                        config=mock.Mock(profile="research"),
                        now=lambda: datetime.fromisoformat(
                            "2026-08-03T09:35:00+09:00"
                        ),
                    )
                )

        monitor.assert_awaited_once()
        self.assertTrue(monitor.await_args.kwargs["dry_run"])

    def test_cli_profile_selects_runtime_config_without_setting_secret_environment(self):
        args = argparse.Namespace(
            command="batch",
            ticker="005930",
            broker=None,
            profile="paper",
            execute_broker=True,
            once=False,
            monitor_interval_minutes=10,
            reconcile_interval_minutes=30,
        )
        before = {
            "LECTURE_PROFILE": os.environ.get("LECTURE_PROFILE"),
            "KIS_APP_SECRET": os.environ.get("KIS_APP_SECRET"),
        }

        with mock.patch(
            "operations.run_analysis_batch",
            new=mock.AsyncMock(return_value={"ok": True}),
        ) as batch, mock.patch("builtins.print"):
            asyncio.run(operations._main(args))

        batch.assert_awaited_once()
        self.assertEqual(batch.await_args.kwargs["config"].profile, "paper")
        self.assertEqual(os.environ.get("LECTURE_PROFILE"), before["LECTURE_PROFILE"])
        self.assertEqual(os.environ.get("KIS_APP_SECRET"), before["KIS_APP_SECRET"])


class OperationsDoctorReviewFindingsTest(unittest.TestCase):
    def _kis_paper_env(self):
        return {
            "LECTURE_PROFILE": "paper",
            "LECTURE_BROKER": "kis",
            "LECTURE_ENABLE_LIVE_BROKER": "1",
            "KIS_PAPER_APP_KEY": "paper-key",
            "KIS_PAPER_APP_SECRET": "paper-secret",
            "KIS_PAPER_ACCOUNT_NO": "paper-account",
            "OPENAI_API_KEY": "sk-test",
            "PERPLEXITY_API_KEY": "pplx-test",
            "FIRECRAWL_API_KEY": "fc-test",
        }

    def _toss_wts_live_env(self):
        return {
            "LECTURE_PROFILE": "live",
            "LECTURE_BROKER": "toss",
            "LECTURE_TOSS_INTEGRATION": "wts",
            "LECTURE_ENABLE_LIVE_BROKER": "1",
            "LECTURE_ALLOW_REAL_BROKER": "1",
            "LECTURE_UNATTENDED_LIVE_ACK": "I_ACCEPT_REAL_ORDERS",
            "TOSSCTL_PATH": "/safe/fake/tossctl",
            "OPENAI_API_KEY": "sk-test",
            "PERPLEXITY_API_KEY": "pplx-test",
            "FIRECRAWL_API_KEY": "fc-test",
        }

    def test_default_kis_doctor_market_check_does_not_persist_market_day_cache(self):
        from operations_doctor import run_doctor

        class FakeKISBrokerAdapter:
            def __init__(self, *, mode=None, client=None, gate=None, clock=None):
                self.mode = mode
                self.client = client
                self.gate = gate
                self.clock = clock or (lambda: datetime.now(timezone.utc))

            async def check_authentication(self):
                return {"authenticated": True}

            async def is_market_open(self):
                if self.gate is not None:
                    return self.gate.check(self.clock())
                import db

                db.save_market_day("KR", "20260810", is_open=True)
                return {"is_open": True}

            async def get_account(self):
                return {"positions": [], "summary": []}

            async def get_orderable_quantity(self, ticker, price):
                return 1

            async def get_quote(self, ticker):
                return {"ticker": ticker, "price": 70100}

            async def get_pending_orders(self, *, business_date=None):
                return {"rows": []}

        class FakeMarketGate:
            def __init__(
                self,
                calendar_client,
                *,
                cache_get=None,
                cache_save=None,
                mode=None,
            ):
                self.cache_save = cache_save

            def check(self, now):
                if self.cache_save is not None:
                    self.cache_save("KR", "20260810", is_open=True)
                return {"is_open": True, "source": "api"}

        with mock.patch(
            "brokers.kis.KISBrokerAdapter",
            new=FakeKISBrokerAdapter,
        ), mock.patch(
            "brokers.kis_client.KISConfig.from_env",
            return_value=object(),
        ), mock.patch(
            "brokers.kis_client.KISClient",
            return_value=object(),
        ), mock.patch(
            "market_calendar.MarketGate",
            new=FakeMarketGate,
        ), mock.patch(
            "db.save_market_day",
            side_effect=AssertionError("doctor must not persist market-day cache"),
        ) as save_market_day:
            report = asyncio.run(
                run_doctor(
                    profile="paper",
                    env=self._kis_paper_env(),
                    unresolved_order_count=lambda: 0,
                    directory_writable=lambda _path: True,
                )
            )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(checks["kis_market_day"].status, "READY")
        save_market_day.assert_not_called()

    def test_toss_wts_doctor_blocks_missing_quote_capability(self):
        from operations_doctor import run_doctor

        class NoQuoteTossWTSAdapter:
            async def check_auth(self):
                return {"success": True, "status": "active"}

            async def get_account(self):
                return {"orderable_amount_krw": 100000}

            async def get_sellable_quantity(self, ticker):
                return 2

            async def get_pending_orders(self):
                return []

            async def get_order_status(self, order_no):
                return {"status": "accepted", "terminal": False}

        report = asyncio.run(
            run_doctor(
                profile="live",
                env=self._toss_wts_live_env(),
                toss_wts_adapter_factory=NoQuoteTossWTSAdapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(checks["toss_wts_fresh_quote"].status, "BLOCKED")
        self.assertNotEqual(checks["toss_wts_fresh_quote"].status, "READY")


if __name__ == "__main__":
    unittest.main()
