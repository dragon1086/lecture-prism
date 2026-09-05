"""
trading.py — 모듈 3: 매매 실행

매수 에이전트 시나리오 → 안전 검증 → 포지션 사이징 → 선택 브로커 주문.
의사결정 트리: 얼마를 살 것인가 / 어떻게 살 것인가 / 체결 안 되면?

실행:
    python trading.py --dry-run    # 시뮬레이션 (기본)
    python trading.py --live       # 실거래 (KIS API 필요)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

log = logging.getLogger(__name__)

# ── 포트폴리오 설정 ──────────────────────────────────────────────
MAX_SLOTS = 10              # 최대 보유 종목 수
CASH_RESERVE_RATIO = 0.7    # 현금 비중 (70% 유지)
BUY_SCORE_THRESHOLD = 6     # 매수 최소 점수 (10점 만점, buy_agent.MIN_BUY_SCORE와 동일 기준)
MIN_RISK_REWARD_RATIO = 1.5 # 신규 진입에 필요한 최소 손익비
RISK_PER_TRADE = 0.01       # 한 거래에서 계좌자산의 1%까지만 위험에 노출
ATR_STOP_MULTIPLE = 2.0     # ATR 두 배를 초기 손절 폭으로 사용

_REGIME_ENTRY_LIMITS = {
    "strong": {"min_score": BUY_SCORE_THRESHOLD, "min_rr": MIN_RISK_REWARD_RATIO, "max_slots": MAX_SLOTS},
    "sideways": {"min_score": BUY_SCORE_THRESHOLD, "min_rr": MIN_RISK_REWARD_RATIO, "max_slots": 8},
    "weak": {"min_score": 8, "min_rr": 2.0, "max_slots": 5},
}

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
TURTLE_EXIT_DAYS = 10   # 최근 N일 저가 이탈 시 추세 종료
EXIT_QUOTE_MAX_AGE = timedelta(minutes=5)


async def run_trading(analyses: list[dict], dry_run: bool = True) -> list[dict]:
    """
    매수 에이전트의 진입 시나리오 목록을 받아 검증하고 주문을 실행.

    Args:
        analyses: buy_agent.py의 run_buy_agent() 결과 목록
        dry_run: True면 시뮬레이션, False면 실거래

    Returns:
        체결된 매매 결과 목록
    """
    results = []

    # 기존 보유분의 청산을 먼저 판단한다. 같은 실행에서 매도 신호가 난
    # 종목을 곧바로 다시 사지 않도록 청산 종목을 신규 진입에서 제외한다.
    holdings = await _get_exit_holdings()
    price_map = await _load_holding_prices(holdings, dry_run=dry_run)
    await _persist_holding_highs(holdings, price_map)
    exit_decisions = await run_exit_check(holdings, price_map)
    held_tickers = {holding["ticker"] for holding in holdings}
    exited_tickers = {decision["ticker"] for decision in exit_decisions}
    for decision in exit_decisions:
        results.append(await _execute_decision(decision, dry_run=dry_run))

    portfolio = await _get_current_portfolio()

    for analysis in analyses:
        if analysis["ticker"] in exited_tickers:
            log.info("  [%s] 이번 실행에서 청산 판단 — 재진입 보류", analysis["ticker"])
            continue
        if analysis["ticker"] in held_tickers:
            log.info("  [%s] 이미 보유 중 — 추가 매수 보류", analysis["ticker"])
            continue
        candidate = dict(analysis)
        try:
            from memory import get_relevant_memories

            candidate["memory_lessons"] = await asyncio.to_thread(
                get_relevant_memories,
                analysis["ticker"],
                analysis.get("sector", ""),
            )
        except Exception as exc:  # noqa: BLE001 - 기억 조회 실패가 매매 본체를 막지 않음
            log.warning(
                "  [%s] 과거 교훈 조회 실패 — 현재 근거만 사용: %s",
                analysis["ticker"],
                type(exc).__name__,
            )
            candidate["memory_lessons"] = []
        decision = _decide_position(candidate, portfolio)
        if decision is None:
            log.info(f"  [{analysis['ticker']}] 매수 조건 미충족 — 패스")
            continue

        log.info(f"  [{analysis['ticker']}] {decision['action']} 결정: {decision['quantity']}주 @ {decision['price']:,}원")

        results.append(await _execute_decision(decision, dry_run=dry_run))

    return results


async def _get_exit_holdings() -> list[dict]:
    """공용 매매일지에서 청산 점검 대상을 읽는다."""

    import db

    return await asyncio.to_thread(db.get_open_holdings)


async def _load_holding_prices(
    holdings: list[dict],
    *,
    dry_run: bool | None = None,
    broker_name: str | None = None,
) -> dict[str, float | dict]:
    """보유 종목 현재가를 읽되 실패한 종목은 청산 판단에서 보류한다."""

    if not holdings:
        return {}
    if _requires_broker_exit_quotes(dry_run, broker_name=broker_name):
        return await _load_broker_holding_prices(holdings, broker_name=broker_name)

    import data_source

    prices: dict[str, float | dict] = {}
    for holding in holdings:
        ticker = holding["ticker"]
        try:
            data = await asyncio.to_thread(data_source.fetch_stock_data, ticker)
            price = float(data.get("current_price") or 0)
        except Exception as exc:  # noqa: BLE001 - 가격 불명은 청산 보류
            log.warning("  [%s] 청산 가격 조회 실패 — 보유 지속: %s", ticker, type(exc).__name__)
            continue
        if price > 0:
            prices[ticker] = price
        else:
            log.warning("  [%s] 청산 가격 없음 — 보유 지속", ticker)
    return prices


def _requires_broker_exit_quotes(
    dry_run: bool | None, *, broker_name: str | None = None
) -> bool:
    if dry_run is not None:
        return dry_run is False
    if broker_name:
        return True
    profile = str(os.getenv("LECTURE_PROFILE") or os.getenv("PRISM_PROFILE") or "")
    normalized = profile.strip().lower().replace("-", "_")
    return normalized in {"paper", "paper_trade", "broker_demo", "live", "real", "prod"}


def _quote_block(ticker: str, *, mode: str, message: str) -> dict:
    return {
        "status": "blocked",
        "mode": mode,
        "ticker": ticker,
        "message": message,
        "operational_alert": True,
    }


async def _load_broker_holding_prices(
    holdings: list[dict], *, broker_name: str | None = None
) -> dict[str, float | dict]:
    """Load paper/live exit prices from the selected broker only."""

    from brokers.base import BrokerQuoteError, validate_broker_quote
    from brokers.factory import get_broker_adapter, selected_broker_name

    broker = (broker_name or selected_broker_name(default="kis")).strip().lower()
    try:
        adapter = get_broker_adapter(broker)
    except Exception as exc:  # noqa: BLE001 - fail closed on adapter uncertainty
        return {
            holding["ticker"]: _quote_block(
                holding["ticker"],
                mode="broker_quote_unavailable",
                message=f"{broker} quote adapter unavailable for {holding['ticker']}: {exc}",
            )
            for holding in holdings
        }

    get_quote = getattr(adapter, "get_quote", None)
    if get_quote is None:
        return {
            holding["ticker"]: _quote_block(
                holding["ticker"],
                mode="broker_quote_unavailable",
                message=f"{broker} adapter does not provide fresh quotes for {holding['ticker']}",
            )
            for holding in holdings
        }

    prices: dict[str, float | dict] = {}
    for holding in holdings:
        ticker = holding["ticker"]
        try:
            quote = await get_quote(ticker)
            validated = validate_broker_quote(
                quote,
                expected_ticker=ticker,
                now=datetime.now(timezone.utc),
                max_age=EXIT_QUOTE_MAX_AGE,
            )
        except BrokerQuoteError as exc:
            prices[ticker] = _quote_block(
                ticker,
                mode="broker_quote_invalid",
                message=f"{broker} quote rejected for {ticker}: {exc}",
            )
            continue
        except Exception as exc:  # noqa: BLE001 - no data-source fallback in broker mode
            prices[ticker] = _quote_block(
                ticker,
                mode="broker_quote_unavailable",
                message=f"{broker} quote unavailable for {ticker}: {exc}",
            )
            continue
        prices[ticker] = float(validated.price)
    return prices


def _numeric_price(value) -> float:
    if isinstance(value, dict) and value.get("status") == "blocked":
        return 0.0
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def _persist_holding_highs(
    holdings: list[dict], price_map: dict[str, float | dict]
) -> None:
    """현재가가 새 고점이면 다음 실행의 트레일링 판단을 위해 저장한다."""

    import db

    for holding in holdings:
        ticker = holding["ticker"]
        current_price = _numeric_price(price_map.get(ticker))
        if current_price <= 0:
            continue
        previous = float(
            holding.get("high_since_entry") or holding.get("entry_price") or 0
        )
        if current_price <= previous:
            continue
        holding["high_since_entry"] = current_price
        await asyncio.to_thread(db.update_holding_high, ticker, current_price)


async def _execute_decision(decision: dict, *, dry_run: bool) -> dict:
    """청산·진입 결정을 같은 안전 실행 경로로 처리한다."""

    if decision.get("status") == "blocked":
        return {
            **decision,
            "accepted": False,
            "executed": False,
            "terminal": True,
            "requested_qty": 0,
            "filled_qty": 0,
            "remaining_qty": 0,
            "executed_price": None,
            "pnl": None,
        }
    if dry_run:
        result = _simulate_trade(decision)
        log.info("  [%s] [시뮬레이션] %s 체결 완료", decision["ticker"], decision["action"])
        return result
    return await _execute_broker_order(decision)


def _decide_position(analysis: dict, portfolio: dict) -> Optional[dict]:
    """
    포지션 사이징 및 매수 여부 결정.

    파트4 트랙D에서 수강생이 이 로직을 수정하는 부분.
    """
    # buy_agent의 decision은 비구속적 시나리오다. 실제 주문 여부는
    # 이 함수가 추천·점수·가격 배열·포트폴리오 조건을 다시 검사해 결정한다.
    # 높은 점수 하나만으로 HOLD/PASS를 주문으로 바꾸지는 않는다.
    if analysis.get("recommendation") != "BUY":
        return None

    regime = str(analysis.get("market_regime") or "strong").strip().lower()
    limits = _REGIME_ENTRY_LIMITS.get(regime, _REGIME_ENTRY_LIMITS["strong"])

    # 매수 점수 필터 (0~10점, analysis가 산출한 buy_score)
    buy_score = analysis.get("buy_score", analysis.get("score", 0))
    if buy_score < limits["min_score"]:
        return None

    # 신규 진입의 가격 배열과 손익비는 주문을 결정하는 이 파일이 직접 검증한다.
    try:
        current_price = float(analysis["current_price"])
        target_price = float(analysis["target_price"])
        stop_loss = float(analysis["stop_loss"])
        risk_reward_ratio = float(analysis["risk_reward_ratio"])
    except (KeyError, TypeError, ValueError):
        log.info("  [%s] 가격·손익비 정보 부족 — 패스", analysis.get("ticker", "?"))
        return None
    atr = None
    if "atr" in analysis:
        try:
            atr = float(analysis["atr"])
        except (TypeError, ValueError):
            atr = 0.0
        if atr <= 0:
            log.info("  [%s] ATR 부족·비정상 — 패스", analysis.get("ticker", "?"))
            return None
        stop_loss = current_price - atr * ATR_STOP_MULTIPLE
        if stop_loss <= 0:
            log.info("  [%s] ATR 손절가 비정상 — 패스", analysis.get("ticker", "?"))
            return None
        risk_reward_ratio = (target_price - current_price) / (current_price - stop_loss)

    if not (
        target_price > current_price > stop_loss
        and risk_reward_ratio >= limits["min_rr"]
    ):
        log.info("  [%s] 가격 배열·손익비 기준 미충족 — 패스", analysis.get("ticker", "?"))
        return None

    # 슬랏 여유 확인
    max_slots = limits["max_slots"]
    if portfolio["slots_used"] >= max_slots:
        log.warning("슬랏이 모두 차있습니다.")
        return None

    # 현금 여유 확인
    available_cash = portfolio["cash"] * (1 - CASH_RESERVE_RATIO)
    if available_cash < 100_000:
        return None

    # 포지션 사이징: 가용 현금을 남은 슬랏으로 균등 배분
    remaining_slots = max_slots - portfolio["slots_used"]
    per_slot_amount = available_cash / max(remaining_slots, 1)

    # 현재가: analysis가 제공(종목별 mock 또는 LLM). 실데이터 연동 시 analysis.get_current_price만 교체.
    quantity = int(per_slot_amount / current_price)
    if atr is not None:
        account_assets = float(portfolio.get("equity") or portfolio["cash"])
        allowed_loss = account_assets * RISK_PER_TRADE
        one_share_risk = current_price - stop_loss
        risk_quantity = int(allowed_loss / one_share_risk)
        quantity = min(quantity, risk_quantity)

    if quantity <= 0:
        return None

    return {
        "action": "BUY",
        "ticker": analysis["ticker"],
        "quantity": quantity,
        "price": current_price,
        "reason": analysis.get("rationale") or analysis.get("reason", ""),
        "target_price": analysis.get("target_price"),
        "stop_loss": stop_loss,
        "memory_lessons": list(analysis.get("memory_lessons") or [])[:5],
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

    # 2) 터틀 청산: fixture나 데이터 공급자가 넘긴 직전 10일 저가 이탈
    recent_lows = holding.get("recent_lows") or []
    if len(recent_lows) >= TURTLE_EXIT_DAYS:
        ten_day_low = min(float(value) for value in recent_lows[-TURTLE_EXIT_DAYS:])
        if current_price < ten_day_low:
            return _exit(holding, current_price, f"10일 저가 이탈 ({ten_day_low:,.0f})")

    # 3) 트레일링 스탑: 수익 구간에서 고점 대비 되돌림
    drawdown = (current_price - high) / high
    if pnl > 0 and drawdown <= -TRAILING_STOP:
        return _exit(holding, current_price, f"트레일링 스탑 (고점比 {drawdown:+.1%})")

    # 4) 목표가 마일스톤 도달
    if pnl >= TAKE_PROFIT:
        return _exit(holding, current_price, f"목표가 도달 ({pnl:+.1%})")

    return None  # 보유 지속


def _exit(holding: dict, price: float, reason: str) -> dict:
    return {
        "action": "SELL",
        "ticker": holding["ticker"],
        "quantity": int(holding.get("quantity", 0)),
        "price": price,
        "reason": reason,
    }


def _blocked_exit(holding: dict, quote_block: dict) -> dict:
    return {
        "action": "BLOCKED_EXIT",
        "ticker": holding["ticker"],
        "quantity": int(holding.get("quantity", 0)),
        "price": None,
        "reason": quote_block["message"],
        "status": "blocked",
        "mode": quote_block["mode"],
        "message": quote_block["message"],
        "operational_alert": True,
    }


async def run_exit_check(holdings: list[dict], price_map: dict) -> list[dict]:
    """보유 종목 청산 여부 일괄 점검. price_map: {ticker: 현재가}."""
    decisions = []
    for h in holdings:
        price = price_map.get(h["ticker"], h["entry_price"])
        if isinstance(price, dict) and price.get("status") == "blocked":
            log.warning("  [%s] 청산 가격 차단: %s", h["ticker"], price["message"])
            decisions.append(_blocked_exit(h, price))
            continue
        decision = _decide_exit(h, price)
        if decision:
            log.info(f"  [{h['ticker']}] 청산 신호: {decision['reason']} @ {price:,.0f}원")
            decisions.append(decision)
        else:
            log.info(f"  [{h['ticker']}] 보유 지속")
    return decisions


def _simulate_trade(decision: dict) -> dict:
    """시뮬레이션 체결 (dry-run 모드)."""
    quantity = int(decision["quantity"])
    return {
        **decision,
        "status": "filled",
        "accepted": True,
        "executed": True,
        "terminal": True,
        "requested_qty": quantity,
        "filled_qty": quantity,
        "remaining_qty": 0,
        "executed_price": decision["price"],
        "mode": "simulation",
        "pnl": None,
    }


def _selected_broker_mode(broker_name: str) -> str:
    """Return the selected live broker mode without importing adapter internals."""
    from brokers.config import normalize_mode

    broker = broker_name.lower()
    if broker == "kis":
        from brokers.kis import selected_kis_mode

        return selected_kis_mode()
    if broker == "kiwoom":
        return normalize_mode(os.getenv("KIWOOM_MODE") or os.getenv("LECTURE_BROKER_MODE"))
    if broker == "toss":
        return normalize_mode(os.getenv("TOSS_SECURITIES_MODE") or os.getenv("LECTURE_BROKER_MODE"))
    return normalize_mode(os.getenv("LECTURE_BROKER_MODE"))


def _live_broker_enabled(broker_name: str) -> bool:
    """Global safety gate for any real broker API call."""
    from brokers.config import any_truthy

    broker = broker_name.upper()
    keys = [
        "LECTURE_ENABLE_LIVE_BROKER",
        f"LECTURE_ENABLE_LIVE_{broker}",
    ]
    if broker == "KIS":
        keys = ["LECTURE_ENABLE_LIVE_BROKER"]
    return any_truthy(keys)


def _real_broker_allowed(broker_name: str) -> bool:
    """Extra safety gate for real-money mode."""
    from brokers.config import any_truthy

    broker = broker_name.upper()
    keys = [
        "LECTURE_ALLOW_REAL_BROKER",
        f"LECTURE_ALLOW_REAL_{broker}",
    ]
    if broker == "KIS":
        keys = ["LECTURE_ALLOW_REAL_BROKER"]
    return any_truthy(keys)


def _live_cli_block_result() -> dict | None:
    """Fail closed before the ``--live`` demo can read broker exit quotes."""
    from brokers.factory import selected_broker_name

    broker = selected_broker_name(default="kis").strip().lower()
    if _live_broker_enabled(broker):
        return None
    return {
        "action": "LIVE_BLOCKED",
        "status": "blocked",
        "accepted": False,
        "executed": False,
        "terminal": True,
        "requested_qty": 0,
        "filled_qty": 0,
        "remaining_qty": 0,
        "executed_price": None,
        "mode": "live_blocked",
        "pnl": None,
        "broker": broker,
        "message": (
            f"{broker} 주문 차단: LECTURE_ENABLE_LIVE_BROKER=1 "
            f"또는 LECTURE_ENABLE_LIVE_{broker.upper()}=1 없이는 "
            "--live를 실행하지 않습니다."
        ),
    }


async def _execute_broker_order(decision: dict, broker_name: str | None = None) -> dict:
    """
    선택 브로커 API 주문 실행.

    강의용 안전장치:
    - 기본값은 절대 주문하지 않고 "live_blocked"를 반환합니다.
    - `.env`에서 LECTURE_BROKER=kis|kiwoom|toss|custom 으로 갈아끼울 수 있습니다.
    - demo/mock도 명시적 플래그가 있어야 호출됩니다.
    - real/prod/live는 별도 이중 플래그가 있어야 하며 초보 실습에서는 쓰지 않습니다.

    주문 유형 선택 로직:
    - lecture-prism의 공통 주문 객체를 브로커별 어댑터가 각 API 필드로 변환합니다.
    - KIS 기존 브리지는 그대로 wrapping하고, Kiwoom은 공식 REST 필드명으로 변환합니다.
    - Toss는 고정된 tossctl WTS JSON 계약을 통해 KIS와 같은 수명주기를 사용합니다.
    """
    from brokers import BrokerOrder
    from brokers.factory import get_broker_adapter, selected_broker_name

    broker = (broker_name or selected_broker_name(default="kis")).strip().lower()
    if not _live_broker_enabled(broker):
        log.warning(
            "  실거래 요청 차단: broker=%s (모드/인증 설정은 읽지 않음)",
            broker,
        )
        return {
            **decision,
            "status": "blocked",
            "accepted": False,
            "executed": False,
            "terminal": True,
            "requested_qty": int(decision.get("quantity", 0)),
            "filled_qty": 0,
            "remaining_qty": int(decision.get("quantity", 0)),
            "executed_price": None,
            "mode": "live_blocked",
            "pnl": None,
            "broker": broker,
            "message": (
                f"{broker} 주문 차단: LECTURE_ENABLE_LIVE_BROKER=1 "
                f"또는 LECTURE_ENABLE_LIVE_{broker.upper()}=1 없이는 주문하지 않습니다."
            ),
        }

    mode = _selected_broker_mode(broker)
    log.warning(
        "  실거래 요청 감지: broker=%s mode=%s", broker, mode
    )

    if mode == "real" and not _real_broker_allowed(broker):
        return {
            **decision,
            "executed": False,
            "executed_price": None,
            "mode": "real_blocked",
            "pnl": None,
            "broker": broker,
            "message": (
                f"실전투자 차단: LECTURE_ALLOW_REAL_BROKER=1 "
                f"또는 LECTURE_ALLOW_REAL_{broker.upper()}=1 없이는 real 모드를 쓰지 않습니다."
            ),
        }

    if broker == "toss" and mode != "real":
        return {
            **decision,
            "status": "blocked",
            "accepted": False,
            "executed": False,
            "terminal": True,
            "requested_qty": int(decision.get("quantity", 0)),
            "filled_qty": 0,
            "remaining_qty": int(decision.get("quantity", 0)),
            "executed_price": None,
            "mode": "toss_demo_unavailable",
            "pnl": None,
            "broker": "toss",
            "message": "Toss WTS에는 모의투자 backend가 없어 demo 주문을 차단합니다.",
        }

    try:
        adapter = get_broker_adapter(broker)
    except Exception as e:  # noqa: BLE001 — 강의용 브리지는 실패 사유를 결과로 돌려줌
        return {
            **decision,
            "executed": False,
            "executed_price": None,
            "mode": "broker_import_failed",
            "pnl": None,
            "broker": broker,
            "message": f"{broker} 어댑터 로드 실패: {e}",
        }

    selected_decision = dict(decision)
    if broker in {"kis", "kiwoom", "toss"}:
        try:
            selected_decision["quantity"] = await _broker_safe_quantity(
                adapter, selected_decision, broker=broker
            )
        except Exception as e:  # account uncertainty must not increase exposure
            return {
                **selected_decision,
                "status": "blocked",
                "accepted": False,
                "executed": False,
                "terminal": True,
                "requested_qty": 0,
                "filled_qty": 0,
                "remaining_qty": 0,
                "executed_price": None,
                "mode": f"{broker}_{mode}_account_unavailable",
                "pnl": None,
                "broker": broker,
                "message": f"{broker} 주문 가능 수량 확인 실패: {e}",
            }
        if selected_decision["quantity"] <= 0:
            return {
                **selected_decision,
                "status": "blocked",
                "accepted": False,
                "executed": False,
                "terminal": True,
                "requested_qty": 0,
                "filled_qty": 0,
                "remaining_qty": 0,
                "executed_price": None,
                "mode": f"{broker}_{mode}_quantity_blocked",
                "pnl": None,
                "broker": broker,
                "message": f"{broker} 주문 가능/보유 수량이 0주입니다.",
            }

    if broker == "toss":
        attempted_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        client_order_id = f"lecture-toss-{attempted_at}-{uuid4().hex}"
    else:
        client_order_id = f"lecture-{uuid4().hex}"
    if broker in {"kis", "kiwoom", "toss"}:
        blocker = _admit_pending_broker_order(
            selected_decision,
            client_order_id=client_order_id,
            broker=broker,
            broker_mode=mode,
        )
        if blocker is not None:
            requested = int(selected_decision["quantity"])
            return {
                **selected_decision,
                "status": "blocked",
                "accepted": False,
                "executed": False,
                "terminal": True,
                "requested_qty": requested,
                "filled_qty": 0,
                "remaining_qty": requested,
                "executed_price": None,
                "mode": f"{broker}_{mode}_pending_order",
                "pnl": None,
                "broker": broker,
                "message": (
                    f"미결 {broker} 주문이 있어 중복 주문을 차단합니다: "
                    f"{blocker.order.intent.client_order_id} "
                    f"({blocker.status.value})"
                ),
            }

    try:
        broker_result = await adapter.place_order(
            BrokerOrder(
                action=selected_decision["action"],
                ticker=selected_decision["ticker"],
                quantity=int(selected_decision["quantity"]),
                price=int(selected_decision["price"]),
                reason=selected_decision.get("reason", ""),
                client_order_id=client_order_id,
            )
        )
    except Exception as e:  # noqa: BLE001 — 인증/네트워크 실패도 초보자에게 설명 가능해야 함
        if broker in {"kis", "kiwoom", "toss"}:
            import db
            from prism_core.domain import OrderStatus

            requested = Decimal(str(selected_decision["quantity"]))
            db.update_broker_order(
                client_order_id,
                status=OrderStatus.UNKNOWN,
                filled_quantity=Decimal("0"),
                remaining_quantity=requested,
                average_fill_price=None,
            )
        return {
            **selected_decision,
            "status": "unknown" if broker in {"kis", "kiwoom", "toss"} else "rejected",
            "accepted": False,
            "executed": False,
            "terminal": broker not in {"kis", "kiwoom", "toss"},
            "requested_qty": int(selected_decision["quantity"]),
            "filled_qty": 0,
            "remaining_qty": int(selected_decision["quantity"]),
            "executed_price": None,
            "mode": f"{broker}_{mode}_failed",
            "pnl": None,
            "broker": broker,
            "client_order_id": client_order_id,
            "message": f"{broker} 주문 실패: {e}",
        }

    if broker == "kis":
        broker_result = await _reconcile_kis_order(
            adapter,
            broker_result,
            selected_decision,
            client_order_id=client_order_id,
        )
    elif broker == "kiwoom":
        broker_result = await _reconcile_kiwoom_order(
            adapter,
            broker_result,
            selected_decision,
            client_order_id=client_order_id,
        )
    elif broker == "toss":
        broker_result = await _reconcile_toss_order(
            adapter,
            broker_result,
            selected_decision,
            client_order_id=client_order_id,
        )

    status = str(broker_result.get("status") or "unknown").lower()
    requested_qty = int(selected_decision["quantity"])
    filled_qty = int(broker_result.get("filled_qty") or 0)
    remaining_qty = int(
        broker_result.get("remaining_qty", requested_qty - filled_qty)
    )
    executed = bool(broker_result.get("executed", status == "filled"))
    return {
        **selected_decision,
        "status": status,
        "accepted": bool(broker_result.get("accepted", False)),
        "executed": executed,
        "terminal": bool(broker_result.get("terminal", executed)),
        "requested_qty": requested_qty,
        "filled_qty": filled_qty,
        "remaining_qty": remaining_qty,
        "executed_price": (
            broker_result.get("executed_price")
            or broker_result.get("average_fill_price")
            or (selected_decision["price"] if executed else None)
        ),
        "mode": broker_result.get("mode") or f"{broker}_{mode}",
        "pnl": None,
        "broker": broker,
        "order_no": broker_result.get("order_no"),
        "client_order_id": client_order_id,
        "message": broker_result.get("message", ""),
        "broker_result": broker_result,
    }


async def _kis_safe_quantity(adapter, decision: dict) -> int:
    requested = int(decision["quantity"])
    if requested <= 0:
        return 0
    if str(decision["action"]).upper() == "BUY":
        method = getattr(adapter, "get_orderable_quantity", None)
        if method is None:
            raise RuntimeError("adapter does not expose orderable quantity")
        orderable = int(await method(decision["ticker"], int(decision["price"])))
        return min(requested, max(orderable, 0))

    account = await adapter.get_account()
    held = 0
    for position in account.get("positions", []):
        ticker = str(position.get("pdno") or position.get("ticker") or "")
        if ticker == str(decision["ticker"]):
            raw = position.get("hldg_qty", position.get("quantity", 0))
            held += max(int(str(raw)), 0)
    return min(requested, held)


async def _broker_safe_quantity(adapter, decision: dict, *, broker: str) -> int:
    if broker == "kis":
        return await _kis_safe_quantity(adapter, decision)
    requested = int(decision["quantity"])
    if requested <= 0:
        return 0
    if str(decision["action"]).upper() == "BUY":
        method = getattr(adapter, "get_orderable_quantity", None)
        if method is None:
            raise RuntimeError("adapter does not expose orderable quantity")
        available = int(await method(decision["ticker"], int(decision["price"])))
    else:
        method = getattr(adapter, "get_sellable_quantity", None)
        if method is None:
            raise RuntimeError("adapter does not expose sellable quantity")
        available = int(await method(decision["ticker"]))
    return min(requested, max(available, 0))


def _admit_pending_broker_order(
    decision: dict,
    *,
    client_order_id: str,
    broker: str,
    broker_mode: str,
):
    import db
    from prism_core.domain import (
        Market,
        OrderIntent,
        OrderSide,
        OrderStatus,
        OrderType,
    )

    quantity = Decimal(str(decision["quantity"]))
    intent = OrderIntent(
        client_order_id=client_order_id,
        market=Market.KR,
        symbol=str(decision["ticker"]),
        side=OrderSide(str(decision["action"]).upper()),
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=Decimal(str(decision["price"])),
        currency="KRW",
        reason=str(decision.get("reason", "")),
    )
    admitted, blocker = db.admit_broker_order(
        intent, broker=broker, broker_mode=broker_mode
    )
    if blocker is not None:
        return blocker
    if admitted is None:
        raise RuntimeError(f"{broker} order admission returned no state")
    for status in (OrderStatus.PREVIEWED, OrderStatus.SUBMITTED):
        db.update_broker_order(
            client_order_id,
            status=status,
            filled_quantity=Decimal("0"),
            remaining_quantity=quantity,
            average_fill_price=None,
        )
    return None


def _admit_pending_kis_order(
    decision: dict, *, client_order_id: str, broker_mode: str
):
    return _admit_pending_broker_order(
        decision,
        client_order_id=client_order_id,
        broker="kis",
        broker_mode=broker_mode,
    )


def _row_value(row: dict, *names: str):
    lower = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _kis_inquiry_snapshot(
    inquiry: dict, *, order_no: str, requested_qty: int
) -> dict | None:
    rows = inquiry.get("rows", []) if isinstance(inquiry, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_order_no = str(_row_value(row, "odno", "order_no") or "")
        if row_order_no != str(order_no):
            continue
        requested = int(
            str(_row_value(row, "ord_qty", "requested_qty") or requested_qty)
        )
        filled = int(
            str(_row_value(row, "tot_ccld_qty", "ccld_qty", "filled_qty") or 0)
        )
        remaining_value = _row_value(row, "rmn_qty", "remaining_qty")
        remaining = (
            int(str(remaining_value))
            if remaining_value not in (None, "")
            else max(requested - filled, 0)
        )
        average_value = _row_value(
            row, "avg_prvs", "avg_ccld_unpr", "average_fill_price"
        )
        average = int(Decimal(str(average_value))) if filled and average_value else None
        if filled >= requested and remaining == 0:
            status = "filled"
        elif filled > 0:
            status = "partial"
        else:
            status = "accepted"
        return {
            "status": status,
            "accepted": True,
            "executed": status == "filled",
            "terminal": status == "filled",
            "order_no": str(order_no),
            "filled_qty": filled,
            "remaining_qty": remaining,
            "average_fill_price": average,
        }
    return None


async def _reconcile_kis_order(
    adapter,
    broker_result: dict,
    decision: dict,
    *,
    client_order_id: str,
) -> dict:
    import db
    from market_calendar import KST
    from prism_core.domain import OrderStatus

    requested = int(decision["quantity"])
    status = str(broker_result.get("status") or "unknown").lower()
    order_no = broker_result.get("order_no")
    org_no = broker_result.get("org_no")
    incomplete_identity = status == "accepted" and not (order_no and org_no)
    ledger_status = {
        "accepted": OrderStatus.ACCEPTED,
        "unknown": OrderStatus.UNKNOWN,
        "rejected": OrderStatus.REJECTED,
        "blocked": OrderStatus.REJECTED,
    }.get(status, OrderStatus.UNKNOWN)
    if incomplete_identity:
        ledger_status = OrderStatus.UNKNOWN
    db.update_broker_order(
        client_order_id,
        status=ledger_status,
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal(str(requested)),
        average_fill_price=None,
    )

    order_date = datetime.now(KST).strftime("%Y%m%d")
    if order_no and org_no:
        db.bind_broker_identity(
            client_order_id,
            broker_order_date=order_date,
            broker_org_no=str(org_no),
            broker_order_no=str(order_no),
        )
    if incomplete_identity:
        return {
            **broker_result,
            "status": "unknown",
            "accepted": False,
            "executed": False,
            "terminal": False,
            "filled_qty": 0,
            "remaining_qty": requested,
            "message": "KIS 접수 응답의 주문 식별자가 불완전하여 재주문을 금지합니다.",
        }
    if status != "accepted" or not order_no:
        return {
            **broker_result,
            "filled_qty": 0,
            "remaining_qty": requested,
        }

    try:
        inquiry = await adapter.get_order_status(
            str(order_no), business_date=order_date
        )
    except Exception as exc:
        return {
            **broker_result,
            "filled_qty": 0,
            "remaining_qty": requested,
            "reconciliation_message": str(exc),
        }
    snapshot = _kis_inquiry_snapshot(
        inquiry, order_no=str(order_no), requested_qty=requested
    )
    if snapshot is None:
        return {
            **broker_result,
            "filled_qty": 0,
            "remaining_qty": requested,
        }
    snapshot_status = {
        "accepted": OrderStatus.ACCEPTED,
        "partial": OrderStatus.PARTIALLY_FILLED,
        "filled": OrderStatus.FILLED,
    }[snapshot["status"]]
    db.update_broker_order(
        client_order_id,
        status=snapshot_status,
        filled_quantity=Decimal(str(snapshot["filled_qty"])),
        remaining_quantity=Decimal(str(snapshot["remaining_qty"])),
        average_fill_price=(
            Decimal(str(snapshot["average_fill_price"]))
            if snapshot["average_fill_price"] is not None
            else None
        ),
    )
    return {**broker_result, **snapshot}


def _toss_snapshot_values(snapshot: dict, *, requested: int) -> tuple:
    from prism_core.domain import OrderStatus

    status = str(snapshot.get("status") or "unknown").lower()
    filled = int(snapshot.get("filled_qty") or 0)
    remaining = int(snapshot.get("remaining_qty", requested - filled))
    if filled < 0 or remaining < 0 or filled + remaining != requested:
        return OrderStatus.UNKNOWN, 0, requested, None
    average = snapshot.get("average_fill_price")
    if filled > 0 and (average is None or Decimal(str(average)) <= 0):
        return OrderStatus.UNKNOWN, 0, requested, None
    target = {
        "accepted": OrderStatus.ACCEPTED,
        "partial": OrderStatus.PARTIALLY_FILLED,
        "filled": OrderStatus.FILLED,
        "canceled": OrderStatus.CANCELED,
        "rejected": OrderStatus.REJECTED,
        "blocked": OrderStatus.REJECTED,
        "unknown": OrderStatus.UNKNOWN,
    }.get(status, OrderStatus.UNKNOWN)
    return target, filled, remaining, average


def _kiwoom_snapshot_values(snapshot: dict, *, requested: int) -> tuple:
    from prism_core.domain import OrderStatus

    status = str(snapshot.get("status") or "unknown").lower()
    filled = int(snapshot.get("filled_qty") or 0)
    remaining = int(snapshot.get("remaining_qty", requested - filled))
    if filled < 0 or remaining < 0 or filled + remaining != requested:
        return OrderStatus.UNKNOWN, 0, requested, None
    average = snapshot.get("average_fill_price")
    if filled > 0 and (average is None or Decimal(str(average)) <= 0):
        return OrderStatus.UNKNOWN, 0, requested, None
    target = {
        "accepted": OrderStatus.ACCEPTED,
        "partial": OrderStatus.PARTIALLY_FILLED,
        "filled": OrderStatus.FILLED,
        "canceled": OrderStatus.CANCELED,
        "cancelled": OrderStatus.CANCELED,
        "rejected": OrderStatus.REJECTED,
        "blocked": OrderStatus.REJECTED,
        "unknown": OrderStatus.UNKNOWN,
    }.get(status, OrderStatus.UNKNOWN)
    return target, filled, remaining, average


def _update_kiwoom_ledger_snapshot(
    client_order_id: str, snapshot: dict, *, requested: int
) -> dict:
    import db
    from prism_core.domain import OrderStatus, validate_transition

    state = db.get_broker_order_state(client_order_id)
    target, filled, remaining, average = _kiwoom_snapshot_values(
        snapshot, requested=requested
    )
    if Decimal(str(filled)) < state.filled_quantity:
        target, filled, remaining, average = (
            OrderStatus.UNKNOWN,
            int(state.filled_quantity),
            int(state.remaining_quantity),
            (
                int(state.average_fill_price)
                if state.average_fill_price is not None
                else None
            ),
        )
    if target is OrderStatus.ACCEPTED and state.status is OrderStatus.PARTIALLY_FILLED:
        return {
            **snapshot,
            "status": "partial",
            "filled_qty": int(state.filled_quantity),
            "remaining_qty": int(state.remaining_quantity),
            "average_fill_price": (
                int(state.average_fill_price)
                if state.average_fill_price is not None
                else None
            ),
        }
    if state.status is not target:
        if not validate_transition(state.status, target):
            target, filled, remaining, average = (
                OrderStatus.UNKNOWN,
                int(state.filled_quantity),
                int(state.remaining_quantity),
                (
                    int(state.average_fill_price)
                    if state.average_fill_price is not None
                    else None
                ),
            )
        db.update_broker_order(
            client_order_id,
            status=target,
            filled_quantity=Decimal(str(filled)),
            remaining_quantity=Decimal(str(remaining)),
            average_fill_price=(
                Decimal(str(average)) if average is not None else None
            ),
        )
    return {
        **snapshot,
        "status": (
            "partial"
            if target is OrderStatus.PARTIALLY_FILLED
            else target.value.lower()
        ),
        "accepted": target is not OrderStatus.UNKNOWN,
        "executed": target is OrderStatus.FILLED,
        "terminal": target in {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED},
        "filled_qty": filled,
        "remaining_qty": remaining,
        "average_fill_price": average,
    }


async def _reconcile_kiwoom_order(
    adapter,
    broker_result: dict,
    decision: dict,
    *,
    client_order_id: str,
) -> dict:
    import db
    from market_calendar import KST

    requested = int(decision["quantity"])
    status = str(broker_result.get("status") or "unknown").lower()
    order_no = broker_result.get("order_no")
    order_date = datetime.now(KST).strftime("%Y%m%d")
    if status in {"accepted", "filled", "partial", "canceled"} and not order_no:
        broker_result = {
            **broker_result,
            "status": "unknown",
            "accepted": False,
            "executed": False,
            "terminal": False,
            "message": "Kiwoom 접수 응답의 주문 식별자가 없어 재주문을 금지합니다.",
        }
        status = "unknown"

    if order_no:
        db.bind_broker_identity(
            client_order_id,
            broker_order_date=order_date,
            broker_org_no="kiwoom",
            broker_order_no=str(order_no),
        )

    initial = {
        **broker_result,
        "status": status,
        "filled_qty": int(broker_result.get("filled_qty") or 0),
        "remaining_qty": int(
            broker_result.get(
                "remaining_qty",
                requested - int(broker_result.get("filled_qty") or 0),
            )
        ),
    }
    initial = _update_kiwoom_ledger_snapshot(
        client_order_id, initial, requested=requested
    )
    if status not in {"accepted", "unknown"} or not order_no:
        return initial
    try:
        snapshot = await adapter.get_order_status(
            str(order_no), business_date=order_date
        )
    except Exception as exc:
        return {**initial, "reconciliation_message": str(exc)}
    snapshot = _update_kiwoom_ledger_snapshot(
        client_order_id, snapshot, requested=requested
    )
    return {**broker_result, **snapshot}


def _toss_order_date(value) -> str:
    normalized = str(value or "").replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError("Toss order_date must be YYYY-MM-DD or YYYYMMDD")
    datetime.strptime(normalized, "%Y%m%d")
    return normalized


def _toss_attempted_at(client_order_id: str) -> datetime:
    parts = str(client_order_id).split("-", 3)
    if len(parts) != 4 or parts[:2] != ["lecture", "toss"]:
        raise ValueError("Toss client_order_id has no recovery timestamp")
    return datetime.strptime(parts[2], "%Y%m%dT%H%M%S%fZ").replace(
        tzinfo=timezone.utc
    )


def _update_toss_ledger_snapshot(
    client_order_id: str, snapshot: dict, *, requested: int
) -> dict:
    import db
    from prism_core.domain import OrderStatus, validate_transition

    state = db.get_broker_order_state(client_order_id)
    target, filled, remaining, average = _toss_snapshot_values(
        snapshot, requested=requested
    )
    if Decimal(str(filled)) < state.filled_quantity:
        target, filled, remaining, average = (
            OrderStatus.UNKNOWN,
            int(state.filled_quantity),
            int(state.remaining_quantity),
            (
                int(state.average_fill_price)
                if state.average_fill_price is not None
                else None
            ),
        )
    if target is OrderStatus.ACCEPTED and state.status is OrderStatus.PARTIALLY_FILLED:
        return {
            **snapshot,
            "status": "partial",
            "filled_qty": int(state.filled_quantity),
            "remaining_qty": int(state.remaining_quantity),
            "average_fill_price": (
                int(state.average_fill_price)
                if state.average_fill_price is not None
                else None
            ),
        }
    if target in {OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELED} and not validate_transition(
        state.status, target
    ):
        if validate_transition(state.status, OrderStatus.ACCEPTED):
            db.update_broker_order(
                client_order_id,
                status=OrderStatus.ACCEPTED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal(str(requested)),
                average_fill_price=None,
            )
            state = db.get_broker_order_state(client_order_id)
    if state.status is not target:
        if not validate_transition(state.status, target):
            target, filled, remaining, average = (
                OrderStatus.UNKNOWN,
                int(state.filled_quantity),
                int(state.remaining_quantity),
                (
                    int(state.average_fill_price)
                    if state.average_fill_price is not None
                    else None
                ),
            )
        db.update_broker_order(
            client_order_id,
            status=target,
            filled_quantity=Decimal(str(filled)),
            remaining_quantity=Decimal(str(remaining)),
            average_fill_price=(
                Decimal(str(average)) if average is not None else None
            ),
        )
    return {
        **snapshot,
        "status": (
            "partial"
            if target is OrderStatus.PARTIALLY_FILLED
            else target.value.lower()
        ),
        "filled_qty": filled,
        "remaining_qty": remaining,
        "average_fill_price": average,
    }


async def _reconcile_toss_order(
    adapter,
    broker_result: dict,
    decision: dict,
    *,
    client_order_id: str,
) -> dict:
    import db

    requested = int(decision["quantity"])
    status = str(broker_result.get("status") or "unknown").lower()
    order_no = broker_result.get("order_no")
    order_date = broker_result.get("order_date")
    identity_complete = False
    identity_error = ""
    if order_no and order_date:
        try:
            db.bind_broker_identity(
                client_order_id,
                broker_order_date=_toss_order_date(order_date),
                broker_org_no="toss",
                broker_order_no=str(order_no),
            )
        except (KeyError, ValueError) as exc:
            identity_error = str(exc)
        else:
            identity_complete = True
    if status in {"accepted", "filled", "canceled"} and not identity_complete:
        status = "unknown"
        broker_result = {
            **broker_result,
            "status": "unknown",
            "accepted": False,
            "executed": False,
            "terminal": False,
            "message": (
                "Toss 접수 응답의 주문 식별자가 불완전해 재주문을 금지합니다."
                + (f" ({identity_error})" if identity_error else "")
            ),
        }

    initial = {
        **broker_result,
        "status": status,
        "filled_qty": int(broker_result.get("filled_qty") or 0),
        "remaining_qty": int(
            broker_result.get(
                "remaining_qty",
                requested - int(broker_result.get("filled_qty") or 0),
            )
        ),
    }
    initial = _update_toss_ledger_snapshot(
        client_order_id, initial, requested=requested
    )
    if status not in {"accepted", "unknown"} or not order_no:
        return initial
    try:
        snapshot = await adapter.get_order_status(str(order_no), market="kr")
    except Exception as exc:
        return {**initial, "reconciliation_message": str(exc)}
    snapshot = _update_toss_ledger_snapshot(
        client_order_id, snapshot, requested=requested
    )
    return {**broker_result, **snapshot}


def _toss_recovery_candidates(state, rows: list[dict]) -> list[dict]:
    from market_calendar import KST

    intent = state.order.intent
    expected_side = intent.side.value.lower()
    expected_qty = int(intent.quantity)
    expected_price = int(intent.limit_price or 0)
    attempted_at = _toss_attempted_at(intent.client_order_id)
    expected_date = attempted_at.astimezone(KST).strftime("%Y%m%d")
    earliest = attempted_at - timedelta(seconds=30)
    latest = attempted_at + timedelta(minutes=5)
    matches = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "") != intent.symbol:
            continue
        if str(row.get("side") or "").lower() != expected_side:
            continue
        if int(row.get("quantity") or 0) != expected_qty:
            continue
        if int(Decimal(str(row.get("price") or 0))) != expected_price:
            continue
        if not row.get("id") or not row.get("order_date"):
            continue
        try:
            candidate_date = _toss_order_date(row["order_date"])
            submitted_at = datetime.fromisoformat(
                str(row.get("submitted_at") or "").replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            continue
        if submitted_at.tzinfo is None:
            continue
        if candidate_date != expected_date or not (
            earliest <= submitted_at.astimezone(timezone.utc) <= latest
        ):
            continue
        matches.append(row)
    return matches


async def reconcile_pending_toss_orders(
    *, adapter=None, mode: str | None = None
) -> list[dict]:
    """Re-query Toss orders after restart without submitting a mutation."""
    import db
    from brokers.factory import get_broker_adapter

    selected_mode = mode or _selected_broker_mode("toss")
    selected_adapter = adapter or get_broker_adapter("toss")
    pending = db.get_pending_broker_orders(
        broker="toss", broker_mode=selected_mode
    )
    results = []
    for state in pending:
        client_order_id = state.order.intent.client_order_id
        requested = int(state.order.intent.quantity)
        order_no = state.broker_order_no
        if not order_no:
            try:
                rows = [
                    *(await selected_adapter.get_pending_orders()),
                    *(await selected_adapter.get_completed_orders(market="kr")),
                ]
                candidates = _toss_recovery_candidates(state, rows)
            except Exception as exc:
                candidates = []
                message = str(exc)
            else:
                message = ""
            if len(candidates) == 1:
                candidate = candidates[0]
                order_no = str(candidate["id"])
                db.bind_broker_identity(
                    client_order_id,
                    broker_order_date=_toss_order_date(candidate["order_date"]),
                    broker_org_no="toss",
                    broker_order_no=order_no,
                )
            else:
                results.append(
                    {
                        "client_order_id": client_order_id,
                        "order_no": None,
                        "status": "unknown",
                        "accepted": False,
                        "executed": False,
                        "terminal": False,
                        "requested_qty": requested,
                        "filled_qty": int(state.filled_quantity),
                        "remaining_qty": int(state.remaining_quantity),
                        "message": message or "Toss 주문 식별자를 하나로 복구하지 못했습니다.",
                    }
                )
                continue
        try:
            snapshot = await selected_adapter.get_order_status(
                str(order_no), market="kr"
            )
            snapshot = _update_toss_ledger_snapshot(
                client_order_id, snapshot, requested=requested
            )
        except Exception as exc:
            results.append(
                {
                    "client_order_id": client_order_id,
                    "order_no": order_no,
                    "status": (
                        "partial"
                        if state.status.value == "PARTIALLY_FILLED"
                        else state.status.value.lower()
                    ),
                    "accepted": state.status.value != "UNKNOWN",
                    "executed": False,
                    "terminal": False,
                    "requested_qty": requested,
                    "filled_qty": int(state.filled_quantity),
                    "remaining_qty": int(state.remaining_quantity),
                    "message": str(exc),
                }
            )
            continue
        results.append(
            {
                **snapshot,
                "client_order_id": client_order_id,
                "requested_qty": requested,
                "message": "Toss 미결 주문 상태를 재조회했습니다.",
            }
        )
    return results


async def reconcile_pending_kiwoom_orders(
    *, adapter=None, mode: str | None = None
) -> list[dict]:
    """Re-query restartable Kiwoom orders without submitting mutations."""
    import db
    from brokers.factory import get_broker_adapter
    from prism_core.domain import OrderStatus

    selected_mode = mode or _selected_broker_mode("kiwoom")
    selected_adapter = adapter or get_broker_adapter("kiwoom")
    pending = db.get_pending_broker_orders(
        broker="kiwoom", broker_mode=selected_mode
    )
    results = []
    for state in pending:
        client_order_id = state.order.intent.client_order_id
        order_no = state.broker_order_no
        order_date = state.broker_order_date
        requested = int(state.order.intent.quantity)
        if not order_no or not order_date:
            results.append(
                {
                    "client_order_id": client_order_id,
                    "order_no": order_no,
                    "status": state.status.value.lower(),
                    "accepted": state.status is not OrderStatus.UNKNOWN,
                    "executed": False,
                    "terminal": False,
                    "requested_qty": requested,
                    "filled_qty": int(state.filled_quantity),
                    "remaining_qty": int(state.remaining_quantity),
                    "message": "Kiwoom 주문 식별자가 없어 자동 조회를 보류합니다.",
                }
            )
            continue
        try:
            snapshot = await selected_adapter.get_order_status(
                str(order_no), business_date=order_date
            )
            snapshot = _update_kiwoom_ledger_snapshot(
                client_order_id, snapshot, requested=requested
            )
        except Exception as exc:
            results.append(
                {
                    "client_order_id": client_order_id,
                    "order_no": order_no,
                    "status": (
                        "partial"
                        if state.status is OrderStatus.PARTIALLY_FILLED
                        else state.status.value.lower()
                    ),
                    "accepted": state.status is not OrderStatus.UNKNOWN,
                    "executed": False,
                    "terminal": False,
                    "requested_qty": requested,
                    "filled_qty": int(state.filled_quantity),
                    "remaining_qty": int(state.remaining_quantity),
                    "message": str(exc),
                }
            )
            continue
        results.append(
            {
                **snapshot,
                "client_order_id": client_order_id,
                "requested_qty": requested,
                "message": "Kiwoom 미결 주문 상태를 재조회했습니다.",
            }
        )
    return results


async def reconcile_pending_kis_orders(
    *, adapter=None, mode: str | None = None
) -> list[dict]:
    """Re-query restartable KIS orders without ever submitting a new order."""
    import db
    from brokers.factory import get_broker_adapter
    from prism_core.domain import OrderStatus

    selected_mode = mode or _selected_broker_mode("kis")
    selected_adapter = adapter or get_broker_adapter("kis")
    pending = db.get_pending_broker_orders(
        broker="kis", broker_mode=selected_mode
    )
    results = []
    for state in pending:
        order_no = state.broker_order_no
        order_date = state.broker_order_date
        requested = int(state.order.intent.quantity)
        if not order_no or not order_date:
            results.append(
                {
                    "client_order_id": state.order.intent.client_order_id,
                    "order_no": order_no,
                    "status": state.status.value.lower(),
                    "accepted": state.status is not OrderStatus.UNKNOWN,
                    "executed": False,
                    "terminal": False,
                    "requested_qty": requested,
                    "filled_qty": int(state.filled_quantity),
                    "remaining_qty": int(state.remaining_quantity),
                    "message": "브로커 주문 식별자가 없어 자동 조회를 보류합니다.",
                }
            )
            continue
        try:
            inquiry = await selected_adapter.get_order_status(
                order_no, business_date=order_date
            )
            snapshot = _kis_inquiry_snapshot(
                inquiry, order_no=order_no, requested_qty=requested
            )
        except Exception as exc:
            snapshot = None
            message = str(exc)
        else:
            message = ""
        if snapshot is None:
            results.append(
                {
                    "client_order_id": state.order.intent.client_order_id,
                    "order_no": order_no,
                    "status": (
                        "partial"
                        if state.status is OrderStatus.PARTIALLY_FILLED
                        else state.status.value.lower()
                    ),
                    "accepted": state.status is not OrderStatus.UNKNOWN,
                    "executed": False,
                    "terminal": False,
                    "requested_qty": requested,
                    "filled_qty": int(state.filled_quantity),
                    "remaining_qty": int(state.remaining_quantity),
                    "message": message or "일치하는 KIS 주문 조회 행이 없습니다.",
                }
            )
            continue
        if Decimal(str(snapshot["filled_qty"])) < state.filled_quantity:
            results.append(
                {
                    **snapshot,
                    "client_order_id": state.order.intent.client_order_id,
                    "status": "unknown",
                    "accepted": True,
                    "executed": False,
                    "terminal": False,
                    "message": "KIS 누적 체결 수량이 원장보다 작아 갱신을 보류합니다.",
                }
            )
            continue
        target = {
            "accepted": OrderStatus.ACCEPTED,
            "partial": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
        }[snapshot["status"]]
        if target is OrderStatus.ACCEPTED and state.status is OrderStatus.PARTIALLY_FILLED:
            target = OrderStatus.PARTIALLY_FILLED
            snapshot = {
                **snapshot,
                "status": "partial",
                "filled_qty": int(state.filled_quantity),
                "remaining_qty": int(state.remaining_quantity),
                "average_fill_price": (
                    int(state.average_fill_price)
                    if state.average_fill_price is not None
                    else None
                ),
            }
        db.update_broker_order(
            state.order.intent.client_order_id,
            status=target,
            filled_quantity=Decimal(str(snapshot["filled_qty"])),
            remaining_quantity=Decimal(str(snapshot["remaining_qty"])),
            average_fill_price=(
                Decimal(str(snapshot["average_fill_price"]))
                if snapshot.get("average_fill_price") is not None
                else None
            ),
        )
        results.append(
            {
                **snapshot,
                "client_order_id": state.order.intent.client_order_id,
                "requested_qty": requested,
                "message": "KIS 미결 주문 상태를 재조회했습니다.",
            }
        )
    return results


async def _execute_kis_order(decision: dict) -> dict:
    """Backward-compatible KIS entrypoint used by older lecture prompts/tests."""
    return await _execute_broker_order(decision, broker_name="kis")


async def _get_current_portfolio() -> dict:
    """교육용 매매일지에서 현재 보유 슬롯을 계산합니다."""
    holdings = await _get_exit_holdings()
    return {
        "cash": 10_000_000,   # 예시: 1천만원
        "slots_used": len(holdings),
        "holdings": holdings,
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
            {"ticker": "005930", "recommendation": "BUY", "decision": "진입", "buy_score": 8,
             "current_price": 71_200, "target_price": 81_200, "stop_loss": 67_600,
             "risk_reward_ratio": 2.8, "rationale": "테스트 진입", "risk": "없음"},
        ]
        blocked = _live_cli_block_result() if args.live else None
        results = (
            [blocked]
            if blocked is not None
            else asyncio.run(run_trading(sample_analyses, dry_run=not args.live))
        )
        print(f"\n체결 결과: {results}")
