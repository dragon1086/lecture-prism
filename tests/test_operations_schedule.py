import asyncio
from datetime import datetime
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import operations
import operations_runtime


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


if __name__ == "__main__":
    unittest.main()
