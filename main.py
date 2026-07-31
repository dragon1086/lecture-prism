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
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


async def _notify(notifier, method_name: str, *args, **kwargs) -> bool:
    """Run one optional notification without changing pipeline outcomes."""

    method = getattr(notifier, method_name, None)
    if method is None:
        return False
    try:
        return bool(await method(*args, **kwargs))
    except Exception as exc:  # noqa: BLE001 - 외부 알림은 항상 fail-open
        log.warning("Discord %s 알림 실패: %s", method_name, type(exc).__name__)
        return False


def _resolve_runtime_options(args) -> dict:
    """Resolve CLI flags plus `.env` profile into pipeline options."""

    from runtime_config import load_runtime_config, resolve_trade_dry_run

    cfg = load_runtime_config(getattr(args, "profile", None))
    return {
        "config": cfg,
        "dry_run": resolve_trade_dry_run(
            explicit_live=bool(getattr(args, "live", False)),
            explicit_dry_run=bool(getattr(args, "dry_run", False)),
            config=cfg,
        ),
        "use_real_data": bool(
            cfg.profile not in {"classroom", "backtest"}
            and (getattr(args, "real", False) or cfg.screening_mode == "real")
        ),
    }


async def run_pipeline(dry_run: bool = True, target_ticker: Optional[str] = None,
                       use_real_data: bool = False, config=None, notifier=None):
    from runtime_config import load_runtime_config, runtime_config_scope

    cfg = config or load_runtime_config()
    with runtime_config_scope(cfg):
        return await _run_pipeline_scoped(
            dry_run=dry_run,
            target_ticker=target_ticker,
            use_real_data=use_real_data,
            config=cfg,
            notifier=notifier,
        )


async def _run_pipeline_scoped(
    dry_run: bool = True,
    target_ticker: Optional[str] = None,
    use_real_data: bool = False,
    config=None,
    notifier=None,
):
    from runtime_config import load_runtime_config
    cfg = config or load_runtime_config()
    if notifier is None:
        from notifications import build_notifier

        notifier = build_notifier()
    if cfg.profile in {"classroom", "backtest"}:
        dry_run = True
        use_real_data = False

    log.info("=" * 60)
    log.info("lecture-prism 파이프라인 시작")
    log.info(f"모드: {'시뮬레이션(dry-run)' if dry_run else '실거래'}")
    log.info(f"런타임 설정: {cfg.summary()}")
    log.info("=" * 60)

    if cfg.profile == "classroom":
        from db import DB_PATH
        from prism_core.classroom import run_classroom_replay

        summary = await asyncio.to_thread(run_classroom_replay, DB_PATH)
        log.info("classroom replay 완료: %s", summary)
        return summary

    # Step 1: 스크리닝
    log.info("[1/4] 스크리닝 시작 — 전종목 필터링")
    from screening import run_screening
    candidates = await run_screening(target_ticker=target_ticker, use_real=use_real_data)
    log.info(f"      → 선정 종목: {candidates}")
    await _notify(
        notifier,
        "screening",
        candidates,
        data_mode=cfg.data_mode,
        use_real_data=use_real_data,
    )

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
                 f"매수점수={result['buy_score']}/10, 목표가={result['target_price']:,}")
        await _notify(notifier, "analysis", result)

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
    await _notify(notifier, "trading", analyses, trade_results)

    # Step 4: 피드백
    log.info("[4/4] 피드백 & 매매일지 기록")
    from feedback import run_feedback
    await run_feedback(trade_results, analyses)
    log.info("      → 매매일지 저장 완료")
    await _notify(notifier, "summary", analyses, trade_results)

    log.info("=" * 60)
    log.info("파이프라인 완료")
    log.info("대시보드: http://localhost:8080")
    log.info("=" * 60)


def _build_arg_parser() -> argparse.ArgumentParser:
    from runtime_config import PROFILE_CHOICES

    parser = argparse.ArgumentParser(description="lecture-prism 자동매매 시스템")
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        help="런타임 프로필 (환경변수 LECTURE_PROFILE보다 우선)",
    )
    parser.add_argument("--dry-run", action="store_true", help="시뮬레이션 모드로 강제 실행")
    parser.add_argument("--live", action="store_true", help="실거래 모드 (KIS API 필요)")
    parser.add_argument("--ticker", type=str, help="특정 종목 코드 (예: 005930)")
    parser.add_argument("--real", action="store_true", help="스크리닝에 yfinance 실데이터 사용 (기본: 데모값)")
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()

    options = _resolve_runtime_options(args)
    asyncio.run(
        run_pipeline(
            dry_run=options["dry_run"],
            target_ticker=args.ticker,
            use_real_data=options["use_real_data"],
            config=options["config"],
        )
    )
