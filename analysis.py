"""
analysis.py — 모듈 2: LLM 분석 파이프라인 (6섹션 리치 리포트)

스크리닝 통과 종목 → AI 에이전트 분석 → 원본 PRISM scenario 형태 투자 의견.

설계 사상 (원본 PRISM 축소판):
  규칙으로 되는 건 규칙으로  → 수급·재무·산업·시장 (실데이터 지표 템플릿)
  맥락 판단이 필요한 건 LLM으로 → 기술·뉴스·전략 (3-에이전트 체인, 파트4 트랙B)

3계층 동작:
  Tier 0 (표준 라이브러리)      : mock 데이터로 6섹션 리치 리포트 (키/설치 불필요)
  Tier 1 (pip install yfinance) : 가격·재무·뉴스·지수 실데이터로 섹션 채움
  Tier 2 (+ OPENAI/OAuth 프록시) : 기술·뉴스·전략 에이전트가 LLM으로 심층 서술

  → 데이터 원천은 data_source.fetch_stock_data() 하나로 단일화(실데이터 접점).

실행:
    python analysis.py 005930
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

import data_source

log = logging.getLogger(__name__)

# ── LLM 연동 설정 ────────────────────────────────────────────────
# 파트3 CH1에서 띄운 ChatGPT OAuth 프록시(OPENAI_BASE_URL=http://localhost:18741/v1)
# 또는 OPENAI_API_KEY가 있으면 실제 LLM을 호출합니다. 둘 다 없으면 mock/규칙으로 동작.
LLM_MODEL = os.getenv("LECTURE_LLM_MODEL", "gpt-5.4-mini")  # PRISM 분석 파이프라인과 동일

# ── 매매 의사결정 기준 (원본 PRISM과 동일 개념) ──────────────────
# buy_score는 0~10점. 시장 국면별 진입 최소점수(MIN_BUY_SCORE)를 넘어야 '진입'.
MIN_BUY_SCORE = 6           # 강세장 기준 진입 임계 (약세장이면 상향)
_MARKET_CONDITION_FALLBACK = (
    "상승추세: KOSPI가 20일 이동평균을 상회, 최근 강세장 조건 충족. "
    "다만 단기 변동성은 확대 구간. (실데이터 미연동 시 데모 기준)"
)


def _llm_enabled() -> bool:
    """OAuth 프록시(base_url) 또는 API 키가 설정돼 있으면 실제 LLM 사용."""
    return bool(os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_KEY"))


async def _llm_complete(system_prompt: str, user_msg: str) -> str:
    """
    OpenAI Chat Completions 호출 (OAuth 프록시 또는 API 키 경유).
    실패 시 RuntimeError를 던져 호출부가 mock/규칙으로 폴백하도록 함.
    """
    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise RuntimeError("openai 패키지 미설치 (pip install openai)") from e

    # 프록시 모드면 키가 없어도 되므로 더미 키 허용.
    # OPENAI_BASE_URL을 명시적으로 넘겨 원본 PRISM의 OAuth 프록시 방향과 맞춥니다.
    client_kwargs = {"api_key": os.getenv("OPENAI_API_KEY", "chatgpt-oauth-placeholder")}
    if os.getenv("OPENAI_BASE_URL"):
        client_kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]
    client = AsyncOpenAI(**client_kwargs)
    resp = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    )
    return resp.choices[0].message.content or ""


def _extract_json(text: str) -> dict:
    """LLM 응답에서 첫 번째 JSON 객체를 추출 (코드펜스/잡설 포함 대응)."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("응답에 JSON 없음")
    return json.loads(match.group(0))


def get_current_price(ticker: str) -> int:
    """현재가 조회(경량 폴백). 실데이터는 data_source.fetch_stock_data()가 담당."""
    return data_source.mock_profile(ticker)["price"]


def _round_to(value: float, unit: int) -> int:
    return int(round(value / unit) * unit)


# ── 분석 에이전트 프롬프트 (파트4 트랙B에서 수강생이 교체) ──────────
TECHNICAL_AGENT_PROMPT = """
당신은 윌리엄 오닐의 CANSLIM 방법론을 따르는 기술적 분석 전문가입니다.
주어진 주가·거래량·이동평균·RSI 데이터를 근거로 추세와 매수 신호를 판단하세요.
판단 기준: 52주 신고가 근접 여부, 거래량 동반 상승, 20일선 정배열, 컵&핸들/플랫 베이스 패턴.
반드시 주어진 수치를 인용하며 3~4문장으로 전문가답게 서술하세요.
"""

