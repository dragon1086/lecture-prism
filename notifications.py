"""비밀값 없이 파이프라인 이벤트를 외부 알림 채널로 전달한다."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Protocol, Sequence

import db


logger = logging.getLogger(__name__)

_DISCORD_MESSAGE_LIMIT = 2_000
_TELEGRAM_MESSAGE_LIMIT = 4_096
_STOP = object()

_DISCORD_WEBHOOK_RE = re.compile(
    r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\S+",
    re.IGNORECASE,
)
_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_NAMED_SECRET_RE = re.compile(
    r"(?ix)"
    r"(?P<prefix>\b(?:token|secret|api[_-]?key|app[_-]?key|authorization|password)"
    r"\b[\"']?\s*[:=]\s*)"
    r"(?:"
    r"(?P<quote>[\"'])(?P<quoted_value>[^\"']*)(?P=quote)"
    r"|(?P<bare_value>[^\s,;}]+)"
    r")"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, repr=False)
class PipelineEvent:
    """한 번의 파이프라인 실행에서 발생한 순서 있는 이벤트."""

    run_id: str
    sequence: int
    event_type: str
    status: str = "succeeded"
    occurred_at: str = field(default_factory=_utc_now)
    profile: str = "mock"
    trade_state: str = "simulation"
    data_source: str | None = None
    data_as_of: str | None = None
    ticker: str | None = None
    summary: str = ""
    details: dict[str, object] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            "PipelineEvent("
            f"run_id={self.run_id!r}, sequence={self.sequence!r}, "
            f"event_type={self.event_type!r}, status={self.status!r})"
        )


class NotificationChannel(Protocol):
    """Dispatcher가 사용하는 최소 알림 채널 계약."""

    name: str
    enabled: bool

    async def send(self, event: PipelineEvent) -> int:
        """이벤트를 보내고 실제 HTTP 시도 횟수를 반환한다."""


class NotificationDeliveryError(RuntimeError):
    """인증 정보나 요청 URL을 포함하지 않는 전달 실패."""

    def __init__(self, message: str, *, attempts: int):
        super().__init__(message)
        self.attempts = attempts


def split_message(message: str, *, limit: int) -> list[str]:
    """줄 경계를 우선해 메시지를 제한 길이 이하 조각으로 나눈다."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    if not message:
        return [""]

    chunks: list[str] = []
    remainder = message
    while len(remainder) > limit:
        boundary = remainder.rfind("\n", 0, limit + 1)
        cut = boundary + 1 if boundary >= 0 else limit
        if cut == 0:
            cut = limit
        chunks.append(remainder[:cut])
        remainder = remainder[cut:]
    if remainder:
        chunks.append(remainder)
    return chunks


def sanitize_notification_text(value: object) -> str:
    """알림 프로세스 경계를 넘기 전에 알려진 인증정보 패턴을 제거한다."""
    text = str(value)
    text = _DISCORD_WEBHOOK_RE.sub("[REDACTED]", text)
    text = _TELEGRAM_TOKEN_RE.sub("[REDACTED]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)

    def redact_named_secret(match: re.Match) -> str:
        quote = match.group("quote") or ""
        return f"{match.group('prefix')}{quote}[REDACTED]{quote}"

    return _NAMED_SECRET_RE.sub(redact_named_secret, text)


def _format_event(event: PipelineEvent) -> str:
    lines = [
        f"[{event.status}] {event.event_type}",
        f"실행 {event.run_id} · 순서 {event.sequence}",
        f"프로필 {event.profile} · 거래 상태 {event.trade_state}",
    ]
    if event.ticker:
        lines.append(f"종목 {event.ticker}")
    if event.data_source or event.data_as_of:
        source = event.data_source or "unknown"
        data_as_of = event.data_as_of or "unknown"
        lines.append(f"데이터 {source} · 기준일 {data_as_of}")
    if event.summary:
        lines.append(event.summary)
    return sanitize_notification_text("\n".join(lines))


class _DisabledChannel:
    enabled = False

    def __init__(self, name: str):
        self.name = name

    async def send(self, event: PipelineEvent) -> int:
        return 0

    def __repr__(self) -> str:
        return f"DisabledChannel(name={self.name!r})"


class _HttpNotificationChannel:
    enabled = True

    def __init__(
        self,
        *,
        name: str,
        endpoint: str,
        message_limit: int,
        timeout: float = 5.0,
        max_retries: int = 2,
        retry_backoff: float = 0.25,
        max_retry_after: float = 5.0,
    ):
        self.name = name
        self._endpoint = endpoint
        self._message_limit = message_limit
        self._timeout = max(0.1, min(float(timeout), 30.0))
        self._max_attempts = max(1, min(int(max_retries) + 1, 6))
        self._retry_backoff = max(0.0, min(float(retry_backoff), 5.0))
        self._max_retry_after = max(0.0, min(float(max_retry_after), 60.0))

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r}, enabled=True)"

    async def send(self, event: PipelineEvent) -> int:
        attempts = 0
        for chunk in split_message(_format_event(event), limit=self._message_limit):
            try:
                attempts += await self._send_chunk(chunk)
            except NotificationDeliveryError as exc:
                exc.attempts += attempts
                raise
        return attempts

    async def _send_chunk(self, chunk: str) -> int:
        payload = self._payload(chunk)
        for attempt in range(1, self._max_attempts + 1):
            try:
                await asyncio.to_thread(
                    _post_json, self._endpoint, payload, self._timeout
                )
                return attempt
            except Exception as exc:
                delay = _retry_delay(
                    exc,
                    attempt=attempt,
                    retry_backoff=self._retry_backoff,
                    max_retry_after=self._max_retry_after,
                )
                if attempt >= self._max_attempts or delay is None:
                    raise NotificationDeliveryError(
                        f"{self.name} notification failed ({_safe_error_kind(exc)})",
                        attempts=attempt,
                    ) from None
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    def _payload(self, chunk: str) -> dict[str, object]:
        raise NotImplementedError


