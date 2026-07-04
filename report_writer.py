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


def render_analysis_report(result: dict) -> str:
    """Render one `analysis.py` scenario dict as a student-readable report."""

    company = result.get("company_name") or result.get("ticker", "Unknown")
    ticker = result.get("ticker", "UNKNOWN")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# {company} ({ticker}) 분석 보고서",
        "",
        f"- 생성 시각: {generated_at}",
        f"- 섹터: {result.get('sector', '-')}",
        f"- 데이터 원천: {result.get('data_source', '-')}",
        f"- 런타임 설정: {result.get('runtime_summary', '-')}",
        "",
        "## 요약",
        "",
        f"- 투자판단: {result.get('recommendation', '-')} -> {result.get('decision', '-')}",
        f"- 매수점수: {result.get('buy_score', '-')}/{result.get('min_score', '-')}",
        f"- 현재가: {_money(result.get('current_price'))}",
        f"- 목표가: {_money(result.get('target_price'))} ({result.get('expected_return_pct', '-')}%)",
        f"- 손절가: {_money(result.get('stop_loss'))} (-{result.get('expected_loss_pct', '-')}%)",
        f"- 손익비: {result.get('risk_reward_ratio', '-')} : 1",
        f"- 투자기간: {result.get('investment_period', '-')}",
        "",
        "## 1. 기술적 분석",
        "",
        _text(result.get("technical_summary")) or "-",
        "",
        "## 2. 수급 분석",
        "",
        _text(result.get("supply_summary")) or "-",
        "",
        "## 3. 재무 분석",
        "",
        _text(result.get("financial_summary")) or "-",
        "",
        "## 4. 산업 분석",
        "",
        _text(result.get("industry_summary")) or "-",
        "",
        "## 5. 뉴스와 촉매",
        "",
        _text(result.get("news_summary")) or "-",
        "",
        "## 6. 시장 국면",
        "",
        _text(result.get("market_condition")) or "-",
        "",
        "## 종합 판단",
        "",
        _text(result.get("rationale")) or "-",
        "",
        "## 주요 리스크",
        "",
        _text(result.get("risk")) or "-",
        "",
        "---",
        "",
        "이 보고서는 강의 실습용 자동 생성 결과입니다. 실제 투자 판단은 본인이 별도로 검증해야 합니다.",
        "",
    ]
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
