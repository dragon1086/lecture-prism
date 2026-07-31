"""
analysis.py — 모듈 2: LLM 분석 파이프라인 (6섹션 리치 리포트)

스크리닝 통과 종목 → AI 에이전트 분석 → 원본 PRISM scenario 형태 투자 의견.

설계 사상 (원본 PRISM 축소판):
  규칙으로 되는 건 규칙으로  → 수급·재무·산업·시장 (실데이터 지표 템플릿)
  맥락 판단이 필요한 건 LLM으로 → 기술·뉴스·전략 (3-에이전트 체인, 파트4 트랙B)

3계층 동작:
  Tier 0 (표준 라이브러리)      : mock 데이터로 6섹션 리치 리포트 (키/설치 불필요)
  Tier 1 (pip install yfinance) : 가격·재무·뉴스·지수 실데이터로 섹션 채움
  Tier 2 (+ OpenAI API/Codex OAuth) : 역할 3개를 단일 LLM 호출로 통합해 심층 서술

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
# ChatGPT OAuth는 공식 Codex CLI 로그인, API 과금은 OPENAI_API_KEY를 사용합니다.
# 둘 다 명시적으로 선택하지 않으면 mock/규칙으로 동작합니다.
LLM_MODEL = os.getenv("LECTURE_LLM_MODEL", "gpt-5.4-mini")  # PRISM 분석 파이프라인과 동일

# ── 매매 의사결정 기준 (원본 PRISM과 동일 개념) ──────────────────
# buy_score는 0~10점. 시장 국면별 진입 최소점수(MIN_BUY_SCORE)를 넘어야 '진입'.
MIN_BUY_SCORE = 6           # 강세장 기준 진입 임계 (약세장이면 상향)


def _has_structured_evidence(data: dict) -> bool:
    """Whether fixture and yfinance data may share metric-based analysis rules."""
    return data.get("source") == "yfinance" or data.get("evidence_kind") == "fixture"


def _llm_enabled() -> bool:
    """Return whether an explicit official LLM provider is ready."""
    from runtime_config import load_runtime_config

    return load_runtime_config().llm_enabled


async def _llm_complete(system_prompt: str, user_msg: str) -> str:
    """
    선택된 공식 공급자 호출 (Codex subscription 또는 OpenAI API).
    실패 시 RuntimeError를 던져 호출부가 mock/규칙으로 폴백하도록 함.
    """
    from llm_provider import LLMProviderError, provider_for
    from runtime_config import load_runtime_config

    provider = provider_for(load_runtime_config())
    if provider is None:
        raise LLMProviderError("활성화된 LLM 공급자가 없습니다")
    return await provider.complete(system_prompt, user_msg)


def _extract_json(text: str) -> dict:
    """LLM 응답에서 첫 번째 JSON 객체를 추출 (코드펜스/잡설 포함 대응)."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("응답에 JSON 객체 없음")


def get_current_price(ticker: str) -> int:
    """현재가 조회(경량 폴백). 실데이터는 data_source.fetch_stock_data()가 담당."""
    return data_source.mock_profile(ticker)["price"]


def _round_to(value: float, unit: int) -> int:
    return int(round(value / unit) * unit)


# ── 분석 에이전트 프롬프트 (파트4 트랙B에서 수강생이 교체) ──────────
TECHNICAL_AGENT_PROMPT = """
당신은 주가·거래량 기술 분석가입니다.
주어진 주가·거래량·이동평균·RSI 근거만 사용해 추세, 과열 여부,
거래량이 가격 움직임을 뒷받침하는지를 판단하세요.
확인되지 않은 차트 패턴을 만들지 말고, 입력에 있는 수치를 인용해 3~4문장으로 서술하세요.
"""

NEWS_AGENT_PROMPT = """
당신은 뉴스·공시를 분석하여 주가 영향을 판단하는 전문가입니다.
주어진 실제 뉴스 헤드라인에서 호재/악재 촉매를 식별하고 시장 반응을 예측하세요.
헤드라인이 영문이면 핵심을 한국어로 해석해 전달하세요. 3~4문장으로 서술하세요.
"""

