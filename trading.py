"""
trading.py — 모듈 3: 매매 실행

분석 결과 → 포지션 사이징 → KIS API 주문 → 결과 기록.
의사결정 트리: 얼마를 살 것인가 / 어떻게 살 것인가 / 체결 안 되면?

실행:
    python trading.py --dry-run    # 시뮬레이션 (기본)
    python trading.py --live       # 실거래 (KIS API 필요)
"""

import asyncio
import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── 포트폴리오 설정 ──────────────────────────────────────────────
MAX_SLOTS = 10              # 최대 보유 종목 수
MAX_SAME_SECTOR = 3         # 동일 섹터 최대 보유 수
CASH_RESERVE_RATIO = 0.7    # 현금 비중 (70% 유지)
BUY_SCORE_THRESHOLD = 4     # 매수 최소 점수 (5점 만점)

# ── 손절 기준 ─────────────────────────────────────────────────────
STOP_LOSS = {
    "default": -0.07,       # 기본 손절 -7%
    "volume_surge": -0.07,  # 거래량 급등 진입 시
    "intraday_surge": -0.05, # 당일 급등 진입 시
}

# ── 청산 기준 (파트4 '청산 조건' 트랙에서 수강생이 수정) ────────────────
# 추세추종 관점: 목표가는 마일스톤, 트레일링 스탑으로 수익을 보호.
TAKE_PROFIT = 0.15      # 목표가 +15% 도달 시 청산 신호
TRAILING_STOP = 0.08    # 고점 대비 -8% 되돌림 시 트레일링 스탑


async def run_trading(analyses: list[dict], dry_run: bool = True) -> list[dict]:
    """
    분석 결과 목록을 받아 매매 의사결정 및 주문 실행.

    Args:
        analyses: analysis.py의 run_analysis() 결과 목록
        dry_run: True면 시뮬레이션, False면 실거래

    Returns:
        체결된 매매 결과 목록
    """
    portfolio = await _get_current_portfolio()
    results = []

    for analysis in analyses:
        decision = _decide_position(analysis, portfolio)
        if decision is None:
            log.info(f"  [{analysis['ticker']}] 매수 조건 미충족 — 패스")
            continue

        log.info(f"  [{analysis['ticker']}] {decision['action']} 결정: {decision['quantity']}주 @ {decision['price']:,}원")

        if dry_run:
            result = _simulate_trade(decision)
            log.info(f"  [{analysis['ticker']}] [시뮬레이션] 체결 완료")
        else:
            result = await _execute_kis_order(decision)

        results.append(result)

    return results


def _decide_position(analysis: dict, portfolio: dict) -> Optional[dict]:
    """
    포지션 사이징 및 매수 여부 결정.

    파트4 트랙D에서 수강생이 이 로직을 수정하는 부분.
    """
    # 점수 기준 필터
    if analysis["score"] < BUY_SCORE_THRESHOLD:
        return None

    # 슬랏 여유 확인
    if portfolio["slots_used"] >= MAX_SLOTS:
        log.warning("슬랏이 모두 차있습니다.")
        return None

    # 현금 여유 확인
    available_cash = portfolio["cash"] * (1 - CASH_RESERVE_RATIO)
    if available_cash < 100_000:
        return None

    # 포지션 사이징: 가용 현금을 남은 슬랏으로 균등 배분
    remaining_slots = MAX_SLOTS - portfolio["slots_used"]
    per_slot_amount = available_cash / max(remaining_slots, 1)

    # TODO: 실제 현재가 조회 (KIS API)
    current_price = 70_000  # 예시: 삼성전자 7만원
    quantity = int(per_slot_amount / current_price)

    if quantity <= 0:
        return None

    return {
        "action": "BUY",
        "ticker": analysis["ticker"],
        "quantity": quantity,
        "price": current_price,
        "reason": analysis["reason"],
        "stop_loss": STOP_LOSS["default"],
    }


def _decide_exit(holding: dict, current_price: float) -> Optional[dict]:
    """
    보유 종목 청산 판단. 파트4 '청산 조건' 트랙의 교체 대상.

    holding: {"ticker", "entry_price", "high_since_entry"(선택), "stop_loss"(선택)}
    추세추종 관점에서 손절 → 트레일링 스탑 → 목표가 순으로 점검합니다.
    """
    entry = holding["entry_price"]
    high = holding.get("high_since_entry", max(entry, current_price))
    stop = holding.get("stop_loss", STOP_LOSS["default"])
    pnl = (current_price - entry) / entry

    # 1) 손절: 진입가 대비 일정 % 하락
    if pnl <= stop:
        return _exit(holding, current_price, f"손절 ({pnl:+.1%})")

    # 2) 트레일링 스탑: 수익 구간에서 고점 대비 되돌림
    drawdown = (current_price - high) / high
    if pnl > 0 and drawdown <= -TRAILING_STOP:
        return _exit(holding, current_price, f"트레일링 스탑 (고점比 {drawdown:+.1%})")

    # 3) 목표가 마일스톤 도달
    if pnl >= TAKE_PROFIT:
        return _exit(holding, current_price, f"목표가 도달 ({pnl:+.1%})")

    return None  # 보유 지속


def _exit(holding: dict, price: float, reason: str) -> dict:
    return {"action": "SELL", "ticker": holding["ticker"], "price": price, "reason": reason}


