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
    reason TEXT
);

CREATE TABLE IF NOT EXISTS analysis_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    recommendation TEXT NOT NULL,    -- BUY / HOLD / PASS
    score INTEGER,
    reason TEXT,
    risk TEXT
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


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── 쓰기 (feedback.py / 파이프라인에서 호출) ──────────────────────────────────

def save_analysis(analysis: dict) -> None:
    """분석 결과 1건 저장."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO analysis_decisions (timestamp, ticker, recommendation, score, reason, risk) "
            "VALUES (?,?,?,?,?,?)",
            (
                _now(),
                analysis.get("ticker", ""),
                analysis.get("recommendation", "PASS"),
                int(analysis.get("score", 0) or 0),
                analysis.get("reason", ""),
                analysis.get("risk", ""),
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
