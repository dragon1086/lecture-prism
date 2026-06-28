"""Toss Securities adapter placeholder.

As of 2026-06-28, public official Toss developer docs that are reachable from
Toss Payments/Toss Invest do not expose a retail securities trading order API.
This adapter is intentionally safe: it gives students a file to extend if they
bring partner/private Toss Securities API documentation, but it never guesses an
endpoint and never sends an order.
"""

from __future__ import annotations

import os
from typing import Any

from .base import BrokerOrder
from .config import mask_secret, normalize_mode


class TossBrokerAdapter:
    name = "toss"

    def __init__(self, *, mode: str | None = None) -> None:
        self.mode = normalize_mode(mode or os.getenv("TOSS_SECURITIES_MODE") or os.getenv("LECTURE_BROKER_MODE"), default="demo")
        self.base_url = os.getenv("TOSS_SECURITIES_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("TOSS_SECURITIES_API_KEY")
        self.account_id = os.getenv("TOSS_SECURITIES_ACCOUNT_ID")

    async def place_order(self, order: BrokerOrder) -> dict[str, Any]:
        return {
            "success": False,
            "mode": "toss_unsupported",
            "order_no": None,
            "message": (
                "토스증권 공개 주문 API 공식 문서를 확인할 수 없어 주문을 보내지 않았습니다. "
                "수강생이 파트너/비공개 문서를 가져온 경우 이 파일에 실제 토큰·주문 엔드포인트를 채우세요."
            ),
            "credentials": {
                "mode": self.mode,
                "base_url": self.base_url or "missing",
                "api_key": mask_secret(self.api_key),
                "account_id": mask_secret(self.account_id),
            },
            "requested_order": {
                "action": order.side,
                "ticker": order.ticker,
                "quantity": order.quantity,
                "price": order.price,
            },
        }