class DiscordChannel(_HttpNotificationChannel):
    """Discord Incoming Webhook 채널. 모든 멘션을 명시적으로 끈다."""

    def __init__(
        self,
        webhook_url: str,
        *,
        timeout: float = 5.0,
        max_retries: int = 2,
        retry_backoff: float = 0.25,
        max_retry_after: float = 5.0,
    ):
        separator = "&" if "?" in webhook_url else "?"
        endpoint = (
            webhook_url
            if "wait=" in urllib.parse.urlsplit(webhook_url).query
            else f"{webhook_url}{separator}wait=true"
        )
        super().__init__(
            name="discord",
            endpoint=endpoint,
            message_limit=_DISCORD_MESSAGE_LIMIT,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            max_retry_after=max_retry_after,
        )

    def _payload(self, chunk: str) -> dict[str, object]:
        return {
            "content": chunk,
            "allowed_mentions": {"parse": [], "replied_user": False},
        }


class TelegramChannel(_HttpNotificationChannel):
    """Telegram Bot API plain-text sendMessage 채널."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        timeout: float = 5.0,
        max_retries: int = 2,
        retry_backoff: float = 0.25,
        max_retry_after: float = 5.0,
    ):
        self._chat_id = chat_id
        super().__init__(
            name="telegram",
            endpoint=f"https://api.telegram.org/bot{bot_token}/sendMessage",
            message_limit=_TELEGRAM_MESSAGE_LIMIT,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            max_retry_after=max_retry_after,
        )

    def _payload(self, chunk: str) -> dict[str, object]:
        return {"chat_id": self._chat_id, "text": chunk}


def _post_json(endpoint: str, payload: dict[str, object], timeout: float) -> None:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout) as response:
        status = int(getattr(response, "status", 200))
        response.read()
        if not 200 <= status < 300:
            raise urllib.error.HTTPError(
                endpoint, status, "notification request failed", response.headers, None
            )


def _retry_delay(
    exc: Exception,
    *,
    attempt: int,
    retry_backoff: float,
    max_retry_after: float,
) -> float | None:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            retry_after = _read_retry_after(exc)
            if retry_after is not None:
                return max(0.0, min(retry_after, max_retry_after))
        elif not 500 <= exc.code < 600:
            return None
    elif not isinstance(
        exc, (TimeoutError, socket.timeout, urllib.error.URLError)
    ):
        return None
    return min(retry_backoff * (2 ** (attempt - 1)), max_retry_after)


def _read_retry_after(exc: urllib.error.HTTPError) -> float | None:
    value = exc.headers.get("Retry-After") if exc.headers else None
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except Exception:
        return None
    candidate = body.get("retry_after")
    if candidate is None and isinstance(body.get("parameters"), dict):
        candidate = body["parameters"].get("retry_after")
    try:
        return float(candidate)
    except (TypeError, ValueError):
        return None


def _safe_error_kind(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        return "network error"
    return "transport error"


class NotificationDispatcher:
    """단일 worker로 이벤트 순서를 보존하고 채널별 전달은 병렬화한다."""

    def __init__(self, channels: Sequence[NotificationChannel]):
        self.channels = tuple(channels)
        self._queue: asyncio.Queue[PipelineEvent | object] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._enqueued: set[tuple[str, int]] = set()
        self.closed = False

    async def start(self) -> None:
        if self.closed:
            raise RuntimeError("notification dispatcher is closed")
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker())

    async def enqueue(self, event: PipelineEvent) -> None:
        if self.closed:
            raise RuntimeError("notification dispatcher is closed")
        if self._worker_task is None:
            raise RuntimeError("notification dispatcher is not started")
        key = (event.run_id, event.sequence)
        if key in self._enqueued:
            return
        self._enqueued.add(key)
        for channel in self.channels:
            enabled = bool(getattr(channel, "enabled", True))
            _persist_delivery(
                event,
                channel=_channel_name(channel),
                status="queued" if enabled else "skipped",
                attempts=0,
            )
        await self._queue.put(event)

    async def close(self, timeout: float = 5.0) -> None:
        if self.closed:
            return
        self.closed = True
        task = self._worker_task
        if task is None:
            return
        await self._queue.put(_STOP)
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=max(0.0, timeout))
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            logger.warning(
                "Notification dispatcher close timed out; pending work was cancelled"
            )
        finally:
            self._worker_task = None

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is _STOP:
                    return
                await self._deliver(item)
            finally:
                self._queue.task_done()

    async def _deliver(self, event: PipelineEvent) -> None:
        await asyncio.gather(
            *(self._deliver_channel(channel, event) for channel in self.channels),
            return_exceptions=True,
        )

    async def _deliver_channel(
        self, channel: NotificationChannel, event: PipelineEvent
    ) -> None:
        name = _channel_name(channel)
        if not bool(getattr(channel, "enabled", True)):
            _persist_delivery(
                event, channel=name, status="skipped", attempts=0
            )
            return
        try:
            result = await channel.send(event)
        except Exception as exc:
            attempts = max(1, int(getattr(exc, "attempts", 1)))
            _persist_delivery(
                event,
                channel=name,
                status="failed",
                attempts=attempts,
                error=f"{type(exc).__name__}: notification delivery failed",
            )
            return
        attempts = max(1, int(result or 1))
        _persist_delivery(
            event, channel=name, status="sent", attempts=attempts
        )


def _channel_name(channel: NotificationChannel) -> str:
    try:
        name = str(channel.name).lower()
    except Exception:
        name = "notification"
    if name in {"discord", "telegram"}:
        return name
    return type(channel).__name__.strip("_").lower()[:40] or "notification"


def _persist_delivery(
    event: PipelineEvent,
    *,
    channel: str,
    status: str,
    attempts: int,
    error: str | None = None,
) -> None:
    try:
        db.save_notification_delivery(
            {
                "run_id": event.run_id,
                "sequence": event.sequence,
                "channel": channel,
                "status": status,
                "attempts": attempts,
                "error": error,
            }
        )
    except Exception:
        logger.warning("Notification delivery status could not be persisted")


def _enabled(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def build_notification_dispatcher(
    environ: Mapping[str, str] | None = None,
) -> NotificationDispatcher:
    """환경설정이 없거나 불완전해도 안전한 no-op dispatcher를 만든다."""
    settings = os.environ if environ is None else environ
    channels: list[NotificationChannel] = []

    discord_enabled = _enabled(settings.get("LECTURE_NOTIFY_DISCORD"))
    webhook_url = settings.get("DISCORD_WEBHOOK_URL", "").strip()
    if discord_enabled and webhook_url:
        channels.append(DiscordChannel(webhook_url))
    else:
        channels.append(_DisabledChannel("discord"))
        if discord_enabled:
            logger.warning(
                "Discord notifications are disabled because configuration is incomplete"
            )

    telegram_enabled = _enabled(settings.get("LECTURE_NOTIFY_TELEGRAM"))
    bot_token = settings.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = settings.get("TELEGRAM_CHAT_ID", "").strip()
    if telegram_enabled and bot_token and chat_id:
        channels.append(TelegramChannel(bot_token, chat_id))
    else:
        channels.append(_DisabledChannel("telegram"))
        if telegram_enabled:
            logger.warning(
                "Telegram notifications are disabled because configuration is incomplete"
            )

    return NotificationDispatcher(channels)


__all__ = [
    "DiscordChannel",
    "NotificationChannel",
    "NotificationDeliveryError",
    "NotificationDispatcher",
    "PipelineEvent",
    "TelegramChannel",
    "build_notification_dispatcher",
    "sanitize_notification_text",
    "split_message",
]
