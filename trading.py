"""
trading.py — 모듈 3: 매매 실행

분석 결과 → 포지션 사이징 → 선택 브로커 API 주문 → 결과 기록.
의사결정 트리: 얼마를 살 것인가 / 어떻게 살 것인가 / 체결 안 되면?

실행:
    python trading.py --dry-run    # 시뮬레이션 (기본)
    python trading.py --live       # 실거래 (KIS API 필요)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

log = logging.getLogger(__name__)

# ── 포트폴리오 설정 ──────────────────────────────────────────────
MAX_SLOTS = 10              # 최대 보유 종목 수
MAX_SAME_SECTOR = 3         # 동일 섹터 최대 보유 수
CASH_RESERVE_RATIO = 0.7    # 현금 비중 (70% 유지)
BUY_SCORE_THRESHOLD = 6     # 매수 최소 점수 (10점 만점, analysis.MIN_BUY_SCORE와 동일 기준)

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
            result = await _execute_broker_order(decision)

        results.append(result)

    return results


def _decide_position(analysis: dict, portfolio: dict) -> Optional[dict]:
    """
    포지션 사이징 및 매수 여부 결정.

    파트4 트랙D에서 수강생이 이 로직을 수정하는 부분.
    """
    # 매수 점수 필터 (0~10점, analysis가 산출한 buy_score)
    buy_score = analysis.get("buy_score", analysis.get("score", 0))
    if buy_score < BUY_SCORE_THRESHOLD:
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

    # 현재가: analysis가 제공(종목별 mock 또는 LLM). 실데이터 연동 시 analysis.get_current_price만 교체.
    current_price = analysis.get("current_price") or 70_000
    quantity = int(per_slot_amount / current_price)

    if quantity <= 0:
        return None

    return {
        "action": "BUY",
        "ticker": analysis["ticker"],
        "quantity": quantity,
        "price": current_price,
        "reason": analysis.get("rationale") or analysis.get("reason", ""),
        "target_price": analysis.get("target_price"),
        "stop_loss": analysis.get("stop_loss", STOP_LOSS["default"]),
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
    return {
        "action": "SELL",
        "ticker": holding["ticker"],
        "quantity": int(holding.get("quantity", 0)),
        "price": price,
        "reason": reason,
    }


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
    # Backward compatibility with the previous KIS-only bridge.
    if broker_name.lower() == "kis":
        keys.append("LECTURE_ENABLE_LIVE_KIS")
    return any_truthy(keys)


def _real_broker_allowed(broker_name: str) -> bool:
    """Extra safety gate for real-money mode."""
    from brokers.config import any_truthy

    broker = broker_name.upper()
    keys = [
        "LECTURE_ALLOW_REAL_BROKER",
        f"LECTURE_ALLOW_REAL_{broker}",
    ]
    if broker_name.lower() == "kis":
        keys.append("LECTURE_ALLOW_REAL_KIS")
    return any_truthy(keys)


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
    - Toss는 공식 공개 증권 주문 API가 확인될 때까지 안전하게 차단됩니다.
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
    if broker == "kis":
        try:
            selected_decision["quantity"] = await _kis_safe_quantity(
                adapter, selected_decision
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
                "message": f"KIS 주문 가능 수량 확인 실패: {e}",
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
                "message": "KIS 주문 가능/보유 수량이 0주입니다.",
            }

    client_order_id = f"lecture-{uuid4().hex}"
    if broker == "kis":
        blocker = _admit_pending_kis_order(
            selected_decision,
            client_order_id=client_order_id,
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
                "mode": f"kis_{mode}_pending_order",
                "pnl": None,
                "broker": "kis",
                "message": (
                    "미결 KIS 주문이 있어 중복 주문을 차단합니다: "
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
        if broker == "kis":
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
            "status": "unknown" if broker == "kis" else "rejected",
            "accepted": False,
            "executed": False,
            "terminal": broker != "kis",
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


def _admit_pending_kis_order(
    decision: dict, *, client_order_id: str, broker_mode: str
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
        intent, broker="kis", broker_mode=broker_mode
    )
    if blocker is not None:
        return blocker
    if admitted is None:
        raise RuntimeError("KIS order admission returned no state")
    for status in (OrderStatus.PREVIEWED, OrderStatus.SUBMITTED):
        db.update_broker_order(
            client_order_id,
            status=status,
            filled_quantity=Decimal("0"),
            remaining_quantity=quantity,
            average_fill_price=None,
        )
    return None


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
            {"ticker": "005930", "recommendation": "BUY", "decision": "진입", "buy_score": 8,
             "current_price": 71_200, "target_price": 81_200, "stop_loss": 67_600,
             "rationale": "테스트 진입", "risk": "없음"},
        ]
        results = asyncio.run(run_trading(sample_analyses, dry_run=not args.live))
        print(f"\n체결 결과: {results}")
