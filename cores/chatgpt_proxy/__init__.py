"""ChatGPT OAuth Proxy for lecture-prism.

Routes OpenAI API calls through ChatGPT Plus/Pro subscription
via an in-process aiohttp proxy server.

This is a teaching-sized copy of PRISM-INSIGHT's ``cores.chatgpt_proxy``.
The public surface is intentionally small:

- ``inject_env()`` points OpenAI SDK calls at ``http://localhost:18741/v1``.
- ``start_proxy()`` starts the local proxy if a ChatGPT OAuth token exists.
- ``stop_proxy()`` shuts it down.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .constants import DEFAULT_PROXY_PORT

logger = logging.getLogger(__name__)

_runner: Any | None = None
_site: Any | None = None


def inject_env(port: int | None = None) -> None:
    """Set OPENAI_BASE_URL and OPENAI_API_KEY env vars.

    MUST be called BEFORE any MCPApp creation so that
    OpenAISettings picks up the proxy URL.
    """
    proxy_port = port or DEFAULT_PROXY_PORT
    os.environ["OPENAI_BASE_URL"] = f"http://localhost:{proxy_port}/v1"
    os.environ["OPENAI_API_KEY"] = "chatgpt-oauth-placeholder"
    logger.info("Environment variables set: OPENAI_BASE_URL=http://localhost:%d/v1", proxy_port)


def clear_env() -> None:
    """Remove proxy env vars (for fallback to standard API)."""
    os.environ.pop("OPENAI_BASE_URL", None)
    os.environ.pop("OPENAI_API_KEY", None)
    logger.info("Proxy environment variables cleared")


async def start_proxy(port: int | None = None) -> bool:
    """Start the ChatGPT OAuth proxy server.

    Returns True if started successfully, False otherwise.
    """
    global _runner, _site

    # OAuth 프록시를 실제로 시작할 때만 선택 패키지를 불러옵니다.
    # 덕분에 기본 mock 데모와 요청 번역기 테스트는 aiohttp 없이도 동작합니다.
    try:
        from aiohttp import web

        from .proxy_server import create_app
        from .token_manager import TokenManager
    except ImportError as e:
        logger.error("ChatGPT OAuth proxy dependencies are unavailable: %s", e)
        return False

    if _runner is not None:
        logger.info("Proxy already running")
        return True

    proxy_port = port or DEFAULT_PROXY_PORT

    try:
        token_manager = TokenManager()
        token_manager.validate_or_fail()

        app = create_app(token_manager)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", proxy_port)
        await site.start()
        _runner = runner
        _site = site

        logger.info("ChatGPT OAuth proxy started on port %d", proxy_port)
        return True

    except Exception as e:
        logger.error("Failed to start proxy: %s", e)
        _runner = None
        _site = None
        return False


async def stop_proxy() -> None:
    """Gracefully stop the proxy server."""
    global _runner, _site

    if _runner is not None:
        await _runner.cleanup()
        logger.info("ChatGPT OAuth proxy stopped")

    _runner = None
    _site = None
