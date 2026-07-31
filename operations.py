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
from datetime import datetime
import logging
import os
from typing import Iterable, Sequence

import trading

log = logging.getLogger(__name__)

_COMMANDS = {"batch", "monitor", "reconcile", "compress"}


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


def due_jobs(
    now: datetime,
    jobs: Sequence[JobSpec] = DEFAULT_JOBS,
    *,
    seen: set[tuple[str, str]] | None = None,
) -> list[JobSpec]:
    """현재 분에 해당하며 아직 실행하지 않은 작업을 반환합니다."""

    minute_key = now.strftime("%Y-%m-%d %H:%M")
    due: list[JobSpec] = []
    for job in jobs:
        if now.weekday() not in job.weekdays or now.strftime("%H:%M") != job.at:
            continue
        marker = (minute_key, job.name)
        if seen is not None and marker in seen:
            continue
        if seen is not None:
            seen.add(marker)
        due.append(job)
    return due


async def run_holding_monitor(*, dry_run: bool = True) -> list[dict]:
    """보유 종목만 다시 읽어 청산 조건을 검사합니다."""

    holdings = await trading._get_exit_holdings()
    prices = await trading._load_holding_prices(holdings)
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


async def run_analysis_batch(*, target_ticker: str | None = None) -> object:
    """기본 시뮬레이션으로 메인 파이프라인을 한 번 실행합니다."""

    from main import run_pipeline

    return await run_pipeline(dry_run=True, target_ticker=target_ticker)


async def run_memory_compression() -> dict:
    """메모리 모듈을 늦게 import해 기본 파이프라인 의존성을 늘리지 않습니다."""

    from memory import compress_memories

    return await asyncio.to_thread(compress_memories)


async def run_job(command: str) -> object:
    """스케줄 명세의 명령 하나를 실행합니다."""

    if command == "batch":
        return await run_analysis_batch()
    if command == "monitor":
        return await run_holding_monitor(dry_run=True)
    if command == "reconcile":
        return await run_order_reconciliation()
    if command == "compress":
        return await run_memory_compression()
    raise ValueError(f"지원하지 않는 작업: {command}")


async def run_scheduler(
    jobs: Sequence[JobSpec] = DEFAULT_JOBS,
    *,
    poll_seconds: int = 20,
) -> None:
    """명시적으로 켰을 때만 동작하는 단순 분 단위 스케줄러."""

    if os.getenv("LECTURE_ENABLE_SCHEDULER", "0") != "1":
        raise RuntimeError(
            "스케줄러는 기본적으로 꺼져 있습니다. "
            "LECTURE_ENABLE_SCHEDULER=1일 때만 실행하세요."
        )
    seen: set[tuple[str, str]] = set()
    while True:
        now = datetime.now()
        for job in due_jobs(now, jobs, seen=seen):
            log.info("예약 작업 시작: %s", job.name)
            try:
                await run_job(job.command)
            except Exception as exc:  # noqa: BLE001 - 다음 예약 작업은 계속 실행
                log.warning("예약 작업 실패 [%s]: %s", job.name, type(exc).__name__)
        current_minute = now.strftime("%Y-%m-%d %H:%M")
        seen.intersection_update(
            marker for marker in seen if marker[0] == current_minute
        )
        await asyncio.sleep(max(1, poll_seconds))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="lecture-prism 보조 운영 작업을 한 번씩 실행합니다."
    )
    parser.add_argument(
        "command",
        choices=("batch", "monitor", "reconcile", "compress", "schedule"),
    )
    parser.add_argument("--ticker", help="batch에서 분석할 단일 종목")
    parser.add_argument(
        "--broker",
        choices=("kis", "kiwoom", "toss", "custom"),
        help="reconcile에서 확인할 브로커",
    )
    return parser


async def _main(args: argparse.Namespace) -> None:
    if args.command == "batch":
        result = await run_analysis_batch(target_ticker=args.ticker)
    elif args.command == "monitor":
        result = await run_holding_monitor(dry_run=True)
    elif args.command == "reconcile":
        result = await run_order_reconciliation(args.broker)
    elif args.command == "compress":
        result = await run_memory_compression()
    else:
        await run_scheduler()
        return
    print(result)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    asyncio.run(_main(_build_parser().parse_args()))
