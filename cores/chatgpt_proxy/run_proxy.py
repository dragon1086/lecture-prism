"""Standalone runner for the lecture-prism ChatGPT OAuth proxy."""

from __future__ import annotations

import argparse
import logging

from aiohttp import web

from .constants import DEFAULT_PROXY_PORT
from .proxy_server import create_app
from .token_manager import TokenManager


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start the lecture-prism ChatGPT OAuth proxy.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PROXY_PORT)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    token_manager = TokenManager()
    token_manager.validate_or_fail()

    app = create_app(token_manager)
    print(f"lecture-prism OAuth proxy: http://127.0.0.1:{args.port}/v1")
    print("health check: /health")
    web.run_app(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
