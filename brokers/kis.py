"""KIS broker adapter backed by the clean-room standard-library client."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from market_calendar import MarketGate, MarketStatus

from .base import BrokerOrder
from .config import normalize_mode
from .kis_client import KISClient, KISConfig

_DEFAULT_KIS_CONFIG = (
    Path(__file__).resolve().parents[1]
    / "trading"
    / "trading"
    / "config"
    / "kis_devlp.yaml"
)


def _yaml_default_mode(config_path: str | Path | None = None) -> str | None:
    """Read the simple `default_mode: demo|real` line without requiring PyYAML."""

    path = Path(config_path) if config_path else _DEFAULT_KIS_CONFIG
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip() == "default_mode":
            return value.strip().strip('"\'') or None
    return None


def selected_kis_mode(
    mode: str | None = None, *, config_path: str | Path | None = None
) -> str:
    """Resolve KIS mode from explicit args, `.env`, then kis_devlp.yaml."""

    return normalize_mode(
        mode
        or os.getenv("LECTURE_KIS_MODE")
        or os.getenv("KIS_MODE")
        or os.getenv("LECTURE_BROKER_MODE")
        or _yaml_default_mode(config_path),
        default="demo",
    )


class KISBrokerAdapter:
    """Map the shared broker contract onto :class:`KISClient` operations.

    Client construction is lazy so importing the module or constructing the
    adapter in the keyless demo path performs no authentication or network I/O.
    """

    name = "kis"

    def __init__(
        self,
        *,
        mode: str | None = None,
        client: KISClient | None = None,
        market_gate: MarketGate | None = None,
    ) -> None:
        self.mode = selected_kis_mode(mode)
        self._client = client
        self._market_gate = market_gate

    def _get_client(self) -> KISClient:
        if self._client is None:
            client_mode = "paper" if self.mode == "demo" else "real"
            self._client = KISClient(KISConfig.from_env(mode=client_mode))
        return self._client

    def _get_market_gate(self) -> MarketGate:
        if self._market_gate is None:
            self._market_gate = MarketGate(self._get_client())
        return self._market_gate

    async def place_order(self, order: BrokerOrder) -> dict[str, Any]:
        side = order.side
        if side not in {"BUY", "SELL"}:
            return self._blocked_result(
                "unsupported_side", "KIS 주문 방향은 BUY 또는 SELL이어야 합니다."
            )

        try:
            market = self._get_market_gate().check()
        except Exception as exc:  # configuration failures must fail closed
            return self._failed_result(exc)
        if not market.order_allowed:
            return self._blocked_result(
                market.reason,
                "현재 시장 상태에서는 주문하지 않습니다. 분석 결과는 계속 사용할 수 있습니다.",
                market=market,
            )

        price = int(order.price or 0)
        try:
            result = self._get_client().place_cash_order(
                order.ticker, side, int(order.quantity), price
            )
        except Exception as exc:  # KIS client exceptions contain safe summaries only
            return self._failed_result(exc)

        status = str(result.get("status") or "rejected").strip().lower()
        accepted = status in {"accepted", "unfilled", "partial_fill", "filled"}
        executed = status == "filled"
        terminal = status in {"filled", "cancelled", "rejected"}
        message = str(result.get("message") or "")
        if status == "accepted" and not message:
            message = "KIS 주문이 접수되었습니다. 체결 조회 전에는 체결로 보지 않습니다."
        return {
            "success": bool(result.get("success")),
            "mode": f"kis_{self.mode}",
            "status": status,
            "accepted": accepted,
            "executed": executed,
            "terminal": terminal,
            "order_no": result.get("order_no"),
            "branch_no": result.get("branch_no"),
            "current_price": price,
            "requires_reconciliation": bool(
                result.get("requires_reconciliation", not terminal)
            ),
            "message": message,
            "raw": result,
        }

    def get_account(self) -> dict[str, Any]:
        return self._get_client().get_balance()

    def get_order_status(self, order_no: str, **kwargs: Any) -> dict[str, Any]:
        return self._get_client().get_order_status(order_no, **kwargs)

    def cancel_order(
        self, order_no: str, quantity: int, **kwargs: Any
    ) -> dict[str, Any]:
        return self._get_client().cancel_order(order_no, quantity, **kwargs)

    def is_market_open(self, now: datetime | None = None) -> bool:
        return self._get_market_gate().check(now).order_allowed

    def _blocked_result(
        self,
        reason: str,
        message: str,
        *,
        market: MarketStatus | None = None,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "mode": f"kis_{self.mode}_blocked",
            "status": "blocked",
            "accepted": False,
            "executed": False,
            "terminal": True,
            "order_no": None,
            "reason": reason,
            "analysis_allowed": (
                market.analysis_allowed if market is not None else True
            ),
            "message": message,
        }

    def _failed_result(self, exc: Exception) -> dict[str, Any]:
        return {
            "success": False,
            "mode": f"kis_{self.mode}_failed",
            "status": "rejected",
            "accepted": False,
            "executed": False,
            "terminal": True,
            "order_no": None,
            "message": f"KIS 요청 실패: {exc}",
        }


__all__ = ["KISBrokerAdapter", "selected_kis_mode"]
