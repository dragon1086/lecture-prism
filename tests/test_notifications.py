from __future__ import annotations

import asyncio
from email.message import Message
import io
import json
import os
from pathlib import Path
from typing import cast
import unittest
from urllib.error import HTTPError
from unittest import mock

import notifications


VALID_WEBHOOK = "https://discord.com/api/webhooks/123456/token-value"
VALID_TELEGRAM_TOKEN = "123456789:" + ("A" * 35)
VALID_TELEGRAM_CHANNEL = "-1001234567890"


class FakeResponse:
    def __init__(self, body=b'{"id":"message-1"}', status=200):
        self._body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body


class FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses) or [FakeResponse()]
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fake_headers(values: dict[str, str] | None = None) -> Message:
    headers = Message()
    for key, value in (values or {}).items():
        headers[key] = value
    return headers


def analysis(ticker="005930", recommendation="BUY", decision="진입"):
    return {
        "ticker": ticker,
        "company_name": "삼성전자" if ticker == "005930" else ticker,
        "data_source": "mock",
        "recommendation": recommendation,
        "decision": decision,
        "buy_score": 8 if recommendation == "BUY" else 4,
        "current_price": 71_200,
        "target_price": 79_700,
        "stop_loss": 66_900,
        "risk_reward_ratio": 2.0,
        "technical_summary": "20일선 위에서 거래량을 동반한 상승 흐름입니다.",
        "supply_summary": "상승일 거래량이 하락일보다 많습니다.",
        "financial_summary": "PER 13.2배, ROE 8.4%입니다.",
        "industry_summary": "HBM 수요 확대를 가정한 시나리오입니다.",
        "news_summary": "공급 확대 기대가 촉매로 작용한다는 가정입니다.",
        "market_condition": "KOSPI가 20일선 위에 있습니다.",
        "rationale": "기술·수급·재무·뉴스를 종합한 판단입니다.",
        "risk": "시장 급락 시 동반 조정 가능성이 있습니다.",
        "cash": 99_999_999,
        "account_number": "do-not-send",
    }


