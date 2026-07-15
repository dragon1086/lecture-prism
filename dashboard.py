"""lecture-prism local operations dashboard.

The dashboard tells the story of one pipeline run.  ``db.py`` remains the only
schema and migration owner; this module never creates sample trades or account
values.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

import db


DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8080
# Backward-compatible import surface. Database access still goes through db.py.
DB_PATH = Path(db.DB_PATH)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="PRISM 실행 대시보드", lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "testserver"],
)


@app.get("/api/dashboard")
def get_dashboard(run_id: str = Query(default="latest")) -> dict:
    """Return one secret-free, run-scoped execution snapshot."""
    return db.get_dashboard_snapshot(run_id)


@app.get("/api/data")
def get_data(run_id: str = Query(default="latest")) -> dict:
    """Compatibility alias for older course links."""
    return db.get_dashboard_snapshot(run_id)


_HTML = r'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>PRISM 실행 대시보드</title>
  <style>
    :root {
      --bg: #07111f;
      --panel: #0d1929;
      --panel-2: #101f31;
      --line: #223249;
      --text: #edf4ff;
      --muted: #91a1b8;
      --blue: #69a7ff;
      --green: #5ed59b;
      --amber: #f0bd62;
      --red: #ff7b7b;
      --gray: #8d9bad;
      --radius: 14px;
      --shadow: 0 16px 36px rgba(0, 0, 0, .18);
    }

    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(circle at 85% -10%, rgba(38, 95, 158, .20), transparent 34rem),
        var(--bg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo",
        "Noto Sans KR", sans-serif;
      font-size: 15px;
      line-height: 1.58;
    }

    button, summary { font: inherit; }
    .muted { color: var(--muted); font-size: .88rem; }
    button:focus-visible, summary:focus-visible, a:focus-visible {
      outline: 3px solid rgba(105, 167, 255, .55);
      outline-offset: 3px;
    }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 20;
      border-bottom: 1px solid rgba(145, 161, 184, .18);
      background: rgba(7, 17, 31, .92);
      backdrop-filter: blur(14px);
    }
    .topbar-inner, .page { width: min(1380px, calc(100% - 40px)); margin: 0 auto; }
    .topbar-inner {
      min-height: 68px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }
    .brand { display: flex; align-items: center; gap: 12px; }
    .brand-mark {
      width: 34px; height: 34px; border-radius: 10px;
      display: grid; place-items: center;
      color: #06101d; background: var(--blue); font-weight: 900;
    }
    .brand strong { display: block; letter-spacing: -.02em; }
    .brand small { color: var(--muted); }
    .refresh-box { display: flex; align-items: center; gap: 12px; }
    #refresh-status { color: var(--muted); font-size: 13px; }
    .refresh-button {
      min-height: 40px; padding: 0 15px; border: 1px solid var(--line);
      border-radius: 10px; color: var(--text); background: var(--panel-2);
      cursor: pointer;
    }
    .refresh-button:hover { border-color: var(--blue); }

    .page { padding: 34px 0 72px; }
    .hero { display: flex; justify-content: space-between; gap: 30px; margin-bottom: 22px; }
    .eyebrow { margin: 0 0 8px; color: var(--blue); font-size: 12px; font-weight: 800; letter-spacing: .12em; }
    h1 { margin: 0; font-size: clamp(28px, 4vw, 46px); line-height: 1.15; letter-spacing: -.045em; }
    .hero p:last-child { max-width: 720px; margin: 12px 0 0; color: var(--muted); }
    .run-state {
      align-self: end; min-width: 190px; padding: 14px 16px;
      border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel);
    }
    .run-state small { display: block; color: var(--muted); }
    .run-state strong { display: block; margin-top: 3px; font-size: 18px; }

    .truth-grid {
      display: grid; grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px; margin-bottom: 32px;
    }
    .truth-item {
      min-height: 88px; padding: 14px 15px;
      border: 1px solid var(--line); border-radius: 12px; background: var(--panel);
    }
    .truth-item span { display: block; color: var(--muted); font-size: 12px; }
    .truth-item strong {
      display: block; margin-top: 8px; overflow-wrap: anywhere;
      font-size: 15px; font-variant-numeric: tabular-nums;
    }

    .notice {
      display: none; margin: 0 0 24px; padding: 14px 16px;
      border: 1px solid rgba(240, 189, 98, .45); border-radius: 12px;
      color: #f8d99f; background: rgba(240, 189, 98, .08);
    }
    .notice.visible { display: block; }
    .notice.error { border-color: rgba(255, 123, 123, .45); color: #ffc0c0; background: rgba(255, 123, 123, .08); }

    .section { margin-top: 34px; scroll-margin-top: 90px; }
    .section-head {
      display: flex; justify-content: space-between; align-items: end;
      gap: 20px; margin-bottom: 13px;
    }
    .section-head h2 { margin: 0; font-size: 21px; letter-spacing: -.025em; }
    .section-head p { margin: 0; color: var(--muted); font-size: 13px; }
    .panel {
      border: 1px solid var(--line); border-radius: var(--radius);
      background: linear-gradient(145deg, rgba(16, 31, 49, .93), rgba(11, 24, 39, .93));
      box-shadow: var(--shadow); overflow: hidden;
    }
    .panel-pad { padding: 20px; }

    .timeline { list-style: none; margin: 0; padding: 7px 0; }
    .timeline li {
      position: relative; display: grid; grid-template-columns: 54px 18px 1fr auto;
      gap: 12px; align-items: start; padding: 9px 18px;
    }
    .timeline li:not(:last-child)::after {
      content: ""; position: absolute; left: 91px; top: 31px; bottom: -9px;
      width: 1px; background: var(--line);
    }
    .seq { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
    .status-dot { width: 11px; height: 11px; margin-top: 5px; border: 2px solid currentColor; border-radius: 50%; background: currentColor; }
    .timeline strong { display: block; }
    .timeline p { margin: 3px 0 0; color: var(--muted); }
    .timeline time { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }

    .delivery-grid, .metric-grid, .analysis-grid, .lesson-grid {
      display: grid; gap: 12px;
    }
    .delivery-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-bottom: 12px; }
    .analysis-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .lesson-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .card { padding: 18px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); }
    .card-top { display: flex; justify-content: space-between; gap: 14px; align-items: center; }
    .card h3 { margin: 0; font-size: 17px; }
    .card p { margin: 9px 0 0; color: var(--muted); }
    .channel-name { display: flex; align-items: center; gap: 9px; }
    .channel-icon { width: 29px; height: 29px; border-radius: 9px; display: grid; place-items: center; background: #172b43; color: var(--blue); font-weight: 800; }
    .delivery-list { margin: 14px 0 0; padding: 0; list-style: none; }
    .delivery-list li { display: flex; justify-content: space-between; gap: 12px; padding-top: 8px; color: var(--muted); font-size: 13px; }

    .badge {
      display: inline-flex; align-items: center; gap: 6px; min-height: 25px;
      padding: 2px 9px; border: 1px solid currentColor; border-radius: 999px;
      font-size: 12px; font-weight: 750; white-space: nowrap;
    }
    .good { color: var(--green); }
    .warn { color: var(--amber); }
    .bad { color: var(--red); }
    .info { color: var(--blue); }
    .neutral { color: var(--gray); }

    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 780px; }
    th, td { padding: 13px 15px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: middle; }
    th { color: var(--muted); font-size: 12px; font-weight: 650; }
    tbody tr:last-child td { border-bottom: 0; }
    td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
    .ticker strong { display: block; }
    .ticker small, .mono { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }

    .metric span { display: block; color: var(--muted); font-size: 12px; }
    .metric strong { display: block; margin-top: 8px; font-size: 23px; font-variant-numeric: tabular-nums; }
    .metric small { display: block; margin-top: 4px; color: var(--muted); }

    .score { font-size: 26px; font-weight: 850; color: var(--blue); }
    .score small { color: var(--muted); font-size: 12px; font-weight: 500; }
    details { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 12px; }
    summary { min-height: 40px; display: flex; align-items: center; color: var(--blue); cursor: pointer; }
    .sections { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .analysis-section { padding: 10px 12px; border-radius: 9px; background: rgba(105, 167, 255, .06); }
    .analysis-section strong { display: block; color: var(--muted); font-size: 11px; }
    .analysis-section p { margin: 4px 0 0; color: var(--text); font-size: 13px; }
    .lesson-meta { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 10px; }

    #empty-state { display: none; padding: 44px 24px; text-align: center; }
    #empty-state.visible { display: block; }
    #empty-state h2 { margin: 0 0 8px; }
    #empty-state p { max-width: 660px; margin: 0 auto; color: var(--muted); }
    .prompt {
      max-width: 700px; margin: 18px auto 0; padding: 15px 17px;
      border: 1px solid var(--line); border-radius: 10px; text-align: left;
      color: #cfe0f7; background: #081422; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .empty-row { padding: 28px 18px; color: var(--muted); text-align: center; }
    footer { margin-top: 52px; color: var(--muted); font-size: 12px; text-align: center; }

    @media (max-width: 1050px) {
      .truth-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .analysis-grid, .lesson-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
      .topbar-inner, .page { width: min(100% - 24px, 1380px); }
      .topbar-inner { min-height: 62px; }
      .brand small, #refresh-status { display: none; }
      .page { padding-top: 24px; }
      .hero { display: block; }
      .run-state { margin-top: 18px; min-width: 0; }
      .truth-grid, .delivery-grid, .metric-grid, .analysis-grid, .lesson-grid, .sections { grid-template-columns: 1fr; }
      .timeline li { grid-template-columns: 35px 15px 1fr; gap: 8px; padding: 12px; }
      .timeline li:not(:last-child)::after { left: 58px; }
      .timeline time { grid-column: 3; }
      .section-head { display: block; }
      .section-head p { margin-top: 4px; }
      .panel-pad { padding: 14px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">P</div>
        <div><strong>PRISM 실행 대시보드</strong><small>한 번의 실행, 하나의 사실 기록</small></div>
      </div>
      <div class="refresh-box">
        <span id="refresh-status" aria-live="polite">데이터를 확인하는 중</span>
        <button id="refresh-button" class="refresh-button" type="button">새로 확인</button>
      </div>
    </div>
  </header>

  <main class="page">
    <div class="hero">
      <div>
        <p class="eyebrow">EXECUTION STORY</p>
        <h1>판단부터 전달과 체결까지<br>한 흐름으로 확인합니다.</h1>
        <p>수익을 꾸미는 화면이 아니라 어떤 데이터로 무엇을 판단했고, 메시지가 전달됐는지, 주문이 실제로 체결됐는지 증명하는 운영 화면입니다.</p>
      </div>
      <div class="run-state"><small>선택한 실행</small><strong id="run-state-text">확인 중</strong></div>
    </div>

    <section id="truth-bar" class="truth-grid" aria-label="실행 사실 요약"></section>
    <div id="stale-notice" class="notice" role="status" aria-live="polite"></div>

    <section id="empty-state" class="panel" aria-live="polite">
      <h2>아직 기록된 실행이 없습니다</h2>
      <p>가짜 보유 종목이나 현금 잔고를 만들지 않았습니다. 아래 문장을 코딩 에이전트에게 붙여넣어 첫 데모를 실행하세요.</p>
      <div class="prompt">이 lecture-prism 프로젝트에서 API 키 없이 main.py 데모를 실행하고, 완료되면 dashboard.py를 localhost에서 열어줘.</div>
    </section>

    <div id="run-content">
      <section id="pipeline-timeline" class="section">
        <div class="section-head"><div><h2>파이프라인 타임라인</h2><p>sequence 순서대로 저장된 단계와 주문 상태</p></div><p id="timeline-count"></p></div>
        <div class="panel"><ol id="timeline-list" class="timeline"></ol></div>
      </section>

      <section id="notification-health" class="section">
        <div class="section-head"><div><h2>자동 보고 전달 상태</h2><p>Discord는 필수 준비, Telegram은 선택 연동입니다</p></div></div>
        <div id="delivery-grid" class="delivery-grid"></div>
      </section>

      <section id="order-truth" class="section">
        <div class="section-head"><div><h2>주문 사실</h2><p>판단·주문 접수·부분 체결·체결·차단은 서로 다른 상태입니다</p></div></div>
        <div class="panel table-wrap"><table><thead><tr><th>종목</th><th>방향</th><th>상태</th><th class="num">요청</th><th class="num">체결</th><th class="num">잔량</th><th class="num">체결가</th><th>주문 참조</th></tr></thead><tbody id="order-body"></tbody></table></div>
      </section>

      <section id="portfolio" class="section">
        <div class="section-head"><div><h2>이번 실행의 반영 포지션</h2><p>체결된 수량만 반영하며 현금 잔고를 추정하지 않습니다</p></div></div>
        <div id="portfolio-metrics" class="metric-grid"></div>
        <div class="panel table-wrap"><table><thead><tr><th>종목</th><th>출처</th><th class="num">수량</th><th class="num">평균 체결가</th><th class="num">알려진 금액</th></tr></thead><tbody id="position-body"></tbody></table></div>
      </section>

      <section id="analyses" class="section">
        <div class="section-head"><div><h2>AI 분석 판단</h2><p>매수 점수는 10점 만점이며 세부 6섹션은 펼쳐볼 수 있습니다</p></div></div>
        <div id="analysis-grid" class="analysis-grid"></div>
      </section>

      <section id="lessons" class="section">
        <div class="section-head"><div><h2>피드백 학습 기록</h2><p>체결된 결과에서만 남긴 다음 판단의 재료</p></div></div>
        <div id="lesson-grid" class="lesson-grid"></div>
      </section>
    </div>

    <footer>localhost 전용 · 시크릿과 계좌번호는 이 화면에 표시하지 않습니다.</footer>
  </main>

  <script>
    const API_PATH = "/api/dashboard";
    const POLL_MS = 5000;
    const query = new URLSearchParams(window.location.search);
    const requestedRunId = query.get("run_id") || "latest";
    let lastConfirmedAt = null;

    const byId = (id) => document.getElementById(id);
    const node = (tag, className, text) => {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined && text !== null) element.textContent = String(text);
      return element;
    };
    const replace = (target, children) => target.replaceChildren(...children);
    const value = (input, fallback = "—") => input === null || input === undefined || input === "" ? fallback : String(input);
    const number = (input) => Number(input || 0).toLocaleString("ko-KR");
    const money = (input) => input === null || input === undefined ? "확인 불가" : `${Number(input).toLocaleString("ko-KR")}원`;
    const shortTime = (input) => {
      if (!input) return "—";
      const date = new Date(input);
      return Number.isNaN(date.getTime()) ? String(input) : date.toLocaleTimeString("ko-KR", {hour: "2-digit", minute: "2-digit", second: "2-digit"});
    };
    const statusClass = (status) => {
      const key = String(status || "").toLowerCase();
      if (["succeeded", "completed", "sent", "filled", "open"].includes(key)) return "good";
      if (["accepted", "unfilled", "partial_fill", "queued", "paper", "closed", "decision_only"].includes(key)) return "warn";
      if (["failed", "rejected", "blocked", "live_blocked"].includes(key)) return "bad";
      if (["running", "submitting", "unknown"].includes(key)) return "info";
      return "neutral";
    };
    const orderLabels = {
      accepted: "주문 접수", partial_fill: "부분 체결", filled: "체결", blocked: "차단",
      rejected: "거절", unfilled: "미체결", submitting: "제출 중", unknown: "확인 필요",
      cancelled: "취소", cancel_requested: "취소 요청", decision_only: "판단만 완료"
    };
    const generalLabels = {
      succeeded: "정상 완료", completed: "완료", running: "진행 중", failed: "실패",
      sent: "전달 완료", skipped: "설정 안 됨", queued: "전달 대기", unknown: "확인 필요",
      mock: "데모(mock)", real_data: "실데이터(real_data)", research: "심층 분석(research)",
      paper: "모의투자(paper)", live: "실거래(live)", simulation: "가상 체결(simulation)",
      open: "개장", closed: "휴장 또는 장 마감", market_open: "주문 가능 시간",
      market_closed: "휴장", outside_order_window: "주문 시간 밖",
      market_status_unknown: "시장 상태 확인 실패",
      live_blocked: "실거래 차단"
    };
    const eventLabels = {
      "pipeline.started": "파이프라인 시작", "market.checked": "시장 상태 확인",
      "screening.started": "스크리닝 시작",
      "screening.completed": "스크리닝 완료", "analysis.started": "분석 시작",
      "analysis.completed": "분석 완료", "trading.started": "매매 판단 시작",
      "trading.decision": "매매 결정",
      "order.status": "주문 상태", "trading.completed": "매매 판단 완료",
      "feedback.started": "피드백 시작", "feedback.saved": "피드백 저장",
      "pipeline.completed": "파이프라인 완료", "pipeline.failed": "파이프라인 실패"
    };

    function badge(label, status) {
      return node("span", `badge ${statusClass(status)}`, label);
    }

    function generalLabel(raw) {
      const key = String(raw || "").toLowerCase();
      return generalLabels[key] || value(raw);
    }

    function renderTruth(run) {
      const facts = [
        ["실행 상태", generalLabel(run.status)], ["실행 프로필", generalLabel(run.profile)],
        ["매매 상태", generalLabel(run.trade_state)], ["데이터 출처", generalLabel(run.data_source)],
        ["데이터 기준일", value(run.data_as_of, "기록 없음")], ["시장 상태", generalLabel(run.market_status)]
      ];
      replace(byId("truth-bar"), facts.map(([label, fact]) => {
        const item = node("div", "truth-item");
        item.append(node("span", "", label), node("strong", "", fact));
        return item;
      }));
      byId("run-state-text").textContent = run.status === "failed" ? `실패 · ${value(run.failure_stage, "단계 미상")}` : generalLabel(run.status);
    }

    function renderTimeline(events) {
      byId("timeline-count").textContent = `${events.length}개 이벤트`;
      if (!events.length) {
        replace(byId("timeline-list"), [node("li", "empty-row", "저장된 단계 이벤트가 없습니다.")]);
        return;
      }
      replace(byId("timeline-list"), events.map((event) => {
        const item = node("li");
        item.append(node("span", "seq", `#${event.sequence}`));
        item.append(node("span", `status-dot ${statusClass(event.status)}`));
        const copy = node("div");
        const label = event.event_type === "order.status" && event.details && event.details.order_status
          ? `${eventLabels[event.event_type]} · ${orderLabels[event.details.order_status] || event.details.order_status}`
          : (eventLabels[event.event_type] || event.event_type);
        copy.append(node("strong", "", event.ticker ? `${label} · ${event.ticker}` : label));
        copy.append(node("p", "", value(event.summary, "상세 설명 없음")));
        item.append(copy, node("time", "", shortTime(event.occurred_at)));
        return item;
      }));
    }

    function renderDeliveries(deliveries) {
      const channels = ["discord", "telegram"];
      replace(byId("delivery-grid"), channels.map((channel) => {
        const records = deliveries.filter((item) => String(item.channel).toLowerCase() === channel);
        const latest = records.length ? records[records.length - 1] : null;
        const card = node("article", "card");
        const top = node("div", "card-top");
        const name = node("div", "channel-name");
        name.append(node("span", "channel-icon", channel === "discord" ? "D" : "T"));
        name.append(node("h3", "", channel === "discord" ? "Discord" : "Telegram"));
        top.append(name, badge(latest ? generalLabel(latest.status) : "설정 안 됨", latest ? latest.status : "disabled"));
        card.append(top);
        const description = channel === "discord" ? "3주차 필수 준비 채널" : "선택으로 함께 받을 수 있는 채널";
        card.append(node("p", "", description));
        const list = node("ul", "delivery-list");
        const sent = records.filter((item) => item.status === "sent").length;
        const failed = records.filter((item) => item.status === "failed").length;
        [["전달 성공", `${sent}건`], ["전달 실패", `${failed}건`], ["마지막 시도", latest ? shortTime(latest.completed_at || latest.queued_at) : "기록 없음"]].forEach(([label, fact]) => {
          const row = node("li"); row.append(node("span", "", label), node("strong", "", fact)); list.append(row);
        });
        card.append(list);
        return card;
      }));
    }

    function renderOrders(orders) {
      const body = byId("order-body");
      if (!orders.length) {
        const row = node("tr"); const cell = node("td", "empty-row", "이번 실행에는 증권사 주문 기록이 없습니다. 시뮬레이션 판단만 수행했을 수 있습니다."); cell.colSpan = 8; row.append(cell); replace(body, [row]); return;
      }
      replace(body, orders.map((order) => {
        const row = node("tr");
        const tickerCell = node("td", "ticker"); tickerCell.append(node("strong", "", order.ticker), node("small", "", `${order.broker} · ${order.mode}`));
        row.append(tickerCell, node("td", "", order.side));
        const state = node("td"); state.append(badge(orderLabels[order.status] || order.status, order.status)); row.append(state);
        row.append(node("td", "num", number(order.requested_qty)), node("td", "num", number(order.filled_qty)), node("td", "num", number(order.remaining_qty)), node("td", "num", money(order.avg_fill_price)), node("td", "mono", value(order.order_no, "발급 전")));
        return row;
      }));
    }

    function renderPortfolio(portfolio, positions) {
      const metrics = [
        ["반영 포지션", `${number(portfolio.position_count)}개`, "체결 수량 기준"],
        ["알려진 포지션 금액", money(portfolio.known_position_value), "평균 체결가가 있는 항목만"],
        ["현금 잔고", "확인 불가", "현금 잔고를 추정하지 않습니다"]
      ];
      replace(byId("portfolio-metrics"), metrics.map(([label, fact, note]) => {
        const card = node("div", "card metric"); card.append(node("span", "", label), node("strong", "", fact), node("small", "", note)); return card;
      }));
      const body = byId("position-body");
      if (!positions.length) {
        const row = node("tr"); const cell = node("td", "empty-row", "체결로 확인된 포지션이 없습니다. 주문 접수나 차단 상태는 보유로 계산하지 않습니다."); cell.colSpan = 5; row.append(cell); replace(body, [row]); return;
      }
      replace(body, positions.map((position) => {
        const row = node("tr");
        row.append(node("td", "ticker", position.ticker), node("td", "", position.source === "broker_fills" ? "KIS 체결" : "시뮬레이션 체결"), node("td", "num", number(position.quantity)), node("td", "num", money(position.average_price)), node("td", "num", position.average_price === null ? "확인 불가" : money(position.quantity * position.average_price)));
        return row;
      }));
    }

    function renderAnalyses(analyses) {
      const labels = {technical_summary: "기술", supply_summary: "수급", financial_summary: "재무", industry_summary: "산업", news_summary: "뉴스", market_condition: "시장"};
      if (!analyses.length) { replace(byId("analysis-grid"), [node("div", "card empty-row", "이번 실행에 저장된 분석 판단이 없습니다.")]); return; }
      replace(byId("analysis-grid"), analyses.map((analysis) => {
        const card = node("article", "card");
        const top = node("div", "card-top");
        const title = node("div"); title.append(node("h3", "", analysis.ticker), badge(value(analysis.recommendation), analysis.recommendation === "BUY" ? "completed" : "unknown"));
        const score = node("div", "score", number(analysis.score)); score.append(node("small", "", " / 10")); top.append(title, score); card.append(top);
        card.append(node("p", "muted", `프로필 ${value(analysis.profile, "기록 없음")} · 데이터 ${value(analysis.data_source, "기록 없음")} · 기준일 ${value(analysis.data_as_of, "기록 없음")}`));
        card.append(node("p", "", value(analysis.reason, "판단 근거가 저장되지 않았습니다.")));
        if (analysis.risk) card.append(node("p", "", `주의: ${analysis.risk}`));
        const sectionEntries = Object.entries(analysis.sections || {}).filter(([, text]) => text);
        if (sectionEntries.length) {
          const detail = node("details"); detail.append(node("summary", "", "6섹션 분석 펼치기"));
          const grid = node("div", "sections");
          sectionEntries.forEach(([key, text]) => { const item = node("div", "analysis-section"); item.append(node("strong", "", labels[key] || key), node("p", "", text)); grid.append(item); });
          detail.append(grid); card.append(detail);
        }
        return card;
      }));
    }

    function renderLessons(lessons) {
      if (!lessons.length) { replace(byId("lesson-grid"), [node("div", "card empty-row", "체결 결과에서 축적된 교훈이 아직 없습니다.")]); return; }
      replace(byId("lesson-grid"), lessons.map((lesson) => {
        const card = node("article", "card"); const meta = node("div", "lesson-meta");
        meta.append(badge(value(lesson.tier), "unknown"), badge(value(lesson.error_type), lesson.error_type === "EXECUTION" ? "rejected" : "accepted"));
        card.append(meta, node("h3", "", `${lesson.ticker} · ${lesson.action}`), node("p", "", lesson.lesson)); return card;
      }));
    }

    function render(snapshot) {
      const empty = !snapshot.run;
      byId("empty-state").classList.toggle("visible", empty);
      byId("run-content").hidden = empty;
      byId("truth-bar").hidden = empty;
      if (empty) {
        byId("run-state-text").textContent = "기록 없음";
        return;
      }
      renderTruth(snapshot.run);
      renderTimeline(snapshot.events || []);
      renderDeliveries(snapshot.deliveries || []);
      renderOrders(snapshot.orders || []);
      renderPortfolio(snapshot.portfolio || {}, snapshot.positions || []);
      renderAnalyses(snapshot.analyses || []);
      renderLessons(snapshot.lessons || []);
      const notice = byId("stale-notice");
      if (snapshot.run.status === "failed") {
        notice.textContent = `파이프라인이 ${value(snapshot.run.failure_stage, "알 수 없는")} 단계에서 멈췄습니다. 완료된 이전 단계의 기록은 그대로 보존했습니다.`;
        notice.className = "notice visible error";
      } else if (["closed", "unknown"].includes(String(snapshot.run.market_status || "").toLowerCase())) {
        notice.textContent = `현재 시장 상태는 ${value(snapshot.run.market_status)}입니다. 분석은 데이터 기준일 ${value(snapshot.run.data_as_of, "기록 없음")} 자료로 계속되지만 주문은 안전하게 제한될 수 있습니다.`;
        notice.className = "notice visible";
      } else {
        notice.className = "notice";
        notice.textContent = "";
      }
    }

    async function refresh() {
      const status = byId("refresh-status");
      try {
        const response = await fetch(`${API_PATH}?run_id=${encodeURIComponent(requestedRunId)}`, {headers: {"Accept": "application/json"}});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const snapshot = await response.json();
        render(snapshot);
        lastConfirmedAt = new Date();
        status.textContent = `마지막 확인 ${lastConfirmedAt.toLocaleTimeString("ko-KR")}`;
      } catch (_error) {
        const when = lastConfirmedAt ? lastConfirmedAt.toLocaleTimeString("ko-KR") : "없음";
        status.textContent = `새로 확인 실패 · 마지막 정상 ${when}`;
        const notice = byId("stale-notice");
        notice.textContent = `대시보드 데이터를 새로 읽지 못했습니다. 마지막으로 확인한 내용은 유지합니다. 마지막 정상 확인: ${when}`;
        notice.className = "notice visible error";
      }
    }

    byId("refresh-button").addEventListener("click", refresh);
    refresh();
    window.setInterval(refresh, POLL_MS);
  </script>
</body>
</html>'''


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(_HTML)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT)
