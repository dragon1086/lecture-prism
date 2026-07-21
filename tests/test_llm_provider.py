import asyncio
import os
from pathlib import Path
import unittest
from unittest import mock

import llm_provider


class _FakeProcess:
    def __init__(self, returncode=None, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.input = None
        self.killed = False

    async def communicate(self, input=None):
        self.input = input
        if self.returncode is None:
            self.returncode = 0
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        if self.returncode is None:
            self.returncode = -9
        return self.returncode


class CodexSubscriptionProviderTest(unittest.TestCase):
    def test_complete_uses_one_ephemeral_read_only_process_without_shell(self):
        calls = []

        async def fake_exec(*argv, **kwargs):
            calls.append((argv, kwargs))
            output_path = Path(argv[argv.index("-o") + 1])
            output_path.write_text('{"recommendation":"HOLD"}', encoding="utf-8")
            process = _FakeProcess()
            calls.append(process)
            return process

        provider = llm_provider.CodexSubscriptionProvider(
            executable="codex", model="gpt-5.4-mini", timeout_seconds=10
        )
        with mock.patch.dict(os.environ, {"LECTURE_TEST_SECRET": "do-not-inherit"}), mock.patch(
            "asyncio.create_subprocess_exec", side_effect=fake_exec
        ):
            result = asyncio.run(
                provider.complete("SYSTEM_PRIVATE_MARKER", "USER_PRIVATE_MARKER")
            )

        self.assertEqual(result, '{"recommendation":"HOLD"}')
        self.assertEqual(len(calls), 2)
        argv, kwargs = calls[0]
        process = calls[1]
        self.assertIn("--ephemeral", argv)
        self.assertIn("read-only", argv)
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--ignore-rules", argv)
        self.assertIn("--strict-config", argv)
        self.assertIn("--disable", argv)
        self.assertIn("shell_tool", argv)
        self.assertIn("unified_exec", argv)
        self.assertIn("--output-schema", argv)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["env"].get("LECTURE_TEST_SECRET"), None)
        self.assertNotEqual(kwargs["env"], os.environ)
        joined = " ".join(argv)
        self.assertNotIn("auth.json", joined)
        self.assertNotIn("OPENAI_API_KEY", joined)
        self.assertNotIn("SYSTEM_PRIVATE_MARKER", joined)
        self.assertNotIn("USER_PRIVATE_MARKER", joined)
        self.assertIn(b"SYSTEM ROLE", process.input)

    def test_environment_rejects_proxy_urls_with_userinfo(self):
        with mock.patch.dict(
            os.environ,
            {
                "HTTPS_PROXY": "http://user:secret@example.test:8080",
                "HTTP_PROXY": "http://proxy.example.test:8080",
            },
            clear=True,
        ):
            child_env = llm_provider._codex_environment()

        self.assertNotIn("HTTPS_PROXY", child_env)
        self.assertEqual(
            child_env["HTTP_PROXY"],
            "http://proxy.example.test:8080",
        )

    def test_timeout_kills_and_reaps_child(self):
        process = _FakeProcess()

        async def fake_exec(*argv, **kwargs):
            return process

        async def fake_wait_for(awaitable, timeout):
            awaitable.close()
            raise asyncio.TimeoutError

        provider = llm_provider.CodexSubscriptionProvider(timeout_seconds=15)
        with mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec), mock.patch(
            "asyncio.wait_for", side_effect=fake_wait_for
        ):
            with self.assertRaisesRegex(llm_provider.LLMProviderError, "timed out"):
                asyncio.run(provider.complete("system", "user"))

        self.assertTrue(process.killed)

    def test_nonzero_exit_is_sanitized_and_fails_closed(self):
        async def fake_exec(*argv, **kwargs):
            return _FakeProcess(returncode=1, stderr=b"secret-looking upstream failure")

        provider = llm_provider.CodexSubscriptionProvider(executable="codex")
        with mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            with self.assertRaisesRegex(llm_provider.LLMProviderError, "Codex.*failed") as ctx:
                asyncio.run(provider.complete("system", "user"))

        self.assertNotIn("secret-looking", str(ctx.exception))

    def test_missing_codex_cli_has_actionable_error(self):
        provider = llm_provider.CodexSubscriptionProvider(executable="missing-codex")
        with mock.patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(llm_provider.LLMProviderError, "Codex CLI"):
                asyncio.run(provider.complete("system", "user"))


class ProviderSelectionTest(unittest.TestCase):
    def test_oauth_mode_selects_official_codex_provider(self):
        cfg = mock.Mock(llm_mode="oauth")
        provider = llm_provider.provider_for(cfg)
        self.assertIsInstance(provider, llm_provider.CodexSubscriptionProvider)

    def test_mock_mode_has_no_provider(self):
        self.assertIsNone(llm_provider.provider_for(mock.Mock(llm_mode="mock")))

    def test_legacy_explicit_oauth_flag_still_selects_codex_in_auto_mode(self):
        cfg = mock.Mock(llm_mode="auto", chatgpt_oauth_requested=True)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(
                llm_provider.provider_for(cfg), llm_provider.CodexSubscriptionProvider
            )


if __name__ == "__main__":
    unittest.main()