class NotificationConfigurationTest(unittest.TestCase):
    def test_default_build_is_noop_without_network_configuration(self):
        self.assertTrue(
            hasattr(notifications, "build_notifier")
            and hasattr(notifications, "NullNotifier")
        )
        with mock.patch.dict(
            os.environ,
            {"LECTURE_NOTIFY_DISCORD": "", "DISCORD_WEBHOOK_URL": ""},
            clear=False,
        ):
            notifier = notifications.build_notifier()

        self.assertIsInstance(notifier, notifications.NullNotifier)

    def test_non_discord_or_non_https_webhook_is_rejected(self):
        self.assertTrue(hasattr(notifications, "is_valid_discord_webhook_url"))
        for url in (
            "http://discord.com/api/webhooks/123/token",
            "https://example.com/api/webhooks/123/token",
            "https://discord.com/not-a-webhook",
        ):
            with self.subTest(url=url):
                self.assertFalse(notifications.is_valid_discord_webhook_url(url))

    def test_explicit_channel_selection_builds_expected_provider(self):
        cases = (
            ("off", notifications.NullNotifier),
            ("discord", notifications.DiscordNotifier),
            ("telegram", notifications.TelegramNotifier),
        )
        settings = {
            "LECTURE_REPORT_CHANNEL": "discord",
            "LECTURE_NOTIFY_DISCORD": "",
            "DISCORD_WEBHOOK_URL": VALID_WEBHOOK,
            "TELEGRAM_BOT_TOKEN": VALID_TELEGRAM_TOKEN,
            "TELEGRAM_CHANNEL_ID": VALID_TELEGRAM_CHANNEL,
        }

        for selected, expected_type in cases:
            with self.subTest(selected=selected), mock.patch.object(
                notifications, "load_dotenv_once"
            ), mock.patch.dict(
                os.environ,
                {**settings, "LECTURE_REPORT_CHANNEL": selected},
                clear=False,
            ):
                notifier = notifications.build_notifier()

            self.assertIsInstance(notifier, expected_type)

        with mock.patch.object(notifications, "load_dotenv_once"), mock.patch.dict(
            os.environ,
            {**settings, "LECTURE_REPORT_CHANNEL": "both"},
            clear=False,
        ):
            both = notifications.build_notifier()

        self.assertIsInstance(both, notifications.CompositeNotifier)
        composite = cast(notifications.CompositeNotifier, both)
        self.assertEqual(
            [type(item) for item in composite.notifiers],
            [notifications.DiscordNotifier, notifications.TelegramNotifier],
        )

    def test_both_uses_the_one_provider_that_is_valid(self):
        with mock.patch.object(
            notifications, "load_dotenv_once"
        ), mock.patch.dict(
            os.environ,
            {
                "LECTURE_REPORT_CHANNEL": "both",
                "LECTURE_NOTIFY_DISCORD": "",
                "DISCORD_WEBHOOK_URL": "",
                "TELEGRAM_BOT_TOKEN": VALID_TELEGRAM_TOKEN,
                "TELEGRAM_CHANNEL_ID": VALID_TELEGRAM_CHANNEL,
            },
            clear=False,
        ):
            notifier = notifications.build_notifier()

        self.assertIsInstance(notifier, notifications.TelegramNotifier)

    def test_legacy_discord_flag_is_used_only_when_new_selection_is_absent(self):
        with mock.patch.object(notifications, "load_dotenv_once"), mock.patch.dict(
            os.environ,
            {
                "LECTURE_NOTIFY_DISCORD": "1",
                "DISCORD_WEBHOOK_URL": VALID_WEBHOOK,
                "TELEGRAM_BOT_TOKEN": "",
                "TELEGRAM_CHANNEL_ID": "",
            },
            clear=False,
        ):
            os.environ.pop("LECTURE_REPORT_CHANNEL", None)
            legacy = notifications.build_notifier()
            os.environ["LECTURE_REPORT_CHANNEL"] = "off"
            explicit_off = notifications.build_notifier()

        self.assertIsInstance(legacy, notifications.DiscordNotifier)
        self.assertIsInstance(explicit_off, notifications.NullNotifier)

    def test_invalid_selection_fails_closed_without_echoing_the_value(self):
        invalid = "telegram https://example.invalid/private"
        with mock.patch.object(
            notifications, "load_dotenv_once"
        ), mock.patch.dict(
            os.environ,
            {
                "LECTURE_REPORT_CHANNEL": invalid,
                "LECTURE_NOTIFY_DISCORD": "1",
                "DISCORD_WEBHOOK_URL": VALID_WEBHOOK,
                "TELEGRAM_BOT_TOKEN": VALID_TELEGRAM_TOKEN,
                "TELEGRAM_CHANNEL_ID": VALID_TELEGRAM_CHANNEL,
            },
            clear=False,
        ), self.assertLogs("notifications", level="WARNING") as captured:
            notifier = notifications.build_notifier()

        self.assertIsInstance(notifier, notifications.NullNotifier)
        self.assertNotIn(invalid, "\n".join(captured.output))


class _ResultNotifier:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.messages = []

    async def send(self, content):
        self.messages.append(content)
        if self.error is not None:
            raise self.error
        return self.result


class CompositeNotifierTest(unittest.TestCase):
    def test_partial_success_returns_true_and_attempts_every_provider(self):
        failed = _ResultNotifier(False)
        succeeded = _ResultNotifier(True)
        notifier = notifications.CompositeNotifier([failed, succeeded])

        sent = asyncio.run(notifier.send("판단"))

        self.assertTrue(sent)
        self.assertEqual(failed.messages, ["판단"])
        self.assertEqual(succeeded.messages, ["판단"])

    def test_provider_exception_is_fail_open_and_does_not_echo_raw_error(self):
        failed = _ResultNotifier(
            error=RuntimeError(
                f"{VALID_TELEGRAM_TOKEN} {VALID_TELEGRAM_CHANNEL} raw"
            )
        )
        succeeded = _ResultNotifier(True)
        notifier = notifications.CompositeNotifier([failed, succeeded])

        with self.assertLogs("notifications", level="WARNING") as captured:
            sent = asyncio.run(notifier.send("판단"))

        self.assertTrue(sent)
        joined = "\n".join(captured.output)
        self.assertNotIn(VALID_TELEGRAM_TOKEN, joined)
        self.assertNotIn(VALID_TELEGRAM_CHANNEL, joined)
        self.assertNotIn("raw", joined)


