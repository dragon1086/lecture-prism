"""Pure execution-policy and local operations-runtime helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile, gettempdir
from typing import Any, Callable, Mapping


LIVE_BROKER_UNATTENDED_ACK = "I_ACCEPT_REAL_ORDERS"

_ACCEPTED_PROFILES = frozenset(
    {"mock", "classroom", "real_data", "research", "backtest", "paper", "live"}
)
_SIMULATION_PROFILES = frozenset({"mock", "classroom", "real_data", "research", "backtest"})
_ACCOUNT_MODES = {
    "paper": "demo",
    "live": "real",
}


@dataclass(frozen=True)
class ExecutionPolicy:
    profile: str
    account_mode: str
    requested_broker_execution: bool
    broker_execution_allowed: bool
    dry_run: bool
    blocked_reasons: tuple[str, ...]


class SchedulerAlreadyRunning(RuntimeError):
    """Raised when another scheduler instance owns the local runtime lock."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | str | None = None) -> str:
    if value is None:
        value = _utcnow()
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds")


def default_runtime_dir(env: Mapping[str, str] | None = None) -> Path:
    source = env if env is not None else os.environ
    configured = str(source.get("LECTURE_OPERATIONS_RUNTIME_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    project_name = Path(__file__).resolve().parent.name
    return Path(gettempdir()) / "lecture-prism-operations" / project_name


def _default_state() -> dict[str, Any]:
    return {
        "scheduler": {
            "status": "unknown",
            "pid": None,
            "project_path": None,
            "heartbeat_at": None,
            "started_at": None,
            "stopped_at": None,
        },
        "jobs": {},
    }


class OperationsStateStore:
    """Atomic JSON state store for local scheduler/status data."""

    def __init__(self, runtime_dir: Path | str | None = None) -> None:
        self.runtime_dir = (
            Path(runtime_dir) if runtime_dir is not None else default_runtime_dir()
        )
        self.path = self.runtime_dir / "operations-state.json"

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return _default_state()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return _default_state()
        if not isinstance(state, dict):
            return _default_state()
        state.setdefault("scheduler", _default_state()["scheduler"])
        state.setdefault("jobs", {})
        return state

    def _write(self, state: Mapping[str, Any]) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.runtime_dir,
            prefix=".operations-state-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        os.replace(temp_name, self.path)

    def record_scheduler_status(
        self,
        status: str,
        *,
        pid: int | None = None,
        project_path: str | Path | None = None,
        heartbeat_at: datetime | str | None = None,
    ) -> None:
        state = self.read()
        scheduler = dict(state.get("scheduler") or {})
        now = _iso(heartbeat_at)
        scheduler["status"] = status
        if pid is not None:
            scheduler["pid"] = int(pid)
        if project_path is not None:
            scheduler["project_path"] = str(project_path)
        if status in {"running", "stopping"}:
            scheduler["heartbeat_at"] = now
        if status == "running" and not scheduler.get("started_at"):
            scheduler["started_at"] = now
        if status == "stopped":
            scheduler["stopped_at"] = now
        state["scheduler"] = scheduler
        self._write(state)

    def record_heartbeat(
        self,
        *,
        pid: int | None = None,
        project_path: str | Path | None = None,
        heartbeat_at: datetime | str | None = None,
    ) -> None:
        self.record_scheduler_status(
            "running",
            pid=pid,
            project_path=project_path,
            heartbeat_at=heartbeat_at,
        )

    def record_job_start(self, job: str, started_at: datetime | str | None = None) -> None:
        state = self.read()
        jobs = dict(state.get("jobs") or {})
        jobs[job] = {
            **dict(jobs.get(job) or {}),
            "status": "running",
            "started_at": _iso(started_at),
            "finished_at": None,
            "error_type": None,
        }
        state["jobs"] = jobs
        self._write(state)

    def record_job_success(self, job: str, finished_at: datetime | str | None = None) -> None:
        self._record_job_finished(job, "success", finished_at)

    def record_job_failure(
        self,
        job: str,
        finished_at: datetime | str | None = None,
        *,
        error_type: str,
    ) -> None:
        self._record_job_finished(job, "failure", finished_at, error_type=error_type)

    def record_job_skipped_overlap(
        self,
        job: str,
        finished_at: datetime | str | None = None,
    ) -> None:
        self._record_job_finished(job, "skipped_overlap", finished_at)

    def _record_job_finished(
        self,
        job: str,
        status: str,
        finished_at: datetime | str | None = None,
        *,
        error_type: str | None = None,
    ) -> None:
        state = self.read()
        jobs = dict(state.get("jobs") or {})
        current = dict(jobs.get(job) or {})
        current.update(
            {
                "status": status,
                "finished_at": _iso(finished_at),
                "error_type": error_type,
            }
        )
        jobs[job] = current
        state["jobs"] = jobs
        self._write(state)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class SchedulerLock:
    """Single-instance scheduler lock with PID and heartbeat checks."""

    def __init__(
        self,
        runtime_dir: Path | str | None = None,
        *,
        project_path: Path | str | None = None,
        pid: int | None = None,
        stale_after_seconds: int | float = 120,
        now: Callable[[], datetime] | None = None,
        pid_alive: Callable[[int], bool] | None = None,
        state_store: OperationsStateStore | None = None,
    ) -> None:
        self.runtime_dir = (
            Path(runtime_dir) if runtime_dir is not None else default_runtime_dir()
        )
        self.path = self.runtime_dir / "scheduler.lock"
        self.project_path = Path(project_path or Path.cwd()).resolve()
        self.pid = int(pid if pid is not None else os.getpid())
        self.stale_after_seconds = float(stale_after_seconds)
        self.now = now or _utcnow
        self.pid_alive = pid_alive or _pid_is_alive
        self.state_store = state_store or OperationsStateStore(self.runtime_dir)
        self._held = False

    def acquire(self) -> bool:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        existing = self._read_lock()
        if existing:
            owner_pid = int(existing.get("pid") or 0)
            heartbeat = _parse_datetime(existing.get("heartbeat_at"))
            age = None if heartbeat is None else (self._now() - heartbeat).total_seconds()
            stale = heartbeat is None or age is None or age > self.stale_after_seconds
            alive = self.pid_alive(owner_pid)
            if alive or not stale:
                raise SchedulerAlreadyRunning(
                    f"scheduler already running with pid {owner_pid}"
                )
        self._write_lock()
        self._held = True
        self.state_store.record_scheduler_status(
            "running",
            pid=self.pid,
            project_path=self.project_path,
            heartbeat_at=self._now(),
        )
        return True

    def heartbeat(self) -> None:
        if not self._owns_lock():
            raise SchedulerAlreadyRunning("scheduler lock is not owned by this process")
        self._write_lock()
        self.state_store.record_heartbeat(
            pid=self.pid,
            project_path=self.project_path,
            heartbeat_at=self._now(),
        )

    def release(self) -> None:
        if not self._owns_lock():
            return
        self.path.unlink()
        self._held = False

    def _now(self) -> datetime:
        current = self.now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current

    def _read_lock(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return {"pid": -1, "heartbeat_at": None}
        return value if isinstance(value, dict) else {"pid": -1, "heartbeat_at": None}

    def _write_lock(self) -> None:
        payload = {
            "pid": self.pid,
            "project_path": str(self.project_path),
            "acquired_at": _iso(self._now()),
            "heartbeat_at": _iso(self._now()),
        }
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.runtime_dir,
            prefix=".scheduler-lock-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        os.replace(temp_name, self.path)

    def _owns_lock(self) -> bool:
        existing = self._read_lock()
        return bool(existing and int(existing.get("pid") or 0) == self.pid)


_SECRET_KEY_PARTS = ("secret", "token", "password", "api_key", "app_key", "ack")


def _redact_value(key: str, value: Any) -> Any:
    if any(part in key.lower() for part in _SECRET_KEY_PARTS):
        return "<redacted>"
    if isinstance(value, str):
        lowered = value.lower()
        if (
            value == LIVE_BROKER_UNATTENDED_ACK
            or value.startswith("sk-")
            or "secret" in lowered
            or "refresh_token" in lowered
        ):
            return "<redacted>"
    return value


def serialize_status(value: Any, *, key: str = "") -> Any:
    """Return a JSON-safe status payload with secret-looking values removed."""

    redacted = _redact_value(key, value)
    if redacted == "<redacted>":
        return redacted
    if isinstance(value, Mapping):
        return {str(k): serialize_status(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, tuple):
        return [serialize_status(item, key=key) for item in value]
    if isinstance(value, list):
        return [serialize_status(item, key=key) for item in value]
    return value


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _profile(value: str) -> str:
    return str(value or "mock").strip().lower().replace(" ", "_")


def resolve_execution_policy(
    profile: str,
    *,
    execute_broker: bool,
    env: Mapping[str, str] | None = None,
) -> ExecutionPolicy:
    """Resolve whether unattended operations may call broker APIs.

    The environment is injectable so callers and tests can decide which values
    are visible. This function never includes raw environment values in the
    returned policy.
    """

    selected_profile = _profile(profile)
    requested = bool(execute_broker)
    source = env if env is not None else os.environ

    if selected_profile not in _ACCEPTED_PROFILES:
        return ExecutionPolicy(
            profile=selected_profile,
            account_mode="simulation",
            requested_broker_execution=requested,
            broker_execution_allowed=False,
            dry_run=True,
            blocked_reasons=("unknown_profile",),
        )

    if selected_profile in _SIMULATION_PROFILES:
        return ExecutionPolicy(
            profile=selected_profile,
            account_mode="simulation",
            requested_broker_execution=requested,
            broker_execution_allowed=False,
            dry_run=True,
            blocked_reasons=("profile_forces_simulation",),
        )

    account_mode = _ACCOUNT_MODES.get(selected_profile, "simulation")
    if not requested:
        return ExecutionPolicy(
            profile=selected_profile,
            account_mode="simulation",
            requested_broker_execution=False,
            broker_execution_allowed=False,
            dry_run=True,
            blocked_reasons=("broker_execution_not_requested",),
        )

    blocked_reasons: list[str] = []
    if not _truthy(source.get("LECTURE_ENABLE_LIVE_BROKER")):
        blocked_reasons.append("live_broker_not_enabled")
    if account_mode == "real":
        if not _truthy(source.get("LECTURE_ALLOW_REAL_BROKER")):
            blocked_reasons.append("real_broker_not_allowed")
        if source.get("LECTURE_UNATTENDED_LIVE_ACK") != LIVE_BROKER_UNATTENDED_ACK:
            blocked_reasons.append("unattended_live_ack_missing")

    blocked = tuple(blocked_reasons)
    return ExecutionPolicy(
        profile=selected_profile,
        account_mode=account_mode,
        requested_broker_execution=True,
        broker_execution_allowed=not blocked,
        dry_run=bool(blocked),
        blocked_reasons=blocked,
    )
