"""Safe JSON subprocess boundary for the pinned ``tossctl`` CLI."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Mapping, Sequence


SUPPORTED_TOSSCTL_VERSION = "0.24.1"
MINIMUM_TOSSCTL_READ_VERSION = (0, 43, 1)
DEFAULT_TIMEOUT_SECONDS = 15.0


class TossctlError(RuntimeError):
    """Base error for tossctl configuration and command failures."""


class TossctlConfigurationError(TossctlError):
    """The pinned tossctl runtime is unavailable or incompatible."""


class TossctlCommandError(TossctlError):
    """A read-only tossctl command failed before a mutation was attempted."""


class TossctlUnknownMutationError(TossctlError):
    """A mutation started but its broker-side outcome cannot be proven."""


def _safe_timeout(raw: str | None) -> float:
    if raw is None or not raw.strip():
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise TossctlConfigurationError(
            "TOSSCTL_TIMEOUT_SECONDS must be a positive number"
        ) from exc
    if timeout <= 0:
        raise TossctlConfigurationError(
            "TOSSCTL_TIMEOUT_SECONDS must be a positive number"
        )
    return timeout


def _minimal_environment(source: Mapping[str, str]) -> dict[str, str]:
    allowed = {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
    }
    env = {key: value for key, value in source.items() if key in allowed}
    env["NO_COLOR"] = "1"
    return env


class TossctlClient:
    """Invoke tossctl with a fixed WTS/JSON contract and no shell expansion."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        timeout: float | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        environ: Mapping[str, str] | None = None,
        backend: str = "wts",
    ) -> None:
        source_env = dict(os.environ if environ is None else environ)
        configured = executable or source_env.get("TOSSCTL_PATH")
        resolved = configured or shutil.which("tossctl", path=source_env.get("PATH"))
        if not resolved and os.name == "nt":
            resolved = shutil.which("tossctl.exe", path=source_env.get("PATH"))
        if not resolved:
            raise TossctlConfigurationError(
                "tossctl 실행 파일을 찾을 수 없습니다. TOSSCTL_PATH를 설정하세요."
            )
        path = Path(resolved).expanduser()
        if configured and not path.is_file():
            raise TossctlConfigurationError(
                f"TOSSCTL_PATH 실행 파일을 찾을 수 없습니다: {path}"
            )
        self.executable = str(path.resolve())
        self.timeout = (
            float(timeout)
            if timeout is not None
            else _safe_timeout(source_env.get("TOSSCTL_TIMEOUT_SECONDS"))
        )
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise TossctlConfigurationError("tossctl timeout must be positive")
        self._runner = runner
        self._env = _minimal_environment(source_env)
        if backend not in {"auto", "openapi", "wts"}:
            raise TossctlConfigurationError(f"unsupported tossctl backend: {backend}")
        self.backend = backend
        self._version_checked = False

    def run_json(
        self, args: Sequence[str], *, mutation: bool = False
    ) -> Any:
        if not args or any(not isinstance(arg, str) or not arg for arg in args):
            raise ValueError("tossctl args must be non-empty strings")
        if not self._version_checked:
            self._check_version()
        return self._invoke(args, mutation=mutation)

    def _check_version(self) -> None:
        payload = self._invoke(["version"], mutation=False)
        version = str(payload.get("version", "")) if isinstance(payload, dict) else ""
        if not self._accepts_version(version):
            raise TossctlConfigurationError(
                "지원하지 않는 tossctl 버전입니다: "
                f"expected={self._version_requirement()} actual={version or 'unknown'}"
            )
        self._version_checked = True

    def _accepts_version(self, version: str) -> bool:
        return version == SUPPORTED_TOSSCTL_VERSION

    def _version_requirement(self) -> str:
        return SUPPORTED_TOSSCTL_VERSION

    def _invoke(self, args: Sequence[str], *, mutation: bool) -> Any:
        command = [
            self.executable,
            "--backend",
            self.backend,
            "--output",
            "json",
            *args,
        ]
        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                shell=False,
                env=dict(self._env),
            )
        except subprocess.TimeoutExpired as exc:
            error_type = (
                TossctlUnknownMutationError if mutation else TossctlCommandError
            )
            raise error_type("tossctl command timed out") from exc
        except OSError as exc:
            error_type = (
                TossctlUnknownMutationError if mutation else TossctlCommandError
            )
            raise error_type("tossctl command could not be started") from exc

        if completed.returncode != 0:
            error_type = (
                TossctlUnknownMutationError if mutation else TossctlCommandError
            )
            raise error_type(
                f"tossctl command failed with exit code {completed.returncode}"
            )
        try:
            return json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            error_type = (
                TossctlUnknownMutationError if mutation else TossctlCommandError
            )
            raise error_type("tossctl returned invalid JSON") from exc


class TossctlReadClient(TossctlClient):
    """Read-only client for the current tossctl official/OpenAPI route."""

    def __init__(self, **kwargs) -> None:
        super().__init__(backend="openapi", **kwargs)

    def _accepts_version(self, version: str) -> bool:
        parsed = self._parse_version(version)
        return parsed is not None and parsed >= MINIMUM_TOSSCTL_READ_VERSION

    def _version_requirement(self) -> str:
        return ".".join(str(part) for part in MINIMUM_TOSSCTL_READ_VERSION) + "+"

    @staticmethod
    def _parse_version(value: str) -> tuple[int, int, int] | None:
        parts = value.strip().removeprefix("v").split(".")
        if len(parts) != 3 or any(not part.isdigit() for part in parts):
            return None
        return int(parts[0]), int(parts[1]), int(parts[2])
