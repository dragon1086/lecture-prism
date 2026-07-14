import asyncio
import json
import sqlite3
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError

import db
from notifications import (
    DiscordChannel,
    NotificationDeliveryError,
    NotificationDispatcher,
    PipelineEvent,
    TelegramChannel,
    build_notification_dispatcher,
    split_message,
)


class _FakeResponse:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b""


class _FakeChannel:
    enabled = True

    def __init__(self, name, *, delay=0.0, failure=None, probe=None):
        self.name = name
        self.delay = delay
        self.failure = failure
        self.probe = probe
        self.sequences = []

    async def send(self, event):
        self.sequences.append(event.sequence)
        if self.probe is not None:
            self.probe["active"] += 1
            self.probe["maximum"] = max(
                self.probe["maximum"], self.probe["active"]
            )
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.failure is not None:
                raise self.failure
            return 1
        finally:
            if self.probe is not None:
                self.probe["active"] -= 1


class _ControlledChannel:
    enabled = True

    def __init__(self, name):
        self.name = name
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.sequences = []

    async def send(self, event):
        self.sequences.append(event.sequence)
        self.started.set()
        await self.release.wait()
        return 1


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._temp_dir.name) / "prism.db"

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._temp_dir.cleanup()

    def _deliveries(self):
        if not db.DB_PATH.exists():
            return []
        with sqlite3.connect(db.DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM notification_deliveries "
                    "ORDER BY sequence, channel"
                ).fetchall()
            ]

    async def test_pipeline_event_defaults_and_repr_hide_payload(self):
        token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        event = PipelineEvent(
            run_id="run-1",
            sequence=1,
            event_type="pipeline.started",
            summary=f"token={token}",
            details={"bot_token": token},
        )

        rendered = repr(event)

        self.assertEqual("succeeded", event.status)
        self.assertEqual("mock", event.profile)
        self.assertEqual("simulation", event.trade_state)
        self.assertTrue(event.occurred_at.endswith("+00:00"))
        self.assertNotIn(token, rendered)
        self.assertNotIn("bot_token", rendered)
        self.assertNotIn(event.summary, rendered)

    async def test_dispatcher_preserves_fifo_and_fans_each_event_out_concurrently(self):
        probe = {"active": 0, "maximum": 0}
        discord = _FakeChannel("discord", delay=0.02, probe=probe)
        telegram = _FakeChannel("telegram", delay=0.02, probe=probe)
        dispatcher = NotificationDispatcher([discord, telegram])
        await dispatcher.start()

        await dispatcher.enqueue(
            PipelineEvent(run_id="run-1", sequence=1, event_type="pipeline.started")
        )
        await dispatcher.enqueue(
            PipelineEvent(run_id="run-1", sequence=2, event_type="pipeline.completed")
        )
        await dispatcher.close()

        self.assertEqual([1, 2], discord.sequences)
        self.assertEqual([1, 2], telegram.sequences)
        self.assertEqual(2, probe["maximum"])

    async def test_one_channel_failure_is_isolated_and_persisted_without_secret(self):
        webhook = "https://discord.com/api/webhooks/123/private-value"
        discord = _FakeChannel("discord", failure=RuntimeError(webhook))
        telegram = _FakeChannel("telegram")
        dispatcher = NotificationDispatcher([discord, telegram])
        await dispatcher.start()

        await dispatcher.enqueue(
            PipelineEvent(run_id="run-1", sequence=1, event_type="pipeline.started")
        )
        await dispatcher.close()

        rows = {row["channel"]: row for row in self._deliveries()}
        self.assertEqual([1], telegram.sequences)
        self.assertEqual("failed", rows["discord"]["status"])
        self.assertEqual("sent", rows["telegram"]["status"])
        self.assertNotIn(webhook, json.dumps(rows, ensure_ascii=False))

    async def test_delivery_is_queued_before_send_and_marked_sent_afterward(self):
        channel = _ControlledChannel("discord")
        dispatcher = NotificationDispatcher([channel])
        await dispatcher.start()

        await dispatcher.enqueue(
            PipelineEvent(run_id="run-1", sequence=1, event_type="pipeline.started")
        )
        await channel.started.wait()

        self.assertEqual("queued", self._deliveries()[0]["status"])

        channel.release.set()
        await dispatcher.close()
        self.assertEqual("sent", self._deliveries()[0]["status"])

    async def test_disabled_configuration_is_a_persisted_no_op(self):
        dispatcher = build_notification_dispatcher(environ={})
        await dispatcher.start()

        with patch(
            "notifications.urllib.request.urlopen",
            side_effect=AssertionError("disabled channels must not use HTTP"),
        ):
            await dispatcher.enqueue(
                PipelineEvent(
                    run_id="run-disabled",
                    sequence=1,
                    event_type="pipeline.started",
                )
            )
            await dispatcher.close()

        rows = self._deliveries()
        self.assertEqual(["discord", "telegram"], [row["channel"] for row in rows])
        self.assertTrue(all(row["status"] == "skipped" for row in rows))
        self.assertTrue(all(row["attempts"] == 0 for row in rows))

    async def test_duplicate_event_is_delivered_only_once(self):
        channel = _FakeChannel("discord")
        dispatcher = NotificationDispatcher([channel])
        event = PipelineEvent(
            run_id="run-duplicate", sequence=1, event_type="pipeline.started"
        )
        await dispatcher.start()

        await dispatcher.enqueue(event)
        await dispatcher.enqueue(event)
        await dispatcher.close()

        self.assertEqual([1], channel.sequences)
        self.assertEqual("sent", self._deliveries()[0]["status"])

    async def test_discord_splits_messages_and_disables_mentions(self):
        webhook = "https://discord.com/api/webhooks/123/private-value"
        channel = DiscordChannel(webhook, max_retries=0)
        event = PipelineEvent(
            run_id="run-1",
            sequence=1,
            event_type="analysis.completed",
            summary="A" * 4300,
        )

        with patch(
            "notifications.urllib.request.urlopen", return_value=_FakeResponse()
        ) as urlopen:
            with patch(
                "notifications.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda function, *args: function(*args)),
            ) as to_thread:
                attempts = await channel.send(event)

        payloads = [
            json.loads(call.args[0].data.decode("utf-8"))
            for call in urlopen.call_args_list
        ]
        self.assertGreater(len(payloads), 1)
        self.assertTrue(all(len(payload["content"]) <= 2000 for payload in payloads))
        self.assertTrue(
            all(payload["allowed_mentions"]["parse"] == [] for payload in payloads)
        )
        self.assertTrue(
            all("wait=true" in call.args[0].full_url for call in urlopen.call_args_list)
        )
        self.assertEqual(len(payloads), attempts)
        self.assertEqual(len(payloads), to_thread.await_count)

    async def test_telegram_splits_messages_and_uses_plain_text(self):
        token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        channel = TelegramChannel(token, "private-chat-id", max_retries=0)
        event = PipelineEvent(
            run_id="run-1",
            sequence=1,
            event_type="analysis.completed",
            summary="가" * 8500,
        )

        with patch(
            "notifications.urllib.request.urlopen", return_value=_FakeResponse()
        ) as urlopen:
            attempts = await channel.send(event)

        payloads = [
            json.loads(call.args[0].data.decode("utf-8"))
            for call in urlopen.call_args_list
        ]
        self.assertGreater(len(payloads), 1)
        self.assertTrue(all(len(payload["text"]) <= 4096 for payload in payloads))
        self.assertTrue(all("parse_mode" not in payload for payload in payloads))
        self.assertTrue(
            all(payload["chat_id"] == "private-chat-id" for payload in payloads)
        )
        self.assertEqual(len(payloads), attempts)

    async def test_outbound_payloads_redact_secrets_and_preserve_safe_summary(self):
        webhook = "https://discord.com/api/webhooks/987/summary-private-value"
        telegram_token = "987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        bearer = "Bearer synthetic.access-token_value"
        named_secret = "sk-synthetic-sensitive"
        safe_summary = "분석 완료: 안전한 요약 내용은 유지됩니다."
        event = PipelineEvent(
            run_id="run-redaction",
            sequence=1,
            event_type="analysis.completed",
            summary=(
                f"{safe_summary}\n"
                f"webhook={webhook}\n"
                f"bot_token={telegram_token}\n"
                f"Authorization: {bearer}\n"
                f"api_key={named_secret}"
            ),
        )
        channels = (
            (
                DiscordChannel(
                    "https://discord.com/api/webhooks/123/transport-value",
                    max_retries=0,
                ),
                "content",
            ),
            (
                TelegramChannel(
                    "123456789:transport-token-value-ABCDE",
                    "private-chat-id",
                    max_retries=0,
                ),
                "text",
            ),
        )

        for channel, payload_key in channels:
            with self.subTest(channel=channel.name):
                with patch(
                    "notifications.urllib.request.urlopen",
                    return_value=_FakeResponse(),
                ) as urlopen:
                    await channel.send(event)

                payload_text = "".join(
                    json.loads(call.args[0].data.decode("utf-8"))[payload_key]
                    for call in urlopen.call_args_list
                )
                self.assertIn(safe_summary, payload_text)
                self.assertIn("[REDACTED]", payload_text)
                for secret in (webhook, telegram_token, bearer, named_secret):
                    self.assertNotIn(secret, payload_text)

    async def test_splitter_prefers_line_boundaries_then_hard_splits(self):
        message = "head\n" + "x" * 13

        parts = split_message(message, limit=8)

        self.assertEqual("head\n", parts[0])
        self.assertEqual(message, "".join(parts))
        self.assertTrue(all(len(part) <= 8 for part in parts))

    async def test_429_retry_after_is_capped(self):
        webhook = "https://discord.com/api/webhooks/123/private-value"
        headers = Message()
        headers["Retry-After"] = "999"
        too_many_requests = HTTPError(
            webhook, 429, "Too Many Requests", headers, None
        )
        channel = DiscordChannel(
            webhook,
            max_retries=2,
            retry_backoff=0.01,
            max_retry_after=0.05,
        )

        with patch(
            "notifications.urllib.request.urlopen",
            side_effect=[too_many_requests, _FakeResponse()],
        ) as urlopen:
            with patch("notifications.asyncio.sleep", new=AsyncMock()) as sleep:
                attempts = await channel.send(
                    PipelineEvent(
                        run_id="run-1",
                        sequence=1,
                        event_type="pipeline.started",
                    )
                )

        self.assertEqual(2, attempts)
        self.assertEqual(2, urlopen.call_count)
        sleep.assert_awaited_once_with(0.05)

    async def test_timeouts_retry_with_bounded_backoff_then_raise_safe_error(self):
        webhook = "https://discord.com/api/webhooks/123/private-value"
        channel = DiscordChannel(
            webhook,
            max_retries=2,
            retry_backoff=0.01,
            max_retry_after=0.05,
        )

        with patch(
            "notifications.urllib.request.urlopen", side_effect=TimeoutError("slow")
        ) as urlopen:
            with patch("notifications.asyncio.sleep", new=AsyncMock()) as sleep:
                with self.assertRaises(NotificationDeliveryError) as captured:
                    await channel.send(
                        PipelineEvent(
                            run_id="run-1",
                            sequence=1,
                            event_type="pipeline.started",
                        )
                    )

        self.assertEqual(3, captured.exception.attempts)
        self.assertNotIn(webhook, str(captured.exception))
        self.assertEqual(3, urlopen.call_count)
        self.assertEqual([0.01, 0.02], [call.args[0] for call in sleep.await_args_list])

    async def test_server_error_retries_but_client_error_does_not(self):
        webhook = "https://discord.com/api/webhooks/123/private-value"
        channel = DiscordChannel(webhook, max_retries=2, retry_backoff=0)
        event = PipelineEvent(
            run_id="run-1", sequence=1, event_type="pipeline.started"
        )
        server_error = HTTPError(webhook, 503, "Unavailable", Message(), None)

        with patch(
            "notifications.urllib.request.urlopen",
            side_effect=[server_error, _FakeResponse()],
        ) as urlopen:
            self.assertEqual(2, await channel.send(event))
        self.assertEqual(2, urlopen.call_count)

        client_error = HTTPError(webhook, 400, "Bad Request", Message(), None)
        with patch(
            "notifications.urllib.request.urlopen", side_effect=client_error
        ) as urlopen:
            with self.assertRaises(NotificationDeliveryError):
                await channel.send(event)
        self.assertEqual(1, urlopen.call_count)

    async def test_close_has_a_finite_flush_timeout(self):
        channel = _ControlledChannel("discord")
        dispatcher = NotificationDispatcher([channel])
        await dispatcher.start()
        await dispatcher.enqueue(
            PipelineEvent(run_id="run-1", sequence=1, event_type="pipeline.started")
        )
        await channel.started.wait()

        with self.assertLogs("notifications", level="WARNING") as captured:
            await asyncio.wait_for(dispatcher.close(timeout=0.01), timeout=0.2)

        self.assertTrue(dispatcher.closed)
        self.assertIn("pending work was cancelled", captured.output[0])

    async def test_channel_repr_hides_credentials(self):
        webhook = "https://discord.com/api/webhooks/123/private-value"
        token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        discord = DiscordChannel(webhook)
        telegram = TelegramChannel(token, "private-chat-id")

        rendered = repr((discord, telegram))

        self.assertNotIn(webhook, rendered)
        self.assertNotIn(token, rendered)
        self.assertNotIn("private-chat-id", rendered)


if __name__ == "__main__":
    unittest.main()
