"""
db.py — 공용 SQLite 저장소

파이프라인(main.py)과 대시보드(dashboard.py)가 공유하는 단일 데이터 소스.
feedback.py가 매매·분석·교훈을 여기에 기록하면 dashboard.py가 읽어서 보여줍니다.

테이블:
  - trade_history       : 매매 의사결정/체결 내역
  - analysis_decisions  : AI 에이전트 분석 결과
  - feedback_lessons    : 축적된 교훈 (단기/중기/장기 메모리)

이 파일이 "스키마의 진실 원천(single source of truth)"입니다.
dashboard.py와 feedback.py 모두 여기서 init_db()를 호출합니다.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

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
    reason TEXT,
    high_since_entry INTEGER
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
    error_type TEXT DEFAULT 'JUDGMENT',
    support_count INTEGER DEFAULT 1,
    source_ids TEXT,
    is_active INTEGER DEFAULT 1
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
        try:
            conn.execute(
                "ALTER TABLE trade_history ADD COLUMN high_since_entry INTEGER"
            )
        except sqlite3.OperationalError:
            pass  # 이미 존재
        for column_sql in (
            "ALTER TABLE feedback_lessons ADD COLUMN support_count INTEGER DEFAULT 1",
            "ALTER TABLE feedback_lessons ADD COLUMN source_ids TEXT",
            "ALTER TABLE feedback_lessons ADD COLUMN is_active INTEGER DEFAULT 1",
        ):
            try:
                conn.execute(column_sql)
            except sqlite3.OperationalError:
                pass  # 이미 존재

    from prism_core.ledger import Ledger

    Ledger(DB_PATH)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── 쓰기 (feedback.py / 파이프라인에서 호출) ──────────────────────────────────

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
            "INSERT INTO trade_history "
            "(timestamp, ticker, action, price, quantity, mode, reason, high_since_entry) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                _now(),
                trade.get("ticker", ""),
                trade.get("action", "PASS"),
                int(trade.get("executed_price") or trade.get("price") or 0),
                int(trade.get("quantity", 0) or 0),
                trade.get("mode", "simulation"),
                trade.get("reason", ""),
                int(
                    trade.get("high_since_entry")
                    or trade.get("executed_price")
                    or trade.get("price")
                    or 0
                )
                if trade.get("action", "PASS") == "BUY"
                else None,
            ),
        )


def update_holding_high(ticker: str, current_price: float) -> None:
    """열린 교육용 BUY 한 건의 최고가를 단조 증가 방식으로 갱신한다."""

    price = int(current_price or 0)
    if not ticker or price <= 0:
        return
    init_db()
    with _connect() as conn:
        latest = conn.execute(
            "SELECT id, action, price, high_since_entry "
            "FROM trade_history WHERE ticker=? "
            "ORDER BY id DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if latest is None or latest["action"] != "BUY":
            return
        previous = int(latest["high_since_entry"] or latest["price"] or 0)
        if price > previous:
            conn.execute(
                "UPDATE trade_history SET high_since_entry=? WHERE id=?",
                (price, latest["id"]),
            )


def save_lesson(ticker: str, action: str, lesson: str,
                tier: str = "short", error_type: str = "JUDGMENT",
                support_count: int = 1, source_ids: str | None = None,
                is_active: bool = True) -> None:
    """교훈 1건 저장 (단기/중기/장기 메모리)."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO feedback_lessons "
            "(timestamp, ticker, action, lesson, tier, error_type, "
            "support_count, source_ids, is_active) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                _now(),
                ticker,
                action,
                lesson,
                tier,
                error_type,
                max(1, int(support_count)),
                source_ids,
                1 if is_active else 0,
            ),
        )


# ── 외부 브로커 주문/시장일 facade ────────────────────────────────────────────

def _ledger():
    """Return the single prism_core ledger without duplicating its SQL rules."""

    from prism_core.ledger import Ledger

    return Ledger(DB_PATH)


def save_broker_order(intent, *, broker: str, broker_mode: str):
    return _ledger().save_broker_order(
        intent, broker=broker, broker_mode=broker_mode
    )


def get_broker_order_state(client_order_id: str):
    return _ledger().get_broker_order_state(client_order_id)


def admit_broker_order(intent, *, broker: str, broker_mode: str):
    return _ledger().admit_broker_order(
        intent, broker=broker, broker_mode=broker_mode
    )


def bind_broker_identity(client_order_id: str, **identity):
    return _ledger().bind_broker_identity(client_order_id, **identity)