async def run_exit_check(holdings: list[dict], price_map: dict) -> list[dict]:
    """보유 종목 청산 여부 일괄 점검. price_map: {ticker: 현재가}."""
    decisions = []
    for h in holdings:
        price = price_map.get(h["ticker"], h["entry_price"])
        decision = _decide_exit(h, price)
        if decision:
            log.info(f"  [{h['ticker']}] 청산 신호: {decision['reason']} @ {price:,.0f}원")
            decisions.append(decision)
        else:
            log.info(f"  [{h['ticker']}] 보유 지속")
    return decisions


def _simulate_trade(decision: dict) -> dict:
    """시뮬레이션 체결 (dry-run 모드)."""
    return {
        **decision,
        "executed": True,
        "executed_price": decision["price"],
        "mode": "simulation",
        "pnl": None,
    }


async def _execute_kis_order(decision: dict) -> dict:
    """
    KIS API 실주문 실행.

    강의용 안전장치:
    - 기본값은 절대 주문하지 않고 "live_blocked"를 반환합니다.
    - 원본 PRISM의 KIS 모듈은 `trading/trading/domestic_stock_trading.py`에
      그대로 포함되어 있으므로, 강사/심화 실습에서 명시적으로 플래그를 켜면
      모의투자(demo) 브리지로만 연결합니다.
    - 실전투자(real)는 별도 이중 플래그가 있어야 하며 초보 실습에서는 쓰지 않습니다.

    주문 유형 선택 로직:
    - 장중: 지정가 주문 (current_price 기준)
    - 장외: 예약주문 (다음 날 시초가)
    - 미체결 처리: N분 후 재주문 or 포기
    """
    log.warning("  실거래 요청 감지: 기본 강의 모드에서는 KIS 주문을 차단합니다.")

    if os.getenv("LECTURE_ENABLE_LIVE_KIS") != "1":
        return {
            **decision,
            "executed": False,
            "executed_price": None,
            "mode": "live_blocked",
            "pnl": None,
            "message": "KIS 주문 차단: LECTURE_ENABLE_LIVE_KIS=1 없이는 주문하지 않습니다.",
        }

    kis_mode = os.getenv("LECTURE_KIS_MODE", "demo").strip().lower()
    if kis_mode == "real" and os.getenv("LECTURE_ALLOW_REAL_KIS") != "1":
        return {
            **decision,
            "executed": False,
            "executed_price": None,
            "mode": "real_blocked",
            "pnl": None,
            "message": "실전투자 차단: LECTURE_ALLOW_REAL_KIS=1 없이는 real 모드를 쓰지 않습니다.",
        }
    if kis_mode not in {"demo", "real"}:
        kis_mode = "demo"

    try:
        module_dir = Path(__file__).resolve().parent / "trading" / "trading"
        if str(module_dir) not in sys.path:
            sys.path.insert(0, str(module_dir))
        domestic = importlib.import_module("domestic_stock_trading")
        AsyncTradingContext = domestic.AsyncTradingContext
    except Exception as e:  # noqa: BLE001 — 강의용 브리지는 실패 사유를 결과로 돌려줌
        return {
            **decision,
            "executed": False,
            "executed_price": None,
            "mode": "kis_import_failed",
            "pnl": None,
            "message": f"KIS 모듈 로드 실패: {e}",
        }

    buy_amount = int(decision["quantity"] * decision["price"])
    try:
        async with AsyncTradingContext(mode=kis_mode, buy_amount=buy_amount) as trader:
            kis_result = await trader.async_buy_stock(
                stock_code=decision["ticker"],
                buy_amount=buy_amount,
                limit_price=int(decision["price"]),
            )
    except Exception as e:  # noqa: BLE001 — 인증/네트워크 실패도 초보자에게 설명 가능해야 함
        return {
            **decision,
            "executed": False,
            "executed_price": None,
            "mode": f"kis_{kis_mode}_failed",
            "pnl": None,
            "message": f"KIS 주문 실패: {e}",
        }

    return {
        **decision,
        "executed": bool(kis_result.get("success")),
        "executed_price": kis_result.get("current_price") or decision["price"],
        "mode": f"kis_{kis_mode}",
        "pnl": None,
        "order_no": kis_result.get("order_no"),
        "message": kis_result.get("message", ""),
        "kis_result": kis_result,
    }


async def _get_current_portfolio() -> dict:
    """현재 포트폴리오 조회. TODO: DB 연동."""
    return {
        "cash": 10_000_000,   # 예시: 1천만원
        "slots_used": 3,       # 현재 3종목 보유 중
        "holdings": [],
    }


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--exit", action="store_true", help="청산(매도) 로직 데모")
    args = parser.parse_args()

    if args.exit:
        # 손절 / 트레일링 스탑 / 목표가 — 세 가지 청산 시나리오 시연
        sample_holdings = [
            {"ticker": "005930", "entry_price": 70_000, "high_since_entry": 82_000},   # 트레일링
            {"ticker": "000660", "entry_price": 120_000, "high_since_entry": 121_000},  # 손절
            {"ticker": "035420", "entry_price": 200_000, "high_since_entry": 235_000},  # 목표가
        ]
        sample_prices = {"005930": 75_000, "000660": 110_000, "035420": 232_000}
        results = asyncio.run(run_exit_check(sample_holdings, sample_prices))
        print(f"\n청산 결정: {results}")
    else:
        sample_analyses = [
            {"ticker": "005930", "recommendation": "BUY", "score": 4, "reason": "테스트", "risk": "없음"},
        ]
        results = asyncio.run(run_trading(sample_analyses, dry_run=not args.live))
        print(f"\n체결 결과: {results}")
