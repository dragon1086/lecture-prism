"""모듈 2의 독립 분석 보고서 에이전트 정의와 실행기."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentSpec:
    name: str
    output_key: str
    prompt: str


_REPORT_BOUNDARY = """
제공된 입력 근거만 사용해 해당 영역의 분석 보고서를 3~5문장으로 작성하세요.
근거에 없는 사실을 만들지 마세요. 매수·매도 여부, 점수, 목표가, 손절가,
주문 수량은 판단하지 마세요. 응답은 {"summary": "..."} JSON 하나만 출력하세요.
""".strip()


AGENT_SPECS = {
    "technical": AgentSpec(
        "기술 분석가",
        "technical_summary",
        "당신은 주가·거래량 기술 분석가입니다. 이동평균, RSI, 수익률과 거래량이 보여주는 추세를 설명합니다.\n"
        + _REPORT_BOUNDARY,
    ),
    "supply": AgentSpec(
        "수급 분석가",
        "supply_summary",
        "당신은 수급 분석가입니다. 상승일·하락일 거래량, 거래량 비율, OBV와 데이터 한계를 설명합니다.\n"
        + _REPORT_BOUNDARY,
    ),
    "financial": AgentSpec(
        "재무 분석가",
        "financial_summary",
        "당신은 재무 분석가입니다. 성장성, 수익성, 밸류에이션 지표를 서로 구분해 설명합니다.\n"
        + _REPORT_BOUNDARY,
    ),
    "industry": AgentSpec(
        "산업 분석가",
        "industry_summary",
        "당신은 산업 분석가입니다. 섹터, 세부 업종, 산업 환경과 기업 위치를 입력 범위 안에서 설명합니다.\n"
        + _REPORT_BOUNDARY,
    ),
    "news": AgentSpec(
        "뉴스 분석가",
        "news_summary",
        "당신은 뉴스 분석가입니다. 확인된 헤드라인의 촉매, 위험과 확인할 후속 사건을 구분해 설명합니다.\n"
        + _REPORT_BOUNDARY,
    ),
    "market": AgentSpec(
        "시장 분석가",
        "market_condition",
        "당신은 시장 분석가입니다. 대표 지수의 추세와 종목 분석에 필요한 시장 배경을 설명합니다.\n"
        + _REPORT_BOUNDARY,
    ),
}


EDITOR_PROMPT = """
당신은 종목 분석 보고서 편집장입니다. 여섯 전문 분석가의 보고서를 읽고
겹치는 내용을 제거하며, 서로 일치하는 근거와 충돌하는 근거를 구분해
4~6문장의 핵심 요약을 작성하세요. 새로운 사실이나 매수·매도 판단,
점수, 목표가, 손절가를 추가하지 마세요.
응답은 {"executive_summary": "..."} JSON 하나만 출력하세요.
""".strip()


async def run_report_agents(
    evidence: dict,
    fallback_sections: dict[str, str],
    *,
    llm_complete: Callable[[str, str], Awaitable[str]],
    extract_json: Callable[[str], dict],
    llm_enabled: bool,
) -> dict[str, str]:
    """독립 전문 에이전트 6개와 후속 편집 에이전트를 실행한다."""
    if not llm_enabled:
        sections = dict(fallback_sections)
        sections["executive_summary"] = _fallback_executive_summary(sections)
        return sections

    async def run_one(spec: AgentSpec) -> tuple[str, str]:
        message = json.dumps(evidence, ensure_ascii=False, default=str)
        try:
            parsed = extract_json(await llm_complete(spec.prompt, message))
            summary = parsed.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError("summary가 비어 있음")
            return spec.output_key, summary.strip()
        except Exception as exc:  # noqa: BLE001 - 한 섹션 실패는 해당 섹션만 폴백
            log.warning("%s 실패 → 규칙 보고서 폴백: %s", spec.name, type(exc).__name__)
            return spec.output_key, fallback_sections[spec.output_key]

    pairs = await asyncio.gather(*(run_one(spec) for spec in AGENT_SPECS.values()))
    sections = dict(pairs)
    editor_message = json.dumps(sections, ensure_ascii=False)
    try:
        parsed = extract_json(await llm_complete(EDITOR_PROMPT, editor_message))
        summary = parsed.get("executive_summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("executive_summary가 비어 있음")
        sections["executive_summary"] = summary.strip()
    except Exception as exc:  # noqa: BLE001 - 편집 실패도 보고서 전체를 막지 않음
        log.warning("보고서 편집 에이전트 실패 → 규칙 요약 폴백: %s", type(exc).__name__)
        sections["executive_summary"] = _fallback_executive_summary(sections)
    return sections


def _fallback_executive_summary(sections: dict[str, str]) -> str:
    technical = sections.get("technical_summary", "기술 근거 없음")
    financial = sections.get("financial_summary", "재무 근거 없음")
    news = sections.get("news_summary", "뉴스 근거 없음")
    return f"기술 근거: {technical} 재무 근거: {financial} 뉴스·촉매: {news}"
