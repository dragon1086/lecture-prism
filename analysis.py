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
당신은 기술적 분석과 뉴스 분석을 종합하여 최종 투자 의견을 제시하는 투자 전략가입니다.
BUY/HOLD/PASS 중 하나를 선택하고 1~5점 확신 점수를 부여하세요.
"""


async def run_analysis(ticker: str) -> dict:
    """
    단일 종목 전체 분석 파이프라인 실행.

    Args:
        ticker: 종목코드

    Returns:
        {
            "ticker": str,
            "recommendation": "BUY" | "HOLD" | "PASS",
            "score": int (1~5),
            "reason": str,
            "risk": str,
            "technical_summary": str,
            "news_summary": str,
        }
    """
    log.info(f"  [{ticker}] 기술적 분석 에이전트 실행 중...")
    technical = await _run_technical_agent(ticker)

    log.info(f"  [{ticker}] 뉴스 분석 에이전트 실행 중...")
    news = await _run_news_agent(ticker)

    log.info(f"  [{ticker}] 투자전략 에이전트 통합 중...")
    strategy = await _run_strategy_agent(ticker, technical, news)

    return {
        "ticker": ticker,
        "recommendation": strategy["recommendation"],
        "score": strategy["score"],
        "reason": strategy["reason"],
        "risk": strategy["risk"],
        "technical_summary": technical["summary"],
        "news_summary": news["summary"],
    }


async def _run_technical_agent(ticker: str) -> dict:
    """기술적 분석 에이전트. LLM 연동 시 실제 호출, 아니면 mock."""
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
    return {
        "ticker": ticker,
        "summary": f"[{ticker}] 기술적 분석: 20일선 위 거래량 급등, 매수 신호 감지",
        "signal": "BULLISH",
    }


async def _run_news_agent(ticker: str) -> dict:
    """뉴스 분석 에이전트. LLM 연동 시 실제 호출, 아니면 mock."""
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
    return {
        "ticker": ticker,
        "summary": f"[{ticker}] 최근 뉴스: 실적 개선 기대감, 외국인 순매수 유입",
        "sentiment": "POSITIVE",
    }


async def _run_strategy_agent(ticker: str, technical: dict, news: dict) -> dict:
    """투자전략 에이전트 — 두 분석을 통합하여 최종 의견 생성. LLM 연동 시 실제 호출."""
    if _llm_enabled():
        try:
            user_msg = (
                f"종목코드: {ticker}\n"
                f"[기술적 분석]\n{technical['summary']}\n\n"
                f"[뉴스 분석]\n{news['summary']}\n\n"
                "위 두 분석을 종합해 최종 투자 의견을 아래 JSON 형식으로만 답해줘:\n"
                '{"recommendation": "BUY|HOLD|PASS", "score": 1~5 정수, '
                '"reason": "판단 근거 한 문장", "risk": "주요 리스크 한 문장"}'
            )
            raw = await _llm_complete(STRATEGY_AGENT_PROMPT, user_msg)
            parsed = _extract_json(raw)
            return {
                "ticker": ticker,
                "recommendation": str(parsed.get("recommendation", "HOLD")).upper(),
                "score": int(parsed.get("score", 3)),
                "reason": str(parsed.get("reason", "")),
                "risk": str(parsed.get("risk", "")),
            }
        except Exception as e:
            log.warning(f"  전략 에이전트 LLM 실패 → mock 폴백: {e}")

    await asyncio.sleep(0.1)
    return {
        "ticker": ticker,
        "recommendation": "BUY",
        "score": 4,
        "reason": "기술적 신호와 뉴스 모두 긍정적. 분할 매수 권장.",
        "risk": "시장 급락 시 연동 하락 가능성",
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"
    result = asyncio.run(run_analysis(ticker))

    print(f"\n{'='*50}")
    print(f"종목: {result['ticker']}")
    print(f"추천: {result['recommendation']} (점수: {result['score']}/5)")
    print(f"근거: {result['reason']}")
    print(f"리스크: {result['risk']}")
    print(f"{'='*50}")
