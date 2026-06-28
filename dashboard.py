"""
dashboard.py — 로컬 웹 대시보드

매매현황 · 의사결정 내역 · 피드백 교훈을 localhost:8080 에서 확인.
피드백 DB가 없으면 데모 데이터로 동작.

실행:
    python dashboard.py          # http://localhost:8080
"""

import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

DB_PATH = Path("prism.db")


# ── DB 초기화 ──────────────────────────────────────────────────────────────────

def _init_db() -> None:
    """테이블 생성 + 데모 데이터 삽입 (처음 실행 시)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            ticker TEXT NOT NULL,
            action TEXT NOT NULL,       -- BUY / SELL / PASS
            price INTEGER,
            quantity INTEGER,
            mode TEXT DEFAULT 'simulation',
            reason TEXT
        );

        CREATE TABLE IF NOT EXISTS analysis_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            ticker TEXT NOT NULL,
            recommendation TEXT NOT NULL,  -- BUY / HOLD / PASS
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
            tier TEXT DEFAULT 'short',     -- short / medium / long
            error_type TEXT DEFAULT 'JUDGMENT'
        );
    """)

    # 데이터가 없으면 데모 데이터 삽입
    if cur.execute("SELECT COUNT(*) FROM trade_history").fetchone()[0] == 0:
        _seed_demo_data(cur)

    conn.commit()
    conn.close()


def _seed_demo_data(cur: sqlite3.Cursor) -> None:
    """강의 시연용 샘플 데이터."""
    now = datetime.now().isoformat()

    cur.executemany(
        "INSERT INTO trade_history (timestamp, ticker, action, price, quantity, mode, reason) VALUES (?,?,?,?,?,?,?)",
        [
            (now, "005930", "BUY",  70000, 14, "simulation", "기술적 신호 + 뉴스 긍정. 분할 매수 권장."),
            (now, "000660", "PASS", 120000, 0, "simulation", "점수 미달 (3/5). 모멘텀 약함."),
            (now, "035420", "BUY",  340000, 2, "simulation", "거래량 급등 + 52주 신고가 근접."),
        ],
    )

    cur.executemany(
        "INSERT INTO analysis_decisions (timestamp, ticker, recommendation, score, reason, risk) VALUES (?,?,?,?,?,?)",
        [
            (now, "005930", "BUY",  4, "20일선 위 거래량 급등. 외국인 순매수 유입.", "시장 급락 시 연동 하락 가능성"),
            (now, "000660", "PASS", 3, "실적 개선 기대. 단, 모멘텀 부족.", "반도체 사이클 불확실성"),
            (now, "035420", "BUY",  4, "네이버 AI 신사업 기대감. 기술적 돌파 임박.", "대형주 전반 조정 시 동반 하락"),
        ],
    )

    cur.executemany(
        "INSERT INTO feedback_lessons (timestamp, ticker, action, lesson, tier, error_type) VALUES (?,?,?,?,?,?)",
        [
            (now, "005930", "BUY", "거래량 급등 + 이평선 돌파 조합은 유효. 시장 하락 시 연동 리스크 존재.", "short", "JUDGMENT"),
            (now, "000660", "PASS", "점수 3점 종목은 관망이 정답. 다음엔 뉴스 촉매 확인 우선.", "short", "JUDGMENT"),
            (now, "035420", "BUY", "52주 신고가 근접 종목은 돌파 시 강한 모멘텀. 단, 거래량 동반 필수.", "medium", "JUDGMENT"),
        ],
    )


# ── FastAPI 앱 ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    _init_db()
    yield

app = FastAPI(title="PRISM Dashboard", lifespan=lifespan)


