"""Optional LLM providers with a keyless, mock-first default.

ChatGPT subscription access is delegated to the official Codex CLI.  This
module never reads or writes Codex credentials; ``codex login`` owns token
storage and refresh on both macOS and Windows.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit


class LLMProviderError(RuntimeError):
    """A provider was unavailable or returned an unusable response."""


class LLMProvider(Protocol):
    async def complete(self, system_prompt: str, user_message: str) -> str: ...


_CODEX_DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "shell_snapshot",
    "plugins",
    "apps",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "goals",
    "hooks",
    "workspace_dependencies",
    "tool_suggest",
)

_SAFE_ENV_KEYS = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "CODEX_HOME",
    "APPDATA",
    "LOCALAPPDATA",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
    "no_proxy",
)

_PROXY_URL_ENV_KEYS = {
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
}

_CODEX_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "technical_summary": {"type": "string"},
        "news_summary": {"type": "string"},
        "llm_veto": {"type": "boolean"},
        "rationale": {"type": "string"},
        "risk": {"type": "string"},
    },
    "required": [
        "technical_summary",
        "news_summary",
        "llm_veto",
        "rationale",
        "risk",
    ],
    "additionalProperties": False,
}


def _codex_environment() -> dict[str, str]:
    """Pass only OS/auth plumbing, never arbitrary parent secrets."""
    child_env: dict[str, str] = {}
    for key in _SAFE_ENV_KEYS:
        value = os.environ.get(key)
        if not value:
            continue
        if key in _PROXY_URL_ENV_KEYS:
            parsed = urlsplit(value if "://" in value else f"//{value}")
            if parsed.username is not None or parsed.password is not None:
                continue
        child_env[key] = value
    return child_env


class CodexSubscriptionProvider:
    """Run one non-interactive Codex turn using the user's ChatGPT login."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.executable = executable or os.getenv("LECTURE_CODEX_EXECUTABLE", "codex")
        self.model = model or os.getenv("LECTURE_CODEX_MODEL", "gpt-5.4-mini")
        configured_timeout = timeout_seconds or int(
            os.getenv("LECTURE_CODEX_TIMEOUT_SECONDS", "180")
        )
        self.timeout_seconds = max(15, min(configured_timeout, 600))

    async def complete(self, system_prompt: str, user_message: str) -> str:
        prompt = (
            "You are the qualitative analysis stage of a trading pipeline. "
            "Use only the evidence supplied below. Do not browse, call tools, or read files. "
            "Return only the requested JSON object.\n\n"
            f"SYSTEM ROLE:\n{system_prompt.strip()}\n\n"
            f"INPUT EVIDENCE:\n{user_message.strip()}"
        )
        with tempfile.TemporaryDirectory(prefix="lecture-prism-codex-") as temp_dir:
            output_path = Path(temp_dir) / "response.txt"
            schema_path = Path(temp_dir) / "response-schema.json"
            schema_path.write_text(
                json.dumps(_CODEX_RESPONSE_SCHEMA), encoding="utf-8"
            )
            argv = [
                self.executable,
                "exec",
                "--ignore-user-config",
                "--ignore-rules",
                "--strict-config",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--model",
                self.model,
                "-c",
                'model_reasoning_effort="low"',
            ]
            for feature in _CODEX_DISABLED_FEATURES:
                argv.extend(("--disable", feature))
            argv.extend(
                ("--output-schema", str(schema_path), "-o", str(output_path), "-")
            )

            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=temp_dir,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=_codex_environment(),
                )
            except FileNotFoundError as exc:
                raise LLMProviderError(
                    "Codex CLI를 찾지 못했습니다. Codex를 설치하고 codex login을 1회 실행하세요."
                ) from exc

            try:
                await asyncio.wait_for(
                    process.communicate(input=prompt.encode("utf-8")),
                    timeout=self.timeout_seconds,
                )
            except BaseException as exc:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.shield(process.wait())
                    except (ProcessLookupError, RuntimeError):
                        pass
                if isinstance(exc, asyncio.TimeoutError):
                    raise LLMProviderError("Codex subscription call timed out") from exc
                raise

            if process.returncode != 0:
                raise LLMProviderError(
                    "Codex subscription call failed. codex login status를 확인하세요."
                )
            try:
                response = output_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise LLMProviderError("Codex response file was not produced") from exc
            if not response:
                raise LLMProviderError("Codex returned an empty response")
            return response


class OpenAIAPIProvider:
    """Official usage-based OpenAI API provider (optional dependency)."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.getenv("LECTURE_LLM_MODEL", "gpt-5.4-mini")

    async def complete(self, system_prompt: str, user_message: str) -> str:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise LLMProviderError("openai 패키지 미설치 (pip install openai)") from exc

        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content or ""


def provider_for(config) -> LLMProvider | None:
    """Select only explicitly enabled providers; auto never guesses OAuth."""

    if config.llm_mode == "oauth" or (
        config.llm_mode == "auto"
        and getattr(config, "chatgpt_oauth_requested", False)
        and not os.getenv("OPENAI_API_KEY")
    ):
        return CodexSubscriptionProvider()
    if config.llm_mode == "openai":
        return OpenAIAPIProvider()
    if config.llm_mode == "auto" and os.getenv("OPENAI_API_KEY"):
        return OpenAIAPIProvider()
    return None
