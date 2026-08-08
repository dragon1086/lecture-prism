from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
import unittest
from unittest import mock

import operations_runtime
import runtime_config


class ExecutionPolicyTest(unittest.TestCase):
    def test_unattended_ack_constant_is_controller_approved_literal(self):
        self.assertEqual(
            operations_runtime.LIVE_BROKER_UNATTENDED_ACK,
            "I_ACCEPT_REAL_ORDERS",
        )
        self.assertEqual(
            runtime_config.LIVE_BROKER_UNATTENDED_ACK,
            "I_ACCEPT_REAL_ORDERS",
        )

    def test_non_operating_profiles_always_resolve_to_simulation(self):
        for profile in ("mock", "classroom", "real_data", "research", "backtest"):
            for execute_broker in (False, True):
                with self.subTest(profile=profile, execute_broker=execute_broker):
                    policy = operations_runtime.resolve_execution_policy(
                        profile,
                        execute_broker=execute_broker,
                        env={
                            "LECTURE_ENABLE_LIVE_BROKER": "1",
                            "LECTURE_ALLOW_REAL_BROKER": "1",
                            "LECTURE_UNATTENDED_LIVE_ACK": runtime_config.LIVE_BROKER_UNATTENDED_ACK,
                        },
                    )

                    self.assertEqual(policy.profile, profile)
                    self.assertEqual(policy.account_mode, "simulation")
                    self.assertFalse(policy.broker_execution_allowed)
                    self.assertTrue(policy.dry_run)
                    self.assertIn("profile_forces_simulation", policy.blocked_reasons)

    def test_paper_and_live_without_execute_broker_resolve_to_simulation(self):
        for profile in ("paper", "live"):
            with self.subTest(profile=profile):
                policy = operations_runtime.resolve_execution_policy(
                    profile,
                    execute_broker=False,
                    env={
                        "LECTURE_ENABLE_LIVE_BROKER": "1",
                        "LECTURE_ALLOW_REAL_BROKER": "1",
                        "LECTURE_UNATTENDED_LIVE_ACK": runtime_config.LIVE_BROKER_UNATTENDED_ACK,
                    },
                )

                self.assertEqual(policy.account_mode, "simulation")
                self.assertFalse(policy.requested_broker_execution)
                self.assertFalse(policy.broker_execution_allowed)
                self.assertTrue(policy.dry_run)
                self.assertIn("broker_execution_not_requested", policy.blocked_reasons)

    def test_paper_execution_requires_live_broker_enable_gate(self):
        blocked = operations_runtime.resolve_execution_policy(
            "paper",
            execute_broker=True,
            env={},
        )
        allowed = operations_runtime.resolve_execution_policy(
            "paper",
            execute_broker=True,
            env={"LECTURE_ENABLE_LIVE_BROKER": "1"},
        )

        self.assertEqual(blocked.account_mode, "demo")
        self.assertTrue(blocked.requested_broker_execution)
        self.assertFalse(blocked.broker_execution_allowed)
        self.assertTrue(blocked.dry_run)
        self.assertEqual(blocked.blocked_reasons, ("live_broker_not_enabled",))

        self.assertEqual(allowed.account_mode, "demo")
        self.assertTrue(allowed.requested_broker_execution)
        self.assertTrue(allowed.broker_execution_allowed)
        self.assertFalse(allowed.dry_run)
        self.assertEqual(allowed.blocked_reasons, ())

    def test_live_execution_requires_enable_allow_and_exact_unattended_ack(self):
        old_ack = (
            "I UNDERSTAND THIS LECTURE-PRISM RUN MAY SEND UNATTENDED REAL BROKER ORDERS"
        )
        cases = [
            ({}, "live_broker_not_enabled"),
            ({"LECTURE_ENABLE_LIVE_BROKER": "1"}, "real_broker_not_allowed"),
            (
                {
                    "LECTURE_ENABLE_LIVE_BROKER": "1",
                    "LECTURE_ALLOW_REAL_BROKER": "1",
                    "LECTURE_UNATTENDED_LIVE_ACK": "yes",
                },
                "unattended_live_ack_missing",
            ),
            (
                {
                    "LECTURE_ENABLE_LIVE_BROKER": "1",
                    "LECTURE_ALLOW_REAL_BROKER": "1",
                    "LECTURE_UNATTENDED_LIVE_ACK": old_ack,
                },
                "unattended_live_ack_missing",
            ),
        ]
        for env, reason in cases:
            with self.subTest(reason=reason):
                policy = operations_runtime.resolve_execution_policy(
                    "live",
                    execute_broker=True,
                    env=env,
                )

                self.assertEqual(policy.account_mode, "real")
                self.assertFalse(policy.broker_execution_allowed)
                self.assertTrue(policy.dry_run)
                self.assertIn(reason, policy.blocked_reasons)

        allowed = operations_runtime.resolve_execution_policy(
            "live",
            execute_broker=True,
            env={
                "LECTURE_ENABLE_LIVE_BROKER": "1",
                "LECTURE_ALLOW_REAL_BROKER": "1",
                "LECTURE_UNATTENDED_LIVE_ACK": runtime_config.LIVE_BROKER_UNATTENDED_ACK,
            },
        )

        self.assertEqual(allowed.account_mode, "real")
        self.assertTrue(allowed.broker_execution_allowed)
        self.assertFalse(allowed.dry_run)
        self.assertEqual(allowed.blocked_reasons, ())

    def test_dangerous_aliases_and_unknown_profiles_fail_closed(self):
        env = {
            "LECTURE_ENABLE_LIVE_BROKER": "1",
            "LECTURE_ALLOW_REAL_BROKER": "1",
            "LECTURE_UNATTENDED_LIVE_ACK": runtime_config.LIVE_BROKER_UNATTENDED_ACK,
        }

        for profile in ("real", "prod", "broker-demo", "livve"):
            with self.subTest(profile=profile):
                policy = operations_runtime.resolve_execution_policy(
                    profile,
                    execute_broker=True,
                    env=env,
                )

                self.assertEqual(policy.profile, profile)
                self.assertEqual(policy.account_mode, "simulation")
                self.assertFalse(policy.broker_execution_allowed)
                self.assertTrue(policy.dry_run)
                self.assertEqual(policy.blocked_reasons, ("unknown_profile",))

    def test_policy_is_immutable_and_redacts_environment_values(self):
        raw_values = (
            "enable-7ab42d07e2",
            "allow-bc932df31d",
            runtime_config.LIVE_BROKER_UNATTENDED_ACK,
        )
        policy = operations_runtime.resolve_execution_policy(
            "live",
            execute_broker=True,
            env={
                "LECTURE_ENABLE_LIVE_BROKER": raw_values[0],
                "LECTURE_ALLOW_REAL_BROKER": raw_values[1],
                "LECTURE_UNATTENDED_LIVE_ACK": raw_values[2],
            },
        )

        with self.assertRaises(Exception):
            policy.dry_run = False

        policy_strings = (
            repr(policy),
            policy.profile,
            policy.account_mode,
            *policy.blocked_reasons,
        )
        for raw_value in raw_values:
            with self.subTest(raw_value=raw_value):
                for text in policy_strings:
                    self.assertNotIn(raw_value, text)

    def test_env_example_exposes_blank_unattended_ack_key(self):
        env_example = Path(".env.example").read_text(encoding="utf-8")

        self.assertIn("LECTURE_UNATTENDED_LIVE_ACK=", env_example)
        self.assertIn(
            f"# 정확히 이 값으로 바꿔야 실전 무인 주문이 허용됩니다: "
            f"{runtime_config.LIVE_BROKER_UNATTENDED_ACK}",
            env_example,
        )


