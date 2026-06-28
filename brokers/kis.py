"""KIS adapter wrapping the existing PRISM/Korea Investment bridge."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .base import BrokerOrder
from .config import normalize_mode


class KISBrokerAdapter:
    name = "kis"

    def __init__(self, *, mode: str | None = None) -> None:
        self.mode = normalize_mode(
            mode or os.getenv("LECTURE_KIS_MODE") or os.getenv("KIS_MODE") or os.getenv("LECTURE_BROKER_MODE"),
            default="demo",
        )

    async def place_order(self, order: BrokerOrder) -> dict[str, Any]:
        if order.side != "BUY":
            return {
                "success": False,
                "mode": f"kis_{self.mode}_unsupported_side",
                "order_no": None,
                "message": "lecture-prism KIS bridge currently exposes buy-only teaching flow.",
            }

        try:
            module_dir = Path(__file__).resolve().parents[1] / "trading" / "trading"
            if str(module_dir) not in sys.path:
                sys.path.insert(0, str(module_dir))
            import domestic_stock_trading as domestic  # type: ignore[import-not-found]

            AsyncTradingContext = domestic.AsyncTradingContext
        except Exception as exc:  # noqa: BLE001 - teaching adapter returns beginner-readable failure
            return {
                "success": False,
                "mode": "kis_import_failed",
                "order_no": None,
                "message": f"KIS 모듈 로드 실패: {exc}",
            }

        price = int(order.price or 0)
        buy_amount = int(order.quantity * price)
        try:
            async with AsyncTradingContext(mode=self.mode, buy_amount=buy_amount) as trader:
                result = await trader.async_buy_stock(
                    stock_code=order.ticker,
                    buy_amount=buy_amount,
                    limit_price=price or None,
                )
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "mode": f"kis_{self.mode}_failed",
                "order_no": None,
                "message": f"KIS 주문 실패: {exc}",
            }

        return {
            "success": bool(result.get("success")),
            "mode": f"kis_{self.mode}",
            "order_no": result.get("order_no"),
            "current_price": result.get("current_price") or price,
            "message": result.get("message", ""),
            "raw": result,
        }
