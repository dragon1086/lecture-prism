"""
memory.py — 모듈 4의 계층형 교훈 압축

원본 PRISM의 LLM 메모리 압축을 수업용으로 작게 재현합니다.

- short  (0~7일): 청산 직후의 상세 교훈
- medium (8~30일): 다시 읽기 쉬운 요약 기록
- long   (31일+): 두 번 이상 반복된 교훈에서 만든 장기 원칙

기본 경로는 표준 라이브러리와 SQLite만 사용합니다. 압축은 수익을
보장하는 장치가 아니라, 다음 판단에 넣을 기록의 양을 제한하는 장치입니다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import json
import re

import db


def _timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min


def _memory_key(lesson: str) -> str:
    """공백·숫자 표현 차이를 줄인 반복 교훈 비교 키."""

    text = re.sub(r"\d[\d,.]*", "#", lesson.lower())
    return re.sub(r"\s+", " ", text).strip()


def compress_memories(
    *,
    now: datetime | None = None,
    short_age_days: int = 7,
    medium_age_days: int = 30,
    min_support: int = 2,
    max_long: int = 20,
) -> dict:
    """오래된 교훈을 중기 기록과 반복 장기 원칙으로 압축합니다."""

    current = now or datetime.now()
    short_cutoff = current - timedelta(days=short_age_days)
    medium_cutoff = current - timedelta(days=medium_age_days)

    old_short = [
        row
        for row in db.get_memory_rows(tier="short", active_only=True)
        if _timestamp(row["timestamp"]) < short_cutoff
    ]
    short_to_medium = db.set_memory_tier(
        [int(row["id"]) for row in old_short],
        "medium",
    )

    old_medium = [
        row
        for row in db.get_memory_rows(tier="medium", active_only=True)
        if _timestamp(row["timestamp"]) < medium_cutoff
    ]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in old_medium:
        groups[(row["error_type"], _memory_key(row["lesson"]))].append(row)

    medium_to_long = 0
    long_created = 0
    for (error_type, _), rows in groups.items():
        support = sum(max(1, int(row["support_count"] or 1)) for row in rows)
        if len(rows) < min_support:
            continue
        representative = rows[0]["lesson"]
        source_ids = [int(row["id"]) for row in rows]
        db.save_lesson(
            ticker="*",
            action=rows[0]["action"],
            lesson=f"반복 원칙({support}건): {representative}",
            tier="long",
            error_type=error_type,
            support_count=support,
            source_ids=json.dumps(source_ids),
        )
        medium_to_long += db.deactivate_memory_rows(source_ids)
        long_created += 1

    long_deactivated = db.enforce_long_memory_limit(max_long)
    return {
        "short_to_medium": short_to_medium,
        "medium_to_long": medium_to_long,
        "long_created": long_created,
        "long_deactivated": long_deactivated,
        "active_short": len(db.get_memory_rows(tier="short", active_only=True)),
        "active_medium": len(db.get_memory_rows(tier="medium", active_only=True)),
        "active_long": len(db.get_memory_rows(tier="long", active_only=True)),
    }


def get_relevant_memories(
    ticker: str,
    sector: str = "",
    *,
    limit: int = 5,
    max_chars: int = 1200,
) -> list[str]:
    """같은 종목 기록을 먼저, 범용 장기 원칙을 다음에 반환합니다."""

    _ = sector  # 강의판에는 섹터별 성과 테이블이 없어 확장 자리만 유지합니다.
    count = max(0, int(limit))
    if not ticker or count == 0:
        return []

    rows = db.get_memory_rows(active_only=True)
    same_ticker = [
        row for row in rows
        if row["ticker"] == ticker and row["tier"] in {"short", "medium"}
    ]
    universal = [
        row for row in rows
        if row["ticker"] == "*" and row["tier"] == "long"
    ]
    universal.sort(
        key=lambda row: (int(row["support_count"] or 1), row["timestamp"]),
        reverse=True,
    )

    selected: list[str] = []
    used_chars = 0
    for row in [*same_ticker, *universal]:
        lesson = str(row["lesson"]).strip()
        if not lesson or used_chars + len(lesson) > max_chars:
            continue
        selected.append(lesson)
        used_chars += len(lesson)
        if len(selected) >= count:
            break
    return selected


if __name__ == "__main__":
    result = compress_memories()
    print("메모리 압축 결과")
    for key, value in result.items():
        print(f"  {key}: {value}")
