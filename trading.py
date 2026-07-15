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
from typing import Optional
from uuid import uuid4

import db
from market_calendar import KST

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

    decision = {
        "action": "BUY",
        "ticker": analysis["ticker"],
        "quantity": quantity,
        "price": current_price,
        "reason": analysis.get("rationale") or analysis.get("reason", ""),
        "target_price": analysis.get("target_price"),
        "stop_loss": analysis.get("stop_loss", STOP_LOSS["default"]),
    }
    if analysis.get("run_id") is not None:
        decision["run_id"] = analysis["run_id"]
    return decision


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
        "quantity": int(holding.get("quantity", 0) or 0),
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
    return {
        **decision,
        "executed": True,
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


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _number_from(record: dict, *keys: str) -> int | None:
    normalized = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        if key.lower() in normalized:
            parsed = _optional_int(normalized[key.lower()])
            if parsed is not None:
                return parsed
    return None


def _rows(value: object) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _cap_kis_quantity(adapter: object, decision: dict) -> int:
    desired = max(0, int(decision.get("quantity", 0) or 0))
    price = max(0, int(decision.get("price", 0) or 0))
    ticker = str(decision.get("ticker") or "")
    account = adapter.get_account()

    if str(decision.get("action") or "").upper() == "SELL":
        for holding in _rows(account.get("output1")):
            holding_ticker = str(
                holding.get("pdno") or holding.get("ticker") or ""
            ).strip()
            if holding_ticker != ticker:
                continue
            sellable = _number_from(
                holding, "ord_psbl_qty", "sellable_qty", "hldg_qty", "quantity"
            )
            return min(desired, max(0, sellable or 0))
        return 0

    orderable = adapter.get_orderable_quantity(ticker, price)
    orderable_qty = _number_from(
        orderable, "nrcvb_buy_qty", "ord_psbl_qty", "buyable_qty"
    )
    if orderable_qty is None or orderable_qty <= 0:
        return 0

    capped = min(desired, orderable_qty)
    if price <= 0:
        return 0

    cash_limits: list[int] = []
    orderable_cash = _number_from(
        orderable, "ord_psbl_cash", "ord_psbl_amt", "buyable_cash"
    )
    if orderable_cash is not None:
        cash_limits.append(max(0, orderable_cash))
    for summary in _rows(account.get("output2")):
        cash = _number_from(
            summary,
            "dnca_tot_amt",
            "ord_psbl_cash",
            "prvs_rcdl_excc_amt",
            "cash",
        )
        if cash is not None:
            cash_limits.append(max(0, cash))
            break
    if cash_limits:
        capped = min(capped, *(cash // price for cash in cash_limits))
    return max(0, capped)


def _db_broker_mode(mode: str) -> str:
    return "real" if str(mode).lower() == "real" else "paper"


def _blocked_order_result(decision: dict, broker: str, mode: str, message: str) -> dict:
    return {
        **decision,
        "quantity": 0,
        "requested_qty": 0,
        "filled_qty": 0,
        "remaining_qty": 0,
        "avg_fill_price": None,
        "status": "blocked",
        "accepted": False,
        "executed": False,
        "executed_price": None,
        "terminal": True,
        "requires_reconciliation": False,
        "mode": f"{broker}_{mode}_blocked",
        "pnl": None,
        "broker": broker,
        "order_no": None,
        "message": message,
    }


def _trade_result_from_order(
    decision: dict,
    order: dict,
    *,
    broker_mode: str,
    broker_result: dict | None = None,
) -> dict:
    status = str(order.get("status") or "unknown")
    filled_qty = int(order.get("filled_qty", 0) or 0)
    avg_fill_price = order.get("avg_fill_price")
    return {
        **decision,
        "quantity": int(order.get("requested_qty", 0) or 0),
        "requested_qty": int(order.get("requested_qty", 0) or 0),
        "filled_qty": filled_qty,
        "remaining_qty": int(order.get("remaining_qty", 0) or 0),
        "avg_fill_price": avg_fill_price,
        "status": status,
        "accepted": status in {"accepted", "unfilled", "partial_fill", "filled"},
        "executed": status == "filled",
        "executed_price": avg_fill_price if status == "filled" else None,
        "terminal": status in {"filled", "cancelled", "rejected"},
        "requires_reconciliation": status in {
            "accepted", "unknown", "unfilled", "partial_fill"
        },
        "mode": broker_mode,
        "pnl": None,
        "broker": "kis",
        "order_no": order.get("order_no"),
        "message": order.get("message") or "",
        "broker_result": broker_result or {},
    }


def _text_from(record: dict, *keys: str) -> str:
    normalized = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        value = normalized.get(key.lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _inquiry_row(response: dict, stored: dict) -> dict | None:
    rows = _rows(response.get("output1"))
    order_no = str(stored.get("order_no") or "").strip()
    if order_no:
        for row in rows:
            candidate = _text_from(row, "odno", "order_no")
            if candidate == order_no:
                return row
        return None

    expected_side = str(stored.get("side") or "").upper()
    expected_code = "02" if expected_side == "BUY" else "01"
    matches = []
    for row in rows:
        if _text_from(row, "pdno", "ticker") != str(stored.get("ticker") or ""):
            continue
        if _number_from(row, "ord_qty", "requested_qty") != int(
            stored["requested_qty"]
        ):
            continue
        side_code = _text_from(row, "sll_buy_dvsn_cd")
        side_name = _text_from(row, "sll_buy_dvsn_cd_name", "side").upper()
        if side_code and side_code != expected_code:
            continue
        side_name_matches = (
            expected_side in side_name
            or (expected_side == "BUY" and "매수" in side_name)
            or (expected_side == "SELL" and "매도" in side_name)
        )
        if side_name and not side_name_matches:
            continue
        matches.append(row)
    return matches[0] if len(matches) == 1 else None


def _order_progress_from_inquiry(stored: dict, response: dict) -> dict | None:
    row = _inquiry_row(response, stored)
    if row is None:
        return None

    requested = int(stored["requested_qty"])
    reported_filled = _number_from(
        row, "tot_ccld_qty", "ccld_qty", "filled_qty"
    )
    filled = max(int(stored.get("filled_qty", 0) or 0), reported_filled or 0)
    filled = min(requested, filled)
    reported_remaining = _number_from(row, "rmn_qty", "remaining_qty")
    if reported_remaining is None:
        remaining = requested - filled
    else:
        remaining = min(
            int(stored.get("remaining_qty", requested) or 0),
            max(0, reported_remaining),
        )
        remaining = min(remaining, requested - filled)

    if filled <= 0:
        status = "unfilled"
    elif filled >= requested or remaining == 0:
        status = "filled"
        filled = requested
        remaining = 0
    else:
        status = "partial_fill"
    average = _number_from(
        row, "avg_prvs", "avg_fill_price", "ccld_avg_pric", "avg_pric"
    )
    if not average:
        average = stored.get("avg_fill_price")
    return {
        **stored,
        "org_no": _text_from(row, "ord_gno_brno", "krx_fwdg_ord_orgno")
        or stored.get("org_no"),
        "order_no": _text_from(row, "odno", "order_no")
        or stored.get("order_no"),
        "status": status,
        "filled_qty": filled,
        "remaining_qty": remaining,
        "avg_fill_price": average,
        "message": f"KIS 체결 조회: {status}",
    }


def _reconcile_stored_order(
    adapter: object, stored: dict, *, broker_mode: str
) -> dict | None:
    order_no = stored.get("order_no")
    if not order_no and stored.get("status") != "unknown":
        return None
    inquiry_kwargs = {}
    if not order_no:
        inquiry_kwargs = {
            "start_date": stored["order_date"],
            "end_date": stored["order_date"],
        }
    response = adapter.get_order_status(str(order_no or ""), **inquiry_kwargs)
    progress = _order_progress_from_inquiry(stored, response)
    if progress is None:
        return None
    updated = db.update_broker_order(progress)
    decision = {
        "run_id": updated.get("run_id"),
        "action": updated["side"],
        "ticker": updated["ticker"],
        "quantity": updated["requested_qty"],
        "price": updated.get("requested_price") or 0,
        "reason": updated.get("message") or "",
    }
    return _trade_result_from_order(
        decision, updated, broker_mode=broker_mode, broker_result=response
    )


async def reconcile_pending_broker_orders(
    *, adapter: object | None = None, mode: str | None = None
) -> list[dict]:
    """재시작 뒤 미종결 KIS 주문을 조회하며 주문 POST는 다시 보내지 않는다."""
    from brokers.factory import get_broker_adapter

    selected_mode = mode or _selected_broker_mode("kis")
    if adapter is None:
        if not _live_broker_enabled("kis"):
            return []
        if str(selected_mode).lower() == "real" and not _real_broker_allowed("kis"):
            return []
        adapter = get_broker_adapter("kis")

    db_mode = _db_broker_mode(selected_mode)
    results = []
    for stored in db.get_pending_broker_orders(broker="kis", mode=db_mode):
        if stored["status"] == "submitting":
            continue
        if not stored.get("order_no") and stored["status"] != "unknown":
            continue
        try:
            result = _reconcile_stored_order(
                adapter,
                stored,
                broker_mode=f"kis_{'real' if db_mode == 'real' else 'demo'}",
            )
        except Exception as exc:  # fail open for the rest of the recovery batch
            log.warning("  KIS 주문 복구 조회 실패: %s", exc)
            continue
        if result is not None:
            results.append(result)
    return results


async def _execute_kis_broker_order(
    decision: dict, adapter: object, *, mode: str
) -> dict:
    try:
        quantity = _cap_kis_quantity(adapter, decision)
    except Exception as exc:
        return _blocked_order_result(
            decision, "kis", mode, f"KIS 주문 가능 수량 조회 실패: {exc}"
        )
    if quantity <= 0:
        return _blocked_order_result(
            decision, "kis", mode, "KIS 계좌의 주문 가능 수량이 없어 주문하지 않습니다."
        )

    adjusted = {**decision, "quantity": quantity}
    db_mode = _db_broker_mode(mode)
    persisted = db.save_broker_order(
        {
            "run_id": decision.get("run_id"),
            "broker": "kis",
            "mode": db_mode,
            "client_request_id": str(
                decision.get("client_request_id") or uuid4().hex
            ),
            "order_date": datetime.now(tz=KST).date().isoformat(),
            "org_no": None,
            "order_no": None,
            "ticker": adjusted["ticker"],
            "side": adjusted["action"],
            "status": "submitting",
            "requested_qty": quantity,
            "filled_qty": 0,
            "remaining_qty": quantity,
            "requested_price": int(adjusted["price"]),
            "avg_fill_price": None,
            "message": "KIS 주문 제출 전 저장",
        }
    )

    from brokers import BrokerOrder

    try:
        broker_result = await adapter.place_order(
            BrokerOrder(
                action=adjusted["action"],
                ticker=adjusted["ticker"],
                quantity=quantity,
                price=int(adjusted["price"]),
                reason=adjusted.get("reason", ""),
            )
        )
    except Exception as exc:
        rejected = db.update_broker_order(
            {
                **persisted,
                "status": "rejected",
                "message": f"KIS 주문 실패: {exc}",
            }
        )
        return _trade_result_from_order(
            adjusted, rejected, broker_mode=f"kis_{mode}"
        )

    status = str(
        broker_result.get("status")
        or ("accepted" if broker_result.get("success") else "rejected")
    ).lower()
    persisted_status = "rejected" if status == "blocked" else status
    if persisted_status not in {"accepted", "unknown", "rejected"}:
        persisted_status = "accepted" if broker_result.get("success") else "rejected"
    persisted = db.update_broker_order(
        {
            **persisted,
            "status": persisted_status,
            "org_no": broker_result.get("branch_no"),
            "order_no": broker_result.get("order_no"),
            "message": broker_result.get("message") or "",
        }
    )
    result = _trade_result_from_order(
        adjusted,
        persisted,
        broker_mode=broker_result.get("mode") or f"kis_{mode}",
        broker_result=broker_result,
    )
    if status == "blocked":
        result.update(
            {
                "status": "blocked",
                "accepted": False,
                "terminal": True,
                "message": broker_result.get("message") or result["message"],
            }
        )
        return result

    if persisted_status == "accepted" and persisted.get("order_no"):
        try:
            reconciled = _reconcile_stored_order(
                adapter,
                persisted,
                broker_mode=broker_result.get("mode") or f"kis_{mode}",
            )
        except Exception as exc:
            log.warning("  KIS 접수 주문 체결 조회 실패: %s", exc)
        else:
            if reconciled is not None:
                return reconciled
    return result


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
    mode = _selected_broker_mode(broker)
    log.warning("  실거래 요청 감지: 기본 강의 모드에서는 브로커 주문을 차단합니다. broker=%s mode=%s", broker, mode)

    if not _live_broker_enabled(broker):
        return {
            **decision,
            "executed": False,
            "executed_price": None,
            "mode": "live_blocked",
            "pnl": None,
            "broker": broker,
            "message": (
                f"{broker} 주문 차단: LECTURE_ENABLE_LIVE_BROKER=1 "
                f"또는 LECTURE_ENABLE_LIVE_{broker.upper()}=1 없이는 주문하지 않습니다."
            ),
        }

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

    if broker == "kis":
        return await _execute_kis_broker_order(decision, adapter, mode=mode)

    try:
        broker_result = await adapter.place_order(
            BrokerOrder(
                action=decision["action"],
                ticker=decision["ticker"],
                quantity=int(decision["quantity"]),
                price=int(decision["price"]),
                reason=decision.get("reason", ""),
            )
        )
    except Exception as e:  # noqa: BLE001 — 인증/네트워크 실패도 초보자에게 설명 가능해야 함
        return {
            **decision,
            "executed": False,
            "executed_price": None,
            "mode": f"{broker}_{mode}_failed",
            "pnl": None,
            "broker": broker,
            "message": f"{broker} 주문 실패: {e}",
        }

    return {
        **decision,
        "executed": bool(broker_result.get("success")),
        "executed_price": broker_result.get("current_price") or decision["price"],
        "mode": broker_result.get("mode") or f"{broker}_{mode}",
        "pnl": None,
        "broker": broker,
        "order_no": broker_result.get("order_no"),
        "message": broker_result.get("message", ""),
        "broker_result": broker_result,
    }


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
