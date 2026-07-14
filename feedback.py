"""
feedback.py — 모듈 4: 피드백 & 메모리 시스템

매매 결과 → 교훈 추출 → 단기/중기/장기 메모리 저장.
"인간 투자자의 매매일지와 동일한 구조"

메모리 계층:
  - 단기 (당일): 오늘 매매 패턴, 체결 이슈
  - 중기 (주간): 섹터 트렌드, 반복 패턴
  - 장기 (월간): 시장 체제 판단, 전략 수정 이력

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
        analysis = analysis_by_ticker.get(result["ticker"], {})

        status = str(result.get("status") or "").lower()
        is_simulation_fill = (
            result.get("mode") == "simulation" and result.get("executed") is True
        )
        is_broker_fill = status == "filled" and result.get("executed") is True
        if not (is_simulation_fill or is_broker_fill):
            log.info(
                "  [%s] 주문 상태 %s — 체결 완료 전까지 매매일지/보유내역에 반영하지 않습니다.",
                result["ticker"],
                status or "pending",
            )
            continue

        # 매매 내역 저장
        completed = dict(result)
        if is_broker_fill:
            completed["quantity"] = int(result.get("filled_qty", 0) or 0)
            completed["executed_price"] = (
                result.get("avg_fill_price") or result.get("executed_price")
            )
        db.save_trade(completed)

        # 판단 오류 vs 실행 오류 분류
        error_type = _classify_error(completed, analysis)

        # 교훈 추출
        lesson = await _extract_lesson(completed, analysis, error_type)

        # 메모리 저장
        await _save_to_memory(completed, lesson, error_type, tier="short")

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
