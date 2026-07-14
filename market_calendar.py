"""KIS 영업일과 한국장 주문 가능 시간을 분리해 판단한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

import db

KST = ZoneInfo("Asia/Seoul")
_ORDER_OPEN = time(9, 0)
_ORDER_CLOSE = time(15, 30)


class _MarketDayClient(Protocol):
    def get_market_day(self, business_date: str) -> dict:
        """Return the official KIS holiday row containing `opnd_yn`."""


@dataclass(frozen=True)
class MarketStatus:
    analysis_allowed: bool
    order_allowed: bool
    reason: str
    business_date: str
    is_open: bool | None
    source: str


class MarketGate:
    """Fail closed for orders while never blocking analysis on calendar errors."""

    def __init__(
        self,
        client: _MarketDayClient,
        clock: Callable[[], datetime] | None = None,
        *,
        broker: str = "kis",
        market: str = "KRX",
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(tz=KST))
        self._broker = broker
        self._market = market

    def check(self, now: datetime | None = None) -> MarketStatus:
        local_now = self._to_kst(now if now is not None else self._clock())
        business_date = local_now.date().isoformat()

        if local_now.weekday() >= 5:
            return MarketStatus(
                analysis_allowed=True,
                order_allowed=False,
                reason="market_closed",
                business_date=business_date,
                is_open=False,
                source="weekend",
            )

        cached = self._read_cache(business_date)
        if cached is not None:
            is_open = bool(cached["is_open"])
            source = "cache"
        else:
            queried = self._query_market_day(business_date)
            if queried is None:
                return MarketStatus(
                    analysis_allowed=True,
                    order_allowed=False,
                    reason="market_status_unknown",
                    business_date=business_date,
                    is_open=None,
                    source="unavailable",
                )
            is_open = queried
            source = "kis_api"

        if not is_open:
            return MarketStatus(
                analysis_allowed=True,
                order_allowed=False,
                reason="market_closed",
                business_date=business_date,
                is_open=False,
                source=source,
            )

        if not (_ORDER_OPEN <= local_now.time().replace(tzinfo=None) < _ORDER_CLOSE):
            return MarketStatus(
                analysis_allowed=True,
                order_allowed=False,
                reason="outside_order_window",
                business_date=business_date,
                is_open=True,
                source=source,
            )

        return MarketStatus(
            analysis_allowed=True,
            order_allowed=True,
            reason="market_open",
            business_date=business_date,
            is_open=True,
            source=source,
        )

    def _read_cache(self, business_date: str) -> dict | None:
        try:
            return db.get_market_day(self._broker, self._market, business_date)
        except Exception:
            return None

    def _query_market_day(self, business_date: str) -> bool | None:
        try:
            result = self._client.get_market_day(business_date)
            opnd_yn = str(result.get("opnd_yn") or "").strip().upper()
            if opnd_yn not in {"Y", "N"}:
                return None
            is_open = opnd_yn == "Y"
            try:
                db.save_market_day(
                    {
                        "broker": self._broker,
                        "market": self._market,
                        "business_date": business_date,
                        "is_open": is_open,
                        "source": "kis_api",
                    }
                )
            except Exception:
                pass
            return is_open
        except Exception:
            return None

    @staticmethod
    def _to_kst(value: datetime) -> datetime:
        if not isinstance(value, datetime):
            raise TypeError("market clock must return datetime")
        if value.tzinfo is None:
            return value.replace(tzinfo=KST)
        return value.astimezone(KST)


__all__ = ["KST", "MarketGate", "MarketStatus"]
