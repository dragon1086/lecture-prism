"""모듈 2: 독립 전문 에이전트가 작성하는 6섹션 분석 보고서.

`analysis_agents.py`의 전문 에이전트 6개가 개별 보고서를 쓰고 편집 에이전트가
핵심 요약을 조립한다. 이 모듈은 매수 의견·점수·목표가·손절가를 만들지 않는다.
API 키가 없으면 같은 인터페이스의 규칙 보고서로 즉시 폴백한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

import data_source

log = logging.getLogger(__name__)

MARKET_STRONG_RETURN_20D = 2.0
MARKET_WEAK_RETURN_20D = -2.0

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


async def run_analysis(ticker: str) -> dict:
    """기존 호출 호환: 분석 보고서를 만든 뒤 모듈 3 매수 에이전트를 실행한다."""
    from buy_agent import run_buy_agent

    return await run_buy_agent(await run_analysis_report(ticker))


async def run_analysis_report(ticker: str) -> dict:
    """독립 전문 에이전트 6개와 편집 에이전트로 분석 보고서를 작성한다."""
    # 데이터 원천 (실데이터 → mock 폴백). 동기 I/O라 스레드에서 실행.
    data = await asyncio.to_thread(data_source.fetch_stock_data, ticker)
    market = await asyncio.to_thread(data_source.fetch_market_index)
    if data["source"] == "yfinance":
        src = "실데이터(yfinance)"
    else:
        src = "모의 데이터(mock)"
    log.info(f"  [{ticker}] 데이터 원천: {src}")

    fallback_sections = {
        "technical_summary": _technical_data_text(data),
        "supply_summary": _section_supply(data),
        "financial_summary": _section_financial(data),
        "industry_summary": _section_industry(data),
        "news_summary": _news_evidence_text(ticker, data),
        "market_condition": _section_market(market),
    }
    evidence = {
        "ticker": ticker,
        "company_name": data.get("name", ticker),
        "current_price": data["current_price"],
        "currency": data.get("currency") or ("KRW" if ticker.isdigit() else "USD"),
        "technical_evidence": fallback_sections["technical_summary"],
        "supply_evidence": fallback_sections["supply_summary"],
        "financial_evidence": fallback_sections["financial_summary"],
        "industry_evidence": fallback_sections["industry_summary"],
        "news_evidence": fallback_sections["news_summary"],
        "market_evidence": fallback_sections["market_condition"],
    }
    from analysis_agents import run_report_agents

    if _llm_enabled():
        log.info("  [%s] 전문 분석 에이전트 6개 개별 실행 중...", ticker)
    sections = await run_report_agents(
        evidence,
        fallback_sections,
        llm_complete=_llm_complete,
        extract_json=_extract_json,
        llm_enabled=_llm_enabled(),
    )
    return _build_report(
        ticker,
        data,
        sections,
        market_regime=_classify_market_regime(market),
    )


# ── 섹션 빌더: 규칙(실데이터 템플릿 / mock) ─────────────────────────────
def _section_supply(data: dict) -> str:
    """수급(거래 흐름). fixture와 실데이터를 같은 거래량 규칙으로 해석."""
    if not _has_structured_evidence(data):
        return "거래량 기반 수급 지표를 확보하지 못했습니다."
    s = data.get("supply", {})
    if s.get("source") == "kis":
        def signed(value: object) -> str:
            return f"{int(value):+,}주"

        return (
            f"KIS 일별 투자자 수급({s.get('as_of', '기준일 미상')}): "
            f"기관 {signed(s.get('institution_net_buy', 0))}, "
            f"외국인 {signed(s.get('foreign_net_buy', 0))}, "
            f"개인 {signed(s.get('individual_net_buy', 0))}. "
            "(실제 주체별 순매수 수량)"
        )
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


def _classify_market_regime(market: dict | None) -> str:
    """KOSPI 20일 수익률을 강세·횡보·약세의 구조화 값으로 바꿉니다."""
    try:
        return_20d = float((market or {})["KOSPI"]["ret_20d"])
    except (KeyError, TypeError, ValueError):
        return "sideways"
    if return_20d >= MARKET_STRONG_RETURN_20D:
        return "strong"
    if return_20d <= MARKET_WEAK_RETURN_20D:
        return "weak"
    return "sideways"


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


def _rule_based_score(data: dict) -> dict:
    """이전 교재·테스트 호환용 정량 점수 진입점."""
    from buy_agent import _rule_based_score as score

    copied = dict(data)
    copied["structured_evidence"] = _has_structured_evidence(data)
    return score(copied)


def _build_report(
    ticker: str,
    data: dict,
    sections: dict,
    *,
    market_regime: str = "sideways",
) -> dict:
    """전문 에이전트 결과를 매수 판단이 없는 분석 보고서로 조립한다."""
    from runtime_config import load_runtime_config

    cfg = load_runtime_config()
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
        supply = data.get("supply", {})
        if supply.get("source") == "kis":
            section_provenance["supply"] = (
                f"KIS 투자자별 일별 순매수 ({supply.get('as_of', '기준일 미상')})"
            )
            data_notice = (
                "가격·재무·뉴스는 yfinance, 수급은 KIS 기준입니다. "
                "각 항목의 기준일을 따로 확인하세요."
            )

    return {
        "ticker": ticker,
        "company_name": data.get("name", ticker),
        "current_price": data["current_price"],
        "sector": data.get("sector", "기타"),
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
        "market_regime": market_regime,
        **sections,
        "_decision_evidence": {
            "structured_evidence": _has_structured_evidence(data),
            "price_vs_ma20": data.get("price_vs_ma20"),
            "ma5": data.get("ma5"),
            "ma20": data.get("ma20"),
            "rsi": data.get("rsi"),
            "vol_ratio": data.get("vol_ratio"),
            "highs": list(data.get("highs") or []),
            "lows": list(data.get("lows") or []),
            "closes": list(data.get("closes") or []),
            "atr14": data.get("atr14"),
            "finance": dict(data.get("finance", {})),
            "supply": dict(data.get("supply", {})),
        },
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"
    r = asyncio.run(run_analysis_report(ticker))

    # 원본 PRISM 리포트와 유사한 6섹션 출력
    if r["data_source"] == "yfinance":
        src = "실데이터(yfinance)"
    else:
        src = "모의 데이터(mock)"
    print(f"\n{'='*60}")
    print(f"  {r['company_name']}({r['ticker']}) · {r['sector']}   [원천: {src}]")
    print(f"{'='*60}")
    print(f"  현재가     : {r['current_price']:,}원")
    print(f"{'-'*60}")
    print(f"  [기술적 분석] {r['technical_summary']}")
    print(f"  [수급 분석]   {r['supply_summary']}")
    print(f"  [재무 분석]   {r['financial_summary']}")
    print(f"  [산업 분석]   {r['industry_summary']}")
    print(f"  [뉴스/촉매]   {r['news_summary']}")
    print(f"  [시장 국면]   {r['market_condition']}")
    print(f"  [편집장 요약] {r['executive_summary']}")
    print(f"{'='*60}")