NEWS_AGENT_PROMPT = """
당신은 뉴스·공시를 분석하여 주가 영향을 판단하는 전문가입니다.
주어진 실제 뉴스 헤드라인에서 호재/악재 촉매를 식별하고 시장 반응을 예측하세요.
헤드라인이 영문이면 핵심을 한국어로 해석해 전달하세요. 3~4문장으로 서술하세요.
"""

STRATEGY_AGENT_PROMPT = """
당신은 기술·수급·재무·산업·뉴스·시장 분석을 종합해 최종 투자 의견을 제시하는 투자 전략가입니다.
윌리엄 오닐식 추세추종 관점에서 목표가는 마일스톤, 손절은 기계적으로 봅니다.
0~10점 매수 점수(buy_score)와 진입 여부, 목표가/손절가/투자기간/핵심 리스크를 제시하세요.
"""


async def run_analysis(ticker: str) -> dict:
    """
    단일 종목 6섹션 분석 파이프라인 실행.

    Returns (원본 PRISM scenario와 유사한 형태):
        ticker, company_name, recommendation(BUY/HOLD/PASS), decision(진입/보류),
        buy_score(0~10), min_score, current_price, target_price, stop_loss,
        risk_reward_ratio, expected_return_pct, expected_loss_pct, investment_period,
        sector, market_condition, rationale, risk, data_source,
        technical_summary, supply_summary, financial_summary, industry_summary, news_summary
    """
    # 데이터 원천 (실데이터 → mock 폴백). 동기 I/O라 스레드에서 실행.
    data = await asyncio.to_thread(data_source.fetch_stock_data, ticker)
    market = await asyncio.to_thread(data_source.fetch_market_index)
    src = "실데이터(yfinance)" if data["source"] == "yfinance" else "모의 데이터(mock)"
    log.info(f"  [{ticker}] 데이터 원천: {src}")

    # 1) 기술적 분석 — LLM(맥락) 또는 데이터 템플릿
    log.info(f"  [{ticker}] 기술적 분석 에이전트 실행 중...")
    technical = await _run_technical_agent(ticker, data)

    # 2) 수급 — 실거래량 파생 프록시 (규칙)
    supply = _section_supply(data)

    # 3) 재무 — 실데이터 지표 (규칙)
    financial = _section_financial(data)

    # 4) 산업 — 섹터/산업 (규칙)
    industry = _section_industry(data)

    # 5) 뉴스 — LLM(맥락) 또는 헤드라인/mock
    log.info(f"  [{ticker}] 뉴스 분석 에이전트 실행 중...")
    news = await _run_news_agent(ticker, data)

    # 6) 시장 국면 — 지수 실데이터 (규칙)
    market_condition = _section_market(market)

    # 종합 — 투자전략가 (LLM 또는 규칙 스코어링)
    log.info(f"  [{ticker}] 투자전략 에이전트 통합 중...")
    strategy = await _run_strategy_agent(
        ticker, data, technical, supply, financial, industry, news, market_condition
    )

    return _build_scenario(
        ticker, data, technical, supply, financial, industry, news, market_condition, strategy
    )


# ── 섹션 빌더: 규칙(실데이터 템플릿 / mock) ─────────────────────────────
def _section_supply(data: dict) -> str:
    """수급(거래 흐름). 실데이터면 거래량 파생 프록시, 아니면 mock 문장."""
    if data["source"] != "yfinance":
        return data.get("supply", "")
    s = data.get("supply", {})
    ratio, obv = s.get("up_down_vol_ratio"), s.get("obv", "중립")
    vol_ratio = data.get("vol_ratio")
    parts = []
    if ratio is not None:
        verdict = "매수 우위" if ratio >= 1 else "매도 우위"
        parts.append(f"최근 상승일/하락일 거래량 비 {ratio}배({verdict})")
    if vol_ratio is not None:
        parts.append(f"당일 거래량은 20일 평균의 {vol_ratio}배")
    parts.append(f"OBV 기준 {obv}")
    body = ", ".join(parts) + "."
    return body + " (※ 기관/외국인/개인 세부 순매수는 KRX 로그인이 필요해 거래량 기반으로 추정)"


