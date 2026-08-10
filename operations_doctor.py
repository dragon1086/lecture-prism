"""Read-only operations readiness checks for lecture-prism.

The doctor reports configuration presence and read-only capability checks only.
It must not print raw configuration values, account numbers, tokens, URLs, or
broker payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import sys
from typing import Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import operations_runtime
from brokers.config import normalize_mode, truthy


READY = "READY"
CONDITIONAL = "CONDITIONAL"
BLOCKED = "BLOCKED"
_SEVERITY = {READY: 0, CONDITIONAL: 1, BLOCKED: 2}
_SENSITIVE_KEY_PARTS = (
    "secret",
    "token",
    "password",
    "api_key",
    "app_key",
    "account",
    "url",
    "webhook",
    "ack",
)
_SECRET_TOKEN_RE = re.compile(
    r"(?i)\b[^\s,;:=]*(?:secret|token|password|api[_-]?key|app[_-]?key)[^\s,;:=]*"
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str

    def __post_init__(self) -> None:
        normalized = str(self.status).strip().upper()
        if normalized not in _SEVERITY:
            raise ValueError(f"unsupported doctor status: {self.status}")
        object.__setattr__(self, "status", normalized)


@dataclass(frozen=True)
class DoctorReport:
    verdict: str
    checks: tuple[CheckResult, ...]

    @classmethod
    def from_checks(cls, checks: Sequence[CheckResult]) -> "DoctorReport":
        ordered = tuple(
            sorted(
                checks,
                key=lambda check: (-_SEVERITY[check.status], check.name),
            )
        )
        verdict = READY
        for check in ordered:
            if _SEVERITY[check.status] > _SEVERITY[verdict]:
                verdict = check.status
        return cls(verdict, ordered)


def _selected_profile(profile: str | None, env: Mapping[str, str]) -> str:
    return str(
        profile
        or env.get("LECTURE_PROFILE")
        or env.get("PRISM_PROFILE")
        or "mock"
    ).strip().lower().replace(" ", "_")


def _sensitive_values(env: Mapping[str, str]) -> tuple[str, ...]:
    values: list[str] = []
    for key, value in env.items():
        if not value:
            continue
        lowered = str(key).lower()
        if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            values.append(str(value))
    return tuple(sorted(values, key=len, reverse=True))


def sanitize_text(text: object, *, secrets: Iterable[str] = ()) -> str:
    safe = str(operations_runtime.sanitize_operations_value("message", str(text)))
    for secret in secrets:
        if secret:
            safe = safe.replace(str(secret), "<redacted>")
    safe = _SECRET_TOKEN_RE.sub("<redacted>", safe)
    return safe


def _check_env_presence(
    name: str,
    keys: Sequence[str],
    *,
    env: Mapping[str, str],
    missing_status: str,
    message: str,
) -> CheckResult:
    present = any(bool(str(env.get(key, "")).strip()) for key in keys)
    if present:
        return CheckResult(name, READY, "configured")
    return CheckResult(name, missing_status, message)


def _directory_writable(path: Path) -> bool:
    return path.exists() and path.is_dir() and os.access(path, os.W_OK)


def _common_checks(
    *,
    profile: str,
    env: Mapping[str, str],
    unresolved_order_count: Callable[[], int],
    directory_writable: Callable[[Path], bool],
    project_root: Path,
) -> list[CheckResult]:
    execute_broker = profile in {"paper", "live"}
    policy = operations_runtime.resolve_execution_policy(
        profile,
        execute_broker=execute_broker,
        env=env,
    )
    if policy.blocked_reasons and profile in {"paper", "live"}:
        policy_status = BLOCKED
        policy_message = "broker execution gates missing: " + ",".join(
            policy.blocked_reasons
        )
    elif policy.blocked_reasons == ("unknown_profile",):
        policy_status = BLOCKED
        policy_message = "unknown profile"
    else:
        policy_status = READY
        policy_message = "configured"

    checks = [
        CheckResult("runtime_profile", policy_status, policy_message),
    ]

    required_files = ("main.py", "operations.py", "trading.py", "db.py")
    missing_files = [name for name in required_files if not (project_root / name).exists()]
    checks.append(
        CheckResult(
            "required_files",
            BLOCKED if missing_files else READY,
            "missing: " + ",".join(missing_files) if missing_files else "present",
        )
    )

    runtime_dir = operations_runtime.default_runtime_dir(env)
    runtime_writable = directory_writable(runtime_dir)
    if runtime_writable:
        runtime_message = "writable"
    elif not runtime_dir.exists():
        runtime_message = "not created"
    else:
        runtime_message = "not writable"
    checks.append(
        CheckResult(
            "local_runtime_dir",
            READY if runtime_writable else BLOCKED,
            runtime_message,
        )
    )

    try:
        ZoneInfo("Asia/Seoul")
        kst_status, kst_message = READY, "Asia/Seoul available"
    except Exception:  # pragma: no cover - depends on host tzdata
        kst_status, kst_message = BLOCKED, "timezone unavailable"
    checks.append(CheckResult("kst_timezone", kst_status, kst_message))

    checks.append(
        CheckResult(
            "scheduler_hint",
            READY,
            "configured" if truthy(env.get("LECTURE_ENABLE_SCHEDULER")) else "not enabled",
        )
    )

    unresolved = int(unresolved_order_count())
    checks.append(
        CheckResult(
            "unresolved_orders",
            BLOCKED if unresolved else READY,
            "pending orders exist" if unresolved else "none",
        )
    )
    return checks


def _optional_checks(*, profile: str, env: Mapping[str, str]) -> list[CheckResult]:
    checks: list[CheckResult] = []
    optional_status = CONDITIONAL if profile in {"research", "paper", "live"} else READY
    checks.append(
        _check_env_presence(
            "llm_configuration",
            ("OPENAI_API_KEY", "PRISM_OPENAI_AUTH_MODE"),
            env=env,
            missing_status=optional_status,
            message="missing optional LLM configuration",
        )
    )
    for tool, key in (
        ("perplexity", "PERPLEXITY_API_KEY"),
        ("firecrawl", "FIRECRAWL_API_KEY"),
    ):
        checks.append(
            _check_env_presence(
                f"research_{tool}",
                (key,),
                env=env,
                missing_status=optional_status,
                message=f"missing optional {tool} configuration",
            )
        )
    if truthy(env.get("LECTURE_NOTIFY_DISCORD")):
        checks.append(
            _check_env_presence(
                "discord_notifications",
                ("DISCORD_WEBHOOK_URL",),
                env=env,
                missing_status=CONDITIONAL,
                message="Discord enabled but webhook missing",
            )
        )
    else:
        checks.append(CheckResult("discord_notifications", READY, "not enabled"))
    return checks


def _kis_prefix(profile: str, env: Mapping[str, str]) -> str:
    if profile == "live":
        return "KIS_REAL"
    selected = normalize_mode(
        env.get("LECTURE_KIS_MODE")
        or env.get("KIS_MODE")
        or env.get("LECTURE_BROKER_MODE"),
        default="demo",
    )
    return "KIS_REAL" if selected == "real" else "KIS_PAPER"


def _kis_credentials_check(profile: str, env: Mapping[str, str]) -> CheckResult:
    prefix = _kis_prefix(profile, env)
    required = (
        f"{prefix}_APP_KEY",
        f"{prefix}_APP_SECRET",
        f"{prefix}_ACCOUNT_NO",
    )
    missing = [key for key in required if not str(env.get(key, "")).strip()]
    if missing:
        return CheckResult(
            "kis_credentials",
            BLOCKED,
            "missing: " + ",".join(missing),
        )
    return CheckResult("kis_credentials", READY, f"{prefix} configured")


def _kiwoom_credentials_check(env: Mapping[str, str]) -> CheckResult:
    token = str(env.get("KIWOOM_ACCESS_TOKEN", "")).strip()
    app_key = str(env.get("KIWOOM_APP_KEY") or env.get("KIWOOM_APPKEY") or "").strip()
    secret_key = str(
        env.get("KIWOOM_SECRET_KEY") or env.get("KIWOOM_SECRETKEY") or ""
    ).strip()
    if token or (app_key and secret_key):
        return CheckResult("kiwoom_credentials", READY, "configured")
    return CheckResult(
        "kiwoom_credentials",
        BLOCKED,
        "missing: KIWOOM_ACCESS_TOKEN or KIWOOM_APP_KEY/KIWOOM_SECRET_KEY",
    )


def _toss_integration(env: Mapping[str, str]) -> str:
    selected = str(
        env.get("LECTURE_TOSS_INTEGRATION")
        or env.get("TOSS_SECURITIES_BACKEND")
        or env.get("TOSS_BACKEND")
        or ""
    ).strip().lower().replace("-", "_")
    if selected in {"official", "official_open_api", "openapi", "open_api", "rest"}:
        return "official"
    if selected in {"wts", "tossctl", "web", "web_session"}:
        return "wts"
    has_official = bool(
        str(env.get("TOSS_OPENAPI_CLIENT_ID", "")).strip()
        or str(env.get("TOSS_OPENAPI_CLIENT_SECRET", "")).strip()
    )
    return "official" if has_official else "wts"


def _toss_official_credentials_check(env: Mapping[str, str]) -> CheckResult:
    required = (
        "TOSS_OPENAPI_CLIENT_ID",
        "TOSS_OPENAPI_CLIENT_SECRET",
        "TOSS_OPENAPI_ACCOUNT_SEQ",
    )
    missing = [key for key in required if not str(env.get(key, "")).strip()]
    if missing:
        return CheckResult(
            "toss_official_credentials",
            BLOCKED,
            "missing: " + ",".join(missing),
        )
    return CheckResult("toss_official_credentials", READY, "configured")


def _toss_wts_contract_check(env: Mapping[str, str]) -> CheckResult:
    if str(env.get("TOSSCTL_PATH", "")).strip():
        return CheckResult("toss_wts_contract", READY, "pinned tossctl configured")
    return CheckResult(
        "toss_wts_contract",
        BLOCKED,
        "missing: TOSSCTL_PATH for pinned tossctl WTS contract",
    )


async def _run_readonly_check(
    name: str,
    operation,
    *,
    secrets: Iterable[str],
) -> CheckResult:
    del secrets
    try:
        await operation()
    except Exception:  # noqa: BLE001 - readiness check must isolate failures
        return CheckResult(name, BLOCKED, "read-only capability unavailable")
    return CheckResult(name, READY, "read-only check passed")


async def _run_capability_check(
    adapter,
    *,
    method_name: str,
    check_name: str,
    operation_factory,
    secrets: Iterable[str],
) -> CheckResult:
    method = getattr(adapter, method_name, None)
    if not callable(method):
        message = (
            f"missing capability: {method_name}"
            if method is None
            else f"unavailable capability: {method_name}"
        )
        return CheckResult(check_name, BLOCKED, message)
    return await _run_readonly_check(
        check_name,
        operation_factory(method),
        secrets=secrets,
    )


def _callable_capability_check(
    adapter,
    *,
    method_name: str,
    check_name: str,
) -> CheckResult:
    method = getattr(adapter, method_name, None)
    if not callable(method):
        message = (
            f"missing capability: {method_name}"
            if method is None
            else f"unavailable capability: {method_name}"
        )
        return CheckResult(check_name, BLOCKED, message)
    return CheckResult(
        check_name,
        BLOCKED,
        "order-level cancellation E2E approval required; cancel_order not invoked",
    )


async def _kis_readiness_checks(
    *,
    profile: str,
    env: Mapping[str, str],
    kis_adapter_factory,
    now: Callable[[], datetime],
) -> list[CheckResult]:
    credentials = _kis_credentials_check(profile, env)
    checks = [credentials]
    if credentials.status == BLOCKED:
        return checks

    secrets = _sensitive_values(env)
    try:
        adapter = kis_adapter_factory()
    except Exception:  # noqa: BLE001 - readiness check must isolate failures
        checks.append(
            CheckResult("kis_adapter", BLOCKED, "adapter initialization unavailable")
        )
        return checks

    business_date = now().strftime("%Y%m%d")
    ticker = str(env.get("LECTURE_DOCTOR_TICKER") or "005930").strip() or "005930"
    price = int(str(env.get("LECTURE_DOCTOR_PRICE") or "1").strip() or "1")

    async def authentication():
        method = getattr(adapter, "check_authentication")
        await method()

    async def market_day():
        await adapter.is_market_open()

    account_cache: dict[str, object] = {}

    async def account_access():
        account_cache["value"] = await adapter.get_account()

    async def holdings():
        if "value" not in account_cache:
            account_cache["value"] = await adapter.get_account()
        account = account_cache["value"]
        if not isinstance(account, Mapping) or "positions" not in account:
            raise RuntimeError("KIS account response missing holdings")

    async def orderable_quantity():
        quantity = await adapter.get_orderable_quantity(ticker, price)
        if int(quantity) < 0:
            raise RuntimeError("KIS orderable quantity is invalid")

    async def fresh_quote():
        await adapter.get_quote(ticker)

    async def pending_order_inquiry():
        method = getattr(adapter, "get_pending_orders", None)
        if method is None:
            raise RuntimeError("KIS pending-order inquiry capability missing")
        await method(business_date=business_date)

    for name, operation in (
        ("kis_authentication", authentication),
        ("kis_market_day", market_day),
        ("kis_account_access", account_access),
        ("kis_orderable_quantity", orderable_quantity),
        ("kis_holdings", holdings),
        ("kis_fresh_quote", fresh_quote),
        ("kis_pending_order_inquiry", pending_order_inquiry),
    ):
        checks.append(await _run_readonly_check(name, operation, secrets=secrets))
    return checks


async def _kiwoom_readiness_checks(
    *,
    env: Mapping[str, str],
    kiwoom_adapter_factory,
    now: Callable[[], datetime],
) -> list[CheckResult]:
    credentials = _kiwoom_credentials_check(env)
    checks = [credentials]
    if credentials.status == BLOCKED:
        return checks

    secrets = _sensitive_values(env)
    try:
        adapter = kiwoom_adapter_factory()
    except Exception:  # noqa: BLE001 - readiness check must isolate failures
        checks.append(
            CheckResult("kiwoom_adapter", BLOCKED, "adapter initialization unavailable")
        )
        return checks

    business_date = now().strftime("%Y%m%d")
    ticker = str(env.get("LECTURE_DOCTOR_TICKER") or "005930").strip() or "005930"
    price = int(str(env.get("LECTURE_DOCTOR_PRICE") or "1").strip() or "1")

    account_cache: dict[str, object] = {}

    async def account_access(method):
        account_cache["value"] = await method()

    async def orderable_quantity(method):
        quantity = await method(ticker, price)
        if int(quantity) < 0:
            raise RuntimeError("Kiwoom orderable quantity is invalid")

    async def sellable_quantity(method):
        quantity = await method(ticker)
        if int(quantity) < 0:
            raise RuntimeError("Kiwoom sellable quantity is invalid")

    async def fresh_quote(method):
        await method(ticker)

    async def pending_order_inquiry(method):
        await method(business_date=business_date)

    async def completed_order_inquiry(method):
        await method(business_date=business_date)

    for method_name, check_name, operation in (
        (
            "check_authentication",
            "kiwoom_authentication",
            lambda method: lambda: method(),
        ),
        (
            "get_account",
            "kiwoom_account_access",
            lambda method: lambda: account_access(method),
        ),
        (
            "get_orderable_quantity",
            "kiwoom_orderable_quantity",
            lambda method: lambda: orderable_quantity(method),
        ),
        (
            "get_sellable_quantity",
            "kiwoom_sellable_quantity",
            lambda method: lambda: sellable_quantity(method),
        ),
        (
            "get_quote",
            "kiwoom_fresh_quote",
            lambda method: lambda: fresh_quote(method),
        ),
        (
            "get_pending_orders",
            "kiwoom_pending_order_inquiry",
            lambda method: lambda: pending_order_inquiry(method),
        ),
        (
            "get_completed_orders",
            "kiwoom_completed_order_inquiry",
            lambda method: lambda: completed_order_inquiry(method),
        ),
    ):
        checks.append(
            await _run_capability_check(
                adapter,
                method_name=method_name,
                check_name=check_name,
                operation_factory=operation,
                secrets=secrets,
            )
        )
    checks.append(
        _callable_capability_check(
            adapter,
            method_name="cancel_order",
            check_name="kiwoom_cancel_capability",
        )
    )
    return checks


async def _toss_official_readiness_checks(
    *,
    env: Mapping[str, str],
    toss_official_adapter_factory,
) -> list[CheckResult]:
    credentials = _toss_official_credentials_check(env)
    checks = [credentials]
    if credentials.status == BLOCKED:
        return checks

    secrets = _sensitive_values(env)
    try:
        adapter = toss_official_adapter_factory()
    except _TossOfficialReadClientIntegrationUnavailable:
        checks.append(
            CheckResult(
                "toss_official_read_client_integration",
                BLOCKED,
                "supported official read-only client integration is not wired; inject through toss_official_adapter_factory",
            )
        )
        return checks
    except Exception:  # noqa: BLE001 - readiness check must isolate failures
        checks.append(
            CheckResult(
                "toss_official_adapter",
                BLOCKED,
                "adapter initialization unavailable",
            )
        )
        return checks

    ticker = str(env.get("LECTURE_DOCTOR_TICKER") or "005930").strip() or "005930"
    pending_cache: dict[str, object] = {}

    async def authentication():
        method = getattr(adapter, "check_authentication")
        result = await method()
        if isinstance(result, Mapping) and result.get("authenticated") is False:
            raise RuntimeError("Toss official authentication unavailable")

    async def account_access():
        account = await adapter.get_account()
        if not isinstance(account, Mapping) or int(account.get("accounts_count", 0)) < 1:
            raise RuntimeError("Toss official account response missing account")

    async def holdings():
        quantity = await adapter.get_sellable_quantity(ticker)
        if int(quantity) < 0:
            raise RuntimeError("Toss official holdings quantity is invalid")

    async def fresh_quote():
        await adapter.get_quote(ticker)

    async def pending_order_inquiry():
        pending = await adapter.get_pending_orders()
        if not isinstance(pending, list):
            raise RuntimeError("Toss official pending orders payload malformed")
        pending_cache["value"] = pending

    async def lifecycle_fixture():
        pending = pending_cache.get("value")
        if pending is None:
            pending = await adapter.get_pending_orders()
            if not isinstance(pending, list):
                raise RuntimeError("Toss official pending orders payload malformed")
        if not pending:
            return
        first = pending[0]
        if not isinstance(first, Mapping):
            raise RuntimeError("Toss official pending order item malformed")
        order_no = first.get("order_no") or first.get("orderId") or first.get("id")
        if not order_no:
            raise RuntimeError("Toss official pending order lacks identifier")
        status = await adapter.get_order_status(str(order_no))
        if not isinstance(status, Mapping) or status.get("status") == "unknown":
            raise RuntimeError("Toss official lifecycle status unknown")

    read_only_checks: list[CheckResult] = []
    for name, operation in (
        ("toss_official_authentication", authentication),
        ("toss_official_account_access", account_access),
        ("toss_official_holdings", holdings),
        ("toss_official_fresh_quote", fresh_quote),
        ("toss_official_pending_order_inquiry", pending_order_inquiry),
        ("toss_official_lifecycle_fixture", lifecycle_fixture),
    ):
        result = await _run_readonly_check(name, operation, secrets=secrets)
        checks.append(result)
        read_only_checks.append(result)
    prerequisites_ready = all(check.status == READY for check in read_only_checks)
    checks.append(
        CheckResult(
            "toss_official_order_e2e",
            (
                CONDITIONAL
                if prerequisites_ready
                else BLOCKED
            ),
            (
                "official live read-only/lifecycle checked; order-level E2E not approved"
                if prerequisites_ready
                else "official read-only/lifecycle prerequisite failed; order-level E2E not approved"
            ),
        )
    )
    return checks


async def _toss_wts_readiness_checks(
    *,
    env: Mapping[str, str],
    toss_wts_adapter_factory,
) -> list[CheckResult]:
    checks = [_toss_wts_contract_check(env)]
    if checks[0].status == BLOCKED:
        return checks

    secrets = _sensitive_values(env)
    try:
        adapter = toss_wts_adapter_factory()
    except Exception:  # noqa: BLE001 - readiness check must isolate failures
        checks.append(
            CheckResult("toss_wts_adapter", BLOCKED, "adapter initialization unavailable")
        )
        return checks

    ticker = str(env.get("LECTURE_DOCTOR_TICKER") or "005930").strip() or "005930"
    pending_cache: dict[str, object] = {}

    async def authentication():
        method = getattr(adapter, "check_auth", None) or getattr(
            adapter, "check_authentication"
        )
        result = await method()
        if not isinstance(result, Mapping):
            raise RuntimeError("Toss WTS authentication payload malformed")
        if result.get("success") is False or result.get("status") in {"blocked", "unknown"}:
            raise RuntimeError("Toss WTS session is unavailable")

    async def account_access():
        await adapter.get_account()

    async def holdings():
        quantity = await adapter.get_sellable_quantity(ticker)
        if int(quantity) < 0:
            raise RuntimeError("Toss WTS holdings quantity is invalid")

    async def fresh_quote():
        method = getattr(adapter, "get_quote", None)
        if not callable(method):
            raise RuntimeError("Toss WTS quote capability missing")
        await method(ticker)

    async def pending_order_inquiry():
        pending = await adapter.get_pending_orders()
        if not isinstance(pending, list):
            raise RuntimeError("Toss WTS pending orders payload malformed")
        pending_cache["value"] = pending

    async def lifecycle_fixture():
        pending = pending_cache.get("value")
        if pending is None:
            pending = await adapter.get_pending_orders()
            if not isinstance(pending, list):
                raise RuntimeError("Toss WTS pending orders payload malformed")
        if not pending:
            return
        first = pending[0]
        if not isinstance(first, Mapping):
            raise RuntimeError("Toss WTS pending order item malformed")
        order_no = first.get("order_no") or first.get("orderId") or first.get("id")
        if not order_no:
            raise RuntimeError("Toss WTS pending order lacks identifier")
        status = await adapter.get_order_status(str(order_no))
        if not isinstance(status, Mapping) or status.get("status") == "unknown":
            raise RuntimeError("Toss WTS lifecycle status unknown")

    auth = await _run_readonly_check(
        "toss_wts_authentication",
        authentication,
        secrets=secrets,
    )
    checks.append(auth)
    if auth.status == BLOCKED:
        return checks

    for name, operation in (
        ("toss_wts_account_access", account_access),
        ("toss_wts_holdings", holdings),
        ("toss_wts_fresh_quote", fresh_quote),
        ("toss_wts_pending_order_inquiry", pending_order_inquiry),
        ("toss_wts_lifecycle_fixture", lifecycle_fixture),
    ):
        checks.append(await _run_readonly_check(name, operation, secrets=secrets))
    checks.append(
        CheckResult(
            "toss_wts_live_boundary",
            BLOCKED,
            "WTS-only live readiness is never READY; manual session recovery required",
        )
    )
    return checks


def _default_kis_adapter_factory(profile: str, env: Mapping[str, str]):
    def build():
        import db
        from brokers.kis import KISBrokerAdapter
        from brokers.kis_client import KISClient, KISConfig
        from market_calendar import MarketGate

        mode = "real" if _kis_prefix(profile, env) == "KIS_REAL" else "demo"
        config_mode = "paper" if mode == "demo" else "real"
        client = KISClient(KISConfig.from_env(config_mode))
        gate = MarketGate(
            client,
            cache_get=db.get_market_day,
            cache_save=None,
            mode=mode,
        )
        return KISBrokerAdapter(mode=mode, client=client, gate=gate)

    return build


def _default_kiwoom_adapter_factory():
    def build():
        from brokers.kiwoom import KiwoomBrokerAdapter

        return KiwoomBrokerAdapter()

    return build


class _TossOfficialReadClientIntegrationUnavailable(RuntimeError):
    """Raised until a supported official REST read client is integrated."""


def _default_toss_official_adapter_factory():
    def build():
        raise _TossOfficialReadClientIntegrationUnavailable(
            "supported official read-only client integration is not wired"
        )

    return build


def _default_toss_wts_adapter_factory():
    def build():
        from brokers.toss import TossBrokerAdapter

        return TossBrokerAdapter(mode="real")

    return build


async def run_doctor(
    *,
    profile: str | None = None,
    env: Mapping[str, str] | None = None,
    kis_adapter_factory=None,
    kiwoom_adapter_factory=None,
    toss_official_adapter_factory=None,
    toss_wts_adapter_factory=None,
    unresolved_order_count=None,
    directory_writable: Callable[[Path], bool] = _directory_writable,
    project_root: Path | None = None,
    now: Callable[[], datetime] = datetime.now,
) -> DoctorReport:
    source = env if env is not None else os.environ
    selected_profile = _selected_profile(profile, source)
    root = project_root or Path(__file__).resolve().parent
    count = unresolved_order_count
    if count is None:
        from operations import _unresolved_order_count

        count = _unresolved_order_count

    checks = []
    checks.extend(
        _common_checks(
            profile=selected_profile,
            env=source,
            unresolved_order_count=count,
            directory_writable=directory_writable,
            project_root=root,
        )
    )
    checks.extend(_optional_checks(profile=selected_profile, env=source))

    broker = str(source.get("LECTURE_BROKER") or "kis").strip().lower()
    if selected_profile in {"paper", "live"}:
        if broker == "kis":
            factory = kis_adapter_factory or _default_kis_adapter_factory(
                selected_profile, source
            )
            checks.extend(
                await _kis_readiness_checks(
                    profile=selected_profile,
                    env=source,
                    kis_adapter_factory=factory,
                    now=now,
                )
            )
        elif broker == "kiwoom":
            factory = kiwoom_adapter_factory or _default_kiwoom_adapter_factory()
            checks.extend(
                await _kiwoom_readiness_checks(
                    env=source,
                    kiwoom_adapter_factory=factory,
                    now=now,
                )
            )
        elif broker == "toss":
            if selected_profile == "paper":
                checks.append(
                    CheckResult(
                        "toss_paper",
                        BLOCKED,
                        "Toss has no paper/demo trading environment",
                    )
                )
            elif _toss_integration(source) == "official":
                factory = (
                    toss_official_adapter_factory
                    or _default_toss_official_adapter_factory()
                )
                checks.extend(
                    await _toss_official_readiness_checks(
                        env=source,
                        toss_official_adapter_factory=factory,
                    )
                )
            else:
                factory = toss_wts_adapter_factory or _default_toss_wts_adapter_factory()
                checks.extend(
                    await _toss_wts_readiness_checks(
                        env=source,
                        toss_wts_adapter_factory=factory,
                    )
                )
        else:
            checks.append(
                CheckResult(
                    "broker_readiness",
                    BLOCKED,
                    "doctor supports KIS, Kiwoom, and Toss readiness",
                )
            )

    return DoctorReport.from_checks(checks)


def format_doctor_report(
    report: DoctorReport,
    *,
    secrets: Iterable[str] = (),
) -> str:
    lines = [f"verdict: {report.verdict}", "checks:"]
    for check in report.checks:
        message = sanitize_text(check.message, secrets=secrets)
        lines.append(f"  [{check.status}] {check.name}: {message}")
    return "\n".join(lines) + "\n"


async def print_doctor(
    *,
    output=sys.stdout,
    profile: str | None = None,
    env: Mapping[str, str] | None = None,
    kis_adapter_factory=None,
    kiwoom_adapter_factory=None,
    toss_official_adapter_factory=None,
    toss_wts_adapter_factory=None,
    unresolved_order_count=None,
    directory_writable: Callable[[Path], bool] = _directory_writable,
    now: Callable[[], datetime] = datetime.now,
) -> DoctorReport:
    source = env if env is not None else os.environ
    report = await run_doctor(
        profile=profile,
        env=source,
        kis_adapter_factory=kis_adapter_factory,
        kiwoom_adapter_factory=kiwoom_adapter_factory,
        toss_official_adapter_factory=toss_official_adapter_factory,
        toss_wts_adapter_factory=toss_wts_adapter_factory,
        unresolved_order_count=unresolved_order_count,
        directory_writable=directory_writable,
        now=now,
    )
    output.write(format_doctor_report(report, secrets=_sensitive_values(source)))
    return report
