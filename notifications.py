"""Optional decision notifications for lecture-prism.

Messages contain screening and AI decision evidence only. Account balances,
account identifiers, broker credentials, webhook values, bot tokens, and
channel IDs never enter the message formatters.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from brokers.config import load_dotenv_once, truthy

log = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 2_000
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_RETRY_AFTER_SECONDS = 5.0
_DISCORD_HOSTS = frozenset({"discord.com", "discordapp.com"})
_TELEGRAM_TOKEN_RE = re.compile(r"^[1-9]\d{4,}:[A-Za-z0-9_-]{20,}$")
_TELEGRAM_CHANNEL_RE = re.compile(r"^(?:-?\d+|@[A-Za-z0-9_]{5,})$")
_SECTION_ROWS = (
    ("기술", "technical_summary"),
    ("수급", "supply_summary"),
    ("재무", "financial_summary"),
    ("산업", "industry_summary"),
    ("뉴스", "news_summary"),
    ("시장", "market_condition"),
)


def _short(value, limit: int = 180) -> str:
    text = " ".join(str(value or "-").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _content(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= MAX_CONTENT_CHARS:
        return cleaned
    return cleaned[: MAX_CONTENT_CHARS - 1].rstrip() + "…"


def _money(value) -> str:
    try:
        return f"{int(float(value)):,}원"
    except (TypeError, ValueError):
        return "-"


def is_valid_discord_webhook_url(value: str) -> bool:
    """Accept only Discord HTTPS Incoming Webhook endpoints."""

    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    host_allowed = host in _DISCORD_HOSTS or any(
        host.endswith("." + allowed) for allowed in _DISCORD_HOSTS
    )
    parts = [part for part in parsed.path.split("/") if part]
    return (
        parsed.scheme == "https"
        and host_allowed
        and len(parts) >= 4
        and parts[0] == "api"
        and parts[1] == "webhooks"
        and bool(parts[2])
        and bool(parts[3])
    )


def is_valid_telegram_bot_token(value: str) -> bool:
    """Accept the documented Telegram bot-token shape without logging it."""

    return bool(_TELEGRAM_TOKEN_RE.fullmatch(str(value or "").strip()))


def is_valid_telegram_channel_id(value: str) -> bool:
    """Accept numeric chat IDs or public @channel usernames."""

    return bool(_TELEGRAM_CHANNEL_RE.fullmatch(str(value or "").strip()))


def _confirmation_url(webhook_url: str) -> str:
    parsed = urlsplit(webhook_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["wait"] = "true"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def format_screening_message(
    candidates: list[str], *, data_mode: str, use_real_data: bool
) -> str:
    from screening import (
        MAX_CANDIDATES,
        MIN_MARKET_CAP_KRW,
        MOMENTUM_DAYS,
        VOLUME_SURGE_RATIO,
    )

    source = "실데이터 우선" if use_real_data else f"{data_mode} 연습 데이터"
    selected = ", ".join(candidates) if candidates else "선정 종목 없음"
    return _content(
        "\n".join(
            [
                "🔎 **스크리닝 완료**",
                f"- 데이터: {source}",
                (
                    f"- 기준: 거래량 {VOLUME_SURGE_RATIO:g}배 이상 · "
                    f"시가총액 {MIN_MARKET_CAP_KRW / 100_000_000:,.0f}억 이상 · "
                    f"{'·'.join(str(day) for day in MOMENTUM_DAYS)}일선 확인"
                ),
                f"- 최종 후보 {len(candidates)}/{MAX_CANDIDATES}: **{selected}**",
                "- 이 결과는 후보 선별이며 매수 주문이 아닙니다.",
            ]
        )
    )


def format_analysis_message(result: dict) -> str:
    company = result.get("company_name") or result.get("ticker", "?")
    ticker = result.get("ticker", "?")
    lines = [
        f"🧠 **종목 분석 · {company} ({ticker})**",
        (
            f"- 판단: **{result.get('recommendation', 'PASS')}** "
            f"({result.get('decision', '보류')}) · "
            f"매수점수 {result.get('buy_score', 0)}/10"
        ),
        f"- 데이터: {_short(result.get('data_source'), 80)}",
        (
            f"- 현재가 {_money(result.get('current_price'))} · "
            f"목표가 {_money(result.get('target_price'))} · "
            f"손절가 {_money(result.get('stop_loss'))} · "
            f"손익비 {result.get('risk_reward_ratio', '-')} : 1"
        ),
    ]
    for label, key in _SECTION_ROWS:
        lines.append(f"- {label}: {_short(result.get(key))}")
    lines.extend(
        [
            f"- 종합 근거: {_short(result.get('rationale'), 220)}",
            f"- 주요 위험: {_short(result.get('risk'), 180)}",
        ]
    )
    return _content("\n".join(lines))


def _format_trade_result(result: dict) -> str:
    action = str(result.get("action") or "PASS").upper()
    ticker = result.get("ticker", "?")
    status = result.get("status", "decision")
    executed = bool(result.get("executed"))
    quantity = int(result.get("filled_qty") or result.get("quantity") or 0)
    price = result.get("executed_price") or result.get("price")
    if executed:
        outcome = f"{status} · {quantity}주 · {_money(price)}"
    else:
        outcome = f"{status} · 실제 체결 없음"
    return _content(
        "\n".join(
            [
                f"⚖️ **매매 판단 · {ticker} · {action}**",
                f"- 결과: {outcome}",
                f"- 모드: {result.get('mode', 'simulation')}",
                f"- 근거: {_short(result.get('reason') or result.get('message'), 300)}",
            ]
        )
    )


def format_trading_messages(analyses: list[dict], trades: list[dict]) -> list[str]:
    messages = [_format_trade_result(result) for result in trades]
    decided = {str(result.get("ticker")) for result in trades}
    for result in analyses:
        ticker = str(result.get("ticker", "?"))
        if ticker in decided:
            continue
        recommendation = str(result.get("recommendation") or "PASS").upper()
        if recommendation == "BUY":
            label = "BUY → 보류"
            reason = "분석은 BUY였지만 매매 단계의 안전 조건을 통과하지 못했습니다."
        else:
            label = f"{recommendation} · 보류"
            reason = result.get("rationale") or result.get("risk")
        messages.append(
            _content(
                "\n".join(
                    [
                        f"⚖️ **매매 판단 · {ticker} · {label}**",
                        "- 결과: 실제 주문·체결 없음",
                        f"- 근거: {_short(reason, 300)}",
                    ]
                )
            )
        )
    return messages


def format_decision_summary(analyses: list[dict], trades: list[dict]) -> str:
    buckets: dict[str, list[str]] = {"SELL": [], "BUY": [], "HOLD": [], "PASS": []}
    decided: set[str] = set()
    for result in trades:
        action = str(result.get("action") or "PASS").upper()
        ticker = str(result.get("ticker", "?"))
        decided.add(ticker)
        bucket = action if action in buckets else "PASS"
        buckets[bucket].append(f"{ticker} — {_short(result.get('reason'), 90)}")
    for result in analyses:
        ticker = str(result.get("ticker", "?"))
        if ticker in decided:
            continue
        recommendation = str(result.get("recommendation") or "PASS").upper()
        bucket = recommendation if recommendation in {"HOLD", "PASS"} else "HOLD"
        buckets[bucket].append(f"{ticker} — {_short(result.get('rationale'), 90)}")

    lines = [
        "📌 **오늘의 AI 판단 요약**",
        "- 이번 실행에서 나온 판단과 근거를 한데 묶었습니다.",
    ]
    for action, label in (
        ("SELL", "매도 판단"),
        ("BUY", "매수 판단"),
        ("HOLD", "보류 판단"),
        ("PASS", "제외 판단"),
    ):
        values = buckets[action]
        lines.append(f"- {label} {len(values)}건")
        lines.extend(f"  - {value}" for value in values)
    return _content("\n".join(lines))


def format_feedback_message(analyses: list[dict], trades: list[dict]) -> str:
    """Describe the records saved after the feedback stage completes."""

    filled = [
        result
        for result in trades
        if result.get("status") == "filled"
        and result.get("executed") is True
        and int(result.get("filled_qty") or 0) > 0
    ]
    lessons = [
        result
        for result in filled
        if str(result.get("action") or "").upper() == "SELL"
    ]
    return _content(
        "\n".join(
            [
                "💾 **피드백 저장 완료**",
                f"- 분석 이력 {len(analyses)}건 → prism.db",
                f"- 가상 체결 기록 {len(filled)}건",
                f"- 결과 교훈 {len(lessons)}건",
                "- BUY 직후에는 결과 교훈을 만들지 않고, SELL 뒤에만 남깁니다.",
            ]
        )
    )


def format_operational_message(event: str, context: dict | None = None) -> str:
    """Format scheduler/service notifications without raw operational secrets."""

    from operations_runtime import sanitize_operations_fields

    safe = sanitize_operations_fields(context or {})
    lines = [f"🛠 **운영 이벤트 · {event}**"]
    for key in (
        "profile",
        "job",
        "status",
        "error",
        "error_type",
        "blocked_reasons",
        "last_data_at",
        "next_run_at",
    ):
        if key in safe:
            lines.append(f"- {key}: {_short(safe[key], 220)}")
    for key in sorted(set(safe) - {
        "profile",
        "job",
        "status",
        "error",
        "error_type",
        "blocked_reasons",
        "last_data_at",
        "next_run_at",
    }):
        lines.append(f"- {key}: {_short(safe[key], 120)}")
    return _content("\n".join(lines))


class _DecisionNotifierMixin:
    async def send(self, content: str) -> bool:
        raise NotImplementedError

    async def screening(
        self,
        candidates: list[str],
        *,
        data_mode: str,
        use_real_data: bool,
    ) -> bool:
        return await self.send(
            format_screening_message(
                candidates,
                data_mode=data_mode,
                use_real_data=use_real_data,
            )
        )

    async def analysis(self, result: dict) -> bool:
        return await self.send(format_analysis_message(result))

    async def trading(self, analyses: list[dict], trades: list[dict]) -> bool:
        messages = format_trading_messages(analyses, trades)
        outcomes = [await self.send(message) for message in messages]
        return all(outcomes) if outcomes else True

    async def summary(self, analyses: list[dict], trades: list[dict]) -> bool:
        return await self.send(format_decision_summary(analyses, trades))

    async def feedback(self, analyses: list[dict], trades: list[dict]) -> bool:
        return await self.send(format_feedback_message(analyses, trades))

    async def operational(self, event: str, context: dict | None = None) -> bool:
        return await self.send(format_operational_message(event, context))


class NullNotifier:
    """Drop-in notifier used when no report provider is configured."""

    enabled = False

    async def send(self, content: str) -> bool:
        _ = content
        return False

    async def screening(self, candidates: list[str], **context) -> bool:
        _ = candidates, context
        return False

    async def analysis(self, result: dict) -> bool:
        _ = result
        return False

    async def trading(self, analyses: list[dict], trades: list[dict]) -> bool:
        _ = analyses, trades
        return False

    async def summary(self, analyses: list[dict], trades: list[dict]) -> bool:
        _ = analyses, trades
        return False

    async def feedback(self, analyses: list[dict], trades: list[dict]) -> bool:
        _ = analyses, trades
        return False

    async def operational(self, event: str, context: dict | None = None) -> bool:
        _ = event, context
        return False


class DiscordNotifier(_DecisionNotifierMixin):
    enabled = True

    def __init__(
        self,
        webhook_url: str,
        *,
        opener: Callable = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not is_valid_discord_webhook_url(webhook_url):
            raise ValueError("invalid Discord webhook URL")
        self._webhook_url = _confirmation_url(webhook_url)
        self._opener = opener
        self._sleep = sleep
        self._timeout_seconds = timeout_seconds

    async def send(self, content: str) -> bool:
        try:
            return await asyncio.to_thread(self._send_sync, _content(content))
        except Exception as exc:  # noqa: BLE001 - 알림 실패는 파이프라인과 분리
            log.warning("Discord 알림 실패: %s", type(exc).__name__)
            return False

    def _send_sync(self, content: str) -> bool:
        payload = json.dumps(
            {
                "content": content,
                "allowed_mentions": {"parse": []},
            },
            ensure_ascii=False,
        ).encode("utf-8")

        for attempt in range(2):
            request = Request(
                self._webhook_url,
                data=payload,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "lecture-prism/discord-notifier",
                },
                method="POST",
            )
            try:
                with self._opener(request, timeout=self._timeout_seconds) as response:
                    status = int(getattr(response, "status", 204))
                    response.read()
                if 200 <= status < 300:
                    return True
                log.warning("Discord 알림 실패: HTTP %s", status)
                return False
            except HTTPError as exc:
                if exc.code == 429 and attempt == 0:
                    delay = self._retry_delay(exc)
                    self._sleep(delay)
                    continue
                log.warning("Discord 알림 실패: HTTP %s", exc.code)
                return False
            except (URLError, TimeoutError, OSError) as exc:
                log.warning("Discord 알림 실패: %s", type(exc).__name__)
                return False
        return False

    @staticmethod
    def _retry_delay(error: HTTPError) -> float:
        raw = error.headers.get("Retry-After") if error.headers else None
        if raw in (None, ""):
            try:
                body = json.loads(error.read().decode("utf-8"))
                raw = body.get("retry_after", 0)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                raw = 0
        try:
            delay = float(raw)
        except (TypeError, ValueError):
            delay = 0.0
        return min(max(delay, 0.0), MAX_RETRY_AFTER_SECONDS)


class TelegramNotifier(_DecisionNotifierMixin):
    enabled = True

    def __init__(
        self,
        bot_token: str,
        channel_id: str,
        *,
        opener: Callable = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not is_valid_telegram_bot_token(bot_token):
            raise ValueError("invalid Telegram bot token")
        if not is_valid_telegram_channel_id(channel_id):
            raise ValueError("invalid Telegram channel ID")
        self._api_url = (
            f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
        )
        self._channel_id = channel_id.strip()
        self._opener = opener
        self._sleep = sleep
        self._timeout_seconds = timeout_seconds

    async def send(self, content: str) -> bool:
        try:
            return await asyncio.to_thread(self._send_sync, _content(content))
        except Exception as exc:  # noqa: BLE001 - 알림 실패는 파이프라인과 분리
            log.warning("Telegram 알림 실패: %s", type(exc).__name__)
            return False

    def _send_sync(self, content: str) -> bool:
        payload = json.dumps(
            {
                "chat_id": self._channel_id,
                "text": self._as_safe_html(content),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        for attempt in range(2):
            request = Request(
                self._api_url,
                data=payload,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "lecture-prism/telegram-notifier",
                },
                method="POST",
            )
            try:
                with self._opener(request, timeout=self._timeout_seconds) as response:
                    status = int(getattr(response, "status", 200))
                    raw = response.read()
                if not 200 <= status < 300:
                    log.warning("Telegram 알림 실패: HTTP %s", status)
                    return False
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    log.warning("Telegram 알림 실패: invalid response")
                    return False
                if body.get("ok") is True:
                    return True
                log.warning("Telegram 알림 실패: API rejected request")
                return False
            except HTTPError as exc:
                if exc.code == 429 and attempt == 0:
                    self._sleep(self._retry_delay(exc))
                    continue
                log.warning("Telegram 알림 실패: HTTP %s", exc.code)
                return False
            except (URLError, TimeoutError, OSError) as exc:
                log.warning("Telegram 알림 실패: %s", type(exc).__name__)
                return False
        return False

    @staticmethod
    def _as_safe_html(content: str) -> str:
        escaped = html.escape(content, quote=False)
        return re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", escaped)

    @staticmethod
    def _retry_delay(error: HTTPError) -> float:
        raw = error.headers.get("Retry-After") if error.headers else None
        if raw in (None, ""):
            try:
                body = json.loads(error.read().decode("utf-8"))
                raw = body.get("parameters", {}).get("retry_after", 0)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                raw = 0
        try:
            delay = float(raw)
        except (TypeError, ValueError):
            delay = 0.0
        return min(max(delay, 0.0), MAX_RETRY_AFTER_SECONDS)


class CompositeNotifier(_DecisionNotifierMixin):
    """Send one formatted message to every configured report provider."""

    enabled = True

    def __init__(self, notifiers) -> None:
        self.notifiers = tuple(notifiers)
        if not self.notifiers:
            raise ValueError("at least one notifier is required")

    async def send(self, content: str) -> bool:
        outcomes = await asyncio.gather(
            *(notifier.send(content) for notifier in self.notifiers),
            return_exceptions=True,
        )
        successful = False
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                log.warning("보고 채널 알림 실패: %s", type(outcome).__name__)
            elif outcome is True:
                successful = True
        return successful


def build_notifier():
    """Build a fail-open notifier from ignored local environment settings."""

    load_dotenv_once()
    selected = os.getenv("LECTURE_REPORT_CHANNEL")
    if selected is None:
        legacy = os.getenv("LECTURE_NOTIFY_DISCORD")
        selected = "discord" if legacy is None or truthy(legacy) else "off"
    selected = selected.strip().lower()
    if selected not in {"discord", "telegram", "both", "off"}:
        log.warning("보고 채널 비활성: 지원하지 않는 선택값입니다.")
        return NullNotifier()
    if selected == "off":
        return NullNotifier()

    notifiers = []
    if selected in {"discord", "both"}:
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        if is_valid_discord_webhook_url(webhook_url):
            notifiers.append(DiscordNotifier(webhook_url))
        elif webhook_url:
            log.warning(
                "Discord 알림 비활성: 유효한 HTTPS webhook 설정이 필요합니다."
            )

    if selected in {"telegram", "both"}:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
        if is_valid_telegram_bot_token(
            bot_token
        ) and is_valid_telegram_channel_id(channel_id):
            notifiers.append(TelegramNotifier(bot_token, channel_id))
        elif bot_token or channel_id:
            log.warning(
                "Telegram 알림 비활성: 유효한 봇 토큰과 채널 ID가 필요합니다."
            )

    if not notifiers:
        return NullNotifier()
    if len(notifiers) == 1:
        return notifiers[0]
    return CompositeNotifier(notifiers)