def _section_financial(data: dict) -> str:
    """재무. 실데이터면 지표 템플릿, 아니면 mock 문장."""
    if data["source"] != "yfinance":
        return data.get("finance", "")
    f = data.get("finance", {})
    bits = []
    if f.get("per") is not None:
        bits.append(f"PER {f['per']}배")
    if f.get("pbr") is not None:
        bits.append(f"PBR {f['pbr']}배")
    if f.get("roe") is not None:
        bits.append(f"ROE {f['roe']}%")
    if f.get("margin") is not None:
        bits.append(f"순이익률 {f['margin']}%")
    if f.get("rev_growth") is not None:
        bits.append(f"매출성장 {f['rev_growth']:+}%")
    if f.get("eps_growth") is not None:
        bits.append(f"이익성장 {f['eps_growth']:+}%")
    if not bits:
        return "재무 지표를 확보하지 못했습니다(야후 데이터 공백)."
    return " · ".join(bits) + "."


def _section_industry(data: dict) -> str:
    """산업/섹터."""
    if data["source"] != "yfinance":
        return data.get("industry", "")
    sector = data.get("sector", "기타")
    industry = data.get("industry", "")
    tail = f" 세부 업종: {industry}." if industry else ""
    return f"섹터 분류: {sector}.{tail} 경쟁 위치·업황은 뉴스·전략 섹션과 함께 판단."


def _section_market(market: dict | None) -> str:
    """시장 국면. 지수 실데이터가 있으면 서술, 없으면 폴백."""
    if not market:
        return _MARKET_CONDITION_FALLBACK
    parts = []
    for name in ("KOSPI", "KOSDAQ"):
        m = market.get(name)
        if m:
            trend = "강세" if m["ret_20d"] >= 0 else "약세"
            parts.append(f"{name} {m['last']:,} (20일 {m['ret_20d']:+}%, {trend})")
    if not parts:
        return _MARKET_CONDITION_FALLBACK
    return " / ".join(parts) + "."


# ── 에이전트: 기술 (LLM 또는 데이터 템플릿) ──────────────────────────────
def _technical_data_text(data: dict) -> str:
    """실데이터 기술 지표를 문장으로."""
    if data["source"] != "yfinance":
        return data.get("tech", "")
    bits = []
    ma20 = data.get("ma20")
    if data.get("price_vs_ma20") is not None:
        rel = "위" if data["price_vs_ma20"] >= 0 else "아래"
        bits.append(f"현재가가 20일선 {rel}({data['price_vs_ma20']:+}%)")
    if data.get("ma5") and ma20:
        arr = "정배열" if data["ma5"] >= ma20 else "역배열"
        bits.append(f"5·20일선 {arr}")
    if data.get("rsi") is not None:
        zone = "과매수" if data["rsi"] >= 70 else "과매도" if data["rsi"] <= 30 else "중립"
        bits.append(f"RSI {data['rsi']}({zone})")
    if data.get("vol_ratio") is not None:
        bits.append(f"거래량 20일평균 {data['vol_ratio']}배")
    if data.get("ret_1d") is not None:
        bits.append(f"전일 대비 {data['ret_1d']:+}%")
    return ", ".join(bits) + "." if bits else "기술 지표 계산 데이터 부족."


async def _run_technical_agent(ticker: str, data: dict) -> str:
    """기술적 분석. LLM 연동 시 실제 호출, 아니면 데이터/mock 템플릿."""
    base = _technical_data_text(data)
    if _llm_enabled():
        try:
            summary = await _llm_complete(
                TECHNICAL_AGENT_PROMPT,
                f"종목코드 {ticker}의 기술적 지표입니다: {base}\n"
                "이 수치를 근거로 추세와 매수 신호 여부를 전문가답게 판단해줘.",
            )
            return summary.strip() or base
        except Exception as e:
            log.warning(f"  기술 에이전트 LLM 실패 → 데이터/mock 폴백: {e}")
    await asyncio.sleep(0.05)  # 네트워크 호출 시뮬레이션(교육용)
    return base


