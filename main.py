"""
main.py — lecture-prism 오케스트레이터

전체 파이프라인: 스크리닝 → 분석 → 매매 → 피드백

실행:
    python main.py                  # 오늘 장 실행
    python main.py --dry-run        # 시뮬레이션 (실거래 없음)
    python main.py --ticker 005930  # 특정 종목만 분석
"""

from __future__ import annotations

import asyncio
import argparse
import logging
import os
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


_OPENAI_ENV_KEYS = ("OPENAI_BASE_URL", "OPENAI_API_KEY")


def _restore_openai_env(saved: dict[str, str | None]) -> None:
    """Restore OpenAI env vars after a failed/finished OAuth proxy run."""
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


async def _maybe_start_chatgpt_oauth_proxy() -> tuple[bool, dict[str, str | None]]:
    """
    Mirror the full PRISM pattern in a teaching-safe way.

    If PRISM_OPENAI_AUTH_MODE=chatgpt_oauth, start the bundled OAuth proxy and
    inject OPENAI_BASE_URL/OPENAI_API_KEY before analysis.py imports the OpenAI
    client. If anything is missing, restore env vars and let analysis.py fall
    back to mock mode instead of blocking the beginner demo.
    """
    saved = {key: os.environ.get(key) for key in _OPENAI_ENV_KEYS}
    from runtime_config import load_runtime_config

    cfg = load_runtime_config()
    if not cfg.llm_enabled or not cfg.chatgpt_oauth_requested or os.getenv("OPENAI_BASE_URL"):
        return False, saved

    try:
        from cores.chatgpt_proxy import inject_env, start_proxy
    except ImportError as exc:
        log.warning("ChatGPT OAuth 프록시 의존성이 없어 mock 모드로 진행합니다: %s", exc)
        return False, saved

    inject_env()
    started = await start_proxy()
    if started:
        log.info("ChatGPT OAuth 프록시 연결: %s", os.environ.get("OPENAI_BASE_URL"))
        return True, saved

    _restore_openai_env(saved)
    log.warning("ChatGPT OAuth 프록시 시작 실패 — LLM 분석은 mock 폴백으로 진행합니다.")
    return False, saved


def _resolve_runtime_options(args) -> dict:
    """Resolve CLI flags plus `.env` profile into pipeline options."""

    from runtime_config import load_runtime_config, resolve_trade_dry_run

    cfg = load_runtime_config()
    return {
        "config": cfg,
        "dry_run": resolve_trade_dry_run(
            explicit_live=bool(getattr(args, "live", False)),
            explicit_dry_run=bool(getattr(args, "dry_run", False)),
            config=cfg,
        ),
        "use_real_data": bool(getattr(args, "real", False) or cfg.screening_mode == "pykrx"),
    }


async def run_pipeline(dry_run: bool = True, target_ticker: Optional[str] = None,
                       use_real_data: bool = False):
    proxy_started = False
    saved_openai_env: dict[str, str | None] = {}

    from runtime_config import load_runtime_config
    cfg = load_runtime_config()

    log.info("=" * 60)
    log.info("lecture-prism 파이프라인 시작")
    log.info(f"모드: {'시뮬레이션(dry-run)' if dry_run else '실거래'}")
    log.info(f"런타임 설정: {cfg.summary()}")
    log.info("=" * 60)

    try:
        proxy_started, saved_openai_env = await _maybe_start_chatgpt_oauth_proxy()

        # Step 1: 스크리닝
        log.info("[1/4] 스크리닝 시작 — 전종목 필터링")
        from screening import run_screening
        candidates = await run_screening(target_ticker=target_ticker, use_real=use_real_data)
        log.info(f"      → 선정 종목: {candidates}")

        if not candidates:
            log.info("선정 종목 없음. 파이프라인 종료.")
            return

        # Step 2: 분석
        log.info("[2/4] 분석 파이프라인 시작")
        from analysis import run_analysis
        analyses = []
        for ticker in candidates:
            log.info(f"      → {ticker} 분석 중...")
            result = await run_analysis(ticker)
            analyses.append(result)
            log.info(f"      → {ticker} 완료: 추천={result['recommendation']}({result['decision']}), "
                     f"매수점수={result['buy_score']}/10, 목표가={result['target_price']:,}원")

        from report_writer import write_reports
        report_paths = await asyncio.to_thread(write_reports, analyses)
        if report_paths:
            joined = ", ".join(str(path) for path in report_paths)
            log.info(f"      → 분석 보고서 저장: {joined}")

        # Step 3: 매매
        log.info("[3/4] 매매 의사결정 시작")
        from trading import run_trading
        trade_results = await run_trading(analyses, dry_run=dry_run)
        log.info(f"      → 체결 건수: {len(trade_results)}")

        # Step 4: 피드백
        log.info("[4/4] 피드백 & 매매일지 기록")
        from feedback import run_feedback
        await run_feedback(trade_results, analyses)
        log.info("      → 매매일지 저장 완료")

        log.info("=" * 60)
        log.info("파이프라인 완료")
        log.info(f"대시보드: http://localhost:8080")
        log.info("=" * 60)
    finally:
        if proxy_started:
            try:
                from cores.chatgpt_proxy import stop_proxy
                await stop_proxy()
            finally:
                _restore_openai_env(saved_openai_env)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="lecture-prism 자동매매 시스템")
    parser.add_argument("--dry-run", action="store_true", help="시뮬레이션 모드로 강제 실행")
    parser.add_argument("--live", action="store_true", help="실거래 모드 (KIS API 필요)")
    parser.add_argument("--ticker", type=str, help="특정 종목 코드 (예: 005930)")
    parser.add_argument("--real", action="store_true", help="스크리닝에 pykrx 실데이터 사용 (기본: 데모값)")
    args = parser.parse_args()

    options = _resolve_runtime_options(args)
    asyncio.run(
        run_pipeline(
            dry_run=options["dry_run"],
            target_ticker=args.ticker,
            use_real_data=options["use_real_data"],
        )
    )
