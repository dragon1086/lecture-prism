"""
operations.py — 자동매매 본체 주변의 작은 운영 작업

한 번의 전체 분석과 별도로 다음 작업을 독립 실행합니다.

- batch: 스크리닝→분석→매매→피드백 전체 배치
- monitor: 보유 종목의 손절·트레일링·목표가 점검
- reconcile: 접수 후 끝나지 않은 브로커 주문 상태 재확인
- compress: 오래된 교훈을 중기 요약과 장기 원칙으로 압축
- schedule: 위 작업을 정해진 시각에 호출하는 교육용 스케줄러

기본값은 항상 시뮬레이션입니다. schedule은 LECTURE_ENABLE_SCHEDULER=1일
때만 시작되며, 실제 주문 안전 게이트는 trading.py가 그대로 담당합니다.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import logging
import os
from pathlib import Path
import signal
import sqlite3
import sys
from typing import Sequence
from zoneinfo import ZoneInfo

import operations_runtime
import trading

log = logging.getLogger(__name__)

_COMMANDS = {"batch", "monitor", "reconcile", "compress"}
KST = ZoneInfo("Asia/Seoul")
_WEEKDAYS = (0, 1, 2, 3, 4)
_RECONCILIATION_FAILURE_STATUSES = {"unavailable", "unsupported", "error", "failure"}
_STALE_DATA_STATUSES = {"stale_data", "blocked_stale_data"}
_STALE_DATA_REASON_CODES = {"stale_data", "blocked_stale"}


class StaleDataSignal(RuntimeError):
    """Typed scheduler signal for stale market/pipeline data."""

    def __init__(
        self,
        *,
        reason_code: str = "stale_data",
        last_data_at: str | None = None,
    ) -> None:
        super().__init__("stale_data")
        self.reason_code = reason_code
        self.last_data_at = last_data_at


@dataclass(frozen=True)
class JobSpec:
    """하루 중 한 시각에 실행할 교육용 작업 명세."""

    name: str
    at: str
    weekdays: tuple[int, ...]
    command: str

    def __post_init__(self) -> None:
        try:
            hour_text, minute_text = self.at.split(":", maxsplit=1)
            hour, minute = int(hour_text), int(minute_text)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("at은 HH:MM 형식이어야 합니다") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("at은 유효한 24시간 시각이어야 합니다")
        if not self.weekdays or any(day not in range(7) for day in self.weekdays):
            raise ValueError("weekdays는 0(월)부터 6(일) 사이여야 합니다")
        if self.command not in _COMMANDS:
            raise ValueError(f"지원하지 않는 작업: {self.command}")


DEFAULT_JOBS = (
    JobSpec("오전 전체 분석", "09:30", (0, 1, 2, 3, 4), "batch"),
    JobSpec("오후 전체 분석", "14:45", (0, 1, 2, 3, 4), "batch"),
    JobSpec("보유 종목 점검", "14:55", (0, 1, 2, 3, 4), "monitor"),
    JobSpec("미체결 주문 확인", "15:05", (0, 1, 2, 3, 4), "reconcile"),
    JobSpec("주간 메모리 압축", "03:00", (6,), "compress"),
)


def _as_kst(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


def _minutes_between(start: str, end: str, interval_minutes: int) -> list[str]:
    if interval_minutes <= 0:
        raise ValueError("interval_minutes는 1 이상이어야 합니다")
    start_hour, start_minute = (int(part) for part in start.split(":", maxsplit=1))
    end_hour, end_minute = (int(part) for part in end.split(":", maxsplit=1))
    current = datetime(2000, 1, 3, start_hour, start_minute, tzinfo=KST)
    last = datetime(2000, 1, 3, end_hour, end_minute, tzinfo=KST)
    values: list[str] = []
    while current <= last:
        values.append(current.strftime("%H:%M"))
        current += timedelta(minutes=interval_minutes)
    return values


def build_schedule(
    *,
    monitor_interval_minutes: int = 10,
    reconcile_interval_minutes: int = 30,
) -> tuple[JobSpec, ...]:
    """Return default jobs plus configurable KST intraday checks."""

    interval_jobs: list[JobSpec] = []
    occupied = {(job.command, job.at) for job in DEFAULT_JOBS}
    for at in _minutes_between("09:35", "15:20", monitor_interval_minutes):
        if ("monitor", at) in occupied:
            continue
        occupied.add(("monitor", at))
        interval_jobs.append(
            JobSpec(f"장중 보유 종목 점검 {at}", at, _WEEKDAYS, "monitor")
        )
    for at in _minutes_between("10:00", "15:00", reconcile_interval_minutes):
        if ("reconcile", at) in occupied:
            continue
        occupied.add(("reconcile", at))
        interval_jobs.append(
            JobSpec(f"장중 미체결 주문 확인 {at}", at, _WEEKDAYS, "reconcile")
        )
    return (*DEFAULT_JOBS, *interval_jobs)


def next_run_after(now: datetime, jobs: Sequence[JobSpec] = DEFAULT_JOBS) -> datetime:
    """Return the next scheduled run after ``now`` in Asia/Seoul time."""

    current = _as_kst(now).replace(second=0, microsecond=0)
    candidates: list[datetime] = []
    for offset in range(14):
        day = current.date() + timedelta(days=offset)
        for job in jobs:
            hour_text, minute_text = job.at.split(":", maxsplit=1)
            candidate = datetime.combine(
                day,
                time(int(hour_text), int(minute_text), tzinfo=KST),
            )
            if candidate.weekday() in job.weekdays and candidate > current:
                candidates.append(candidate)
    if not candidates:
        raise ValueError("향후 14일 안에 실행할 작업이 없습니다")
    return min(candidates)


def is_korean_market_open(now: datetime) -> bool:
    """Best-effort KST market-hours check for unattended broker execution."""

    current = _as_kst(now)
    if current.weekday() not in _WEEKDAYS:
        return False
    current_time = current.time().replace(tzinfo=None)
    return time(9, 0) <= current_time <= time(15, 30)


def due_jobs(
    now: datetime,
    jobs: Sequence[JobSpec] = DEFAULT_JOBS,
    *,
    seen: set[tuple[str, str]] | None = None,
) -> list[JobSpec]:
    """현재 분에 해당하며 아직 실행하지 않은 작업을 반환합니다."""

    current = _as_kst(now)
    minute_key = current.strftime("%Y-%m-%d %H:%M")
    due: list[JobSpec] = []
    for job in jobs:
        if current.weekday() not in job.weekdays or current.strftime("%H:%M") != job.at:
            continue
        marker = (minute_key, job.command)
        if seen is not None and marker in seen:
            continue
        if seen is not None:
            seen.add(marker)
        due.append(job)
    return due


async def run_holding_monitor(*, dry_run: bool = True) -> list[dict]:
    """보유 종목만 다시 읽어 청산 조건을 검사합니다."""

    holdings = await trading._get_exit_holdings()
    prices = await trading._load_holding_prices(holdings, dry_run=dry_run)
    await trading._persist_holding_highs(holdings, prices)
    decisions = await trading.run_exit_check(holdings, prices)
    results = [
        await trading._execute_decision(decision, dry_run=dry_run)
        for decision in decisions
    ]
    if results:
        from feedback import run_feedback

        await run_feedback(results, [])
    return results


async def run_order_reconciliation(broker_name: str | None = None) -> dict:
    """미결 주문을 조회만 하며 새 주문은 만들지 않습니다."""

    broker = (broker_name or os.getenv("LECTURE_BROKER", "kis")).strip().lower()
    readers = {
        "kis": trading.reconcile_pending_kis_orders,
        "toss": trading.reconcile_pending_toss_orders,
    }
    reader = readers.get(broker)
    if reader is None:
        return {"broker": broker, "status": "unsupported", "orders": []}
    try:
        orders = await reader()
    except Exception as exc:  # noqa: BLE001 - 보조 작업 하나가 전체 스케줄을 막지 않음
        log.warning("미체결 주문 확인 실패 [%s]: %s", broker, type(exc).__name__)
        return {
            "broker": broker,
            "status": "unavailable",
            "orders": [],
            "error_type": type(exc).__name__,
        }
    return {"broker": broker, "status": "ok", "orders": orders}


async def run_analysis_batch(
    *,
    target_ticker: str | None = None,
    dry_run: bool = True,
    config=None,
    notifier=None,
) -> object:
    """기본 시뮬레이션으로 메인 파이프라인을 한 번 실행합니다."""

    from main import run_pipeline

    use_real_data = bool(
        config is not None
        and config.profile not in {"classroom", "backtest"}
        and config.screening_mode == "real"
    )
    return await run_pipeline(
        dry_run=dry_run,
        target_ticker=target_ticker,
        use_real_data=use_real_data,
        config=config,
        notifier=notifier,
    )


async def run_memory_compression() -> dict:
    """메모리 모듈을 늦게 import해 기본 파이프라인 의존성을 늘리지 않습니다."""

    from memory import compress_memories

    return await asyncio.to_thread(compress_memories)


async def run_job(
    command: str,
    *,
    policy: operations_runtime.ExecutionPolicy | None = None,
    config=None,
    notifier=None,
) -> object:
    """스케줄 명세의 명령 하나를 실행합니다."""

    dry_run = True if policy is None else policy.dry_run
    if command == "batch":
        return await run_analysis_batch(
            dry_run=dry_run,
            config=config,
            notifier=notifier,
        )
    if command == "monitor":
        return await run_holding_monitor(dry_run=dry_run)
    if command == "reconcile":
        return await run_order_reconciliation()
    if command == "compress":
        return await run_memory_compression()
    raise ValueError(f"지원하지 않는 작업: {command}")


async def run_scheduled_job(
    job: JobSpec,
    *,
    state_store: operations_runtime.OperationsStateStore,
    active_jobs: set[str],
    policy: operations_runtime.ExecutionPolicy | None = None,
    config=None,
    notifier=None,
    market_open_checker=None,
    operations_logger: logging.Logger | None = None,
    now=datetime.now,
) -> dict:
    """Run one due job with a non-blocking same-command overlap guard."""

    job_key = job.command
    if job_key in active_jobs or job.name in active_jobs:
        finished_at = now().isoformat(timespec="seconds")
        state_store.record_job_skipped_overlap(job_key, finished_at)
        if operations_logger is not None:
            operations_runtime.log_operation(
                operations_logger,
                "job_skipped_overlap",
                job=job_key,
                finished_at=finished_at,
            )
        return {"job": job_key, "status": "skipped_overlap"}

    current = _as_kst(now())
    if (
        policy is not None
        and policy.profile in {"paper", "live"}
        and not policy.dry_run
    ):
        checker = market_open_checker or is_korean_market_open
        if bool(checker(current)):
            pass
        else:
            finished_at = current.isoformat(timespec="seconds")
            state_store.record_job_skipped_market_closed(job_key, finished_at)
            if operations_logger is not None:
                operations_runtime.log_operation(
                    operations_logger,
                    "job_skipped_market_closed",
                    job=job_key,
                    profile=policy.profile,
                    finished_at=finished_at,
                )
            return {"job": job_key, "status": "skipped_market_closed"}

    active_jobs.add(job_key)
    started_at = _as_kst(now()).isoformat(timespec="seconds")
    state_store.record_job_start(job_key, started_at)
    if operations_logger is not None:
        operations_runtime.log_operation(
            operations_logger,
            "job_start",
            job=job_key,
            profile=getattr(config, "profile", None),
            dry_run=None if policy is None else policy.dry_run,
            started_at=started_at,
        )
    try:
        result = await run_job(
            job.command,
            policy=policy,
            config=config,
            notifier=notifier,
        )
    except StaleDataSignal as exc:
        return await _record_stale_data(
            job_key,
            state_store=state_store,
            notifier=notifier,
            operations_logger=operations_logger,
            now=now,
            context={
                "reason_code": exc.reason_code,
                "last_data_at": exc.last_data_at,
                "profile": getattr(config, "profile", None),
            },
        )
    except Exception as exc:
        finished_at = _as_kst(now()).isoformat(timespec="seconds")
        state_store.record_job_failure(
            job_key,
            finished_at,
            error_type=type(exc).__name__,
        )
        if operations_logger is not None:
            operations_runtime.log_operation(
                operations_logger,
                "job_failure",
                job=job_key,
                error=exc,
                finished_at=finished_at,
            )
        await _notify_operational(
            notifier,
            "job_failure",
            {
                "job": job_key,
                "profile": getattr(config, "profile", None),
                "error": exc,
            },
        )
        raise
    else:
        if _is_reconciliation_failure(job.command, result):
            return await _record_reconciliation_failure(
                job_key,
                state_store=state_store,
                notifier=notifier,
                operations_logger=operations_logger,
                now=now,
                result=result,
                profile=getattr(config, "profile", None),
            )
        if _is_stale_data_result(result):
            return await _record_stale_data(
                job_key,
                state_store=state_store,
                notifier=notifier,
                operations_logger=operations_logger,
                now=now,
                context={
                    "profile": getattr(config, "profile", None),
                    "result": result,
                    **(result if isinstance(result, dict) else {}),
                },
            )
        finished_at = _as_kst(now()).isoformat(timespec="seconds")
        state_store.record_job_success(job_key, finished_at)
        if operations_logger is not None:
            operations_runtime.log_operation(
                operations_logger,
                "job_success",
                job=job_key,
                finished_at=finished_at,
            )
        return {"job": job_key, "status": "success"}
    finally:
        active_jobs.discard(job_key)


def _is_reconciliation_failure(command: str, result: object) -> bool:
    if command != "reconcile" or not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").strip().lower()
    return status in _RECONCILIATION_FAILURE_STATUSES


def _is_stale_data_result(result: object) -> bool:
    if isinstance(result, list):
        return any(_is_stale_data_result(item) for item in result)
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").strip().lower()
    reason_code = str(result.get("reason_code") or "").strip().lower()
    mode = str(result.get("mode") or "").strip().lower()
    operational_alert = bool(result.get("operational_alert"))
    quote_blocked = (
        operational_alert
        and status == "blocked"
        and mode.startswith("broker_quote_")
    )
    return (
        status in _STALE_DATA_STATUSES
        or reason_code in _STALE_DATA_REASON_CODES
        or quote_blocked
    )


async def _record_reconciliation_failure(
    job_key: str,
    *,
    state_store: operations_runtime.OperationsStateStore,
    notifier,
    operations_logger: logging.Logger | None,
    now,
    result: dict,
    profile: str | None,
) -> dict:
    finished_at = _as_kst(now()).isoformat(timespec="seconds")
    state_store.record_job_failure(
        job_key,
        finished_at,
        error_type="ReconciliationFailure",
    )
    context = {
        "job": job_key,
        "profile": profile,
        "status": result.get("status"),
        "broker": result.get("broker"),
        "error_type": result.get("error_type") or "ReconciliationFailure",
        "result": result,
        "finished_at": finished_at,
    }
    if operations_logger is not None:
        operations_runtime.log_operation(
            operations_logger,
            "reconciliation_failure",
            **context,
        )
    await _notify_operational(notifier, "reconciliation_failure", context)
    return {"job": job_key, "status": "failure", "error_type": "ReconciliationFailure"}


async def _record_stale_data(
    job_key: str,
    *,
    state_store: operations_runtime.OperationsStateStore,
    notifier,
    operations_logger: logging.Logger | None,
    now,
    context: dict,
) -> dict:
    finished_at = _as_kst(now()).isoformat(timespec="seconds")
    state_store.record_job_failure(
        job_key,
        finished_at,
        error_type="StaleData",
    )
    payload = {
        "job": job_key,
        "status": "stale_data",
        "error_type": "StaleData",
        "finished_at": finished_at,
        **context,
    }
    if operations_logger is not None:
        operations_runtime.log_operation(
            operations_logger,
            "stale_data",
            **payload,
        )
    await _notify_operational(notifier, "stale_data", payload)
    return {"job": job_key, "status": "stale_data", "error_type": "StaleData"}


async def _notify_operational(notifier, event: str, context: dict) -> bool:
    if notifier is None:
        return False
    method = getattr(notifier, "operational", None)
    if method is None:
        return False
    try:
        return bool(await method(event, context))
    except Exception as exc:  # noqa: BLE001 - 운영 알림은 스케줄 결과와 분리
        log.warning("운영 알림 실패: %s", type(exc).__name__)
        return False


def request_scheduler_stop(
    stop_event: asyncio.Event,
    state_store: operations_runtime.OperationsStateStore,
    *,
    pid: int | None = None,
    project_path: str | Path | None = None,
    owner_token: str | None = None,
    process_identity: str | None = None,
) -> None:
    """Signal-safe stop callback used by SIGINT/SIGTERM handlers and tests."""

    stop_event.set()
    selected_pid = pid or os.getpid()
    if project_path is not None and owner_token is not None:
        state_store.record_scheduler_status_if_owner(
            "stopping",
            pid=selected_pid,
            project_path=project_path,
            owner_token=owner_token,
            process_identity=process_identity,
        )
    else:
        state_store.record_scheduler_status("stopping", pid=selected_pid)


def _install_signal_handlers(
    stop_event: asyncio.Event,
    state_store: operations_runtime.OperationsStateStore,
    lock: operations_runtime.SchedulerLock,
) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                signum,
                request_scheduler_stop,
                stop_event,
                state_store,
                pid=os.getpid(),
                project_path=lock.project_path,
                owner_token=lock.owner_token,
                process_identity=lock.process_identity_token,
            )
        except (NotImplementedError, RuntimeError):
            signal.signal(
                signum,
                lambda _signum, _frame: request_scheduler_stop(
                    stop_event,
                    state_store,
                    pid=os.getpid(),
                    project_path=lock.project_path,
                    owner_token=lock.owner_token,
                    process_identity=lock.process_identity_token,
                ),
            )


async def run_scheduler(
    jobs: Sequence[JobSpec] = DEFAULT_JOBS,
    *,
    poll_seconds: int = 20,
    runtime_dir: str | Path | None = None,
    state_store: operations_runtime.OperationsStateStore | None = None,
    stop_event: asyncio.Event | None = None,
    now_func=datetime.now,
    sleep=asyncio.sleep,
    profile: str | None = None,
    execute_broker: bool = False,
    once: bool = False,
    monitor_interval_minutes: int = 10,
    reconcile_interval_minutes: int = 30,
    market_open_checker=None,
    notifier=None,
    operations_logger: logging.Logger | None = None,
) -> None:
    """명시적으로 켰을 때만 동작하는 단순 분 단위 스케줄러."""

    if os.getenv("LECTURE_ENABLE_SCHEDULER", "0") != "1":
        raise RuntimeError(
            "스케줄러는 기본적으로 꺼져 있습니다. "
            "LECTURE_ENABLE_SCHEDULER=1일 때만 실행하세요."
        )
    if runtime_dir is None:
        runtime_path = operations_runtime.default_runtime_dir()
    else:
        runtime_path = Path(runtime_dir)
    if jobs is DEFAULT_JOBS:
        jobs = build_schedule(
            monitor_interval_minutes=monitor_interval_minutes,
            reconcile_interval_minutes=reconcile_interval_minutes,
        )
    config, policy = _load_runtime_context_without_env_mutation(
        profile,
        execute_broker=execute_broker,
    )
    if operations_logger is None:
        operations_logger = operations_runtime.configure_operations_logger(
            directory=runtime_path / "logs",
        )
    state = state_store or operations_runtime.OperationsStateStore(runtime_path)
    lock = operations_runtime.SchedulerLock(runtime_path, state_store=state)
    event = stop_event or asyncio.Event()
    active_jobs: set[str] = set()
    seen: set[tuple[str, str]] = set()
    lock.acquire()
    _install_signal_handlers(event, state, lock)
    operations_runtime.log_operation(
        operations_logger,
        "service_start",
        profile=config.profile,
        dry_run=policy.dry_run,
        account_mode=policy.account_mode,
        blocked_reasons=policy.blocked_reasons,
    )
    await _notify_operational(
        notifier,
        "service_start",
        {
            "profile": config.profile,
            "status": "running",
            "blocked_reasons": policy.blocked_reasons,
        },
    )
    if execute_broker and policy.blocked_reasons:
        await _notify_operational(
            notifier,
            "blocked_unattended_gate",
            {
                "profile": config.profile,
                "blocked_reasons": policy.blocked_reasons,
            },
        )
    try:
        while not event.is_set():
            lock.heartbeat()
            now = now_func()
            for job in due_jobs(now, jobs, seen=seen):
                if event.is_set():
                    break
                log.info("예약 작업 시작: %s", job.name)
                try:
                    await run_scheduled_job(
                        job,
                        state_store=state,
                        active_jobs=active_jobs,
                        policy=policy,
                        config=config,
                        notifier=notifier,
                        market_open_checker=market_open_checker,
                        operations_logger=operations_logger,
                        now=now_func,
                    )
                except Exception as exc:  # noqa: BLE001 - 다음 예약 작업은 계속 실행
                    log.warning("예약 작업 실패 [%s]: %s", job.name, type(exc).__name__)
            current_minute = _as_kst(now).strftime("%Y-%m-%d %H:%M")
            seen.intersection_update(
                marker for marker in seen if marker[0] == current_minute
            )
            if once:
                event.set()
                break
            await sleep(max(1, poll_seconds))
    finally:
        if lock.owns_metadata():
            state.record_scheduler_status_if_owner(
                "stopped",
                pid=lock.pid,
                project_path=lock.project_path,
                owner_token=lock.owner_token,
                process_identity=lock.process_identity_token,
            )
        else:
            state.record_scheduler_status_if_owner(
                "lost_lock",
                pid=lock.pid,
                project_path=lock.project_path,
                owner_token=lock.owner_token,
                process_identity=lock.process_identity_token,
            )
        lock.release()
        operations_runtime.log_operation(
            operations_logger,
            "service_stop",
            profile=config.profile,
        )
        await _notify_operational(
            notifier,
            "service_stop",
            {
                "profile": config.profile,
                "status": "stopped",
            },
        )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _unresolved_order_count() -> int:
    import db

    if not db.DB_PATH.exists():
        return 0
    with sqlite3.connect(db.DB_PATH) as conn:
        if not _table_exists(conn, "broker_orders"):
            return 0
        row = conn.execute(
            "SELECT COUNT(*) FROM broker_orders "
            "WHERE status NOT IN ('FILLED', 'REJECTED', 'CANCELED')"
        ).fetchone()
    return int(row[0] if row else 0)


def _last_data_timestamp() -> str | None:
    import db

    if not db.DB_PATH.exists():
        return None
    timestamps: list[str] = []
    with sqlite3.connect(db.DB_PATH) as conn:
        for table in ("analysis_decisions", "trade_history", "feedback_lessons"):
            if not _table_exists(conn, table):
                continue
            row = conn.execute(f"SELECT MAX(timestamp) FROM {table}").fetchone()  # noqa: S608
            if row and row[0]:
                timestamps.append(str(row[0]))
    return max(timestamps) if timestamps else None


def build_status_snapshot(
    *,
    state_store: operations_runtime.OperationsStateStore | None = None,
    profile: str | None = None,
    execute_broker: bool = False,
    env: dict[str, str] | None = None,
    unresolved_order_count=_unresolved_order_count,
    last_data_timestamp=_last_data_timestamp,
    now=lambda: datetime.now().isoformat(timespec="seconds"),
) -> dict:
    source = env if env is not None else os.environ
    selected_profile = (
        profile
        or source.get("LECTURE_PROFILE")
        or source.get("PRISM_PROFILE")
        or "mock"
    )
    policy = operations_runtime.resolve_execution_policy(
        selected_profile,
        execute_broker=execute_broker,
        env=source,
    )
    state = (state_store or operations_runtime.OperationsStateStore()).read()
    broker = str(source.get("LECTURE_BROKER") or "kis").strip().lower()
    return operations_runtime.serialize_status(
        {
            "profile": policy.profile,
            "broker": broker,
            "account_mode": policy.account_mode,
            "dry_run": policy.dry_run,
            "blocked_reasons": policy.blocked_reasons,
            "scheduler": state.get("scheduler", {}),
            "jobs": state.get("jobs", {}),
            "unresolved_order_count": unresolved_order_count(),
            "last_data_timestamp": last_data_timestamp(),
            "next_jobs": [
                {"name": job.name, "command": job.command, "at": job.at}
                for job in DEFAULT_JOBS
            ],
            "generated_at": now(),
        }
    )


def format_status(snapshot: dict) -> str:
    scheduler = snapshot.get("scheduler") or {}
    jobs = snapshot.get("jobs") or {}
    lines = [
        f"profile: {snapshot.get('profile')}",
        f"broker: {snapshot.get('broker')}",
        f"account_mode: {snapshot.get('account_mode')}",
        f"dry_run: {snapshot.get('dry_run')}",
        f"scheduler_status: {scheduler.get('status')}",
        f"scheduler_pid: {scheduler.get('pid')}",
        f"scheduler_heartbeat: {scheduler.get('heartbeat_at')}",
        f"unresolved_order_count: {snapshot.get('unresolved_order_count')}",
        f"last_data_timestamp: {snapshot.get('last_data_timestamp')}",
        "jobs:",
    ]
    for name in sorted(jobs):
        job = jobs[name] or {}
        lines.append(f"  {name}: {job.get('status')}")
    lines.append("next_jobs:")
    for job in snapshot.get("next_jobs") or []:
        lines.append(f"  {job['at']} {job['command']} ({job['name']})")
    return "\n".join(lines) + "\n"


def print_status(
    *,
    state_store: operations_runtime.OperationsStateStore | None = None,
    output=sys.stdout,
    profile: str | None = None,
    execute_broker: bool = False,
    env: dict[str, str] | None = None,
    unresolved_order_count=_unresolved_order_count,
    last_data_timestamp=_last_data_timestamp,
    now=lambda: datetime.now().isoformat(timespec="seconds"),
) -> None:
    snapshot = build_status_snapshot(
        state_store=state_store,
        profile=profile,
        execute_broker=execute_broker,
        env=env,
        unresolved_order_count=unresolved_order_count,
        last_data_timestamp=last_data_timestamp,
        now=now,
    )
    output.write(format_status(snapshot))


def _restore_environment(snapshot: dict[str, str]) -> None:
    for key in tuple(os.environ):
        if key not in snapshot:
            os.environ.pop(key, None)
    os.environ.update(snapshot)


def _reset_dotenv_loaded_marker() -> None:
    try:
        from brokers import config as broker_config

        env_path = broker_config.project_root() / ".env"
        broker_config._LOADED_ENV_FILES.discard(env_path.resolve())  # noqa: SLF001
    except Exception:  # noqa: BLE001 - env restoration must not block operations
        return


def _load_runtime_context_without_env_mutation(
    profile: str | None,
    *,
    execute_broker: bool,
):
    from runtime_config import load_runtime_config

    before = dict(os.environ)
    try:
        config = load_runtime_config(profile)
        loaded_env = dict(os.environ)
    finally:
        _restore_environment(before)
        _reset_dotenv_loaded_marker()
    policy = operations_runtime.resolve_execution_policy(
        config.profile,
        execute_broker=execute_broker,
        env=loaded_env,
    )
    return config, policy


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="lecture-prism 보조 운영 작업을 한 번씩 실행합니다."
    )
    parser.add_argument(
        "command",
        choices=("batch", "monitor", "reconcile", "compress", "schedule", "status", "doctor"),
    )
    parser.add_argument("--ticker", help="batch에서 분석할 단일 종목")
    parser.add_argument(
        "--broker",
        choices=("kis", "kiwoom", "toss", "custom"),
        help="reconcile에서 확인할 브로커",
    )
    parser.add_argument(
        "--profile",
        help="이번 operations 실행에만 적용할 런타임 프로필",
    )
    parser.add_argument(
        "--execute-broker",
        action="store_true",
        help="ExecutionPolicy가 허용할 때만 schedule/batch/monitor의 dry_run을 해제",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="schedule 루프를 한 번만 평가해 테스트 가능한 실행으로 제한",
    )
    parser.add_argument(
        "--monitor-interval-minutes",
        type=int,
        default=10,
        help="장중 보유종목 점검 간격(분)",
    )
    parser.add_argument(
        "--reconcile-interval-minutes",
        type=int,
        default=30,
        help="장중 미체결 주문 확인 간격(분)",
    )
    return parser


async def _main(args: argparse.Namespace) -> None:
    if args.command == "doctor":
        from operations_doctor import print_doctor

        await print_doctor(profile=getattr(args, "profile", None))
        return

    config, policy = _load_runtime_context_without_env_mutation(
        getattr(args, "profile", None),
        execute_broker=bool(getattr(args, "execute_broker", False)),
    )
    if args.command == "batch":
        result = await run_analysis_batch(
            target_ticker=args.ticker,
            dry_run=policy.dry_run,
            config=config,
        )
    elif args.command == "monitor":
        result = await run_holding_monitor(dry_run=policy.dry_run)
    elif args.command == "reconcile":
        result = await run_order_reconciliation(args.broker)
    elif args.command == "compress":
        result = await run_memory_compression()
    elif args.command == "status":
        print_status(
            profile=config.profile,
            execute_broker=bool(getattr(args, "execute_broker", False)),
        )
        return
    else:
        await run_scheduler(
            profile=config.profile,
            execute_broker=bool(getattr(args, "execute_broker", False)),
            once=bool(getattr(args, "once", False)),
            monitor_interval_minutes=int(getattr(args, "monitor_interval_minutes", 10)),
            reconcile_interval_minutes=int(
                getattr(args, "reconcile_interval_minutes", 30)
            ),
        )
        return
    print(result)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    asyncio.run(_main(_build_parser().parse_args()))