async def _run_news_agent(ticker: str, data: dict) -> str:
    """뉴스 분석. 실데이터 헤드라인 → LLM 해석, 아니면 mock/헤드라인 나열."""
    news = data.get("news")
    headlines = news if isinstance(news, list) else []
    if _llm_enabled():
        try:
            src_txt = "\n".join(f"- {h}" for h in headlines) if headlines else (
                news if isinstance(news, str) else "관련 뉴스 없음")
            summary = await _llm_complete(
                NEWS_AGENT_PROMPT,
                f"종목코드 {ticker} 관련 최근 뉴스 헤드라인입니다:\n{src_txt}\n\n"
                "여기서 호재/악재 촉매를 골라 시장 영향을 한국어로 정리해줘.",
            )
            return summary.strip()
        except Exception as e:
            log.warning(f"  뉴스 에이전트 LLM 실패 → 데이터/mock 폴백: {e}")
    await asyncio.sleep(0.05)
    if headlines:
        return "최근 헤드라인: " + " / ".join(headlines[:3])
    return news if isinstance(news, str) else "관련 뉴스 없음"


# ── 에이전트: 투자전략 (LLM 통합 또는 규칙 스코어링) ────────────────────
def _rule_based_score(data: dict) -> dict:
    """실데이터(LLM 없음) 경로용 규칙 기반 매수 점수 0~10."""
    if data["source"] != "yfinance":
        # mock: 프로필이 준 판단값 사용
        return {"recommendation": data.get("rec", "BUY"), "buy_score": data.get("buy_score", 7),
                "expected_return_pct": data.get("ret", 12), "expected_loss_pct": data.get("loss", 6),
                "investment_period": data.get("period", "중기")}
    score = 5.0
    if data.get("price_vs_ma20") is not None:
        score += 1.2 if data["price_vs_ma20"] >= 0 else -1.0
    if data.get("ma5") and data.get("ma20"):
        score += 0.8 if data["ma5"] >= data["ma20"] else -0.8
    rsi = data.get("rsi")
    if rsi is not None:
        if rsi >= 75:
            score -= 1.0          # 과열
        elif rsi <= 30:
            score += 0.5          # 과매도 반등 여지
    if data.get("vol_ratio") is not None and data["vol_ratio"] >= 1.5:
        score += 1.0             # 거래량 동반
    f = data.get("finance", {})
    if f.get("rev_growth") is not None and f["rev_growth"] > 0:
        score += 0.7
    if f.get("roe") is not None and f["roe"] >= 10:
        score += 0.5
    s = data.get("supply", {})
    if s.get("up_down_vol_ratio") is not None and s["up_down_vol_ratio"] >= 1:
        score += 0.5
    buy_score = int(max(0, min(10, round(score))))
    rec = "BUY" if buy_score >= 7 else "HOLD" if buy_score >= 5 else "PASS"
    return {"recommendation": rec, "buy_score": buy_score,
            "expected_return_pct": 12, "expected_loss_pct": 6, "investment_period": "중기"}


async def _run_strategy_agent(ticker, data, technical, supply, financial,
                              industry, news, market_condition) -> dict:
    """투자전략가 — 6섹션 통합 최종 의견. LLM 연동 시 실제 호출."""
    price = data["current_price"]
    if _llm_enabled():
        try:
            user_msg = (
                f"종목코드: {ticker} / 현재가: {price:,}원\n"
                f"[기술적 분석] {technical}\n[수급] {supply}\n[재무] {financial}\n"
                f"[산업] {industry}\n[뉴스] {news}\n[시장 국면] {market_condition}\n\n"
                "위 6개 분석을 종합해 최종 투자 의견을 아래 JSON 형식으로만 답해줘:\n"
                '{"recommendation":"BUY|HOLD|PASS", "buy_score":0~10 정수, '
                '"target_price":목표가(원,정수), "stop_loss":손절가(원,정수), '
                '"expected_return_pct":기대수익률, "expected_loss_pct":기대손실률, '
                '"investment_period":"단기|중기|장기", '
                '"rationale":"진입/보류 근거 한 문장", "risk":"주요 리스크 한 문장"}'
            )
            raw = await _llm_complete(STRATEGY_AGENT_PROMPT, user_msg)
            parsed = _extract_json(raw)
            parsed["current_price"] = price
            parsed.setdefault("recommendation", "HOLD")
            return parsed
        except Exception as e:
            log.warning(f"  전략 에이전트 LLM 실패 → 규칙 스코어링 폴백: {e}")

    await asyncio.sleep(0.05)
    scored = _rule_based_score(data)
    scored["current_price"] = price
    scored["rationale"] = (
        f"기술·수급·재무·뉴스 종합 {scored['recommendation']} 판단. {technical[:40]}…")
    scored["risk"] = "시장 급락 시 대형주 동반 조정 및 수급 이탈 가능성."
    return scored