COMBINED_AGENT_PROMPT = f"""
당신은 한 번의 호출 안에서 아래 세 역할을 순서대로 수행하는 투자 분석 위원회입니다.

[기술 분석가]
{TECHNICAL_AGENT_PROMPT.strip()}

[뉴스 분석가]
{NEWS_AGENT_PROMPT.strip()}

[리스크 검토자]
정량 엔진의 추천·점수·목표가·손절가를 변경하지 마세요. 제공된 근거에 모순,
중대한 악재, 출처 부족이 있으면 llm_veto를 true로 두고 이유를 설명하세요.
그 외에는 false로 두되, 확정 수익이나 근거 없는 사실을 만들지 마세요.

응답은 요청된 JSON 하나뿐이어야 합니다.
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
    if data["source"] == "yfinance":
        src = "실데이터(yfinance)"
    else:
        src = "모의 데이터(mock)"
    log.info(f"  [{ticker}] 데이터 원천: {src}")

    # 규칙·원천 데이터로 6섹션의 근거를 먼저 만든다. LLM은 이 근거를
    # 수집하지 않고 해석만 하며, Plus OAuth는 종목당 한 번만 호출한다.
    technical = _technical_data_text(data)

    # 2) 수급 — 실거래량 파생 프록시 (규칙)
    supply = _section_supply(data)

    # 3) 재무 — 실데이터 지표 (규칙)
    financial = _section_financial(data)

    # 4) 산업 — 섹터/산업 (규칙)
    industry = _section_industry(data)

    # 5) 뉴스 — 검증 가능한 헤드라인/선택 리서치 원문
    news = _news_evidence_text(ticker, data)

    # 6) 시장 국면 — 지수 실데이터 (규칙)
    market_condition = _section_market(market)

    # 정량 점수·추천·가격은 규칙 엔진이 소유한다. LLM은 서술을 보강하고
    # 명시적으로 veto할 수만 있으며, PASS/HOLD를 BUY로 올릴 수 없다.
    strategy = _rule_based_score(data)
    strategy["current_price"] = data["current_price"]
    strategy["rationale"] = (
        f"기술·수급·재무·뉴스 종합 {strategy['recommendation']} 판단. {technical[:40]}…"
    )
    strategy["risk"] = "시장 급락 시 동반 조정 및 수급 이탈 가능성."

    # 종합 — 기술·뉴스·전략 역할을 단일 구조화 호출로 실행한다.
    if _llm_enabled():
        log.info(f"  [{ticker}] 통합 LLM 분석 1회 실행 중...")
        try:
            enriched = await _run_combined_llm_agent(
                ticker, data, technical, supply, financial, industry, news, market_condition
            )
            technical = enriched.pop("technical_summary", technical) or technical
            news = enriched.pop("news_summary", news) or news
            strategy = _apply_llm_overlay(strategy, enriched)
        except Exception as exc:  # noqa: BLE001 - provider failure must fall back
            log.warning("  통합 LLM 실패 → 규칙 분석 폴백: %s", exc)

    return _build_scenario(
        ticker, data, technical, supply, financial, industry, news, market_condition, strategy
    )


# ── 섹션 빌더: 규칙(실데이터 템플릿 / mock) ─────────────────────────────
def _section_supply(data: dict) -> str:
    """수급(거래 흐름). fixture와 실데이터를 같은 거래량 규칙으로 해석."""
    if not _has_structured_evidence(data):
        return "거래량 기반 수급 지표를 확보하지 못했습니다."
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
    if data.get("evidence_kind") == "fixture":
        return body + " (교육용 고정 가격·거래량 시나리오 기반이며 실제 주체별 순매수 정보가 아님)"
    return body + " (※ 기관/외국인/개인 세부 순매수는 KRX 로그인이 필요해 거래량 기반으로 추정)"


def _section_financial(data: dict) -> str:
    """재무. fixture와 실데이터를 같은 지표 템플릿으로 표현."""
    if not _has_structured_evidence(data):
        return "재무 지표를 확보하지 못했습니다."
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
    sector = data.get("sector", "기타")
    industry = data.get("industry", "")
    tail = f" 세부 업종: {industry}." if industry else ""
    if data.get("evidence_kind") == "fixture":
        context = data.get("industry_context", "")
        return f"섹터 분류: {sector}.{tail} 교육용 산업 시나리오: {context}"
    return f"섹터 분류: {sector}.{tail} 경쟁 위치·업황은 뉴스·전략 섹션과 함께 판단."


def _section_market(market: dict | None) -> str:
    """시장 국면. 지수 실데이터가 있으면 서술, 없으면 폴백."""
    if not market:
        return "시장 지수 데이터를 확보하지 못했습니다."
    parts = []
    for name in ("KOSPI", "KOSDAQ"):
        m = market.get(name)
        if m:
            trend = "강세" if m["ret_20d"] >= 0 else "약세"
            parts.append(f"{name} {m['last']:,} (20일 {m['ret_20d']:+}%, {trend})")
    if not parts:
        return "시장 지수 데이터를 확보하지 못했습니다."
    result = " / ".join(parts) + "."
    if market.get("source") == "fixture":
        return result + " (교육용 고정 시장 시나리오이며 현재 지수 정보가 아님)"
    return result


# ── 에이전트: 기술 (LLM 또는 데이터 템플릿) ──────────────────────────────
def _technical_data_text(data: dict) -> str:
    """fixture와 실데이터 기술 지표를 같은 문장 템플릿으로 표현."""
    if not _has_structured_evidence(data):
        return "기술 지표 계산 데이터 부족."
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


def _news_evidence_text(ticker: str, data: dict) -> str:
    """Return bounded news evidence without asking an LLM to collect data."""
    news = data.get("news")
    headlines = news if isinstance(news, list) else []
    text = "\n".join(f"- {headline}" for headline in headlines[:8])
    if not text:
        text = news if isinstance(news, str) else "관련 뉴스 없음"
    if data.get("evidence_kind") == "fixture":
        text = f"교육용 촉매 시나리오(현재 뉴스 아님):\n{text}"
    research_context = _optional_research_context(ticker, data)
    return f"{text}\n\n{research_context}" if research_context else text


def _normalize_llm_result(parsed: dict) -> dict:
    """Keep only qualitative fields; all trading numbers stay deterministic."""
    result = {"llm_veto": parsed.get("llm_veto") is True}
    for key in ("technical_summary", "news_summary", "rationale", "risk"):
        value = parsed.get(key)
        result[key] = value.strip() if isinstance(value, str) else ""
    return result


def _apply_llm_overlay(strategy: dict, qualitative: dict) -> dict:
    """Apply prose and a one-way veto without weakening quantitative gates."""
    result = dict(strategy)
    if qualitative.get("llm_veto") is True and result.get("recommendation") == "BUY":
        result["recommendation"] = "HOLD"
    for key in ("rationale", "risk"):
        if qualitative.get(key):
            result[key] = qualitative[key]
    return result


async def _run_combined_llm_agent(ticker, data, technical, supply, financial,
                                  industry, news, market_condition) -> dict:
    """Run the three teaching roles in one provider request per ticker."""
    price = data["current_price"]
    currency = data.get("currency") or ("KRW" if ticker.isdigit() else "USD")
    evidence = {
        "ticker": ticker,
        "company_name": data.get("name", ticker),
        "current_price": price,
        "currency": currency,
        "technical_evidence": technical,
        "supply_evidence": supply,
        "financial_evidence": financial,
        "industry_evidence": industry,
        "news_evidence": news,
        "market_regime": market_condition,
    }
    schema_example = {
        "technical_summary": "근거 수치를 인용한 요약",
        "news_summary": "확인된 헤드라인만 해석한 요약",
        "llm_veto": False,
        "rationale": "진입 또는 보류 근거",
        "risk": "주요 리스크",
    }
    message = (
        "아래 입력 근거만 사용해 분석하세요. JSON 스키마의 모든 키를 채우세요.\n"
        f"입력 근거:\n{json.dumps(evidence, ensure_ascii=False)}\n\n"
        f"출력 JSON 예시(숫자는 반드시 JSON number):\n"
        f"{json.dumps(schema_example, ensure_ascii=False)}"
    )
    parsed = _extract_json(await _llm_complete(COMBINED_AGENT_PROMPT, message))
    return _normalize_llm_result(parsed)


def _optional_research_context(ticker: str, data: dict) -> str:
    from runtime_config import load_runtime_config

    cfg = load_runtime_config()
    if cfg.report_mode != "research":
        return ""
    if not any(cfg.tool_ready.get(tool) for tool in ("perplexity", "firecrawl")):
        return ""
    try:
        import research_tools

        return research_tools.build_research_context(
            ticker,
            data.get("name", ticker),
            data.get("sector", ""),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("  선택 리서치 컨텍스트 생성 실패 → 기본 뉴스로 진행: %s", exc)
        return ""


# ── 규칙 기반 전략 점수 ─────────────────────────────────────────────
def _rule_based_score(data: dict) -> dict:
    """실데이터(LLM 없음) 경로용 규칙 기반 매수 점수 0~10."""
    if not _has_structured_evidence(data):
        return {"recommendation": "PASS", "buy_score": 0,
                "expected_return_pct": 12, "expected_loss_pct": 6, "investment_period": "중기"}
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


def _build_scenario(ticker, data, technical, supply, financial,
                    industry, news, market_condition, strategy) -> dict:
    """전략 결과 + 현재가로 목표가/손절/손익비 등 파생 지표 계산."""
    from runtime_config import load_runtime_config

    cfg = load_runtime_config()
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
    is_fixture = data.get("evidence_kind") == "fixture"
    if is_fixture:
        data_status = "교육용 고정 시나리오"
        data_notice = data.get("notice", "교육용 시나리오입니다.")
        section_provenance = {
            "technical": "교육용 고정 가격·거래량 시나리오",
            "supply": "교육용 고정 거래량 시나리오",
            "financial": "교육용 고정 재무 시나리오",
            "industry": "교육용 산업 시나리오",
            "news": "교육용 촉매 시나리오",
            "market": "교육용 고정 시장 시나리오",
        }
    else:
        data_status = "조회 시점의 yfinance 스냅샷"
        data_notice = "시세·재무·뉴스 항목의 제공 시점이 다를 수 있으므로 원문을 별도로 확인하세요."
        section_provenance = {
            "technical": "yfinance 가격·거래량 지표",
            "supply": "yfinance 거래량 파생 프록시",
            "financial": "yfinance 재무 지표",
            "industry": "yfinance 섹터·산업 분류",
            "news": "yfinance 뉴스 헤드라인",
            "market": "yfinance KOSPI/KOSDAQ 지수",
        }

    scenario = {
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
        "data_status": data_status,
        "data_notice": data_notice,
        "data_as_of": data.get("as_of"),
        "section_provenance": section_provenance,
        "runtime_profile": cfg.profile,
        "data_mode": cfg.data_mode,
        "report_mode": cfg.report_mode,
        "research_tools": list(cfg.research_tools),
        "research_tool_ready": dict(cfg.tool_ready),
        "runtime_summary": cfg.summary(),
        # 6섹션 요약
        "technical_summary": technical,
        "supply_summary": supply,
        "financial_summary": financial,
        "industry_summary": industry,
        "news_summary": news_summary,
    }
    return scenario


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"
    r = asyncio.run(run_analysis(ticker))

    # 원본 PRISM 리포트와 유사한 6섹션 출력
    if r["data_source"] == "yfinance":
        src = "실데이터(yfinance)"
    else:
        src = "모의 데이터(mock)"
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