class DiscordTransportTest(unittest.TestCase):
    def test_payload_disables_mentions_caps_content_and_waits_for_confirmation(self):
        self.assertTrue(
            hasattr(notifications, "DiscordNotifier")
            and hasattr(notifications, "DEFAULT_TIMEOUT_SECONDS")
        )
        opener = FakeOpener()
        notifier = notifications.DiscordNotifier(VALID_WEBHOOK, opener=opener)
        sent = asyncio.run(notifier.send("@everyone " + ("가" * 2_100)))

        self.assertTrue(sent)
        self.assertEqual(len(opener.requests), 1)
        request, timeout = opener.requests[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertLessEqual(len(payload["content"]), 2_000)
        self.assertIn("wait=true", request.full_url)
        self.assertEqual(timeout, notifications.DEFAULT_TIMEOUT_SECONDS)

    def test_rate_limit_retries_once_without_exposing_webhook(self):
        self.assertTrue(hasattr(notifications, "DiscordNotifier"))
        rate_limited = HTTPError(
            VALID_WEBHOOK,
            429,
            "rate limited",
            fake_headers({"Retry-After": "0"}),
            io.BytesIO(b'{"retry_after":0}'),
        )
        opener = FakeOpener(rate_limited, FakeResponse())
        sleeps = []
        notifier = notifications.DiscordNotifier(
            VALID_WEBHOOK,
            opener=opener,
            sleep=sleeps.append,
        )

        sent = asyncio.run(notifier.send("테스트"))

        self.assertTrue(sent)
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(sleeps, [0.0])

    def test_transport_failure_log_never_contains_webhook_token(self):
        failure = HTTPError(
            VALID_WEBHOOK,
            500,
            "server error",
            fake_headers(),
            io.BytesIO(b""),
        )
        notifier = notifications.DiscordNotifier(
            VALID_WEBHOOK,
            opener=FakeOpener(failure),
        )

        with self.assertLogs("notifications", level="WARNING") as captured:
            sent = asyncio.run(notifier.send("테스트"))

        self.assertFalse(sent)
        self.assertNotIn("token-value", "\n".join(captured.output))


class TelegramTransportTest(unittest.TestCase):
    def test_credentials_accept_channel_ids_and_reject_urls_or_whitespace(self):
        self.assertTrue(
            notifications.is_valid_telegram_bot_token(VALID_TELEGRAM_TOKEN)
        )
        for channel_id in (VALID_TELEGRAM_CHANNEL, "123456789", "@prism_notice"):
            with self.subTest(channel_id=channel_id):
                self.assertTrue(
                    notifications.is_valid_telegram_channel_id(channel_id)
                )

        for token in ("", "not-a-token", "12345:space token"):
            with self.subTest(token=token):
                self.assertFalse(notifications.is_valid_telegram_bot_token(token))
        for channel_id in ("", "short", "https://t.me/prism_notice", "-100 123"):
            with self.subTest(channel_id=channel_id):
                self.assertFalse(
                    notifications.is_valid_telegram_channel_id(channel_id)
                )

    def test_payload_uses_fixed_api_host_safe_html_and_no_preview(self):
        opener = FakeOpener(
            FakeResponse(b'{"ok":true,"result":{"message_id":1}}')
        )
        notifier = notifications.TelegramNotifier(
            VALID_TELEGRAM_TOKEN,
            VALID_TELEGRAM_CHANNEL,
            opener=opener,
        )

        sent = asyncio.run(notifier.send("**판단** <보류>"))

        self.assertTrue(sent)
        self.assertEqual(len(opener.requests), 1)
        request, timeout = opener.requests[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            request.full_url,
            f"https://api.telegram.org/bot{VALID_TELEGRAM_TOKEN}/sendMessage",
        )
        self.assertEqual(payload["chat_id"], VALID_TELEGRAM_CHANNEL)
        self.assertEqual(payload["text"], "<b>판단</b> &lt;보류&gt;")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertTrue(payload["disable_web_page_preview"])
        self.assertEqual(timeout, notifications.DEFAULT_TIMEOUT_SECONDS)

    def test_rate_limit_retries_once_with_bounded_delay(self):
        telegram_url = (
            f"https://api.telegram.org/bot{VALID_TELEGRAM_TOKEN}/sendMessage"
        )
        rate_limited = HTTPError(
            telegram_url,
            429,
            "rate limited",
            fake_headers(),
            io.BytesIO(b'{"ok":false,"parameters":{"retry_after":99}}'),
        )
        opener = FakeOpener(
            rate_limited,
            FakeResponse(b'{"ok":true,"result":{"message_id":2}}'),
        )
        sleeps = []
        notifier = notifications.TelegramNotifier(
            VALID_TELEGRAM_TOKEN,
            VALID_TELEGRAM_CHANNEL,
            opener=opener,
            sleep=sleeps.append,
        )

        sent = asyncio.run(notifier.send("테스트"))

        self.assertTrue(sent)
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(sleeps, [notifications.MAX_RETRY_AFTER_SECONDS])

    def test_api_failure_log_never_contains_token_channel_or_raw_error(self):
        failure = OSError(
            f"bot={VALID_TELEGRAM_TOKEN} channel={VALID_TELEGRAM_CHANNEL} raw"
        )
        notifier = notifications.TelegramNotifier(
            VALID_TELEGRAM_TOKEN,
            VALID_TELEGRAM_CHANNEL,
            opener=FakeOpener(failure),
        )

        with self.assertLogs("notifications", level="WARNING") as captured:
            sent = asyncio.run(notifier.send("테스트"))

        self.assertFalse(sent)
        joined = "\n".join(captured.output)
        self.assertNotIn(VALID_TELEGRAM_TOKEN, joined)
        self.assertNotIn(VALID_TELEGRAM_CHANNEL, joined)
        self.assertNotIn("raw", joined)


class DiscordMessageFormatTest(unittest.TestCase):
    def test_analysis_message_contains_six_evidence_sections(self):
        self.assertTrue(hasattr(notifications, "format_analysis_message"))
        message = notifications.format_analysis_message(analysis())

        for label in ("기술", "수급", "재무", "산업", "뉴스", "시장"):
            self.assertIn(label, message)
        self.assertIn("BUY", message)
        self.assertIn("8/10", message)
        self.assertLessEqual(len(message), 2_000)

    def test_trading_messages_cover_sell_buy_and_hold_without_inventing_orders(self):
        self.assertTrue(hasattr(notifications, "format_trading_messages"))
        analyses = [
            analysis("005930"),
            analysis("000660", recommendation="HOLD", decision="보류"),
        ]
        trades = [
            {
                "ticker": "035720",
                "action": "SELL",
                "status": "filled",
                "executed": True,
                "filled_qty": 2,
                "executed_price": 47_850,
                "reason": "손절 (-7.2%)",
                "mode": "simulation",
            },
            {
                "ticker": "005930",
                "action": "BUY",
                "status": "filled",
                "executed": True,
                "filled_qty": 3,
                "executed_price": 71_200,
                "reason": "추세 돌파",
                "mode": "simulation",
            },
        ]

        messages = notifications.format_trading_messages(analyses, trades)
        joined = "\n".join(messages)

        self.assertIn("SELL", joined)
        self.assertIn("BUY", joined)
        self.assertIn("HOLD", joined)
        self.assertIn("보류", joined)

    def test_decision_summary_excludes_account_and_cash_fields(self):
        self.assertTrue(hasattr(notifications, "format_decision_summary"))
        analyses = [analysis()]
        trades = [
            {
                "ticker": "005930",
                "action": "BUY",
                "status": "filled",
                "reason": "추세 돌파",
                "cash": 123,
                "account_number": "secret",
            }
        ]

        message = notifications.format_decision_summary(analyses, trades)

        self.assertIn("AI 판단 요약", message)
        self.assertIn("매수 판단", message)
        self.assertNotIn("123", message)
        self.assertNotIn("secret", message)
        self.assertNotIn("account", message.lower())
        self.assertNotIn("계좌", message)

    def test_feedback_message_marks_saved_records_without_inventing_buy_lesson(self):
        self.assertTrue(hasattr(notifications, "format_feedback_message"))
        message = notifications.format_feedback_message(
            [analysis()],
            [
                {
                    "ticker": "005930",
                    "action": "BUY",
                    "status": "filled",
                    "executed": True,
                    "filled_qty": 3,
                }
            ],
        )

        self.assertIn("피드백 저장 완료", message)
        self.assertIn("분석 이력 1건", message)
        self.assertIn("가상 체결 기록 1건", message)
        self.assertIn("결과 교훈 0건", message)
        self.assertIn("SELL 뒤", message)
        self.assertIn("prism.db", message)

    def test_operational_messages_cover_events_without_raw_sensitive_payloads(self):
        self.assertTrue(hasattr(notifications, "format_operational_message"))
        sensitive_context = {
            "profile": "live",
            "job": "reconcile",
            "error": RuntimeError(
                "raw outage sk-secret-ops https://broker.example/token "
                "account 123-456 balance 987654321"
            ),
            "account_number": "123-456",
            "balance": 987654321,
            "token": "ops-token-value",
            "webhook_url": VALID_WEBHOOK,
            "telegram_channel_id": VALID_TELEGRAM_CHANNEL,
            "last_data_at": "2026-08-01T09:00:00+09:00",
        }
        events = (
            "service_start",
            "service_stop",
            "job_failure",
            "stale_data",
            "reconciliation_failure",
            "blocked_unattended_gate",
        )

        for event in events:
            with self.subTest(event=event):
                message = notifications.format_operational_message(
                    event,
                    sensitive_context,
                )

                self.assertIn(event, message)
                self.assertIn("live", message)
                self.assertNotIn("raw outage", message)
                self.assertNotIn("sk-secret-ops", message)
                self.assertNotIn("https://broker.example", message)
                self.assertNotIn("123-456", message)
                self.assertNotIn("987654321", message)
                self.assertNotIn("ops-token-value", message)
                self.assertNotIn("token-value", message)
                self.assertNotIn(VALID_TELEGRAM_CHANNEL, message)
                self.assertLessEqual(len(message), 2_000)

    def test_operational_discord_notification_is_fail_open(self):
        self.assertTrue(hasattr(notifications.DiscordNotifier, "operational"))
        failure = OSError("webhook token-value raw network failure")
        notifier = notifications.DiscordNotifier(
            VALID_WEBHOOK,
            opener=FakeOpener(failure),
        )

        with self.assertLogs("notifications", level="WARNING") as captured:
            sent = asyncio.run(
                notifier.operational(
                    "job_failure",
                    {
                        "profile": "paper",
                        "error": failure,
                        "webhook_url": VALID_WEBHOOK,
                    },
                )
            )

        self.assertFalse(sent)
        joined = "\n".join(captured.output)
        self.assertNotIn("token-value", joined)
        self.assertNotIn("raw network failure", joined)

    def test_operational_message_redacts_secret_patterns_under_neutral_string_keys(self):
        message = notifications.format_operational_message(
            "job_failure",
            {
                "profile": "paper",
                "job": "monitor",
                "error": (
                    "api_key=sk-neutral-secret app_key=KISAPP123 "
                    "app_secret=KISSECRET456 Authorization: Bearer bearer-secret "
                    "authorization=Bearer equals-token "
                    "AUTHORIZATION:Bearer colon-token "
                    "Authorization : Bearer spaced-token "
                    "DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123/raw-token "
                    "telegram_channel_id=-1009988776655 "
                    "channel_id=-1001122334455 account_number=123-456-789 "
                    "normal ticker 005930 price 71200"
                ),
            },
        )

        self.assertNotIn("sk-neutral-secret", message)
        self.assertNotIn("KISAPP123", message)
        self.assertNotIn("KISSECRET456", message)
        self.assertNotIn("bearer-secret", message)
        self.assertNotIn("equals-token", message)
        self.assertNotIn("colon-token", message)
        self.assertNotIn("spaced-token", message)
        self.assertNotIn("raw-token", message)
        self.assertNotIn("-1009988776655", message)
        self.assertNotIn("-1001122334455", message)
        self.assertNotIn("123-456-789", message)
        self.assertIn("005930", message)
        self.assertIn("71200", message)


class ReportChannelDocumentationContractTest(unittest.TestCase):
    def test_example_and_architecture_document_optional_decision_notifications(self):
        env_example = Path(".env.example").read_text(encoding="utf-8")
        architecture = Path("docs/architecture.md").read_text(encoding="utf-8")
        runtime_profiles = Path("docs/runtime-profiles.md").read_text(encoding="utf-8")

        for phrase in (
            "LECTURE_REPORT_CHANNEL=discord",
            "discord | telegram | both | off",
            'DISCORD_WEBHOOK_URL=""',
            'TELEGRAM_BOT_TOKEN=""',
            'TELEGRAM_CHANNEL_ID=""',
        ):
            self.assertIn(phrase, env_example)
        self.assertIn("notifications.py", architecture)
        self.assertIn("선택한 보고 채널", architecture)
        self.assertIn("Telegram", architecture)
        self.assertIn("AI 판단 요약", runtime_profiles)
        self.assertIn("피드백 저장", architecture)
        self.assertIn("피드백 저장", runtime_profiles)
        self.assertIn("계좌 잔고", runtime_profiles)
        self.assertIn("보내지", runtime_profiles)
        for phrase in (
            "discord",
            "telegram",
            "both",
            "off",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHANNEL_ID",
        ):
            self.assertIn(phrase, runtime_profiles)


if __name__ == "__main__":
    unittest.main()