def _build_scenario(ticker, data, technical, supply, financial,
                    industry, news, market_condition, strategy) -> dict:
    """전략 결과 + 현재가로 목표가/손절/손익비 등 파생 지표 계산."""
    price = strategy.get("current_price") or data["current_price"]
    rec = strategy.get("recommendation", "HOLD").upper()
    buy_score = int(strategy.get("buy_score", 5))
    ret = float(strategy.get("expected_return_pct", 12))
    loss = float(strategy.get("expected_loss_pct", 6)) or 6
    target = strategy.get("target_price") or _round_to(price * (1 + ret / 100), 100)
    stop = strategy.get("stop_loss") or _round_to(price * (1 - loss / 100), 100)
    # 손익비는 목표가/손절가로 역산 (LLM이 직접 준 값이 있어도 일관성 위해 재계산)
    up = max(target - price, 0) / price * 100
    dn = max(price - stop, 1) / price * 100
    rr = round(up / dn, 1) if dn else 0.0
    decision = "진입" if (rec == "BUY" and buy_score >= MIN_BUY_SCORE) else "보류"
    news_summary = news if isinstance(news, str) else " / ".join(news)

    return {
        "ticker": ticker,
        "company_name": data.get("name", ticker),
        "recommendation": rec,
        "decision": decision,
        "buy_score": buy_score,
        "min_score": MIN_BUY_SCORE,
        "current_price": price,
        "target_price": target,
        "stop_loss": stop,
        "risk_reward_ratio": rr,
        "expected_return_pct": round(up, 1),
        "expected_loss_pct": round(dn, 1),
        "investment_period": strategy.get("investment_period", "중기"),
        "sector": data.get("sector", "기타"),
        "market_condition": market_condition,
        "rationale": strategy.get("rationale") or strategy.get("reason", ""),
        "risk": strategy.get("risk", ""),
        "data_source": data["source"],
        # 6섹션 요약
        "technical_summary": technical,
        "supply_summary": supply,
        "financial_summary": financial,
        "industry_summary": industry,
        "news_summary": news_summary,
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"
    r = asyncio.run(run_analysis(ticker))

    # 원본 PRISM 리포트와 유사한 6섹션 출력
    src = "실데이터(yfinance)" if r["data_source"] == "yfinance" else "모의 데이터(mock)"
    print(f"\n{'='*60}")
    print(f"  {r['company_name']}({r['ticker']}) · {r['sector']}   [원천: {src}]")
    print(f"{'='*60}")
    print(f"  투자판단   : {r['recommendation']} → {r['decision']}  "
          f"(매수점수 {r['buy_score']}/10, 진입기준 {r['min_score']})")
    print(f"  현재가     : {r['current_price']:,}원   투자기간: {r['investment_period']}")
    print(f"  목표가     : {r['target_price']:,}원 (+{r['expected_return_pct']}%)")
    print(f"  손절가     : {r['stop_loss']:,}원 (-{r['expected_loss_pct']}%)")
    print(f"  손익비     : {r['risk_reward_ratio']} : 1")
    print(f"{'-'*60}")
    print(f"  [기술적 분석] {r['technical_summary']}")
    print(f"  [수급 분석]   {r['supply_summary']}")
    print(f"  [재무 분석]   {r['financial_summary']}")
    print(f"  [산업 분석]   {r['industry_summary']}")
    print(f"  [뉴스/촉매]   {r['news_summary']}")
    print(f"  [시장 국면]   {r['market_condition']}")
    print(f"  [종합 판단]   {r['rationale']}")
    print(f"  [리스크]      {r['risk']}")
    print(f"{'='*60}")