def _query(sql: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/data")
def get_data() -> dict:
    return {
        "trades":    _query("SELECT * FROM trade_history ORDER BY id DESC LIMIT 20"),
        "analyses":  _query("SELECT * FROM analysis_decisions ORDER BY id DESC LIMIT 20"),
        "lessons":   _query("SELECT * FROM feedback_lessons ORDER BY id DESC LIMIT 20"),
    }


@app.get("/", response_class=HTMLResponse)
def index():
    data = get_data()
    trades   = data["trades"]
    analyses = data["analyses"]
    lessons  = data["lessons"]

    def action_badge(action: str) -> str:
        colors = {"BUY": "#22C55E", "SELL": "#EF4444", "PASS": "#6B7280", "HOLD": "#F59E0B"}
        c = colors.get(action, "#6B7280")
        return f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600;">{action}</span>'

    def tier_badge(tier: str) -> str:
        labels = {"short": "단기", "medium": "중기", "long": "장기"}
        colors = {"short": "#3B82F6", "medium": "#7C3AED", "long": "#D97706"}
        c = colors.get(tier, "#6B7280")
        return f'<span style="background:{c};color:#fff;padding:2px 6px;border-radius:4px;font-size:11px;">{labels.get(tier, tier)}</span>'

    trade_rows = "".join(
        f"<tr><td>{t['ticker']}</td><td>{action_badge(t['action'])}</td>"
        f"<td>{t['price']:,}원</td><td>{t['quantity']}주</td>"
        f"<td style='color:#6B7280;font-size:12px;'>{t['reason'][:40]}...</td></tr>"
        for t in trades
    )

    analysis_rows = "".join(
        f"<tr><td>{a['ticker']}</td><td>{action_badge(a['recommendation'])}</td>"
        f"<td><strong>{a['score']}/5</strong></td>"
        f"<td style='color:#6B7280;font-size:12px;'>{a['reason'][:40]}...</td></tr>"
        for a in analyses
    )

    lesson_rows = "".join(
        f"<tr><td>{tier_badge(l['tier'])}</td><td>{l['ticker']}</td>"
        f"<td style='font-size:13px;'>{l['lesson']}</td></tr>"
        for l in lessons
    )

    stats = {
        "total": len(trades),
        "buy":   sum(1 for t in trades if t["action"] == "BUY"),
        "pass":  sum(1 for t in trades if t["action"] == "PASS"),
        "lessons": len(lessons),
    }

    stats_html = "".join(
        f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:16px 24px;text-align:center;">'
        f'<div style="font-size:28px;font-weight:700;color:#1E293B;">{v}</div>'
        f'<div style="font-size:12px;color:#64748B;margin-top:4px;">{k}</div></div>'
        for k, v in [
            ("오늘 분석", stats["total"]),
            ("매수 결정", stats["buy"]),
            ("패스", stats["pass"]),
            ("교훈 축적", stats["lessons"]),
        ]
    )

    updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if any(t.get("mode") == "live" for t in trades):
        db_note = "✅ 실거래 연동"
    elif trades:
        db_note = "🧪 시뮬레이션 데이터"
    else:
        db_note = "⚠️ 데이터 없음 (main.py 실행 전)"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>PRISM 대시보드</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Noto Sans KR', sans-serif; background: #F1F5F9; color: #1E293B; }}
    .header {{ background: #1E293B; color: #fff; padding: 20px 32px; display: flex; align-items: center; gap: 16px; }}
    .header h1 {{ font-size: 20px; font-weight: 700; }}
    .header .meta {{ font-size: 12px; color: #94A3B8; margin-left: auto; }}
    .container {{ max-width: 1100px; margin: 32px auto; padding: 0 24px; display: flex; flex-direction: column; gap: 24px; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
    .card {{ background: #fff; border-radius: 12px; border: 1px solid #E2E8F0; overflow: hidden; }}
    .card-header {{ padding: 16px 20px; border-bottom: 1px solid #F1F5F9; font-weight: 700; font-size: 14px; display: flex; align-items: center; gap: 8px; }}
    .card-body {{ padding: 0; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ background: #F8FAFC; padding: 10px 16px; text-align: left; font-size: 12px; color: #64748B; font-weight: 500; }}
    td {{ padding: 12px 16px; border-top: 1px solid #F1F5F9; vertical-align: middle; }}
    tr:hover td {{ background: #F8FAFC; }}
    .note {{ font-size: 12px; color: #94A3B8; padding: 8px 20px 16px; }}
  </style>
</head>
<body>
  <div class="header">
    <div>🔮</div>
    <h1>PRISM 대시보드</h1>
    <div class="meta">{db_note} &nbsp;|&nbsp; 마지막 갱신: {updated} &nbsp;|&nbsp; <a href="/api/data" style="color:#60A5FA;text-decoration:none;">JSON API</a></div>
  </div>

  <div class="container">
    <!-- 통계 -->
    <div class="stats">{stats_html}</div>

    <!-- 매매 현황 -->
    <div class="card">
      <div class="card-header">📊 매매 의사결정 현황</div>
      <div class="card-body">
        <table>
          <thead><tr><th>종목</th><th>결정</th><th>가격</th><th>수량</th><th>근거</th></tr></thead>
          <tbody>{trade_rows}</tbody>
        </table>
      </div>
      <div class="note">시뮬레이션 모드 — 실거래는 KIS API 연동 후 trading.py 수정</div>
    </div>

    <!-- 에이전트 분석 결과 -->
    <div class="card">
      <div class="card-header">🤖 AI 에이전트 분석 결과</div>
      <div class="card-body">
        <table>
          <thead><tr><th>종목</th><th>추천</th><th>점수</th><th>판단 근거</th></tr></thead>
          <tbody>{analysis_rows}</tbody>
        </table>
      </div>
    </div>

    <!-- 피드백 교훈 -->
    <div class="card">
      <div class="card-header">📝 축적된 교훈 (단기/중기/장기 메모리)</div>
      <div class="card-body">
        <table>
          <thead><tr><th>계층</th><th>종목</th><th>교훈</th></tr></thead>
          <tbody>{lesson_rows}</tbody>
        </table>
      </div>
      <div class="note">교훈은 다음 매매 프롬프트에 반영할 수 있도록 저장됩니다 (자동 주입은 심화 실습에서 확장)</div>
    </div>
  </div>

  <script>
    // 30초마다 자동 새로고침
    setTimeout(() => location.reload(), 30000);
  </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