def update_broker_order(client_order_id: str, **snapshot):
    return _ledger().update_broker_order(client_order_id, **snapshot)


def get_pending_broker_orders(*, broker: str, broker_mode: str):
    return _ledger().get_pending_broker_orders(
        broker=broker, broker_mode=broker_mode
    )


def save_market_day(market, trade_date: str, **values):
    return _ledger().save_market_day(market, trade_date, **values)


def get_market_day(market, trade_date: str, **filters):
    return _ledger().get_market_day(market, trade_date, **filters)


# ── 읽기 (feedback.py 교훈 주입 / dashboard.py 표시) ──────────────────────────

def get_recent_lessons(n: int = 5) -> list[str]:
    """최근 N개 교훈 텍스트 (다음 매매 프롬프트에 주입용)."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT lesson FROM feedback_lessons ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [r["lesson"] for r in rows]


def get_memory_rows(
    *, tier: str | None = None, active_only: bool = True
) -> list[dict]:
    """압축 작업과 다음 판단이 읽을 구조화된 교훈 목록."""

    init_db()
    where = []
    values: list[object] = []
    if tier is not None:
        where.append("tier=?")
        values.append(tier)
    if active_only:
        where.append("is_active=1")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, timestamp, ticker, action, lesson, tier, error_type, "
            "support_count, source_ids, is_active "
            f"FROM feedback_lessons {clause} "
            "ORDER BY timestamp DESC, id DESC",
            values,
        ).fetchall()
    return [dict(row) for row in rows]


def set_memory_tier(ids: list[int], tier: str) -> int:
    """선택한 활성 교훈을 다음 압축 계층으로 이동."""

    if not ids:
        return 0
    if tier not in {"short", "medium", "long"}:
        raise ValueError(f"unknown memory tier: {tier}")
    init_db()
    placeholders = ",".join("?" for _ in ids)
    with _connect() as conn:
        cursor = conn.execute(
            f"UPDATE feedback_lessons SET tier=? "
            f"WHERE is_active=1 AND id IN ({placeholders})",  # noqa: S608
            [tier, *ids],
        )
    return int(cursor.rowcount)


def deactivate_memory_rows(ids: list[int]) -> int:
    """압축 재료가 된 행을 삭제하지 않고 비활성화."""

    if not ids:
        return 0
    init_db()
    placeholders = ",".join("?" for _ in ids)
    with _connect() as conn:
        cursor = conn.execute(
            f"UPDATE feedback_lessons SET is_active=0 "
            f"WHERE id IN ({placeholders})",  # noqa: S608
            ids,
        )
    return int(cursor.rowcount)


def enforce_long_memory_limit(max_count: int) -> int:
    """지원 건수가 낮은 장기 원칙부터 비활성화해 개수를 제한."""

    limit = max(1, int(max_count))
    init_db()
    with _connect() as conn:
        active = conn.execute(
            "SELECT COUNT(*) FROM feedback_lessons "
            "WHERE tier='long' AND is_active=1"
        ).fetchone()[0]
        excess = max(0, int(active) - limit)
        if not excess:
            return 0
        ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM feedback_lessons "
                "WHERE tier='long' AND is_active=1 "
                "ORDER BY support_count ASC, timestamp ASC, id ASC LIMIT ?",
                (excess,),
            ).fetchall()
        ]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE feedback_lessons SET is_active=0 "
            f"WHERE id IN ({placeholders})",  # noqa: S608
            ids,
        )
    return len(ids)


def get_open_holdings() -> list[dict]:
    """교육용 매매일지에서 종목별 최신 BUY 상태를 청산 대상으로 읽는다.

    반복 실습에서 같은 BUY가 여러 번 기록돼도 수량을 누적하지 않는다.
    각 종목의 가장 최근 BUY/SELL 한 건을 현재 상태로 보고, 최신 상태가
    BUY인 종목만 반환한다.
    """

    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ticker, action, price, quantity, high_since_entry "
            "FROM trade_history "
            "WHERE action IN ('BUY', 'SELL') "
            "ORDER BY id DESC"
        ).fetchall()

    seen: set[str] = set()
    holdings: list[dict] = []
    for row in rows:
        ticker = str(row["ticker"])
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        if row["action"] != "BUY":
            continue
        price = int(row["price"] or 0)
        quantity = int(row["quantity"] or 0)
        if price <= 0 or quantity <= 0:
            continue
        holdings.append(
            {
                "ticker": ticker,
                "entry_price": price,
                "quantity": quantity,
                "high_since_entry": int(row["high_since_entry"] or price),
            }
        )
    return holdings


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
