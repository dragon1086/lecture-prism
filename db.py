"""
db.py — 공용 SQLite 저장소

파이프라인(main.py)과 대시보드(dashboard.py)가 공유하는 단일 데이터 소스.
feedback.py가 매매·분석·교훈을 여기에 기록하면 dashboard.py가 읽어서 보여줍니다.

테이블:
  - trade_history       : 매매 의사결정/체결 내역
  - analysis_decisions  : AI 에이전트 분석 결과
  - feedback_lessons    : 축적된 교훈 (단기/중기/장기 메모리)
  - pipeline_runs       : 파이프라인 실행 상태
  - pipeline_events     : 실행별 순서가 보장된 이벤트
  - notification_deliveries : 채널별 알림 전달 상태 (비밀값 제외)

이 파일이 "스키마의 진실 원천(single source of truth)"입니다.
dashboard.py와 feedback.py 모두 여기서 init_db()를 호출합니다.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "prism.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,            -- BUY / SELL / PASS
    price INTEGER,
    quantity INTEGER,
    mode TEXT DEFAULT 'simulation',
    reason TEXT
);

CREATE TABLE IF NOT EXISTS analysis_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    recommendation TEXT NOT NULL,    -- BUY / HOLD / PASS
    score INTEGER,
    reason TEXT,
    risk TEXT,
    sections TEXT                    -- 6섹션 요약 JSON (기술/수급/재무/산업/뉴스/시장)
);

CREATE TABLE IF NOT EXISTS feedback_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    lesson TEXT NOT NULL,
    tier TEXT DEFAULT 'short',       -- short / medium / long
    error_type TEXT DEFAULT 'JUDGMENT'
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    profile TEXT NOT NULL,
    trade_state TEXT NOT NULL,
    data_source TEXT,
    data_as_of TEXT,
    market_status TEXT,
    failure_stage TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    ticker TEXT,
    summary TEXT,
    details TEXT,
    UNIQUE(run_id, sequence)
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    queued_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT,
    UNIQUE(run_id, sequence, channel)
);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """테이블 생성 (없을 때만). 멱등 — 여러 번 호출해도 안전."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        # 구버전 DB 마이그레이션: sections 컬럼이 없으면 추가
        try:
            conn.execute("ALTER TABLE analysis_decisions ADD COLUMN sections TEXT")
        except sqlite3.OperationalError:
            pass  # 이미 존재


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_utc_timestamp(value: object | None) -> str:
    if value is None:
        return _utc_now()
    timestamp = str(value).strip()
    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + "+00:00"
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


_SENSITIVE_KEY_PARTS = (
    "account",
    "api_key",
    "app_key",
    "authorization",
    "bot_token",
    "cano",
    "chat_id",
    "hts_id",
    "password",
    "secret",
    "token",
    "webhook",
)
_DISCORD_WEBHOOK_RE = re.compile(
    r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\S+",
    re.IGNORECASE,
)
_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
_NAMED_SECRET_RE = re.compile(
    r"(?ix)"
    r"(?P<prefix>\b(?:token|secret|api[_-]?key|app[_-]?key|authorization|password)"
    r"\b[\"']?\s*[:=]\s*)"
    r"(?:"
    r"(?P<quote>[\"'])(?P<quoted_value>[^\"']*)(?P=quote)"
    r"|(?P<bare_value>[^\s,;}]+)"
    r")"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _sanitize_text(value: str) -> str:
    value = _DISCORD_WEBHOOK_RE.sub("[REDACTED]", value)
    value = _TELEGRAM_TOKEN_RE.sub("[REDACTED]", value)
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)

    def redact_named_secret(match: re.Match) -> str:
        quote = match.group("quote") or ""
        return f"{match.group('prefix')}{quote}[REDACTED]{quote}"

    return _NAMED_SECRET_RE.sub(redact_named_secret, value)


