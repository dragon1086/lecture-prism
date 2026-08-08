import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import operations
import operations_runtime


class RecordingNotifier:
    def __init__(self) -> None:
        self.events = []

    async def operational(self, event, context=None):
        self.events.append((event, context or {}))
        return True


class OperationsScheduleTest(unittest.TestCase):
    def test_due_jobs_match_weekday_and_exact_minute(self):
        jobs = [
            operations.JobSpec(
                name="analysis",
                at="09:30",
                weekdays=(0, 1, 2, 3, 4),
                command="batch",
            ),
            operations.JobSpec(
                name="compression",
                at="03:00",
                weekdays=(6,),
                command="compress",
            ),
        ]

        monday = datetime(2026, 8, 3, 9, 30)
        self.assertEqual(
            [job.name for job in operations.due_jobs(monday, jobs)],
            ["analysis"],
        )

    def test_due_jobs_interpret_aware_datetimes_in_kst(self):
        job = operations.JobSpec(
            name="analysis",
            at="09:30",
            weekdays=(0, 1, 2, 3, 4),
            command="batch",
        )
        monday_utc = datetime.fromisoformat("2026-08-03T00:30:00+00:00")

        self.assertEqual(
            [item.name for item in operations.due_jobs(monday_utc, [job])],
            ["analysis"],
        )

    def test_build_schedule_uses_configurable_intraday_intervals(self):
        jobs = operations.build_schedule(
            monitor_interval_minutes=15,
            reconcile_interval_minutes=45,
        )
        monitor_times = [
            job.at
            for job in jobs
            if job.command == "monitor" and job.name.startswith("장중")
        ]
        reconcile_times = [
            job.at
            for job in jobs
            if job.command == "reconcile" and job.name.startswith("장중")
        ]

        self.assertEqual(monitor_times[:3], ["09:35", "09:50", "10:05"])
        self.assertEqual(reconcile_times[:3], ["10:00", "10:45", "11:30"])
        self.assertIn("15:20", monitor_times)
        self.assertNotIn("15:35", monitor_times)

    def test_build_schedule_has_unique_command_minutes(self):
        jobs = operations.build_schedule()
        command_minutes = [(job.command, job.at) for job in jobs]

        self.assertEqual(len(command_minutes), len(set(command_minutes)))

    def test_due_jobs_runs_one_command_once_when_names_collide_in_same_minute(self):
        jobs = [
            operations.JobSpec("legacy monitor", "14:55", (0,), "monitor"),
            operations.JobSpec("interval monitor", "14:55", (0,), "monitor"),
        ]
        seen = set()

        first = operations.due_jobs(datetime(2026, 8, 3, 14, 55), jobs, seen=seen)
        second = operations.due_jobs(datetime(2026, 8, 3, 14, 55), jobs, seen=seen)

        self.assertEqual([job.command for job in first], ["monitor"])
        self.assertEqual(second, [])

    def test_next_run_after_skips_weekends_in_kst(self):
        job = operations.JobSpec(
            name="analysis",
            at="09:30",
            weekdays=(0, 1, 2, 3, 4),
            command="batch",
        )
        friday_after_close = datetime.fromisoformat("2026-08-07T16:00:00+09:00")

        next_run = operations.next_run_after(friday_after_close, [job])

        self.assertEqual(next_run.isoformat(), "2026-08-10T09:30:00+09:00")

    def test_due_jobs_do_not_repeat_in_same_minute(self):
        job = operations.JobSpec(
            name="monitor",
            at="10:00",
            weekdays=(0,),
            command="monitor",
        )
        now = datetime(2026, 8, 3, 10, 0)
        seen = set()

        first = operations.due_jobs(now, [job], seen=seen)
        second = operations.due_jobs(now, [job], seen=seen)

        self.assertEqual([item.name for item in first], ["monitor"])
        self.assertEqual(second, [])

    def test_invalid_schedule_time_is_rejected(self):
        with self.assertRaises(ValueError):
            operations.JobSpec(
                name="broken",
                at="25:90",
                weekdays=(0,),
                command="batch",
            )

    def test_overlapping_same_job_is_persisted_as_skipped_overlap(self):
        self.assertTrue(hasattr(operations, "run_scheduled_job"))
        job = operations.JobSpec(
            name="monitor",
            at="10:00",
            weekdays=(0,),
            command="monitor",
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            with mock.patch("operations.run_job", new=mock.AsyncMock()) as run_job:
                result = asyncio.run(
                    operations.run_scheduled_job(
                        job,
                        state_store=store,
                        active_jobs={"monitor"},
                        now=lambda: datetime(2026, 8, 3, 10, 0),
                    )
                )
            state = store.read()

        self.assertEqual(result["status"], "skipped_overlap")
        self.assertEqual(state["jobs"]["monitor"]["status"], "skipped_overlap")
        run_job.assert_not_awaited()

    def test_market_closed_blocks_broker_executing_paper_job_but_not_simulation(self):
        job = operations.JobSpec(
            name="monitor",
            at="09:35",
            weekdays=(0,),
            command="monitor",
        )
        paper_policy = operations_runtime.resolve_execution_policy(
            "paper",
            execute_broker=True,
            env={"LECTURE_ENABLE_LIVE_BROKER": "1"},
        )
        mock_policy = operations_runtime.resolve_execution_policy(
            "mock",
            execute_broker=True,
            env={"LECTURE_ENABLE_LIVE_BROKER": "1"},
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            with mock.patch("operations.run_job", new=mock.AsyncMock()) as run_job:
                blocked = asyncio.run(
                    operations.run_scheduled_job(
                        job,
                        state_store=store,
                        active_jobs=set(),
                        policy=paper_policy,
                        config=mock.Mock(profile="paper"),
                        market_open_checker=lambda _now: False,
                        now=lambda: datetime.fromisoformat("2026-08-03T09:35:00+09:00"),
                    )
                )
                simulated = asyncio.run(
                    operations.run_scheduled_job(
                        job,
                        state_store=store,
                        active_jobs=set(),
                        policy=mock_policy,
                        config=mock.Mock(profile="mock"),
                        market_open_checker=lambda _now: False,
                        now=lambda: datetime.fromisoformat("2026-08-03T09:35:00+09:00"),
                    )
                )

        self.assertEqual(blocked["status"], "skipped_market_closed")
        self.assertEqual(simulated["status"], "success")
        run_job.assert_awaited_once()

    def test_market_closed_check_defaults_to_kst_market_hours_for_broker_execution(self):
        job = operations.JobSpec(
            name="monitor",
            at="08:59",
            weekdays=(0,),
            command="monitor",
        )
        policy = operations_runtime.resolve_execution_policy(
            "paper",
            execute_broker=True,
            env={"LECTURE_ENABLE_LIVE_BROKER": "1"},
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            with mock.patch("operations.run_job", new=mock.AsyncMock()) as run_job:
                result = asyncio.run(
                    operations.run_scheduled_job(
                        job,
                        state_store=store,
                        active_jobs=set(),
                        policy=policy,
                        config=mock.Mock(profile="paper"),
                        now=lambda: datetime.fromisoformat("2026-08-03T08:59:00+09:00"),
                    )
                )

        self.assertEqual(result["status"], "skipped_market_closed")
        run_job.assert_not_awaited()

    def test_operations_log_rotates_by_kst_date_and_size_and_sanitizes_fields(self):
        current = [datetime.fromisoformat("2026-08-03T09:00:00+09:00")]
        with tempfile.TemporaryDirectory() as tmp:
            logger = operations_runtime.configure_operations_logger(
                "tests.operations.rotating",
                Path(tmp),
                max_bytes=160,
                now=lambda: current[0],
            )
            operations_runtime.log_operation(
                logger,
                "service_start",
                profile="live",
                account_number="123-456",
                balance=987654321,
                token="ops-token-value",
                webhook_url="https://broker.example/secret",
                error=RuntimeError("raw outage sk-secret-ops"),
            )
            operations_runtime.log_operation(logger, "job_success", job="monitor")
            current[0] = datetime.fromisoformat("2026-08-04T09:00:00+09:00")
            operations_runtime.log_operation(logger, "service_stop", profile="live")
            for handler in logger.handlers:
                handler.flush()

            files = sorted(path.name for path in Path(tmp).glob("operations-*.log*"))
            rendered = "\n".join(
                path.read_text(encoding="utf-8")
                for path in sorted(Path(tmp).glob("operations-*.log*"))
            )

        self.assertIn("operations-2026-08-03.log", files)
        self.assertIn("operations-2026-08-04.log", files)
        self.assertGreaterEqual(
            len([name for name in files if name.startswith("operations-2026-08-03")]),
            2,
        )
        self.assertIn("event=service_start", rendered)
        self.assertIn("event=service_stop", rendered)
        self.assertIn("profile=live", rendered)
        self.assertIn("<redacted>", rendered)
        self.assertNotIn("123-456", rendered)
        self.assertNotIn("987654321", rendered)
        self.assertNotIn("ops-token-value", rendered)
        self.assertNotIn("https://broker.example", rendered)
        self.assertNotIn("raw outage", rendered)

    def test_scheduled_job_writes_structured_operations_log_lines(self):
        job = operations.JobSpec(
            name="monitor",
            at="09:35",
            weekdays=(0,),
            command="monitor",
        )
        with tempfile.TemporaryDirectory() as tmp:
            logger = operations_runtime.configure_operations_logger(
                "tests.operations.joblog",
                Path(tmp),
                max_bytes=10_000,
                now=lambda: datetime.fromisoformat("2026-08-03T09:35:00+09:00"),
            )
            store = operations_runtime.OperationsStateStore(Path(tmp) / "state")
            with mock.patch("operations.run_job", new=mock.AsyncMock()):
                asyncio.run(
                    operations.run_scheduled_job(
                        job,
                        state_store=store,
                        active_jobs=set(),
                        operations_logger=logger,
                        now=lambda: datetime.fromisoformat("2026-08-03T09:35:00+09:00"),
                    )
                )
            for handler in logger.handlers:
                handler.flush()
            rendered = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(tmp).glob("operations-*.log*")
            )

        self.assertIn("event=job_start", rendered)
        self.assertIn("event=job_success", rendered)
        self.assertIn("job=monitor", rendered)

    def test_reconciliation_unavailable_is_persisted_logged_and_notified_as_failure(self):
        job = operations.JobSpec(
            name="reconcile",
            at="10:00",
            weekdays=(0,),
            command="reconcile",
        )
        notifier = RecordingNotifier()
        with tempfile.TemporaryDirectory() as tmp:
            logger = operations_runtime.configure_operations_logger(
                "tests.operations.reconcile_failure",
                Path(tmp),
                max_bytes=10_000,
                now=lambda: datetime.fromisoformat("2026-08-03T10:00:00+09:00"),
            )
            store = operations_runtime.OperationsStateStore(Path(tmp) / "state")
            with mock.patch(
                "operations.run_order_reconciliation",
                new=mock.AsyncMock(
                    return_value={
                        "broker": "kis",
                        "status": "unavailable",
                        "orders": [],
                        "error_type": "TimeoutError",
                        "raw": "api_key=leak Authorization: Bearer leak-token",
                    }
                ),
            ):
                result = asyncio.run(
                    operations.run_scheduled_job(
                        job,
                        state_store=store,
                        active_jobs=set(),
                        notifier=notifier,
                        operations_logger=logger,
                        now=lambda: datetime.fromisoformat("2026-08-03T10:00:00+09:00"),
                    )
                )
            for handler in logger.handlers:
                handler.flush()
            state = store.read()
            rendered = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(tmp).glob("operations-*.log*")
            )

        self.assertEqual(result["status"], "failure")
        self.assertEqual(state["jobs"]["reconcile"]["status"], "failure")
        self.assertEqual(state["jobs"]["reconcile"]["error_type"], "ReconciliationFailure")
        self.assertIn("event=reconciliation_failure", rendered)
        self.assertNotIn("leak-token", rendered)
        self.assertEqual([event for event, _ in notifier.events], ["reconciliation_failure"])

    def test_stale_data_result_is_persisted_logged_and_notified_without_prose_parsing(self):
        job = operations.JobSpec(
            name="monitor",
            at="10:00",
            weekdays=(0,),
            command="monitor",
        )
        notifier = RecordingNotifier()
        with tempfile.TemporaryDirectory() as tmp:
            logger = operations_runtime.configure_operations_logger(
                "tests.operations.stale_data",
                Path(tmp),
                max_bytes=10_000,
                now=lambda: datetime.fromisoformat("2026-08-03T10:00:00+09:00"),
            )
            store = operations_runtime.OperationsStateStore(Path(tmp) / "state")
            with mock.patch(
                "operations.run_job",
                new=mock.AsyncMock(
                    return_value={
                        "status": "blocked_stale_data",
                        "reason_code": "stale_data",
                        "ticker": "005930",
                        "message": "normal ticker 005930 price 71200 remains visible",
                    }
                ),
            ):
                result = asyncio.run(
                    operations.run_scheduled_job(
                        job,
                        state_store=store,
                        active_jobs=set(),
                        notifier=notifier,
                        operations_logger=logger,
                        now=lambda: datetime.fromisoformat("2026-08-03T10:00:00+09:00"),
                    )
                )
            for handler in logger.handlers:
                handler.flush()
            state = store.read()
            rendered = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(tmp).glob("operations-*.log*")
            )

        self.assertEqual(result["status"], "stale_data")
        self.assertEqual(state["jobs"]["monitor"]["status"], "failure")
        self.assertEqual(state["jobs"]["monitor"]["error_type"], "StaleData")
        self.assertIn("event=stale_data", rendered)
        self.assertIn("005930", rendered)
        self.assertIn("71200", rendered)
        self.assertEqual([event for event, _ in notifier.events], ["stale_data"])

    def test_typed_stale_data_signal_is_persisted_logged_and_notified(self):
        job = operations.JobSpec(
            name="batch",
            at="10:00",
            weekdays=(0,),
            command="batch",
        )
        notifier = RecordingNotifier()
        with tempfile.TemporaryDirectory() as tmp:
            logger = operations_runtime.configure_operations_logger(
                "tests.operations.stale_signal",
                Path(tmp),
                max_bytes=10_000,
                now=lambda: datetime.fromisoformat("2026-08-03T10:00:00+09:00"),
            )
            store = operations_runtime.OperationsStateStore(Path(tmp) / "state")
            with mock.patch(
                "operations.run_job",
                new=mock.AsyncMock(
                    side_effect=operations.StaleDataSignal(
                        reason_code="stale_data",
                        last_data_at="2026-08-01T09:00:00+09:00",
                    )
                ),
            ):
                result = asyncio.run(
                    operations.run_scheduled_job(
                        job,
                        state_store=store,
                        active_jobs=set(),
                        notifier=notifier,
                        operations_logger=logger,
                        now=lambda: datetime.fromisoformat("2026-08-03T10:00:00+09:00"),
                    )
                )
            state = store.read()

        self.assertEqual(result["status"], "stale_data")
        self.assertEqual(state["jobs"]["batch"]["status"], "failure")
        self.assertEqual(state["jobs"]["batch"]["error_type"], "StaleData")
        self.assertEqual([event for event, _ in notifier.events], ["stale_data"])

    def test_log_rotation_uses_zoneinfo_asia_seoul(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = operations_runtime.DailySizeRotatingOperationsHandler(
                Path(tmp),
                now=lambda: datetime.fromisoformat("2026-08-03T15:00:00+00:00"),
            )
            try:
                path = handler._current_path()
            finally:
                handler.close()

        self.assertEqual(path.name, "operations-2026-08-04.log")
        self.assertIsInstance(operations_runtime.KST, ZoneInfo)
        self.assertEqual(operations_runtime.KST.key, "Asia/Seoul")

    def test_schedule_once_still_requires_explicit_scheduler_enable(self):
        with mock.patch.dict(os.environ, {"LECTURE_ENABLE_SCHEDULER": "0"}):
            with self.assertRaises(RuntimeError):
                asyncio.run(operations.run_scheduler((), once=True))

    def test_scheduler_stop_callback_records_stopping_without_sending_signals(self):
        self.assertTrue(hasattr(operations, "request_scheduler_stop"))

        async def exercise_stop_callback(store):
            stop_event = asyncio.Event()
            operations.request_scheduler_stop(stop_event, store, pid=1234)
            return stop_event.is_set()

        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            stopped = asyncio.run(exercise_stop_callback(store))
            state = store.read()

        self.assertTrue(stopped)
        self.assertEqual(state["scheduler"]["status"], "stopping")
        self.assertEqual(state["scheduler"]["pid"], 1234)

    def test_scheduler_records_stopped_and_releases_lock_in_finally(self):
        async def run_once(runtime_dir, store):
            stop_event = asyncio.Event()

            async def stop_after_sleep(_seconds):
                operations.request_scheduler_stop(stop_event, store, pid=os.getpid())

            with mock.patch("operations._install_signal_handlers"):
                await operations.run_scheduler(
                    (),
                    poll_seconds=1,
                    runtime_dir=runtime_dir,
                    state_store=store,
                    stop_event=stop_event,
                    now_func=lambda: datetime(2026, 8, 3, 10, 0),
                    sleep=stop_after_sleep,
                )

        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            store = operations_runtime.OperationsStateStore(runtime_dir)
            with mock.patch.dict(os.environ, {"LECTURE_ENABLE_SCHEDULER": "1"}):
                asyncio.run(run_once(runtime_dir, store))
            state = store.read()

        self.assertEqual(state["scheduler"]["status"], "stopped")
        self.assertFalse((runtime_dir / "scheduler.lock").exists())

    def test_scheduler_records_lost_lock_when_metadata_owner_changes_before_finally(self):
        async def run_once(runtime_dir, store):
            stop_event = asyncio.Event()

            async def replace_owner_then_stop(_seconds):
                metadata_path = runtime_dir / "scheduler.lock"
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata["owner_token"] = "replacement-token"
                metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
                operations.request_scheduler_stop(stop_event, store, pid=os.getpid())

            with mock.patch("operations._install_signal_handlers"):
                await operations.run_scheduler(
                    (),
                    poll_seconds=1,
                    runtime_dir=runtime_dir,
                    state_store=store,
                    stop_event=stop_event,
                    now_func=lambda: datetime(2026, 8, 3, 10, 0),
                    sleep=replace_owner_then_stop,
                )

        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            store = operations_runtime.OperationsStateStore(runtime_dir)
            with mock.patch.dict(os.environ, {"LECTURE_ENABLE_SCHEDULER": "1"}):
                asyncio.run(run_once(runtime_dir, store))
            state = store.read()

        self.assertEqual(state["scheduler"]["status"], "lost_lock")

    def test_scheduler_does_not_write_lost_lock_over_replacement_state_owner(self):
        async def run_once(runtime_dir, store):
            stop_event = asyncio.Event()

            async def replace_owner_then_stop(_seconds):
                metadata_path = runtime_dir / "scheduler.lock"
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata.update(
                    {
                        "pid": 7777,
                        "project_path": str(runtime_dir),
                        "owner_token": "replacement-token",
                    }
                )
                metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
                store.record_scheduler_status(
                    "running",
                    pid=7777,
                    project_path=runtime_dir,
                    heartbeat_at="2026-08-03T10:00:30",
                    owner_token="replacement-token",
                )
                stop_event.set()

            with mock.patch("operations._install_signal_handlers"):
                await operations.run_scheduler(
                    (),
                    poll_seconds=1,
                    runtime_dir=runtime_dir,
                    state_store=store,
                    stop_event=stop_event,
                    now_func=lambda: datetime(2026, 8, 3, 10, 0),
                    sleep=replace_owner_then_stop,
                )

        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            store = operations_runtime.OperationsStateStore(runtime_dir)
            with mock.patch.dict(os.environ, {"LECTURE_ENABLE_SCHEDULER": "1"}):
                asyncio.run(run_once(runtime_dir, store))
            state = store.read()

        self.assertEqual(state["scheduler"]["status"], "running")
        self.assertEqual(state["scheduler"]["pid"], 7777)
        self.assertEqual(state["scheduler"]["owner_token"], "replacement-token")


if __name__ == "__main__":
    unittest.main()
