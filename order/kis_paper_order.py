"""`.env`에서 선택한 KIS 환경으로 국내주식 1주 시장가 주문을 전송합니다."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brokers.base import real_mode_mutation_block
from brokers.config import any_truthy, load_env_file
from brokers.kis import selected_kis_mode
from brokers.kis_client import KISClient, KISConfig


ORDER_QUANTITY = 1
MARKET_ORDER_PRICE = 0


def _domestic_ticker(value: str) -> str:
    ticker = str(value).strip()
    if len(ticker) != 6 or not ticker.isascii() or not ticker.isdigit():
        raise ValueError("국내주식 종목코드는 숫자 6자리여야 합니다.")
    return ticker


def _order_client() -> KISClient:
    load_env_file(PROJECT_ROOT / ".env")
    mode = selected_kis_mode()
    config_mode = "paper" if mode == "demo" else "real"
    try:
        config = KISConfig.from_env(config_mode)
    except ValueError as exc:
        prefix = "KIS_PAPER" if config_mode == "paper" else "KIS_REAL"
        raise ValueError(
            f".env에 {prefix}_APP_KEY, {prefix}_APP_SECRET, "
            f"{prefix}_ACCOUNT_NO를 입력해 주세요."
        ) from exc
    return KISClient(
        config,
        token_cache_path=PROJECT_ROOT / ".cache" / f"KIS_{config_mode}_order.token",
    )


def run(
    ticker: str,
    *,
    client: KISClient | None = None,
    on_quote: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """선택한 KIS 환경으로 1주 시장가 매수 주문을 전송합니다."""

    selected_ticker = _domestic_ticker(ticker)
    selected_client = client or _order_client()
    if not any_truthy(("LECTURE_ENABLE_LIVE_BROKER", "LECTURE_ENABLE_LIVE_KIS")):
        return {
            "success": False,
            "status": "blocked",
            "accepted": False,
            "executed": False,
            "terminal": True,
            "mode": f"kis_{selected_client.config.mode}_live_gate_blocked",
            "order_no": None,
            "message": (
                "KIS 주문 전송 차단: LECTURE_ENABLE_LIVE_BROKER=1 또는 "
                "LECTURE_ENABLE_LIVE_KIS=1을 설정해야 합니다."
            ),
            "ticker": selected_ticker,
            "quantity": ORDER_QUANTITY,
            "side": "BUY",
            "order_type": "MARKET",
            "order_price": MARKET_ORDER_PRICE,
            "sent": False,
        }
    blocked = real_mode_mutation_block("kis", selected_client.config.mode)
    if blocked is not None:
        return {
            **blocked,
            "ticker": selected_ticker,
            "quantity": ORDER_QUANTITY,
            "side": "BUY",
            "order_type": "MARKET",
            "order_price": MARKET_ORDER_PRICE,
            "sent": False,
        }

    quote = selected_client.get_quote(selected_ticker)
    order = {
        "ticker": selected_ticker,
        "mode": selected_client.config.mode,
        "quote_price": int(quote.price),
        "currency": quote.currency,
        "quote_source": quote.source,
        "quantity": ORDER_QUANTITY,
        "side": "BUY",
        "order_type": "MARKET",
        "order_price": MARKET_ORDER_PRICE,
        "sent": False,
    }
    if on_quote is not None:
        on_quote(dict(order))
    result = selected_client.place_cash_order(
        selected_ticker,
        "BUY",
        ORDER_QUANTITY,
        MARKET_ORDER_PRICE,
    )
    return {**order, **result, "sent": True}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=".env에서 선택한 KIS 환경으로 국내주식 1주 시장가 매수"
    )
    parser.add_argument("ticker", help="국내주식 종목코드 6자리")
    return parser


def main() -> int:
    args = _parser().parse_args()
    quote_displayed = False

    def show_quote(order: dict[str, Any]) -> None:
        nonlocal quote_displayed
        print(f"종목코드: {order['ticker']}")
        print(f"조회 가격: {order['quote_price']:,}원")
        print("주문 내용: 시장가 매수 1주", flush=True)
        quote_displayed = True

    try:
        result = run(args.ticker, on_quote=show_quote)
    except Exception as exc:  # 명령줄에서는 비밀값 없이 한 줄로 실패를 알립니다.
        stage = "주문 실패" if quote_displayed else "실행 실패"
        print(f"{stage}: {exc}", file=sys.stderr)
        return 1

    if result["status"] == "blocked":
        print(f"종목코드: {result['ticker']}")
        print(f"주문 차단: {result['message']}")
        return 1
    if result["sent"]:
        mode_label = "모의" if result.get("mode") == "paper" else "실전"
        print(f"{mode_label}주문 결과: {result['status']}")
        if result.get("order_no"):
            print(f"주문 번호: {result['order_no']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
