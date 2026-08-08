"""Pure execution-policy resolution for unattended operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


LIVE_BROKER_UNATTENDED_ACK = (
    "I UNDERSTAND THIS LECTURE-PRISM RUN MAY SEND UNATTENDED REAL BROKER ORDERS"
)

_SIMULATION_PROFILES = frozenset({"mock", "classroom", "real_data", "research", "backtest"})
_ACCOUNT_MODES = {
    "paper": "demo",
    "live": "real",
}


@dataclass(frozen=True)
class ExecutionPolicy:
    profile: str
    account_mode: str
    requested_broker_execution: bool
    broker_execution_allowed: bool
    dry_run: bool
    blocked_reasons: tuple[str, ...]


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _profile(value: str) -> str:
    return str(value or "mock").strip().lower().replace("-", "_").replace(" ", "_")


def resolve_execution_policy(
    profile: str,
    *,
    execute_broker: bool,
    env: Mapping[str, str] | None = None,
) -> ExecutionPolicy:
    """Resolve whether unattended operations may call broker APIs.

    The environment is injectable so callers and tests can decide which values
    are visible. This function never includes raw environment values in the
    returned policy.
    """

    selected_profile = _profile(profile)
    requested = bool(execute_broker)
    source = env if env is not None else os.environ

    if selected_profile in _SIMULATION_PROFILES:
        return ExecutionPolicy(
            profile=selected_profile,
            account_mode="simulation",
            requested_broker_execution=requested,
            broker_execution_allowed=False,
            dry_run=True,
            blocked_reasons=("profile_forces_simulation",),
        )

    account_mode = _ACCOUNT_MODES.get(selected_profile, "simulation")
    if not requested:
        return ExecutionPolicy(
            profile=selected_profile,
            account_mode="simulation",
            requested_broker_execution=False,
            broker_execution_allowed=False,
            dry_run=True,
            blocked_reasons=("broker_execution_not_requested",),
        )

    blocked_reasons: list[str] = []
    if not _truthy(source.get("LECTURE_ENABLE_LIVE_BROKER")):
        blocked_reasons.append("live_broker_not_enabled")
    if account_mode == "real":
        if not _truthy(source.get("LECTURE_ALLOW_REAL_BROKER")):
            blocked_reasons.append("real_broker_not_allowed")
        if source.get("LECTURE_UNATTENDED_LIVE_ACK") != LIVE_BROKER_UNATTENDED_ACK:
            blocked_reasons.append("unattended_live_ack_missing")

    blocked = tuple(blocked_reasons)
    return ExecutionPolicy(
        profile=selected_profile,
        account_mode=account_mode,
        requested_broker_execution=True,
        broker_execution_allowed=not blocked,
        dry_run=bool(blocked),
        blocked_reasons=blocked,
    )
