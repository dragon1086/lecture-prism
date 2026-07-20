"""Fail-closed KR order-session gate with an injected KIS calendar source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from prism_core.domain import Market


KST = ZoneInfo("Asia/Seoul")
_SESSION_OPEN = time(9, 0)
_SESSION_CLOSE = time(15, 30)


@dataclass(frozen=True)
class MarketStatus:
    checked_at: datetime
    market_date: str
    order_allowed: bool
    is_business_day: bool | None
    in_session: bool
    reason: str
    source: str


class MarketGate:
    """Allow domestic orders only with positive session and calendar evidence."""

    def __init__(
        self,
        calendar_client,
        *,
        cache_get: Callable[..., Mapping[str, Any] | None] | None = None,
        cache_save: Callable[..., Any] | None = None,
        mode: str = "paper",
        cache_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        if not isinstance(cache_ttl, timedelta) or cache_ttl <= timedelta(0):
            raise ValueError("cache_ttl must be positive")
        self.calendar_client = calendar_client
        self.cache_get = cache_get
        self.cache_save = cache_save
        self.mode = str(mode).strip().lower() or "paper"
        self.cache_ttl = cache_ttl

    @staticmethod
    def _aware(value: object) -> datetime | None:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return None
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value

    @staticmethod
    def _record_date(record: Mapping[str, Any]) -> str | None:
        for key in ("market_date", "trade_date", "business_date"):
            value = record.get(key)
            if isinstance(value, str):
                return value
        return None

    @classmethod
    def _valid_calendar_record(
        cls,
        record: object,
        market_date: str,
    ) -> tuple[bool, bool] | None:
        if not isinstance(record, Mapping):
            return None
        if cls._record_date(record) != market_date:
            return None
        is_open = record.get("is_open")
        if type(is_open) is not bool:
            return None
        opnd_yn = record.get("opnd_yn")
        if opnd_yn is not None and opnd_yn not in {"Y", "N"}:
            return None
        if opnd_yn is not None and (opnd_yn == "Y") is not is_open:
            return None
        return is_open, True

    def _cached_open(
        self,
        record: object,
        *,
        market_date: str,
        now: datetime,
    ) -> bool | None:
        validated = self._valid_calendar_record(record, market_date)
        if validated is None or not isinstance(record, Mapping):
            return None
        checked_at = self._aware(record.get("checked_at"))
        if checked_at is None:
            return None
        age = now.astimezone(checked_at.tzinfo) - checked_at
        if age < timedelta(0) or age > self.cache_ttl:
            return None
        return validated[0]

    @staticmethod
    def _status(
        now: datetime,
        market_date: str,
        *,
        allowed: bool,
        business_day: bool | None,
        in_session: bool,
        reason: str,
        source: str,
    ) -> MarketStatus:
        return MarketStatus(
            checked_at=now,
            market_date=market_date,
            order_allowed=allowed,
            is_business_day=business_day,
            in_session=in_session,
            reason=reason,
            source=source,
        )

    def check(self, now: datetime) -> MarketStatus:
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be a timezone-aware datetime")
        local = now.astimezone(KST)
        market_date = local.strftime("%Y%m%d")
        if local.weekday() >= 5:
            return self._status(
                local,
                market_date,
                allowed=False,
                business_day=False,
                in_session=False,
                reason="weekend",
                source="deterministic",
            )
        in_session = _SESSION_OPEN <= local.time().replace(tzinfo=None) < _SESSION_CLOSE
        if not in_session:
            return self._status(
                local,
                market_date,
                allowed=False,
                business_day=None,
                in_session=False,
                reason="outside_regular_session",
                source="deterministic",
            )

        cached = None
        if self.cache_get is not None:
            try:
                cached = self.cache_get(
                    Market.KR,
                    market_date,
                    broker_mode=self.mode,
                )
            except Exception:
                cached = None
        cached_open = self._cached_open(
            cached,
            market_date=market_date,
            now=local,
        )
        if cached_open is not None:
            return self._status(
                local,
                market_date,
                allowed=cached_open,
                business_day=cached_open,
                in_session=True,
                reason="open" if cached_open else "holiday",
                source="cache",
            )

        try:
            api_record = self.calendar_client.get_market_day(market_date)
            validated = self._valid_calendar_record(api_record, market_date)
            if validated is None:
                raise ValueError("invalid KIS calendar response")
            is_open = validated[0]
        except Exception:
            return self._status(
                local,
                market_date,
                allowed=False,
                business_day=None,
                in_session=True,
                reason="calendar_unavailable",
                source="none",
            )

        if self.cache_save is not None:
            try:
                self.cache_save(
                    Market.KR,
                    market_date,
                    is_open=is_open,
                    source="kis",
                    broker_mode=self.mode,
                    checked_at=local.isoformat(),
                )
            except Exception:
                pass
        return self._status(
            local,
            market_date,
            allowed=is_open,
            business_day=is_open,
            in_session=True,
            reason="open" if is_open else "holiday",
            source="api",
        )
