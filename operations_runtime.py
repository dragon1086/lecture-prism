"""Pure execution-policy and local operations-runtime helpers."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile, gettempdir
from typing import Any, Callable, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo


LIVE_BROKER_UNATTENDED_ACK = "I_ACCEPT_REAL_ORDERS"
KST = ZoneInfo("Asia/Seoul")

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


class _AdvisoryLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None
        self._backend = ""

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise SchedulerAlreadyRunning("scheduler already running") from exc
                self._backend = "msvcrt"
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise SchedulerAlreadyRunning("scheduler already running") from exc
                self._backend = "fcntl"
        except Exception:
            handle.close()
            raise
        self.handle = handle

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if self._backend == "msvcrt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif self._backend == "fcntl":
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


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


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write_json(path: Path, state: Mapping[str, Any], *, prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=prefix,
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        os.replace(temp_name, path)
        temp_name = ""
        _fsync_directory(path.parent)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


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
        _atomic_write_json(self.path, state, prefix=".operations-state-")

    def record_scheduler_status(
        self,
        status: str,
        *,
        pid: int | None = None,
        project_path: str | Path | None = None,
        heartbeat_at: datetime | str | None = None,
        owner_token: str | None = None,
        process_identity: str | None = None,
    ) -> None:
        state = self.read()
        scheduler = dict(state.get("scheduler") or {})
        now = _iso(heartbeat_at)
        scheduler["status"] = status
        if pid is not None:
            scheduler["pid"] = int(pid)
        if project_path is not None:
            scheduler["project_path"] = str(project_path)
        if owner_token is not None:
            scheduler["owner_token"] = owner_token
        if process_identity is not None:
            scheduler["process_identity"] = process_identity
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
        owner_token: str | None = None,
        process_identity: str | None = None,
    ) -> None:
        self.record_scheduler_status(
            "running",
            pid=pid,
            project_path=project_path,
            heartbeat_at=heartbeat_at,
            owner_token=owner_token,
            process_identity=process_identity,
        )

    def scheduler_owner_matches(
        self,
        *,
        pid: int,
        project_path: str | Path,
        owner_token: str,
    ) -> bool:
        scheduler = dict(self.read().get("scheduler") or {})
        return (
            int(scheduler.get("pid") or 0) == int(pid)
            and str(scheduler.get("project_path") or "") == str(project_path)
            and str(scheduler.get("owner_token") or "") == str(owner_token)
        )

    def record_scheduler_status_if_owner(
        self,
        status: str,
        *,
        pid: int,
        project_path: str | Path,
        owner_token: str,
        heartbeat_at: datetime | str | None = None,
        process_identity: str | None = None,
    ) -> bool:
        if not self.scheduler_owner_matches(
            pid=pid,
            project_path=project_path,
            owner_token=owner_token,
        ):
            return False
        self.record_scheduler_status(
            status,
            pid=pid,
            project_path=project_path,
            heartbeat_at=heartbeat_at,
            owner_token=owner_token,
            process_identity=process_identity,
        )
        return True

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

    def record_job_skipped_market_closed(
        self,
        job: str,
        finished_at: datetime | str | None = None,
    ) -> None:
        self._record_job_finished(job, "skipped_market_closed", finished_at)

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


def _process_identity(pid: int) -> str | None:
    """Best-effort stable identity for a live process.

    Linux exposes process start ticks through /proc. Platforms without a
    standard-library-safe way to inspect another process return None, and
    callers fail closed when identity is required.
    """

    if pid <= 0:
        return None
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        text = stat_path.read_text(encoding="utf-8")
    except OSError:
        return None
    end = text.rfind(")")
    if end < 0:
        return None
    fields = text[end + 2 :].split()
    if len(fields) <= 19:
        return None
    return f"proc-start:{fields[19]}"


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
        process_identity: Callable[[int], str | None] | None = None,
        state_store: OperationsStateStore | None = None,
    ) -> None:
        self.runtime_dir = (
            Path(runtime_dir) if runtime_dir is not None else default_runtime_dir()
        )
        self.path = self.runtime_dir / "scheduler.lock"
        self._advisory = _AdvisoryLock(self.runtime_dir / "scheduler.lock.advisory")
        self.project_path = Path(project_path or Path.cwd()).resolve()
        self.pid = int(pid if pid is not None else os.getpid())
        self.stale_after_seconds = float(stale_after_seconds)
        self.now = now or _utcnow
        self.pid_alive = pid_alive or _pid_is_alive
        self.process_identity = process_identity or _process_identity
        self.state_store = state_store or OperationsStateStore(self.runtime_dir)
        self.owner_token = uuid4().hex
        self.process_identity_token: str | None = None
        self.acquired_at: str | None = None
        self._held = False

    def acquire(self) -> bool:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._advisory.acquire()
        try:
            existing = self._read_lock()
            if existing and not self._metadata_is_recoverable(existing):
                raise SchedulerAlreadyRunning("scheduler metadata owner is still active")
            self.acquired_at = _iso(self._now())
            self.process_identity_token = self.process_identity(self.pid)
            self._write_lock(acquired_at=self.acquired_at, heartbeat_at=self.acquired_at)
            self._held = True
            self.state_store.record_scheduler_status(
                "running",
                pid=self.pid,
                project_path=self.project_path,
                heartbeat_at=self.acquired_at,
                owner_token=self.owner_token,
                process_identity=self.process_identity_token,
            )
        except Exception:
            self.release()
            raise
        return True

    def heartbeat(self) -> None:
        if not self.owns_metadata():
            raise SchedulerAlreadyRunning("scheduler lock is not owned by this process")
        heartbeat_at = _iso(self._now())
        self._write_lock(
            acquired_at=self.acquired_at or heartbeat_at,
            heartbeat_at=heartbeat_at,
        )
        self.state_store.record_heartbeat(
            pid=self.pid,
            project_path=self.project_path,
            heartbeat_at=heartbeat_at,
            owner_token=self.owner_token,
            process_identity=self.process_identity_token,
        )

    def release(self) -> None:
        try:
            if self.owns_metadata():
                self.path.unlink()
                _fsync_directory(self.runtime_dir)
        finally:
            self._advisory.release()
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

    def _metadata_is_recoverable(self, existing: Mapping[str, Any]) -> bool:
        try:
            owner_pid = int(existing.get("pid") or 0)
        except (TypeError, ValueError):
            return False
        if owner_pid <= 0:
            return False

        owner_identity = existing.get("process_identity")
        owner_project = str(existing.get("project_path") or "")
        if not self.pid_alive(owner_pid):
            return True
        observed_identity: str | None = None
        if owner_identity:
            observed_identity = self.process_identity(owner_pid)
            if observed_identity is None:
                return False
            if str(observed_identity) != str(owner_identity):
                return True

        heartbeat = _parse_datetime(existing.get("heartbeat_at"))
        if heartbeat is None:
            return False
        stale = (self._now() - heartbeat).total_seconds() > self.stale_after_seconds
        if not stale:
            return False
        if not owner_identity:
            return True

        same_owner = (
            owner_project == str(self.project_path)
            and str(observed_identity) == str(owner_identity)
        )
        return not same_owner

    def _write_lock(self, *, acquired_at: str, heartbeat_at: str) -> None:
        payload = {
            "pid": self.pid,
            "project_path": str(self.project_path),
            "owner_token": self.owner_token,
            "process_identity": self.process_identity_token,
            "acquired_at": acquired_at,
            "heartbeat_at": heartbeat_at,
        }
        _atomic_write_json(self.path, payload, prefix=".scheduler-lock-")

    def owns_metadata(self) -> bool:
        existing = self._read_lock()
        return bool(
            existing
            and int(existing.get("pid") or 0) == self.pid
            and str(existing.get("project_path") or "") == str(self.project_path)
            and str(existing.get("owner_token") or "") == self.owner_token
        )

    def _owns_lock(self) -> bool:
        return self.owns_metadata()


_SECRET_KEY_PARTS = ("secret", "token", "password", "api_key", "app_key", "ack")
_SENSITIVE_FIELD_PARTS = (
    *_SECRET_KEY_PARTS,
    "account",
    "balance",
    "cash",
    "url",
    "webhook",
    "authorization",
)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_LABELED_SECRET_RE = re.compile(
    r"(?i)\b("
    r"(?:[a-z0-9]+_)*(?:api|app|access|refresh)?_?"
    r"(?:key|secret|token)"
    r"|authorization"
    r"|discord_webhook_url"
    r"|webhook_url"
    r"|account_number"
    r"|account"
    r")\s*[:=]\s*[^\s,;]+"
)
_BEARER_RE = re.compile(r"(?i)\bAuthorization\s*[:=]\s*Bearer\s+[^\s,;]+")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9._-]+")


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


def sanitize_operations_value(key: str, value: Any) -> Any:
    """Return a log/notification-safe value without raw secrets or payloads."""

    lowered_key = key.lower()
    if isinstance(value, BaseException):
        return type(value).__name__
    if any(part in lowered_key for part in _SENSITIVE_FIELD_PARTS):
        return "<redacted>"
    if isinstance(value, str):
        if value == LIVE_BROKER_UNATTENDED_ACK:
            return "<redacted>"
        text = _BEARER_RE.sub("Authorization: Bearer <redacted>", value)
        text = _LABELED_SECRET_RE.sub(
            "<redacted>",
            text,
        )
        text = _SK_RE.sub("<redacted>", text)
        text = _URL_RE.sub("<redacted>", text)
        lowered = value.lower()
        if "account" in lowered or "balance" in lowered or "token" in lowered:
            if text == value:
                return "<redacted>"
        return text
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_operations_value(str(item_key), item_value)
            for item_key, item_value in value.items()
        }
    if isinstance(value, tuple):
        return tuple(sanitize_operations_value(key, item) for item in value)
    if isinstance(value, list):
        return [sanitize_operations_value(key, item) for item in value]
    redacted = _redact_value(key, value)
    if redacted == "<redacted>":
        return redacted
    return value


def sanitize_operations_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            continue
        safe[str(key)] = serialize_status(sanitize_operations_value(str(key), value))
    return safe


def _format_field_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        text = ",".join(str(item) for item in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return " ".join(text.split())


def format_operations_log_line(event: str, **fields: Any) -> str:
    safe = sanitize_operations_fields(fields)
    parts = [f"event={event}"]
    for key in sorted(safe):
        parts.append(f"{key}={_format_field_value(safe[key])}")
    return " ".join(parts)


class DailySizeRotatingOperationsHandler(logging.Handler):
    """Rotate operation logs when the KST date changes or max size is exceeded."""

    def __init__(
        self,
        directory: Path | str,
        *,
        max_bytes: int = 1_000_000,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(logging.INFO)
        self.directory = Path(directory)
        self.max_bytes = int(max_bytes)
        self.now = now or _utcnow
        self._stream = None
        self._path: Path | None = None
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) + "\n"
            stream = self._stream_for_message(message)
            stream.write(message)
            stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        super().close()

    def _current_path(self) -> Path:
        current = self.now()
        if current.tzinfo is not None:
            current = current.astimezone(KST)
        date_key = current.strftime("%Y-%m-%d")
        return self.directory / f"operations-{date_key}.log"

    def _stream_for_message(self, message: str):
        path = self._current_path()
        self.directory.mkdir(parents=True, exist_ok=True)
        if self._path != path:
            if self._stream is not None:
                self._stream.close()
            self._path = path
            self._stream = path.open("a", encoding="utf-8")
        if (
            self.max_bytes > 0
            and path.exists()
            and path.stat().st_size + len(message.encode("utf-8")) > self.max_bytes
            and path.stat().st_size > 0
        ):
            if self._stream is not None:
                self._stream.close()
            self._rotate_size(path)
            self._stream = path.open("a", encoding="utf-8")
        return self._stream

    @staticmethod
    def _rotate_size(path: Path) -> None:
        index = 1
        while path.with_name(f"{path.name}.{index}").exists():
            index += 1
        path.rename(path.with_name(f"{path.name}.{index}"))


def configure_operations_logger(
    logger_name: str = "lecture_prism.operations",
    directory: Path | str = Path("logs"),
    *,
    max_bytes: int = 1_000_000,
    now: Callable[[], datetime] | None = None,
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    for handler in list(logger.handlers):
        if getattr(handler, "_lecture_prism_operations_handler", False):
            logger.removeHandler(handler)
            handler.close()
    handler = DailySizeRotatingOperationsHandler(
        directory,
        max_bytes=max_bytes,
        now=now,
    )
    handler._lecture_prism_operations_handler = True
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_operation(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(format_operations_log_line(event, **fields))


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
