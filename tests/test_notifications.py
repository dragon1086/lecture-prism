import asyncio
import io
import json
import os
from pathlib import Path
import unittest
from urllib.error import HTTPError
from unittest import mock

import notifications


VALID_WEBHOOK = "https://discord.com/api/webhooks/123456/token-value"


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"id":"message-1"}'


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
            {"Retry-After": "0"},
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
            {},
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


class DiscordDocumentationContractTest(unittest.TestCase):
    def test_example_and_architecture_document_optional_decision_notifications(self):
        env_example = Path(".env.example").read_text(encoding="utf-8")
        architecture = Path("docs/architecture.md").read_text(encoding="utf-8")
        runtime_profiles = Path("docs/runtime-profiles.md").read_text(encoding="utf-8")

        self.assertIn("LECTURE_NOTIFY_DISCORD=0", env_example)
        self.assertIn('DISCORD_WEBHOOK_URL=""', env_example)
        self.assertIn("notifications.py", architecture)
        self.assertIn("AI 판단 요약", runtime_profiles)
        self.assertIn("계좌 잔고", runtime_profiles)
        self.assertIn("보내지", runtime_profiles)


if __name__ == "__main__":
    unittest.main()
