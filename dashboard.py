"""
dashboard.py — 로컬 웹 대시보드

매매현황 · 의사결정 내역 · 피드백 교훈을 localhost:8080 에서 확인.
피드백 DB가 없으면 데모 데이터로 동작.

실행:
    python dashboard.py          # http://localhost:8080
"""

import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
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
    """강의 시연용 샘플 데이터 (현실적인 매매 시나리오)."""
    def ts(days: float = 0, hours: float = 0) -> str:
        return (datetime.now() - timedelta(days=days, hours=hours)).isoformat()

    # ── 매매 내역: 보유 6종목(BUY) + 청산 2종목(SELL) + 관망 1종목(PASS) ──
    cur.executemany(
        "INSERT INTO trade_history (timestamp, ticker, action, price, quantity, mode, reason) VALUES (?,?,?,?,?,?,?)",
        [
            # 현재 보유 (최신 액션 = BUY)
            (ts(4, 1),  "005930", "BUY",  71200, 14, "simulation", "20일선 돌파 + 외국인 5거래일 연속 순매수. 분할 1차 진입."),
            (ts(3, 2),  "000660", "BUY", 178500,  6, "simulation", "HBM3E 공급 확대 리포트. 거래량 평균 3배 급증."),
            (ts(3, 0),  "042700", "BUY", 143000,  7, "simulation", "반도체 후공정 수주 모멘텀. 52주 신고가 근접."),
            (ts(2, 3),  "005380", "BUY", 245000,  4, "simulation", "분기 실적 서프라이즈 + 배당 매력. 추세 추종 진입."),
            (ts(1, 5),  "247540", "BUY", 168000,  6, "simulation", "2차전지 업황 바닥 통과 신호. 기관 순매수 전환."),
            (ts(1, 1),  "035420", "BUY", 215000,  5, "simulation", "AI 검색·광고 회복 기대. 기술적 박스 상단 돌파."),
            # 청산 완료 (최신 액션 = SELL → 보유에서 제외)
            (ts(0, 6),  "035720", "SELL", 49200,  8, "simulation", "목표가 +9% 도달. 트레일링 스탑으로 익절."),
            (ts(2, 2),  "068270", "SELL",182000,  5, "simulation", "손절 -7% 도달. 이평선 정배열 붕괴로 기계적 청산."),
            # 관망 (PASS)
            (ts(0, 2),  "105560", "PASS", 76300,  0, "simulation", "점수 3점·촉매 부재. 거래량 한산으로 관망."),
        ],
    )

    # ── AI 분석 결정: 추천/점수/리스크 다양 ──
    cur.executemany(
        "INSERT INTO analysis_decisions (timestamp, ticker, recommendation, score, reason, risk) VALUES (?,?,?,?,?,?)",
        [
            (ts(0, 1), "005930", "BUY",  5, "20일선 위 거래량 3배 급등. 외국인 5거래일 순매수 유입.", "지수 급락 시 대형주 동반 조정"),
            (ts(0, 1), "000660", "BUY",  5, "HBM 수요 강세 + 목표주가 상향 리포트 다수.", "메모리 가격 피크아웃 우려"),
            (ts(0, 1), "042700", "BUY",  4, "후공정 장비 수주 증가. 신고가 돌파 임박.", "전방 capex 둔화 가능성"),
            (ts(0, 1), "035420", "BUY",  4, "AI 신사업 기대 + 광고 매출 회복 조짐.", "플랫폼 규제 리스크"),
            (ts(0, 1), "247540", "BUY",  4, "낙폭과대 + 기관 수급 전환. 업황 바닥 신호.", "전기차 수요 둔화 지속 시 변동성"),
            (ts(0, 1), "005380", "HOLD", 3, "실적은 양호하나 단기 과열 구간. 눌림목 대기.", "환율·금리 변수 상존"),
            (ts(0, 1), "105560", "PASS", 3, "밸류 매력 있으나 촉매 부재. 거래량 한산.", "금리 인하 지연 시 모멘텀 약화"),
            (ts(0, 1), "068270", "PASS", 2, "이평선 정배열 붕괴 + 수급 이탈.", "바이오 섹터 투심 악화"),
        ],
    )

    # ── 피드백 교훈: 단기/중기/장기 + 판단/실행 오류 ──
    cur.executemany(
        "INSERT INTO feedback_lessons (timestamp, ticker, action, lesson, tier, error_type) VALUES (?,?,?,?,?,?)",
        [
            (ts(0, 3), "005930", "BUY",  "거래량 급등 + 이평선 돌파 조합은 진입 승률이 높았다. 타이밍 양호.", "short",  "JUDGMENT"),
            (ts(0, 5), "035720", "SELL", "지정가 미체결로 진입이 1틱 밀렸다. 변동성 큰 날은 시장가도 고려.", "short",  "EXECUTION"),
            (ts(1, 2), "247540", "BUY",  "낙폭과대 반등은 기관 수급 전환을 확인한 뒤 진입해야 승률이 높다.", "medium", "JUDGMENT"),
            (ts(2, 1), "068270", "SELL", "정배열 붕괴 종목은 추격 금지. 손절 -7% 룰의 기계적 준수가 손실을 방어했다.", "medium", "JUDGMENT"),
            (ts(5, 0), "000660", "BUY",  "반도체는 사이클 산업. 재고·가격 같은 업황 턴 신호를 매크로와 함께 봐야 한다.", "long",   "JUDGMENT"),
            (ts(0, 4), "105560", "PASS", "점수 3점·촉매 없는 저평가주는 관망이 정답. 시간 비용이 크다.", "short",  "JUDGMENT"),
            (ts(6, 0), "005380", "BUY",  "배당락·실적시즌 일정을 사전 반영해야 이벤트 드리븐 슬리피지를 줄인다.", "long",   "EXECUTION"),
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


# 데모 종목 코드 → 회사명 (표시용)
_TICKER_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
    "035720": "카카오",
    "005380": "현대차",
    "042700": "한미반도체",
    "247540": "에코프로비엠",
    "105560": "KB금융",
    "068270": "셀트리온",
}


def _name(ticker: str) -> str:
    return _TICKER_NAMES.get(ticker, ticker)


def _dedup_latest(rows: list[dict], key: str = "ticker") -> list[dict]:
    """같은 종목이 여러 번(반복 실행) 있으면 가장 최근 1건만 남긴다."""
    seen: dict[str, dict] = {}
    for r in rows:  # rows are ordered newest-first
        if r[key] not in seen:
            seen[r[key]] = r
    return list(seen.values())


# 시맨틱 색상 토큰 (참고: prism-insight examples/dashboard 다크 테마)
_ACTION = {
    "BUY":  ("oklch(0.72 0.17 145)", "oklch(0.65 0.18 145 / 0.15)"),
    "SELL": ("oklch(0.70 0.20 25)",  "oklch(0.60 0.22 25 / 0.15)"),
    "HOLD": ("oklch(0.80 0.13 85)",  "oklch(0.75 0.14 85 / 0.15)"),
    "PASS": ("oklch(0.70 0.01 264)", "oklch(0.60 0.01 264 / 0.15)"),
}
_TIER = {
    "short":  ("단기", "oklch(0.72 0.16 264)"),
    "medium": ("중기", "oklch(0.70 0.16 300)"),
    "long":   ("장기", "oklch(0.78 0.13 60)"),
}


@app.get("/", response_class=HTMLResponse)
def index():
    data = get_data()
    trades   = data["trades"]
    analyses = data["analyses"]
    lessons  = data["lessons"]

    # 보유 = 종목별 최신 액션이 BUY인 종목 (이후 SELL되면 제외)
    holdings = [t for t in _dedup_latest(trades) if t["action"] == "BUY"]
    analyses_u = _dedup_latest(analyses)

    def action_badge(action: str) -> str:
        fg, bg = _ACTION.get(action, _ACTION["PASS"])
        return (f'<span class="badge" style="color:{fg};background:{bg};">'
                f'<span class="dot" style="background:{fg};"></span>{action}</span>')

    def tier_badge(tier: str) -> str:
        label, fg = _TIER.get(tier, ("기타", "oklch(0.7 0.01 264)"))
        return f'<span class="tier" style="color:{fg};border-color:{fg};">{label}</span>'

    def score_bar(score: int) -> str:
        score = score or 0
        pct = int(score / 5 * 100)
        col = "oklch(0.72 0.17 145)" if score >= 4 else ("oklch(0.80 0.13 85)" if score == 3 else "oklch(0.70 0.20 25)")
        return (f'<div class="scorewrap"><div class="scorebar"><span style="width:{pct}%;background:{col};"></span></div>'
                f'<span class="scoreval">{score}<small>/5</small></span></div>')

    # ── 포트폴리오(보유) 테이블 ──
    total_invested = sum((h["price"] or 0) * (h["quantity"] or 0) for h in holdings)
    holding_rows = ""
    for h in holdings:
        amount = (h["price"] or 0) * (h["quantity"] or 0)
        weight = (amount / total_invested * 100) if total_invested else 0
        holding_rows += (
            f'<tr><td><div class="tkr"><strong>{_name(h["ticker"])}</strong>'
            f'<span class="code">{h["ticker"]}</span></div></td>'
            f'<td class="num">{h["quantity"]:,}주</td>'
            f'<td class="num">{h["price"]:,}원</td>'
            f'<td class="num">{amount:,}원</td>'
            f'<td><div class="wbar"><span style="width:{weight:.0f}%;"></span></div>'
            f'<span class="wlabel">{weight:.0f}%</span></td></tr>'
        )
    if not holding_rows:
        holding_rows = '<tr><td colspan="5" class="empty">보유 종목이 없습니다 — <code>python main.py</code>를 먼저 실행하세요.</td></tr>'

    # ── 최근 매매 내역 (BUY/SELL/PASS, 시간순) ──
    trade_rows = ""
    for t in trades[:8]:
        when = (t["timestamp"] or "")[5:16].replace("T", " ")
        qty = f'{t["quantity"]:,}주' if t["quantity"] else "—"
        trade_rows += (
            f'<tr><td class="muted small num">{when}</td>'
            f'<td><div class="tkr"><strong>{_name(t["ticker"])}</strong>'
            f'<span class="code">{t["ticker"]}</span></div></td>'
            f'<td>{action_badge(t["action"])}</td>'
            f'<td class="num">{t["price"]:,}원</td><td class="num">{qty}</td>'
            f'<td class="muted small">{(t["reason"] or "")[:42]}</td></tr>'
        )
    if not trade_rows:
        trade_rows = '<tr><td colspan="6" class="empty">매매 내역이 없습니다.</td></tr>'

    # ── AI 분석 결정 테이블 ──
    analysis_rows = ""
    for a in analyses_u:
        analysis_rows += (
            f'<tr><td><div class="tkr"><strong>{_name(a["ticker"])}</strong>'
            f'<span class="code">{a["ticker"]}</span></div></td>'
            f'<td>{action_badge(a["recommendation"])}</td>'
            f'<td>{score_bar(a["score"])}</td>'
            f'<td class="muted small">{(a["reason"] or "")[:48]}</td></tr>'
        )
    if not analysis_rows:
        analysis_rows = '<tr><td colspan="4" class="empty">분석 데이터가 없습니다.</td></tr>'

    # ── 교훈 카드 ──
    lesson_cards = ""
    for l in lessons:
        et = "판단" if (l.get("error_type") or "").upper() == "JUDGMENT" else "실행"
        lesson_cards += (
            f'<div class="lesson">'
            f'<div class="lesson-top">{tier_badge(l["tier"])}'
            f'<span class="lesson-tkr">{_name(l["ticker"])} · {l["ticker"]}</span>'
            f'<span class="etype">{et}오류</span></div>'
            f'<div class="lesson-body">{l["lesson"]}</div></div>'
        )
    if not lesson_cards:
        lesson_cards = '<div class="empty">축적된 교훈이 없습니다.</div>'

    # ── KPI 카드 ──
    avg_score = (sum(a["score"] or 0 for a in analyses_u) / len(analyses_u)) if analyses_u else 0
    slot_pct = int(len(holdings) / 10 * 100)
    kpis = [
        ("보유 종목", f"{len(holdings)}", f"/ 10 슬롯 · {slot_pct}% 사용", slot_pct, "oklch(0.65 0.24 264)"),
        ("투자 금액", f"{total_invested:,}", "원 (시뮬레이션)", None, "oklch(0.70 0.15 200)"),
        ("평균 확신 점수", f"{avg_score:.1f}", "/ 5.0 · AI 분석", int(avg_score / 5 * 100), "oklch(0.72 0.17 145)"),
        ("분석 종목", f"{len(analyses_u)}", "건 · 6에이전트 파이프라인", None, "oklch(0.78 0.13 60)"),
        ("축적 교훈", f"{len(lessons)}", "건 · 단기/중기/장기", None, "oklch(0.70 0.16 300)"),
    ]
    kpi_html = ""
    for label, value, sub, pct, col in kpis:
        bar = (f'<div class="kpi-bar"><span style="width:{pct}%;background:{col};"></span></div>'
               if pct is not None else "")
        kpi_html += (
            f'<div class="kpi"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value" style="color:{col};">{value}</div>'
            f'<div class="kpi-sub">{sub}</div>{bar}</div>'
        )

    updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if any(t.get("mode") == "live" for t in trades):
        status = '<span class="pill live">● 실거래 연동</span>'
    elif trades:
        status = '<span class="pill sim">● 시뮬레이션</span>'
    else:
        status = '<span class="pill warn">● 데이터 없음</span>'

    return PAGE.format(
        status=status, updated=updated, kpi_html=kpi_html,
        holding_rows=holding_rows, trade_rows=trade_rows,
        analysis_rows=analysis_rows, lesson_cards=lesson_cards,
    )


# ── HTML 템플릿 (다크 파이낸스 대시보드) ───────────────────────────────────────
# 디자인 토큰 출처: prism-insight examples/dashboard (oklch 다크 테마)
PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>나만의 AI 매매시스템 · 실시간 대시보드</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: oklch(0.12 0.015 264); --card: oklch(0.155 0.015 264);
      --card2: oklch(0.20 0.015 264); --border: oklch(0.27 0.015 264);
      --fg: oklch(0.96 0.005 264); --muted: oklch(0.62 0.01 264);
      --primary: oklch(0.65 0.24 264); --radius: 14px;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Noto Sans KR', system-ui, sans-serif; background: var(--bg);
      color: var(--fg); -webkit-font-smoothing: antialiased; }}
    .num, .kpi-value, .scoreval, .code, .wlabel {{ font-family: 'JetBrains Mono', monospace;
      font-variant-numeric: tabular-nums; }}
    a {{ color: var(--primary); text-decoration: none; }}

    /* 헤더 */
    .header {{ position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 14px;
      padding: 18px 32px; background: oklch(0.13 0.015 264 / 0.85); backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border); }}
    .logo {{ width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center;
      font-size: 20px; background: linear-gradient(135deg, var(--primary), oklch(0.6 0.2 300));
      box-shadow: 0 0 22px oklch(0.65 0.24 264 / 0.5); }}
    .header h1 {{ font-size: 18px; font-weight: 800; letter-spacing: -0.3px; }}
    .header .sub {{ font-size: 12px; color: var(--muted); margin-top: 1px; }}
    .header .right {{ margin-left: auto; display: flex; align-items: center; gap: 16px;
      font-size: 12px; color: var(--muted); }}
    .pill {{ font-size: 12px; font-weight: 700; padding: 5px 12px; border-radius: 999px; }}
    .pill.sim {{ color: oklch(0.8 0.13 85); background: oklch(0.75 0.14 85 / 0.14); }}
    .pill.live {{ color: oklch(0.72 0.17 145); background: oklch(0.65 0.18 145 / 0.14); }}
    .pill.warn {{ color: oklch(0.7 0.2 25); background: oklch(0.6 0.22 25 / 0.14); }}

    .container {{ max-width: 1180px; margin: 28px auto 64px; padding: 0 24px;
      display: flex; flex-direction: column; gap: 22px; }}

    /* KPI */
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 16px; }}
    .kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
      padding: 18px 20px; position: relative; overflow: hidden; }}
    .kpi::before {{ content: ""; position: absolute; inset: 0 auto 0 0; width: 3px;
      background: var(--primary); opacity: 0.6; }}
    .kpi-label {{ font-size: 12px; color: var(--muted); font-weight: 500; }}
    .kpi-value {{ font-size: 30px; font-weight: 800; margin: 6px 0 2px; letter-spacing: -1px; }}
    .kpi-sub {{ font-size: 11px; color: var(--muted); }}
    .kpi-bar {{ height: 5px; border-radius: 999px; background: oklch(0.27 0.015 264); margin-top: 12px; overflow: hidden; }}
    .kpi-bar span {{ display: block; height: 100%; border-radius: 999px; }}

    /* 카드 */
    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
      overflow: hidden; }}
    .card-h {{ display: flex; align-items: center; gap: 10px; padding: 16px 22px;
      border-bottom: 1px solid var(--border); font-weight: 700; font-size: 14px; }}
    .card-h .ic {{ font-size: 16px; }}
    .card-h .hint {{ margin-left: auto; font-size: 11px; color: var(--muted); font-weight: 400; }}

    /* 테이블 */
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ text-align: left; padding: 11px 22px; font-size: 11px; font-weight: 600;
      color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px;
      background: oklch(0.17 0.015 264); }}
    td {{ padding: 14px 22px; font-size: 13.5px; border-top: 1px solid var(--border); }}
    td.num {{ text-align: right; }}
    th.num {{ text-align: right; }}
    tbody tr {{ transition: background 0.12s; }}
    tbody tr:hover td {{ background: oklch(0.19 0.015 264); }}
    .muted {{ color: var(--muted); }} .small {{ font-size: 12px; }}
    .empty {{ text-align: center; color: var(--muted); padding: 32px; font-size: 13px; }}
    .tkr {{ display: flex; flex-direction: column; gap: 2px; }}
    .tkr .code {{ font-size: 11px; color: var(--muted); }}

    /* 배지 */
    .badge {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 11px;
      border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .badge .dot {{ width: 6px; height: 6px; border-radius: 50%; }}
    .tier {{ display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11px;
      font-weight: 700; border: 1px solid; }}

    /* 점수 바 */
    .scorewrap {{ display: flex; align-items: center; gap: 10px; }}
    .scorebar {{ width: 90px; height: 6px; border-radius: 999px; background: oklch(0.27 0.015 264); overflow: hidden; }}
    .scorebar span {{ display: block; height: 100%; border-radius: 999px; }}
    .scoreval {{ font-size: 13px; font-weight: 700; }} .scoreval small {{ color: var(--muted); font-weight: 500; }}

    /* 비중 바 */
    .wbar {{ display: inline-block; width: 100px; height: 6px; border-radius: 999px;
      background: oklch(0.27 0.015 264); overflow: hidden; vertical-align: middle; }}
    .wbar span {{ display: block; height: 100%; background: var(--primary); border-radius: 999px; }}
    .wlabel {{ font-size: 12px; color: var(--muted); margin-left: 8px; }}

    /* 교훈 */
    .lessons {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 14px; padding: 20px 22px; }}
    .lesson {{ background: var(--card2); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }}
    .lesson-top {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
    .lesson-tkr {{ font-size: 12px; color: var(--muted); font-weight: 600; }}
    .etype {{ margin-left: auto; font-size: 10px; color: var(--muted); border: 1px solid var(--border);
      padding: 1px 7px; border-radius: 999px; }}
    .lesson-body {{ font-size: 13px; line-height: 1.6; color: oklch(0.85 0.01 264); }}

    .foot {{ text-align: center; font-size: 11px; color: var(--muted); padding: 8px 0 20px; }}
    @media (max-width: 640px) {{ .header {{ padding: 14px 18px; }} .container {{ padding: 0 14px; }}
      th, td {{ padding: 10px 14px; }} }}
  </style>
</head>
<body>
  <div class="header">
    <div class="logo">🔮</div>
    <div>
      <h1>나만의 AI 매매시스템 · 실시간 대시보드</h1>
      <div class="sub">lecture-prism · AI 자동매매 시뮬레이션</div>
    </div>
    <div class="right">
      {status}
      <span>갱신 {updated}</span>
      <a href="/api/data">JSON API ↗</a>
    </div>
  </div>

  <div class="container">
    <div class="kpis">{kpi_html}</div>

    <div class="card">
      <div class="card-h"><span class="ic">💼</span> 보유 포트폴리오
        <span class="hint">매수 결정 종목 · 시뮬레이션</span></div>
      <table>
        <thead><tr><th>종목</th><th class="num">수량</th><th class="num">매수가</th>
          <th class="num">투자금액</th><th>비중</th></tr></thead>
        <tbody>{holding_rows}</tbody>
      </table>
    </div>

    <div class="card">
      <div class="card-h"><span class="ic">🧾</span> 최근 매매 내역
        <span class="hint">매수 · 청산 · 관망 체결 기록</span></div>
      <table>
        <thead><tr><th>시각</th><th>종목</th><th>구분</th><th class="num">가격</th>
          <th class="num">수량</th><th>사유</th></tr></thead>
        <tbody>{trade_rows}</tbody>
      </table>
    </div>

    <div class="card">
      <div class="card-h"><span class="ic">🤖</span> AI 에이전트 분석 결정
        <span class="hint">기술·뉴스·전략 에이전트 종합</span></div>
      <table>
        <thead><tr><th>종목</th><th>추천</th><th>확신 점수</th><th>판단 근거</th></tr></thead>
        <tbody>{analysis_rows}</tbody>
      </table>
    </div>

    <div class="card">
      <div class="card-h"><span class="ic">📝</span> 축적된 교훈
        <span class="hint">단기/중기/장기 메모리 · 다음 매매 프롬프트에 반영</span></div>
      <div class="lessons">{lesson_cards}</div>
    </div>

    <div class="foot">lecture-prism · 교육용 데모 · 30초마다 자동 새로고침</div>
  </div>

  <script>
    setTimeout(() => location.reload(), 30000);
  </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