def _sanitize_value(value: Any, *, key: object | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_value(item_value, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_text(str(value))


def _pack_event_details(details: object) -> str | None:
    if details is None:
        return None
    return json.dumps(_sanitize_value(details), ensure_ascii=False)


def _sanitize_error(error: object | None) -> str | None:
    if error is None:
        return None
    if not isinstance(error, str):
        return json.dumps(_sanitize_value(error), ensure_ascii=False)

    stripped = error.strip()
    if stripped.startswith(("{", "[")):
        try:
            structured = json.loads(stripped)
        except json.JSONDecodeError:
            return "[REDACTED]"
        return json.dumps(_sanitize_value(structured), ensure_ascii=False)
    return _sanitize_text(error)


# ── 쓰기 (feedback.py / 파이프라인에서 호출) ──────────────────────────────────

def start_pipeline_run(run: dict) -> None:
    """파이프라인 실행 시작 상태를 저장한다."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO pipeline_runs "
            "(run_id, started_at, status, profile, trade_state, data_source, data_as_of, market_status) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                run["run_id"],
                _normalize_utc_timestamp(run.get("started_at")),
                run.get("status", "running"),
                run.get("profile", "mock"),
                run.get("trade_state", "simulation"),
                run.get("data_source"),
                run.get("data_as_of"),
                run.get("market_status"),
            ),
        )


def finish_pipeline_run(
    run_id: str, status: str, failure_stage: str | None = None
) -> None:
    """파이프라인 실행의 최종 상태와 완료 시각을 기록한다."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "UPDATE pipeline_runs "
            "SET completed_at = ?, status = ?, failure_stage = ? WHERE run_id = ?",
            (_utc_now(), status, failure_stage, run_id),
        )


def save_pipeline_event(event: dict) -> None:
    """비밀값을 제거한 파이프라인 이벤트를 저장한다."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO pipeline_events "
            "(run_id, sequence, occurred_at, event_type, status, ticker, summary, details) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                event["run_id"],
                int(event["sequence"]),
                event.get("occurred_at") or _utc_now(),
                event["event_type"],
                event.get("status") or "succeeded",
                event.get("ticker"),
                _sanitize_text(str(event.get("summary") or "")),
                _pack_event_details(event.get("details")),
            ),
        )


def save_notification_delivery(delivery: dict) -> None:
    """채널 전달 상태만 저장하고 인증 정보는 버린다."""
    init_db()
    status = delivery.get("status", "queued")
    completed_at = delivery.get("completed_at")
    if completed_at is None and status in {"sent", "failed", "skipped"}:
        completed_at = _utc_now()
    sanitized_error = _sanitize_error(delivery.get("error"))
    with _connect() as conn:
        conn.execute(
            "INSERT INTO notification_deliveries "
            "(run_id, sequence, channel, status, attempts, queued_at, completed_at, error) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id, sequence, channel) DO UPDATE SET "
            "status = excluded.status, attempts = excluded.attempts, "
            "completed_at = excluded.completed_at, error = excluded.error",
            (
                delivery["run_id"],
                int(delivery["sequence"]),
                delivery["channel"],
                status,
                int(delivery.get("attempts", 0) or 0),
                delivery.get("queued_at") or _utc_now(),
                completed_at,
                sanitized_error,
            ),
        )

# analysis.py 6섹션 요약 키 (dashboard.py가 같은 키로 렌더링)
_SECTION_KEYS = ("technical_summary", "supply_summary", "financial_summary",
                 "industry_summary", "news_summary", "market_condition")


def _pack_sections(analysis: dict) -> str | None:
    """6섹션 요약을 JSON 문자열로 (있는 것만). 없으면 None."""
    sections = {k: analysis[k] for k in _SECTION_KEYS if analysis.get(k)}
    return json.dumps(sections, ensure_ascii=False) if sections else None


def save_analysis(analysis: dict) -> None:
    """분석 결과 1건 저장."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO analysis_decisions (timestamp, ticker, recommendation, score, reason, risk, sections) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                _now(),
                analysis.get("ticker", ""),
                analysis.get("recommendation", "PASS"),
                int(analysis.get("buy_score", analysis.get("score", 0)) or 0),  # 0~10점
                analysis.get("rationale") or analysis.get("reason", ""),
                analysis.get("risk", ""),
                _pack_sections(analysis),
            ),
        )


def save_trade(trade: dict) -> None:
    """매매 결과 1건 저장."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO trade_history (timestamp, ticker, action, price, quantity, mode, reason) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                _now(),
                trade.get("ticker", ""),
                trade.get("action", "PASS"),
                int(trade.get("executed_price") or trade.get("price") or 0),
                int(trade.get("quantity", 0) or 0),
                trade.get("mode", "simulation"),
                trade.get("reason", ""),
            ),
        )


def save_lesson(ticker: str, action: str, lesson: str,
                tier: str = "short", error_type: str = "JUDGMENT") -> None:
    """교훈 1건 저장 (단기/중기/장기 메모리)."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO feedback_lessons (timestamp, ticker, action, lesson, tier, error_type) "
            "VALUES (?,?,?,?,?,?)",
            (_now(), ticker, action, lesson, tier, error_type),
        )


# ── 읽기 (feedback.py 교훈 주입 / dashboard.py 표시) ──────────────────────────

def get_latest_pipeline_run() -> dict | None:
    """가장 최근에 시작된 파이프라인 실행을 반환한다."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_pipeline_events(run_id: str) -> list[dict]:
    """실행 이벤트를 발생 순서대로 반환한다."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pipeline_events WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]

def get_recent_lessons(n: int = 5) -> list[str]:
    """최근 N개 교훈 텍스트 (다음 매매 프롬프트에 주입용)."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT lesson FROM feedback_lessons ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [r["lesson"] for r in rows]


def count_rows(table: str) -> int:
    """행 수 (데모 데이터 시드 여부 판단용)."""
    init_db()
    allowed = {"trade_history", "analysis_decisions", "feedback_lessons"}
    if table not in allowed:
        raise ValueError(f"unknown table: {table}")
    with _connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


if __name__ == "__main__":
    init_db()
    print(f"DB 초기화 완료: {DB_PATH}")
    for t in ("trade_history", "analysis_decisions", "feedback_lessons"):
        print(f"  {t}: {count_rows(t)} rows")
