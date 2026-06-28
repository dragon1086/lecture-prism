"""Small stdlib-only environment helpers for broker adapters."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LOADED_ENV_FILES: set[Path] = set()


def project_root() -> Path:
    return _PROJECT_ROOT


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return key, value


def load_env_file(path: str | Path | None = None, *, override: bool = False) -> Path | None:
    """Load a simple KEY=VALUE .env file without adding python-dotenv.

    Existing process environment values win by default. This is enough for the
    lecture use case: students can keep secrets in a local `.env` while the
    repository only commits `.env.example`.
    """

    env_path = Path(path) if path else _PROJECT_ROOT / ".env"
    env_path = env_path.expanduser().resolve()
    if env_path in _LOADED_ENV_FILES and not override:
        return env_path if env_path.exists() else None
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if not parsed:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value

    _LOADED_ENV_FILES.add(env_path)
    return env_path


def load_dotenv_once() -> None:
    load_env_file()


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def any_truthy(keys: Iterable[str]) -> bool:
    return any(truthy(os.getenv(key)) for key in keys)


def normalize_mode(value: str | None, *, default: str = "demo") -> str:
    normalized = str(value or default).strip().lower()
    if normalized in {"demo", "paper", "mock", "vps", "sim", "simulation"}:
        return "demo"
    if normalized in {"real", "prod", "live"}:
        return "real"
    return default


def mask_secret(value: str | None, *, visible: int = 4) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) <= visible * 2:
        return "*" * len(text)
    return f"{text[:visible]}{'*' * (len(text) - visible * 2)}{text[-visible:]}"
