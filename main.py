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
import uuid
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
        "use_real_data": bool(getattr(args, "real", False) or cfg.screening_mode == "real"),
    }


async def run_pipeline(dry_run: bool = True, target_ticker: Optional[str] = None,
                       use_real_data: bool = False, dispatcher=None):
    proxy_started = False
    saved_openai_env: dict[str, str | None] = {}

    from runtime_config import load_runtime_config
    from notifications import PipelineEvent, build_notification_dispatcher
    import db

    cfg = load_runtime_config()
    dispatcher = dispatcher or build_notification_dispatcher()
    dispatcher_started = False
    run_id = uuid.uuid4().hex
    sequence = 0
    current_stage = "startup"
    trade_state = "simulation" if dry_run else cfg.trade_mode
    data_source = "mock" if cfg.data_mode == "mock" else None
    data_as_of = None
    market_status = "simulation" if dry_run else "unknown"

    async def emit(
        event_type: str,
        *,
        status: str = "succeeded",
        ticker: str | None = None,
        summary: str = "",
        details: dict[str, object] | None = None,
    ) -> PipelineEvent:
        nonlocal sequence
        sequence += 1
        event = PipelineEvent(
            run_id=run_id,
            sequence=sequence,
            event_type=event_type,
            status=status,
            profile=cfg.profile,
            trade_state=trade_state,
            data_source=data_source,
            data_as_of=data_as_of,
            ticker=ticker,
            summary=summary,
            details=details or {},
        )
        db.save_pipeline_event(
            {
                "run_id": event.run_id,
                "sequence": event.sequence,
                "occurred_at": event.occurred_at,
                "event_type": event.event_type,
                "status": event.status,
                "ticker": event.ticker,
                "summary": event.summary,
                "details": event.details,
            }
        )
        if dispatcher_started:
            try:
                await dispatcher.enqueue(event)
            except Exception:  # noqa: BLE001 - 알림은 파이프라인을 중단하지 않는다
                log.warning("알림 큐 등록 실패 — 파이프라인은 계속 진행합니다.")
        return event

    log.info("=" * 60)
    log.info("lecture-prism 파이프라인 시작")
    log.info(f"모드: {'시뮬레이션(dry-run)' if dry_run else '실거래'}")
    log.info(f"런타임 설정: {cfg.summary()}")
    log.info("=" * 60)

    try:
        try:
            await dispatcher.start()
            dispatcher_started = True
        except Exception:  # noqa: BLE001 - 알림은 선택 기능이다
            log.warning("알림 dispatcher 시작 실패 — 알림 없이 계속 진행합니다.")

        db.start_pipeline_run(
            {
                "run_id": run_id,
                "profile": cfg.profile,
                "trade_state": trade_state,
                "data_source": data_source,
                "data_as_of": data_as_of,
                "market_status": market_status,
            }
        )
        await emit("pipeline.started", summary="파이프라인을 시작합니다.")
        proxy_started, saved_openai_env = await _maybe_start_chatgpt_oauth_proxy()

        # Step 1: 스크리닝
        current_stage = "screening"
        log.info("[1/4] 스크리닝 시작 — 전종목 필터링")
        await emit("screening.started", summary="종목 스크리닝을 시작합니다.")
        from screening import run_screening
        candidates = await run_screening(target_ticker=target_ticker, use_real=use_real_data)
        log.info(f"      → 선정 종목: {candidates}")
        await emit(
            "screening.completed",
            summary=f"후보 종목 {len(candidates)}개를 선정했습니다.",
            details={"candidate_count": len(candidates)},
        )

        if not candidates:
            log.info("선정 종목 없음. 파이프라인 종료.")
            await emit(
                "pipeline.completed",
                summary="선정 종목 없이 파이프라인을 정상 종료했습니다.",
                details={"candidate_count": 0},
            )
            db.finish_pipeline_run(run_id, "succeeded")
            return

        # Step 2: 분석
        current_stage = "analysis"
        log.info("[2/4] 분석 파이프라인 시작")
        await emit(
            "analysis.started",
            summary=f"후보 종목 {len(candidates)}개 분석을 시작합니다.",
            details={"candidate_count": len(candidates)},
        )
        from analysis import run_analysis
        analyses = []
        for ticker in candidates:
            log.info(f"      → {ticker} 분석 중...")
            result = await run_analysis(ticker)
            result["run_id"] = run_id
            analyses.append(result)
            result_data_source = result.get("data_source")
            if result_data_source is not None:
                data_source = result_data_source
                data_as_of = result.get("data_as_of")
                db.update_pipeline_run_provenance(
                    run_id,
                    data_source=data_source,
                    data_as_of=data_as_of,
                )
            log.info(f"      → {ticker} 완료: 추천={result['recommendation']}({result['decision']}), "
                     f"매수점수={result['buy_score']}/10, 목표가={result['target_price']:,}원")
            await emit(
                "analysis.completed",
                ticker=ticker,
                summary=f"{ticker} 분석을 완료했습니다.",
                details={
                    "recommendation": result.get("recommendation"),
                    "buy_score": result.get("buy_score"),
                },
            )

        from report_writer import write_reports
        report_paths = await asyncio.to_thread(write_reports, analyses)
        if report_paths:
            joined = ", ".join(str(path) for path in report_paths)
            log.info(f"      → 분석 보고서 저장: {joined}")

        # Step 3: 매매
        current_stage = "trading"
        log.info("[3/4] 매매 의사결정 시작")
        await emit("trading.started", summary="매매 의사결정을 시작합니다.")
        from trading import run_trading
        trade_results = await run_trading(analyses, dry_run=dry_run)
        for trade_result in trade_results:
            trade_result.setdefault("run_id", run_id)
            broker_market_status = trade_result.get("market_status")
            if broker_market_status:
                market_status = str(broker_market_status)
                db.update_pipeline_run_market_status(run_id, market_status)
            order_status = str(
                trade_result.get("status")
                or ("filled" if trade_result.get("executed") else "decision_only")
            ).lower()
            requested_qty = int(
                trade_result.get("requested_qty")
                or trade_result.get("quantity")
                or 0
            )
            filled_qty = int(
                trade_result.get("filled_qty")
                or (requested_qty if trade_result.get("executed") else 0)
            )
            await emit(
                "order.status",
                status="failed" if order_status == "rejected" else "completed",
                ticker=trade_result.get("ticker"),
                summary=(
                    f"{trade_result.get('ticker', '종목')} 주문 상태: {order_status}"
                ),
                details={
                    "action": trade_result.get("action"),
                    "order_status": order_status,
                    "requested_qty": requested_qty,
                    "filled_qty": filled_qty,
                    "remaining_qty": int(
                        trade_result.get("remaining_qty")
                        if trade_result.get("remaining_qty") is not None
                        else max(0, requested_qty - filled_qty)
                    ),
                    "mode": trade_result.get("mode"),
                    "market_status": broker_market_status,
                },
            )
        log.info(f"      → 매매 결과 건수: {len(trade_results)}")
        await emit(
            "trading.completed",
            summary=f"매매 결과 {len(trade_results)}건을 처리했습니다.",
            details={"trade_count": len(trade_results)},
        )

        # Step 4: 피드백
        current_stage = "feedback"
        log.info("[4/4] 피드백 & 매매일지 기록")
        await emit("feedback.started", summary="피드백 기록을 시작합니다.")
        from feedback import run_feedback
        await run_feedback(trade_results, analyses)
        log.info("      → 매매일지 저장 완료")
        await emit("feedback.completed", summary="피드백과 매매일지를 저장했습니다.")

        await emit("pipeline.completed", summary="파이프라인을 정상 완료했습니다.")
        db.finish_pipeline_run(run_id, "succeeded")

        log.info("=" * 60)
        log.info("파이프라인 완료")
        log.info(f"대시보드: http://localhost:8080")
        log.info("=" * 60)
    except Exception as exc:
        try:
            await emit(
                "pipeline.failed",
                status="failed",
                summary=f"{current_stage} 단계에서 파이프라인이 실패했습니다.",
                details={"failure_stage": current_stage, "error_type": type(exc).__name__},
            )
            db.finish_pipeline_run(run_id, "failed", failure_stage=current_stage)
        except Exception:  # noqa: BLE001 - 원래 예외를 보존한다
            log.warning("파이프라인 실패 상태를 저장하지 못했습니다.")
        raise
    finally:
        try:
            await dispatcher.close(timeout=5.0)
        except Exception:  # noqa: BLE001 - 알림 종료 실패도 fail-open
            log.warning("알림 dispatcher 종료 실패 — 파이프라인 결과는 유지합니다.")
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
    parser.add_argument("--real", action="store_true", help="스크리닝에 yfinance 실데이터 사용 (기본: 데모값)")
    args = parser.parse_args()

    options = _resolve_runtime_options(args)
    asyncio.run(
        run_pipeline(
            dry_run=options["dry_run"],
            target_ticker=args.ticker,
            use_real_data=options["use_real_data"],
        )
    )
