"""
feedback.py — 모듈 4: 피드백 & 메모리 시스템

매매 결과 → 교훈 추출 → 단기/중기/장기 메모리 저장.
"인간 투자자의 매매일지와 동일한 구조"

메모리 계층은 memory.py가 승격합니다:
  - 단기 (0~7일): 청산 뒤 남긴 상세 교훈
  - 중기 (8~30일): 한 번 더 검토할 교훈
  - 장기 (31일+): 반복된 교훈에서만 추린 원칙

실행:
    python feedback.py    # 최근 매매일지 조회
"""

import asyncio
import logging

import db

log = logging.getLogger(__name__)


async def run_feedback(trade_results: list[dict], analyses: list[dict]) -> None:
    """
    매매 완료 후 피드백 저장.

    분석 결과·매매 결과·추출 교훈을 모두 공용 DB(prism.db)에 기록합니다.
    → dashboard.py가 이 데이터를 읽어 화면에 표시합니다 (피드백 루프 연결).

    Args:
        trade_results: trading.py의 run_trading() 결과
        analyses: analysis.py의 run_analysis() 결과들
    """
    # 분석 결과는 체결 여부와 무관하게 전부 기록 (PASS도 의사결정 이력)
    for analysis in analyses:
        db.save_analysis(analysis)

    if not trade_results:
        log.info("  오늘 체결 내역 없음. 분석 이력만 기록하고 피드백 스킵.")
        return

    # 체결된 종목만 분석 결과와 매칭 (PASS 종목은 trade_results에 없음)
    analysis_by_ticker = {a["ticker"]: a for a in analyses}

    for result in trade_results:
        if not (
            result.get("status") == "filled"
            and result.get("executed") is True
            and int(result.get("filled_qty") or 0) > 0
        ):
            log.info(
                "  [%s] 미체결/진행 중 주문은 매매일지와 교훈에서 제외: %s",
                result.get("ticker", "?"),
                result.get("status", "unknown"),
            )
            continue
        analysis = analysis_by_ticker.get(result["ticker"], {})

        # 매매 내역 저장
        db.save_trade(result)

        # 신규 매수 직후에는 성패를 아직 알 수 없다. 진입 근거는 분석·매매
        # 기록에 남기고, 판단 교훈은 포지션이 끝난 SELL 이후에 만든다.
        if result.get("action") == "BUY":
            log.info(
                "  [%s] 신규 진입 기록 완료 — 결과 교훈은 청산 뒤 생성",
                result["ticker"],
            )
            continue

        # 판단 오류 vs 실행 오류 분류
        error_type = _classify_error(result, analysis)

        # 교훈 추출
        lesson = await _extract_lesson(result, analysis, error_type)

        # 메모리 저장
        await _save_to_memory(result, lesson, error_type, tier="short")

        log.info(f"  [{result['ticker']}] 매매일지 저장: {lesson[:50]}...")


def _classify_error(result: dict, analysis: dict) -> str:
    """
    판단 오류 vs 실행 오류 분류.

    - 판단 오류: 분석은 맞았는데 결과가 나빴다 → 에이전트 프롬프트 개선 필요
    - 실행 오류: 체결 문제, API 오류 → 매매 로직 개선 필요
    """
    _ = result, analysis  # TODO: 실제 분류 로직 구현
    if not result.get("executed", False):
        return "EXECUTION_ERROR"
    return "JUDGMENT"  # 기본값: 판단 결과로 분류


async def _extract_lesson(result: dict, analysis: dict, error_type: str) -> str:
    """
    교훈 추출.

    TODO(파트4 실습): 실제 LLM 호출로 교체 — "이 매매에서 무엇을 배울 수 있는가?"
    현재는 분석 근거를 활용한 규칙 기반 요약 (LLM 없이도 동작).
    """
    ticker = result["ticker"]
    action = result["action"]
    reason = analysis.get("rationale") or analysis.get("reason", "근거 미기록")

    if error_type == "EXECUTION_ERROR":
        return f"{ticker} {action}: 체결 실패. 분석 판단보다 주문 실행 경로(가격/타이밍) 점검 필요."
    if all(
        analysis.get(key) is not None
        for key in ("buy_score", "risk_reward_ratio", "stop_loss")
    ):
        return (
            f"{ticker} {action}: 다음에도 매수점수 {analysis['buy_score']}/10, "
            f"손익비 {analysis['risk_reward_ratio']}:1, "
            f"손절가 {int(analysis['stop_loss']):,}원을 함께 확인하고 "
            "진입 근거와 판단을 다시 볼 조건을 기록한다."
        )
    return f"{ticker} {action}: 진입 근거 = {reason} 시장 전체 하락 시 연동 리스크 모니터링."


async def _save_to_memory(result: dict, lesson: str,
                          error_type: str = "JUDGMENT", tier: str = "short") -> None:
    """
    메모리 계층(prism.db)에 저장.

    tier: "short" (당일) | "medium" (주간) | "long" (월간)
    → dashboard.py의 feedback_lessons 테이블에 그대로 표시됨.
    """
    db.save_lesson(
        ticker=result["ticker"],
        action=result["action"],
        lesson=lesson,
        tier=tier,
        error_type=error_type,
    )
    log.debug(f"  메모리 저장 [{tier}/{error_type}]: {result['ticker']}")


async def get_recent_lessons(n: int = 5) -> list[str]:
    """
    최근 N개 교훈 조회 (다음 매매 프롬프트에 주입용).

    DB에 교훈이 쌓이기 전(첫 실행)에는 기본 시드 교훈을 반환합니다.
    """
    lessons = db.get_recent_lessons(n)
    if lessons:
        return lessons

    # DB가 비어있을 때 폴백 (첫 실행 시연용)
    return [
        "거래량 급등 시 분할 매수가 일괄 매수보다 안정적",
        "뉴스 촉매 없는 기술적 돌파는 신뢰도 낮음",
        "외국인 순매수 동반 시 성공률 높음",
    ][:n]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    async def main():
        lessons = await get_recent_lessons()
        print("\n최근 매매 교훈:")
        for i, lesson in enumerate(lessons, 1):
            print(f"  {i}. {lesson}")

    asyncio.run(main())