class OperationsStateStoreTest(unittest.TestCase):
    def test_state_store_writes_json_atomically_and_preserves_previous_state_on_replace_failure(self):
        self.assertTrue(hasattr(operations_runtime, "OperationsStateStore"))
        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            store.record_scheduler_status("running", pid=111, heartbeat_at="2026-08-08T09:00:00+00:00")
            before = json.loads((Path(tmp) / "operations-state.json").read_text(encoding="utf-8"))

            with mock.patch("operations_runtime.os.replace", side_effect=RuntimeError("disk full")):
                with self.assertRaises(RuntimeError):
                    store.record_scheduler_status("stopping", pid=111)

            after = json.loads((Path(tmp) / "operations-state.json").read_text(encoding="utf-8"))

        self.assertEqual(before, after)
        self.assertEqual(after["scheduler"]["status"], "running")
        self.assertEqual(after["scheduler"]["pid"], 111)
        self.assertEqual(list(Path(tmp).glob(".operations-state-*.tmp")), [])

    def test_state_store_cleans_temp_file_when_replace_fails(self):
        self.assertTrue(hasattr(operations_runtime, "OperationsStateStore"))
        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))

            with mock.patch("operations_runtime.os.replace", side_effect=RuntimeError("disk full")):
                with self.assertRaises(RuntimeError):
                    store.record_scheduler_status("running", pid=111)

            leftovers = list(Path(tmp).glob(".operations-state-*.tmp"))

        self.assertEqual(leftovers, [])

    def test_state_store_fsyncs_temp_file_before_replace(self):
        self.assertTrue(hasattr(operations_runtime, "OperationsStateStore"))
        events = []
        real_replace = os.replace

        def fake_fsync(_fd):
            events.append("fsync")

        def fake_replace(source, target):
            events.append("replace")
            real_replace(source, target)

        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            with mock.patch("operations_runtime.os.fsync", side_effect=fake_fsync):
                with mock.patch("operations_runtime.os.replace", side_effect=fake_replace):
                    store.record_scheduler_status("running", pid=111)

        self.assertIn("replace", events)
        self.assertIn("fsync", events)
        self.assertLess(events.index("fsync"), events.index("replace"))

    def test_state_store_records_job_lifecycle_and_heartbeat_timestamps(self):
        self.assertTrue(hasattr(operations_runtime, "OperationsStateStore"))
        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            store.record_scheduler_status("running", pid=222, heartbeat_at="2026-08-08T09:00:00+00:00")
            store.record_job_start("monitor", "2026-08-08T09:01:00+00:00")
            store.record_job_success("monitor", "2026-08-08T09:02:00+00:00")
            store.record_job_start("reconcile", "2026-08-08T09:03:00+00:00")
            store.record_job_failure(
                "reconcile",
                "2026-08-08T09:04:00+00:00",
                error_type="TimeoutError",
            )
            state = store.read()

        self.assertEqual(state["scheduler"]["heartbeat_at"], "2026-08-08T09:00:00+00:00")
        self.assertEqual(state["jobs"]["monitor"]["status"], "success")
        self.assertEqual(state["jobs"]["monitor"]["started_at"], "2026-08-08T09:01:00+00:00")
        self.assertEqual(state["jobs"]["monitor"]["finished_at"], "2026-08-08T09:02:00+00:00")
        self.assertEqual(state["jobs"]["reconcile"]["status"], "failure")
        self.assertEqual(state["jobs"]["reconcile"]["error_type"], "TimeoutError")

    def test_status_snapshot_redacts_secret_like_values(self):
        self.assertTrue(hasattr(operations_runtime, "OperationsStateStore"))
        self.assertTrue(hasattr(operations_runtime, "serialize_status"))
        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            store.record_scheduler_status("running", pid=333, heartbeat_at="2026-08-08T09:00:00+00:00")
            status = operations_runtime.serialize_status(
                {
                    "profile": "live",
                    "broker": "kis",
                    "account_mode": "real",
                    "scheduler": store.read()["scheduler"],
                    "jobs": {"monitor": {"status": "success"}},
                    "blocked_reasons": ("token-secret-42",),
                    "api_key": "sk-live-secret-42",
                    "nested": {"refresh_token": "refresh-secret-42"},
                }
            )

        rendered = json.dumps(status, ensure_ascii=False, sort_keys=True)
        self.assertIn("<redacted>", rendered)
        self.assertNotIn("sk-live-secret-42", rendered)
        self.assertNotIn("refresh-secret-42", rendered)
        self.assertNotIn("token-secret-42", rendered)


