"""
analysis.py — 모듈 2: LLM 분석 파이프라인

스크리닝 통과 종목 → AI 에이전트 분석 → 투자 의견.
LLM이 담당하는 영역: 맥락 판단, 뉘앙스, 종합적 사고가 필요한 부분.

에이전트 구조 (Anthropic Prompt Chaining 패턴):
  기술적 분석 에이전트 → 뉴스 분석 에이전트 → 투자전략 에이전트

실행:
    python analysis.py 005930
"""

import asyncio
import json
import logging
import os
import re

log = logging.getLogger(__name__)

# ── LLM 연동 설정 ────────────────────────────────────────────────
# 파트3 CH1에서 띄운 ChatGPT OAuth 프록시(OPENAI_BASE_URL=http://localhost:18741/v1)
# 또는 OPENAI_API_KEY가 있으면 실제 LLM을 호출합니다. 둘 다 없으면 mock으로 동작.
LLM_MODEL = os.getenv("LECTURE_LLM_MODEL", "gpt-5.4-mini")  # PRISM 분석 파이프라인과 동일


def _llm_enabled() -> bool:
    """OAuth 프록시(base_url) 또는 API 키가 설정돼 있으면 실제 LLM 사용."""
    return bool(os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_KEY"))


async def _llm_complete(system_prompt: str, user_msg: str) -> str:
    """
    OpenAI Chat Completions 호출 (OAuth 프록시 또는 API 키 경유).
    실패 시 RuntimeError를 던져 호출부가 mock으로 폴백하도록 함.
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


# ── 매매 의사결정 기준 (원본 PRISM과 동일 개념) ──────────────────
# buy_score는 0~10점. 시장 국면별 진입 최소점수(min_score)를 넘어야 '진입'.
MIN_BUY_SCORE = 6           # 강세장 기준 진입 임계 (약세장이면 상향)
MARKET_CONDITION = (
    "상승추세: KOSPI가 20일 이동평균을 상회, 최근 10거래일 약 +5%로 강세장 조건 충족. "
    "다만 단기 변동성은 확대 구간."
)

# 종목별 시연용 프로필 (실데이터 연동 전까지 mock 기준값)
#   price=현재가, ret/loss=기대수익/손실(%) → 목표가·손절가·손익비 자동 계산
_PROFILES: dict[str, dict] = {
    "005930": dict(name="삼성전자", price=71200, sector="전기전자/반도체", rec="BUY", buy_score=8, period="중기", ret=14, loss=5,
                   tech="20일선 회복 후 거래량 평균 3배 동반 상승. 외국인 5거래일 연속 순매수.",
                   news="HBM·파운드리 수주 기대와 메모리 업황 저점 통과 전망이 우호적."),
    "000660": dict(name="SK하이닉스", price=178500, sector="전기전자/반도체", rec="BUY", buy_score=9, period="중기", ret=16, loss=6,
                   tech="정배열 유지하며 52주 신고가 근접. 돌파 시 강한 모멘텀 예상.",
                   news="HBM3E 공급 확대와 목표주가 상향 리포트가 다수 발간됨."),
    "035420": dict(name="NAVER", price=215000, sector="서비스/인터넷", rec="BUY", buy_score=7, period="중기", ret=12, loss=6,
                   tech="박스권 상단 돌파 시도. 거래량이 점증하며 수급 개선 신호.",
                   news="AI 검색·광고 매출 회복 기대감이 투자심리를 자극."),
    "042700": dict(name="한미반도체", price=143000, sector="반도체장비", rec="BUY", buy_score=8, period="중기", ret=15, loss=6,
                   tech="후공정 장비 수주 모멘텀으로 신고가 근접. 눌림목마다 매수세 유입.",
                   news="HBM 본더 수주 증가와 전방 capex 기대가 긍정적."),
    "247540": dict(name="에코프로비엠", price=168000, sector="2차전지", rec="BUY", buy_score=7, period="중기", ret=13, loss=7,
                   tech="낙폭과대 후 기관 순매수 전환. 이평선 수렴 후 반등 시도.",
                   news="2차전지 업황 바닥 통과 신호가 일부 지표에서 포착."),
    "005380": dict(name="현대차", price=245000, sector="자동차", rec="HOLD", buy_score=5, period="중기", ret=9, loss=5,
                   tech="단기 급등 후 과열 구간. 20일선까지 눌림목 형성 가능.",
                   news="실적은 양호하나 환율·금리 변수로 방향성은 중립."),
    "035720": dict(name="카카오", price=47850, sector="서비스/인터넷", rec="HOLD", buy_score=5, period="단기", ret=8, loss=5,
                   tech="20일선 부근에서 등락 반복. 방향성 불명확.",
                   news="신사업 모멘텀이 약화되며 뚜렷한 촉매가 부재."),
    "105560": dict(name="KB금융", price=76300, sector="금융", rec="PASS", buy_score=3, period="단기", ret=7, loss=5,
                   tech="거래량 한산, 모멘텀 부재. 박스권 하단 부근.",
                   news="밸류 매력은 있으나 단기 촉매가 보이지 않음."),
    "068270": dict(name="셀트리온", price=187000, sector="바이오", rec="PASS", buy_score=2, period="단기", ret=7, loss=7,
                   tech="이평선 정배열 붕괴 + 수급 이탈. 추세 훼손.",
                   news="바이오 섹터 투자심리 악화로 반등 동력 약함."),
}


def get_current_price(ticker: str) -> int:
    """현재가 조회 (mock). 실데이터 연동 시 이 함수만 KIS/pykrx로 교체하면 됨."""
    return _PROFILES.get(ticker, {}).get("price", 70_000)


def _round_to(value: float, unit: int) -> int:
    return int(round(value / unit) * unit)


# ── 분석 에이전트 설정 (파트4 트랙B에서 수강생이 프롬프트 교체) ────
TECHNICAL_AGENT_PROMPT = """
당신은 윌리엄 오닐의 CANSLIM 방법론을 따르는 기술적 분석 전문가입니다.
주어진 주가 데이터와 거래량 정보를 분석하고, 매수 신호 여부를 판단하세요.
판단 기준:
- 52주 신고가 근접 여부
- 거래량 동반 상승 여부
- 컵&핸들 또는 플랫 베이스 패턴
"""

NEWS_AGENT_PROMPT = """
당신은 뉴스와 공시를 분석하여 주가에 미치는 영향을 판단하는 전문가입니다.
최근 뉴스에서 긍정/부정 촉매를 찾고, 시장 반응을 예측하세요.
"""

STRATEGY_AGENT_PROMPT = """
당신은 기술·뉴스 분석을 종합해 최종 투자 의견을 제시하는 투자 전략가입니다.
윌리엄 오닐식 추세추종 관점에서 목표가는 마일스톤, 손절은 기계적으로 봅니다.
0~10점 매수 점수(buy_score)와 진입 여부, 목표가/손절가/투자기간을 제시하세요.
"""


async def run_analysis(ticker: str) -> dict:
    """
    단일 종목 전체 분석 파이프라인 실행.

    Returns (원본 PRISM scenario와 유사한 형태):
        ticker, recommendation(BUY/HOLD/PASS), decision(진입/보류),
        buy_score(0~10), min_score, current_price, target_price, stop_loss,
        risk_reward_ratio, expected_return_pct, expected_loss_pct,
        investment_period, sector, market_condition, rationale, risk,
        technical_summary, news_summary
    """
    log.info(f"  [{ticker}] 기술적 분석 에이전트 실행 중...")
    technical = await _run_technical_agent(ticker)

    log.info(f"  [{ticker}] 뉴스 분석 에이전트 실행 중...")
    news = await _run_news_agent(ticker)

    log.info(f"  [{ticker}] 투자전략 에이전트 통합 중...")
    strategy = await _run_strategy_agent(ticker, technical, news)

    return _build_scenario(ticker, technical, news, strategy)


def _build_scenario(ticker: str, technical: dict, news: dict, strategy: dict) -> dict:
    """전략 에이전트 결과 + 현재가로 목표가/손절/손익비 등 파생 지표 계산."""
    price = strategy.get("current_price") or get_current_price(ticker)
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

    return {
        "ticker": ticker,
        "company_name": _PROFILES.get(ticker, {}).get("name", ticker),
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
        "sector": _PROFILES.get(ticker, {}).get("sector", "기타"),
        "market_condition": MARKET_CONDITION,
        "rationale": strategy.get("rationale") or strategy.get("reason", ""),
        "risk": strategy.get("risk", ""),
        "technical_summary": technical["summary"],
        "news_summary": news["summary"],
    }


async def _run_technical_agent(ticker: str) -> dict:
    """기술적 분석 에이전트. LLM 연동 시 실제 호출, 아니면 종목별 mock."""
    if _llm_enabled():
        try:
            summary = await _llm_complete(
                TECHNICAL_AGENT_PROMPT,
                f"종목코드 {ticker}의 기술적 분석을 2~3문장으로 요약하고 매수 신호 여부를 판단해줘.",
            )
            return {"ticker": ticker, "summary": summary.strip(), "signal": "LLM"}
        except Exception as e:
            log.warning(f"  기술 에이전트 LLM 실패 → mock 폴백: {e}")

    await asyncio.sleep(0.1)  # 네트워크 호출 시뮬레이션
    prof = _PROFILES.get(ticker)
    summary = prof["tech"] if prof else f"{ticker}: 20일선 위 거래량 급등, 매수 신호 감지"
    return {"ticker": ticker, "summary": summary, "signal": "BULLISH"}


async def _run_news_agent(ticker: str) -> dict:
    """뉴스 분석 에이전트. LLM 연동 시 실제 호출, 아니면 종목별 mock."""
    if _llm_enabled():
        try:
            summary = await _llm_complete(
                NEWS_AGENT_PROMPT,
                f"종목코드 {ticker}와 관련해 최근 시장에서 주목할 호재/악재 촉매를 2~3문장으로 정리해줘.",
            )
            return {"ticker": ticker, "summary": summary.strip(), "sentiment": "LLM"}
        except Exception as e:
            log.warning(f"  뉴스 에이전트 LLM 실패 → mock 폴백: {e}")

    await asyncio.sleep(0.1)
    prof = _PROFILES.get(ticker)
    summary = prof["news"] if prof else f"{ticker}: 실적 개선 기대감, 외국인 순매수 유입"
    return {"ticker": ticker, "summary": summary, "sentiment": "POSITIVE"}


async def _run_strategy_agent(ticker: str, technical: dict, news: dict) -> dict:
    """투자전략 에이전트 — 두 분석을 통합하여 최종 의견 생성. LLM 연동 시 실제 호출."""
    price = get_current_price(ticker)
    if _llm_enabled():
        try:
            user_msg = (
                f"종목코드: {ticker} / 현재가: {price:,}원\n"
                f"[기술적 분석]\n{technical['summary']}\n\n"
                f"[뉴스 분석]\n{news['summary']}\n\n"
                "위 두 분석을 종합해 최종 투자 의견을 아래 JSON 형식으로만 답해줘:\n"
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
            log.warning(f"  전략 에이전트 LLM 실패 → mock 폴백: {e}")

    await asyncio.sleep(0.1)
    prof = _PROFILES.get(ticker, {})
    return {
        "ticker": ticker,
        "current_price": price,
        "recommendation": prof.get("rec", "BUY"),
        "buy_score": prof.get("buy_score", 7),
        "expected_return_pct": prof.get("ret", 12),
        "expected_loss_pct": prof.get("loss", 6),
        "investment_period": prof.get("period", "중기"),
        "rationale": f"기술·뉴스 종합 결과 {prof.get('rec', 'BUY')} 판단. "
                     f"{technical['summary'][:24]}… / {news['summary'][:24]}…",
        "risk": "시장 급락 시 대형주 동반 조정 가능성",
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"
    r = asyncio.run(run_analysis(ticker))

    # 원본 PRISM 리포트와 유사한 섹션형 출력
    print(f"\n{'='*56}")
    print(f"  {r['company_name']}({r['ticker']}) · {r['sector']}")
    print(f"{'='*56}")
    print(f"  투자판단   : {r['recommendation']} → {r['decision']}  "
          f"(매수점수 {r['buy_score']}/10, 진입기준 {r['min_score']})")
    print(f"  현재가     : {r['current_price']:,}원   투자기간: {r['investment_period']}")
    print(f"  목표가     : {r['target_price']:,}원 (+{r['expected_return_pct']}%)")
    print(f"  손절가     : {r['stop_loss']:,}원 (-{r['expected_loss_pct']}%)")
    print(f"  손익비     : {r['risk_reward_ratio']} : 1")
    print(f"{'-'*56}")
    print(f"  [기술적 분석] {r['technical_summary']}")
    print(f"  [뉴스 분석]   {r['news_summary']}")
    print(f"  [시장 국면]   {r['market_condition']}")
    print(f"  [종합 판단]   {r['rationale']}")
    print(f"  [리스크]      {r['risk']}")
    print(f"{'='*56}")
