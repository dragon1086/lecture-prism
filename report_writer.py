"""Markdown report writer for lecture-prism analysis results.

Reports are runtime artifacts for students to inspect after a pipeline run.
This module stays stdlib-only and never requires API keys.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path

from brokers.config import load_dotenv_once, truthy

log = logging.getLogger(__name__)

DEFAULT_REPORT_DIR = Path("reports")
BUY_SCORE_MAX = 10


def _reports_enabled() -> bool:
    load_dotenv_once()
    raw = os.getenv("LECTURE_SAVE_REPORTS")
    return True if raw is None else truthy(raw)


def _safe_filename(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", text.strip())
    return cleaned.strip("_") or "report"


def _money(value) -> str:
    try:
        return f"{int(float(value)):,}원"
    except (TypeError, ValueError):
        return "-"


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " / ".join(str(item) for item in value)
    return str(value)


def _section_lines(title: str, summary, provenance: str | None) -> list[str]:
    """Render one analysis section with an optional, explicit evidence label."""
    lines = [f"## {title}", ""]
    if provenance:
        lines.extend([f"> 근거: {provenance}", ""])
    lines.extend([_text(summary) or "-", ""])
    return lines


def _trade_scenario_lines(result: dict) -> list[str]:
    """분석값을 보고서용 진입·무효화·청산 설명으로 바로 펼친다."""

    recommendation = str(result.get("recommendation") or "HOLD").upper()
    decision = str(result.get("decision") or "보류")
    buy_score = int(result.get("buy_score") or 0)
    min_score = int(result.get("min_score") or 0)
    current_price = result.get("current_price")
    target_price = result.get("target_price")
    stop_loss = result.get("stop_loss")
    risk_reward_ratio = result.get("risk_reward_ratio", "-")
    score_ok = recommendation == "BUY" and decision == "진입" and buy_score >= min_score
    try:
        geometry_ok = float(target_price) > float(current_price) > float(stop_loss)
    except (TypeError, ValueError):
        geometry_ok = False

    status = (
        "추천·진입·매수점수 기준 통과"
        if score_ok
        else "추천·진입·매수점수 기준 미통과"
    )
    geometry = (
        "목표가·현재가·손절가 순서 확인"
        if geometry_ok
        else "목표가·현재가·손절가 순서 불일치"
    )
    technical = _text(result.get("technical_summary")) or "-"
    market = _text(result.get("market_condition")) or "-"
    return [
        "## 매매 시나리오",
        "",
        "### 이번 시나리오의 통과 여부",
        "",
        f"- {status}",
        f"- {geometry}",
        f"- 손익비 {risk_reward_ratio} : 1은 `trading.py`의 신규 진입 규칙에서 최종 확인",
        "",
        "### 진입 전 확인",
        "",
        f"- 매수점수 {buy_score}/10이 진입 기준 {min_score}점 이상인지 확인",
        (
            f"- 현재가 {_money(current_price)}, 목표가 {_money(target_price)}, "
            f"손절가 {_money(stop_loss)}의 순서 확인"
        ),
        f"- 기술 근거: {technical}",
        f"- 시장 확인: {market}",
        "",
        "### 판단을 다시 볼 조건",
        "",
        f"- 종가가 손절가 {_money(stop_loss)} 아래로 마감하면 손절을 점검",
        "- 추천·진입 상태나 매수점수가 바뀌면 새 주문보다 분석 근거를 먼저 확인",
        "",
        "### 청산 원칙",
        "",
        f"- 손절: 손절가 {_money(stop_loss)}에 닿으면 먼저 점검",
        "- 트레일링 스탑: 수익 구간에서는 고점 대비 되돌림을 다음으로 점검",
        f"- 목표가: {_money(target_price)} 도달은 확정 수익이 아니라 다음 판단의 마일스톤",
        "",
        "### 시나리오 메모",
        "",
        (
            "보고서는 확인할 근거를 정리하고, 실제 진입 허용 여부는 "
            "`trading.py`가 가격 배열·손익비·포지션 한도를 다시 검사합니다."
        ),
        "",
    ]


def render_analysis_report(result: dict) -> str:
    """Render an analysis report, optionally followed by a buy scenario."""

    company = result.get("company_name") or result.get("ticker", "Unknown")
    ticker = result.get("ticker", "UNKNOWN")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_as_of = result.get("data_as_of")
    section_provenance = result.get("section_provenance") or {}
    lines = [
        f"# {company} ({ticker}) 분석 보고서",
        "",
        f"- 생성 시각: {generated_at}",
        f"- 섹터: {result.get('sector', '-')}",
        f"- 데이터 원천: {result.get('data_source', '-')}",
        f"- 데이터 상태: {result.get('data_status', '-')}",
        f"- 런타임 설정: {result.get('runtime_summary', '-')}",
        "",
    ]
    if data_as_of:
        lines.append(f"- 분석 기준: {data_as_of}")
    if result.get("data_notice"):
        lines.append(f"- 주의: {result['data_notice']}")
    lines.extend([
        "",
        "## 편집장 핵심 요약",
        "",
        _text(result.get("executive_summary")) or "-",
        "",
    ])
    for title, summary_key, provenance_key in (
        ("1. 기술적 분석", "technical_summary", "technical"),
        ("2. 수급 분석", "supply_summary", "supply"),
        ("3. 재무 분석", "financial_summary", "financial"),
        ("4. 산업 분석", "industry_summary", "industry"),
        ("5. 뉴스와 촉매", "news_summary", "news"),
        ("6. 시장 국면", "market_condition", "market"),
    ):
        lines.extend(_section_lines(
            title,
            result.get(summary_key),
            section_provenance.get(provenance_key),
        ))
    if "recommendation" in result:
        lines.extend([
            "## 매수 시나리오 요약",
            "",
            f"- 투자판단: {result.get('recommendation', '-')} -> {result.get('decision', '-')}",
            f"- 매수점수: {result.get('buy_score', '-')}/{BUY_SCORE_MAX}",
            f"- 현재가: {_money(result.get('current_price'))}",
            f"- 목표가: {_money(result.get('target_price'))} ({result.get('expected_return_pct', '-')}%)",
            f"- 손절가: {_money(result.get('stop_loss'))} (-{result.get('expected_loss_pct', '-')}%)",
            f"- 손익비: {result.get('risk_reward_ratio', '-')} : 1",
            "",
        ])
        lines.extend(_trade_scenario_lines(result))
        lines.extend([
            "## 매수 에이전트 판단",
            "",
            _text(result.get("rationale")) or "-",
            "",
            "## 주요 리스크",
            "",
            _text(result.get("risk")) or "-",
            "",
        ])
    lines.extend([
        "---",
        "",
        "이 보고서는 강의 실습용 자동 생성 결과입니다. 실제 투자 판단은 본인이 별도로 검증해야 합니다.",
        "",
    ])
    return "\n".join(lines)


def write_analysis_report(result: dict, *, output_dir: Path | str = DEFAULT_REPORT_DIR) -> Path:
    """Write one Markdown report and return its path."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ticker = _safe_filename(str(result.get("ticker", "UNKNOWN")))
    company = _safe_filename(str(result.get("company_name") or ticker))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{stamp}-{ticker}-{company}.md"
    path.write_text(render_analysis_report(result), encoding="utf-8")
    return path


def write_reports(analyses: list[dict], *, output_dir: Path | str = DEFAULT_REPORT_DIR) -> list[Path]:
    """Write Markdown reports when enabled by `.env`."""

    if not _reports_enabled():
        return []
    paths = []
    for result in analyses:
        try:
            paths.append(write_analysis_report(result, output_dir=output_dir))
        except OSError as exc:
            log.warning("분석 보고서 저장 실패(%s): %s", result.get("ticker", "?"), exc)
    return paths
