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
  - broker_orders       : 복구 가능한 증권사 주문 상태
  - market_calendar_cache : 시장 영업일 조회 캐시

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

CREATE TABLE IF NOT EXISTS broker_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    mode TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    order_date TEXT NOT NULL,
    org_no TEXT,
    order_no TEXT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_qty INTEGER NOT NULL,
    filled_qty INTEGER NOT NULL DEFAULT 0,
    remaining_qty INTEGER NOT NULL,
    requested_price INTEGER,
    avg_fill_price REAL,
    message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(broker, mode, client_request_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_broker_orders_broker_identity
ON broker_orders(broker, mode, order_date, org_no, order_no)
WHERE org_no IS NOT NULL AND org_no <> ''
  AND order_no IS NOT NULL AND order_no <> '';

CREATE INDEX IF NOT EXISTS idx_broker_orders_pending
ON broker_orders(broker, mode, status, updated_at)
WHERE status IN (
    'submitting', 'accepted', 'unknown', 'unfilled',
    'partial_fill', 'cancel_requested'
);

CREATE TABLE IF NOT EXISTS market_calendar_cache (
    broker TEXT NOT NULL,
    market TEXT NOT NULL,
    business_date TEXT NOT NULL,
    is_open INTEGER NOT NULL,
    source TEXT,
    checked_at TEXT NOT NULL,
    PRIMARY KEY(broker, market, business_date)
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


def update_pipeline_run_provenance(
    run_id: str, *, data_source: str | None, data_as_of: str | None
) -> None:
    """분석에서 확인된 실제 데이터 출처와 기준일을 실행 행에 반영한다."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "UPDATE pipeline_runs SET data_source = ?, data_as_of = ? WHERE run_id = ?",
            (data_source, data_as_of, run_id),
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


_ORDER_STATUSES = {
    "submitting",
    "accepted",
    "unknown",
    "unfilled",
    "partial_fill",
    "filled",
    "cancel_requested",
    "cancelled",
    "rejected",
}
_PENDING_ORDER_STATUSES = (
    "submitting",
    "accepted",
    "unknown",
    "unfilled",
    "partial_fill",
    "cancel_requested",
)
_TERMINAL_ORDER_STATUSES = {"filled", "cancelled", "rejected"}
_ORDER_TRANSITIONS = {
    "submitting": {"accepted", "unknown", "rejected"},
    "accepted": {
        "unfilled", "partial_fill", "filled", "cancel_requested", "rejected"
    },
    "unknown": {
        "accepted", "unfilled", "partial_fill", "filled",
        "cancel_requested", "cancelled", "rejected",
    },
    "unfilled": {"partial_fill", "filled", "cancel_requested", "cancelled", "rejected"},
    "partial_fill": {"filled", "cancel_requested", "cancelled", "rejected"},
    "cancel_requested": {"partial_fill", "filled", "cancelled", "rejected"},
    "filled": set(),
    "cancelled": set(),
    "rejected": set(),
}


def _clean_order_identifier(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _find_broker_order(conn: sqlite3.Connection, order: dict) -> sqlite3.Row | None:
    if order.get("id") is not None:
        return conn.execute(
            "SELECT * FROM broker_orders WHERE id = ?", (int(order["id"]),)
        ).fetchone()

    broker = str(order.get("broker") or "").strip().lower()
    mode = str(order.get("mode") or "").strip().lower()
    order_date = str(order.get("order_date") or "").strip()
    org_no = _clean_order_identifier(order.get("org_no"))
    order_no = _clean_order_identifier(order.get("order_no"))
    if broker and mode and order_date and org_no and order_no:
        row = conn.execute(
            "SELECT * FROM broker_orders "
            "WHERE broker = ? AND mode = ? AND order_date = ? "
            "AND org_no = ? AND order_no = ?",
            (broker, mode, order_date, org_no, order_no),
        ).fetchone()
        if row is not None:
            return row

    client_request_id = str(order.get("client_request_id") or "").strip()
    if broker and mode and client_request_id:
        return conn.execute(
            "SELECT * FROM broker_orders "
            "WHERE broker = ? AND mode = ? AND client_request_id = ?",
            (broker, mode, client_request_id),
        ).fetchone()
    return None


def _normalized_order(order: dict, existing: sqlite3.Row | None = None) -> dict:
    source = dict(existing) if existing is not None else {}
    source.update(
        {
            key: order[key]
            for key in (
                "broker", "mode", "client_request_id", "order_date", "org_no",
                "order_no", "ticker", "side", "status", "requested_qty",
                "filled_qty", "remaining_qty", "requested_price", "avg_fill_price",
                "message", "created_at", "updated_at",
            )
            if key in order
        }
    )
    required = (
        "broker", "mode", "client_request_id", "order_date", "ticker", "side",
        "status", "requested_qty",
    )
    missing = [name for name in required if source.get(name) in (None, "")]
    if missing:
        raise ValueError(f"missing broker order fields: {', '.join(missing)}")

    status = str(source["status"]).strip().lower()
    if status not in _ORDER_STATUSES:
        raise ValueError(f"unknown broker order status: {status}")
    requested_qty = int(source["requested_qty"])
    filled_qty = int(source.get("filled_qty") or 0)
    remaining_qty = int(
        source.get("remaining_qty")
        if source.get("remaining_qty") is not None
        else requested_qty - filled_qty
    )
    if requested_qty <= 0:
        raise ValueError("requested_qty must be positive")
    if filled_qty < 0 or remaining_qty < 0 or filled_qty > requested_qty:
        raise ValueError("invalid broker order quantities")
    if filled_qty + remaining_qty > requested_qty:
        raise ValueError("filled_qty plus remaining_qty exceeds requested_qty")

    now = _utc_now()
    created_at = source.get("created_at") or now
    requested_price = source.get("requested_price")
    avg_fill_price = source.get("avg_fill_price")
    return {
        "broker": str(source["broker"]).strip().lower(),
        "mode": str(source["mode"]).strip().lower(),
        "client_request_id": str(source["client_request_id"]).strip(),
        "order_date": str(source["order_date"]).strip(),
        "org_no": _clean_order_identifier(source.get("org_no")),
        "order_no": _clean_order_identifier(source.get("order_no")),
        "ticker": str(source["ticker"]).strip(),
        "side": str(source["side"]).strip().upper(),
        "status": status,
        "requested_qty": requested_qty,
        "filled_qty": filled_qty,
        "remaining_qty": remaining_qty,
        "requested_price": int(requested_price) if requested_price is not None else None,
        "avg_fill_price": float(avg_fill_price) if avg_fill_price is not None else None,
        "message": _sanitize_text(str(source.get("message") or "")),
        "created_at": _normalize_utc_timestamp(created_at),
        "updated_at": _normalize_utc_timestamp(source.get("updated_at") or now),
    }


def _validate_order_progress(existing: sqlite3.Row, updated: dict) -> None:
    current_status = str(existing["status"])
    next_status = updated["status"]
    if current_status != next_status:
        if current_status in _TERMINAL_ORDER_STATUSES:
            raise ValueError(f"terminal order state cannot regress from {current_status}")
        if next_status not in _ORDER_TRANSITIONS[current_status]:
            raise ValueError(
                f"invalid broker order transition: {current_status} -> {next_status}"
            )
    if int(existing["requested_qty"]) != updated["requested_qty"]:
        raise ValueError("requested_qty cannot change")
    if updated["filled_qty"] < int(existing["filled_qty"]):
        raise ValueError("filled_qty cannot decrease")
    if updated["remaining_qty"] > int(existing["remaining_qty"]):
        raise ValueError("remaining_qty cannot increase")


def _update_broker_order_row(
    conn: sqlite3.Connection, existing: sqlite3.Row, order: dict
) -> dict:
    updated = _normalized_order(order, existing)
    _validate_order_progress(existing, updated)
    conn.execute(
        "UPDATE broker_orders SET "
        "order_date = ?, org_no = ?, order_no = ?, ticker = ?, side = ?, status = ?, "
        "requested_qty = ?, filled_qty = ?, remaining_qty = ?, requested_price = ?, "
        "avg_fill_price = ?, message = ?, updated_at = ? WHERE id = ?",
        (
            updated["order_date"], updated["org_no"], updated["order_no"],
            updated["ticker"], updated["side"], updated["status"],
            updated["requested_qty"], updated["filled_qty"], updated["remaining_qty"],
            updated["requested_price"], updated["avg_fill_price"], updated["message"],
            updated["updated_at"], existing["id"],
        ),
    )
    return dict(
        conn.execute("SELECT * FROM broker_orders WHERE id = ?", (existing["id"],)).fetchone()
    )


def save_broker_order(order: dict) -> dict:
    """주문을 저장하고 client/broker 식별자가 같으면 단조롭게 갱신한다."""
    init_db()
    with _connect() as conn:
        existing = _find_broker_order(conn, order)
        if existing is not None:
            return _update_broker_order_row(conn, existing, order)
        normalized = _normalized_order(order)
        cursor = conn.execute(
            "INSERT INTO broker_orders "
            "(broker, mode, client_request_id, order_date, org_no, order_no, ticker, side, "
            "status, requested_qty, filled_qty, remaining_qty, requested_price, "
            "avg_fill_price, message, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                normalized["broker"], normalized["mode"],
                normalized["client_request_id"], normalized["order_date"],
                normalized["org_no"], normalized["order_no"], normalized["ticker"],
                normalized["side"], normalized["status"], normalized["requested_qty"],
                normalized["filled_qty"], normalized["remaining_qty"],
                normalized["requested_price"], normalized["avg_fill_price"],
                normalized["message"], normalized["created_at"], normalized["updated_at"],
            ),
        )
        return dict(
            conn.execute("SELECT * FROM broker_orders WHERE id = ?", (cursor.lastrowid,)).fetchone()
        )


def update_broker_order(order: dict) -> dict:
    """기존 주문을 식별해 허용된 전이와 수량 진행만 저장한다."""
    init_db()
    with _connect() as conn:
        existing = _find_broker_order(conn, order)
        if existing is None:
            raise KeyError("broker order not found")
        return _update_broker_order_row(conn, existing, order)


def get_pending_broker_orders(
    *, broker: str | None = None, mode: str | None = None
) -> list[dict]:
    """재시작 후 조회·복구가 필요한 비종결 주문을 반환한다."""
    init_db()
    placeholders = ",".join("?" for _ in _PENDING_ORDER_STATUSES)
    sql = f"SELECT * FROM broker_orders WHERE status IN ({placeholders})"
    params: list[object] = list(_PENDING_ORDER_STATUSES)
    if broker is not None:
        sql += " AND broker = ?"
        params.append(str(broker).strip().lower())
    if mode is not None:
        sql += " AND mode = ?"
        params.append(str(mode).strip().lower())
    sql += " ORDER BY updated_at, id"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def save_market_day(day: dict) -> dict:
    """브로커가 확인한 시장 영업일을 인증정보 없이 upsert한다."""
    broker = str(day.get("broker") or "").strip().lower()
    market = str(day.get("market") or "").strip().upper()
    business_date = str(day.get("business_date") or "").strip()
    if not broker or not market or not business_date or "is_open" not in day:
        raise ValueError("broker, market, business_date and is_open are required")
    checked_at = _normalize_utc_timestamp(day.get("checked_at"))
    source = _sanitize_text(str(day.get("source") or ""))
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO market_calendar_cache "
            "(broker, market, business_date, is_open, source, checked_at) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(broker, market, business_date) DO UPDATE SET "
            "is_open = excluded.is_open, source = excluded.source, checked_at = excluded.checked_at",
            (broker, market, business_date, int(bool(day["is_open"])), source, checked_at),
        )
        row = conn.execute(
            "SELECT * FROM market_calendar_cache "
            "WHERE broker = ? AND market = ? AND business_date = ?",
            (broker, market, business_date),
        ).fetchone()
    result = dict(row)
    result["is_open"] = bool(result["is_open"])
    return result


def get_market_day(broker: str, market: str, business_date: str) -> dict | None:
    """시장 영업일 캐시를 조회한다."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM market_calendar_cache "
            "WHERE broker = ? AND market = ? AND business_date = ?",
            (
                str(broker).strip().lower(),
                str(market).strip().upper(),
                str(business_date).strip(),
            ),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["is_open"] = bool(result["is_open"])
    return result

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