class SchedulerLockTest(unittest.TestCase):
    def test_lock_recovers_when_metadata_is_stale_after_advisory_owner_exits(self):
        self.assertTrue(hasattr(operations_runtime, "SchedulerLock"))
        now = datetime(2026, 8, 8, 9, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            store = operations_runtime.OperationsStateStore(Path(tmp))
            (Path(tmp) / "scheduler.lock").write_text(
                json.dumps(
                    {
                        "pid": 999,
                        "project_path": "/project",
                        "owner_token": "crashed-owner-token",
                        "acquired_at": "2026-08-08T09:00:00+00:00",
                        "heartbeat_at": "2026-08-08T09:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            stale = operations_runtime.SchedulerLock(
                Path(tmp),
                project_path=Path("/project"),
                pid=1000,
                now=lambda: now,
                pid_alive=lambda pid: False,
                stale_after_seconds=60,
                state_store=store,
            )

            self.assertTrue(stale.acquire())
            state = json.loads((Path(tmp) / "scheduler.lock").read_text(encoding="utf-8"))
            stale.release()

        self.assertEqual(state["pid"], 1000)
        self.assertEqual(state["project_path"], "/project")

    def test_lock_rejects_live_advisory_owner_even_when_heartbeat_is_stale(self):
        self.assertTrue(hasattr(operations_runtime, "SchedulerLock"))
        now = datetime(2026, 8, 8, 9, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            first = operations_runtime.SchedulerLock(
                Path(tmp),
                project_path=Path("/project"),
                pid=999,
                now=lambda: now - timedelta(hours=3),
                pid_alive=lambda pid: True,
            )
            first.acquire()
            duplicate = operations_runtime.SchedulerLock(
                Path(tmp),
                project_path=Path("/project"),
                pid=1000,
                now=lambda: now,
                pid_alive=lambda pid: True,
                stale_after_seconds=60,
            )

            with self.assertRaises(operations_runtime.SchedulerAlreadyRunning):
                duplicate.acquire()

            state = json.loads((Path(tmp) / "scheduler.lock").read_text(encoding="utf-8"))
            first.release()

        self.assertEqual(state["pid"], 999)

    def test_release_requires_pid_project_path_and_owner_token(self):
        self.assertTrue(hasattr(operations_runtime, "SchedulerLock"))
        with tempfile.TemporaryDirectory() as tmp:
            first = operations_runtime.SchedulerLock(
                Path(tmp),
                project_path=Path("/project"),
                pid=999,
                pid_alive=lambda pid: False,
            )
            first.acquire()
            second = operations_runtime.SchedulerLock(
                Path(tmp),
                project_path=Path("/project"),
                pid=999,
                pid_alive=lambda pid: False,
            )

            second.release()
            self.assertTrue((Path(tmp) / "scheduler.lock").exists())
            first.release()
            self.assertFalse((Path(tmp) / "scheduler.lock").exists())

    def test_heartbeat_preserves_acquired_at_and_replaces_owner_token_after_reacquire(self):
        self.assertTrue(hasattr(operations_runtime, "SchedulerLock"))
        current = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            first = operations_runtime.SchedulerLock(
                Path(tmp),
                project_path=Path("/project"),
                pid=999,
                now=lambda: current,
            )
            first.acquire()
            initial = json.loads((Path(tmp) / "scheduler.lock").read_text(encoding="utf-8"))
            current = datetime(2026, 8, 8, 9, 5, tzinfo=timezone.utc)
            first.heartbeat()
            after_heartbeat = json.loads((Path(tmp) / "scheduler.lock").read_text(encoding="utf-8"))
            first.release()

            current = datetime(2026, 8, 8, 9, 10, tzinfo=timezone.utc)
            second = operations_runtime.SchedulerLock(
                Path(tmp),
                project_path=Path("/project"),
                pid=999,
                now=lambda: current,
            )
            second.acquire()
            replacement = json.loads((Path(tmp) / "scheduler.lock").read_text(encoding="utf-8"))
            second.release()

        self.assertEqual(after_heartbeat["acquired_at"], initial["acquired_at"])
        self.assertEqual(after_heartbeat["heartbeat_at"], "2026-08-08T09:05:00+00:00")
        self.assertNotEqual(replacement["owner_token"], initial["owner_token"])
        self.assertEqual(replacement["acquired_at"], "2026-08-08T09:10:00+00:00")

    def test_real_concurrent_process_cannot_acquire_held_advisory_lock(self):
        self.assertTrue(hasattr(operations_runtime, "SchedulerLock"))
        holder = textwrap.dedent(
            """
            import pathlib
            import sys
            import time
            import operations_runtime

            runtime = pathlib.Path(sys.argv[1])
            sentinel = pathlib.Path(sys.argv[2])
            lock = operations_runtime.SchedulerLock(runtime, project_path=runtime)
            lock.acquire()
            print("acquired", flush=True)
            deadline = time.time() + 10
            while not sentinel.exists() and time.time() < deadline:
                time.sleep(0.05)
            lock.release()
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            sentinel = runtime_dir / "release"
            process = subprocess.Popen(
                [sys.executable, "-c", holder, str(runtime_dir), str(sentinel)],
                cwd=str(Path(__file__).resolve().parents[1]),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                first_line = process.stdout.readline().strip()
                if first_line != "acquired":
                    _, stderr = process.communicate(timeout=10)
                    self.fail(f"holder did not acquire lock: stdout={first_line!r} stderr={stderr}")
                metadata_path = runtime_dir / "scheduler.lock"
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
                metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

                duplicate = operations_runtime.SchedulerLock(
                    runtime_dir,
                    project_path=runtime_dir,
                    stale_after_seconds=1,
                )
                with self.assertRaises(operations_runtime.SchedulerAlreadyRunning):
                    duplicate.acquire()
            finally:
                sentinel.touch()
                stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(process.returncode, 0, stderr)

    def test_real_concurrent_process_startup_allows_only_one_acquirer(self):
        self.assertTrue(hasattr(operations_runtime, "SchedulerLock"))
        contender = textwrap.dedent(
            """
            import pathlib
            import sys
            import time
            import operations_runtime

            runtime = pathlib.Path(sys.argv[1])
            start = pathlib.Path(sys.argv[2])
            ready = pathlib.Path(sys.argv[3])
            ready.touch()
            deadline = time.time() + 10
            while not start.exists() and time.time() < deadline:
                time.sleep(0.001)
            lock = operations_runtime.SchedulerLock(runtime, project_path=runtime)
            try:
                lock.acquire()
            except operations_runtime.SchedulerAlreadyRunning:
                print("blocked", flush=True)
                raise SystemExit(0)
            print("acquired", flush=True)
            time.sleep(0.2)
            lock.release()
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            start = runtime_dir / "start"
            processes = []
            for index in range(8):
                ready = runtime_dir / f"ready-{index}"
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-c",
                            contender,
                            str(runtime_dir),
                            str(start),
                            str(ready),
                        ],
                        cwd=str(Path(__file__).resolve().parents[1]),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                )

            deadline = datetime.now().timestamp() + 10
            while datetime.now().timestamp() < deadline:
                if all((runtime_dir / f"ready-{index}").exists() for index in range(8)):
                    break
            start.touch()
            outputs = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(stdout.strip())

        self.assertEqual(outputs.count("acquired"), 1)
        self.assertEqual(outputs.count("blocked"), 7)


if __name__ == "__main__":
    unittest.main()
