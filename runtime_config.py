"""Runtime profile and integration settings for lecture-prism.

This module is intentionally stdlib-only. Students should be able to control
the project from `.env` without installing extra configuration packages.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from brokers.config import load_dotenv_once, normalize_mode, truthy
from brokers.factory import selected_broker_name
from operations_runtime import LIVE_BROKER_UNATTENDED_ACK


_PROFILE_DEFAULTS = {
    "mock": {
        "data_mode": "mock",
        "screening_mode": "mock",
        "llm_mode": "mock",
        "report_mode": "lite",
        "research_tools": "",
        "trade_mode": "simulation",
    },
    "classroom": {
        "data_mode": "mock",
        "screening_mode": "fixture",
        "llm_mode": "mock",
        "report_mode": "lite",
        "research_tools": "",
        "trade_mode": "simulation",
    },
    "real_data": {
        "data_mode": "auto",
        "screening_mode": "mock",
        "llm_mode": "mock",
        "report_mode": "lite",
        "research_tools": "",
        "trade_mode": "simulation",
    },
    "research": {
        "data_mode": "auto",
        "screening_mode": "mock",
        "llm_mode": "auto",
        "report_mode": "research",
        "research_tools": "perplexity,firecrawl",
        "trade_mode": "simulation",
    },
    "paper": {
        "data_mode": "yfinance",
        "screening_mode": "real",
        "llm_mode": "auto",
        "report_mode": "research",
        "research_tools": "perplexity,firecrawl",
        "trade_mode": "demo",
    },
    "live": {
        "data_mode": "yfinance",
        "screening_mode": "real",
        "llm_mode": "auto",
        "report_mode": "research",
        "research_tools": "perplexity,firecrawl",
        "trade_mode": "real",
    },
    "backtest": {
        "data_mode": "mock",
        "screening_mode": "fixture",
        "llm_mode": "mock",
        "report_mode": "lite",
        "research_tools": "",
        "trade_mode": "simulation",
    },
}

_PROFILE_ALIASES = {
    "dummy": "mock",
    "demo": "mock",
    "basic": "mock",
    "class": "classroom",
    "replay": "classroom",
    "realdata": "real_data",
    "real-data": "real_data",
    "advanced": "research",
    "prism": "research",
    "full": "research",
    "paper_trade": "paper",
    "paper-trade": "paper",
    "broker_demo": "paper",
    "broker-demo": "paper",
    "real": "live",
    "prod": "live",
    "walk_forward": "backtest",
}

PROFILE_CHOICES = tuple(sorted(set(_PROFILE_DEFAULTS) | set(_PROFILE_ALIASES)))
_FIXED_SIMULATION_PROFILES = frozenset({"classroom", "backtest"})

_DATA_ALIASES = {
    "dummy": "mock",
    "demo": "mock",
    "simulation": "mock",
    "yf": "yfinance",
    "yahoo": "yfinance",
}

_LLM_ALIASES = {
    "dummy": "mock",
    "none": "mock",
    "off": "mock",
    "chatgpt": "oauth",
    "chatgpt_oauth": "oauth",
    "api": "openai",
}

_REPORT_ALIASES = {
    "mock": "lite",
    "basic": "lite",
    "full": "research",
    "prism": "research",
}

_TRADE_ALIASES = {
    "mock": "simulation",
    "dummy": "simulation",
    "sim": "simulation",
    "dryrun": "simulation",
    "dry-run": "simulation",
    "paper": "demo",
    "paper_trade": "demo",
    "broker_demo": "demo",
    "broker-demo": "demo",
    "prod": "real",
    "live": "real",
}


@dataclass(frozen=True)
class RuntimeConfig:
    profile: str
    data_mode: str
    screening_mode: str
    llm_mode: str
    report_mode: str
    research_tools: tuple[str, ...]
    trade_mode: str
    broker: str
    broker_mode: str
    llm_enabled: bool
    chatgpt_oauth_requested: bool
    tool_ready: dict[str, bool]
    live_broker_enabled: bool
    real_broker_allowed: bool

    def summary(self) -> str:
        tools = ",".join(self.research_tools) if self.research_tools else "off"
        return (
            f"profile={self.profile}, data={self.data_mode}, screening={self.screening_mode}, "
            f"llm={self.llm_mode}, report={self.report_mode}, tools={tools}, "
            f"trade={self.trade_mode}, broker={self.broker}/{self.broker_mode}"
        )


_CURRENT_RUNTIME_CONFIG: ContextVar[RuntimeConfig | None] = ContextVar(
    "lecture_prism_runtime_config", default=None
)


@contextmanager
def runtime_config_scope(config: RuntimeConfig) -> Iterator[RuntimeConfig]:
    """Expose one normalized config to all readers in this execution context."""

    token = _CURRENT_RUNTIME_CONFIG.set(config)
    try:
        yield config
    finally:
        _CURRENT_RUNTIME_CONFIG.reset(token)


def _normalize(value: str | None, *, default: str, aliases: dict[str, str],
               allowed: set[str]) -> str:
    text = str(value or default).strip().lower().replace(" ", "_")
    text = aliases.get(text, text)
    return text if text in allowed else default


def _profile(explicit: str | None = None) -> str:
    raw = explicit
    if raw is None:
        raw = os.getenv("LECTURE_PROFILE") or os.getenv("PRISM_PROFILE")
    return _normalize(
        raw,
        default="mock",
        aliases=_PROFILE_ALIASES,
        allowed=set(_PROFILE_DEFAULTS),
    )


def _csv(value: str) -> tuple[str, ...]:
    seen = []
    for raw in value.split(","):
        item = raw.strip().lower().replace("-", "_")
        if item and item not in seen:
            seen.append(item)
    return tuple(seen)


def _tool_ready(tool: str) -> bool:
    if tool == "perplexity":
        return bool(os.getenv("PERPLEXITY_API_KEY"))
    if tool == "firecrawl":
        return bool(os.getenv("FIRECRAWL_API_KEY"))
    return False


def _llm_enabled(llm_mode: str) -> tuple[bool, bool]:
    oauth_requested = (
        os.getenv("PRISM_OPENAI_AUTH_MODE") == "chatgpt_oauth"
        or llm_mode == "oauth"
    )
    api_ready = bool(os.getenv("OPENAI_API_KEY"))
    if llm_mode == "mock":
        return False, oauth_requested
    if llm_mode == "openai":
        return api_ready, oauth_requested
    if llm_mode == "oauth":
        return oauth_requested, oauth_requested
    return bool(api_ready or oauth_requested), oauth_requested


def load_runtime_config(profile: str | None = None) -> RuntimeConfig:
    """Load `.env` and return normalized runtime settings."""

    scoped = _CURRENT_RUNTIME_CONFIG.get()
    if profile is None and scoped is not None:
        return scoped

    load_dotenv_once()
    profile = _profile(profile)
    defaults = _PROFILE_DEFAULTS[profile]

    if profile in _FIXED_SIMULATION_PROFILES:
        return RuntimeConfig(
            profile=profile,
            data_mode=defaults["data_mode"],
            screening_mode=defaults["screening_mode"],
            llm_mode=defaults["llm_mode"],
            report_mode=defaults["report_mode"],
            research_tools=(),
            trade_mode=defaults["trade_mode"],
            broker="paper",
            broker_mode="paper",
            llm_enabled=False,
            chatgpt_oauth_requested=False,
            tool_ready={},
            live_broker_enabled=False,
            real_broker_allowed=False,
        )

    data_mode = _normalize(
        os.getenv("LECTURE_DATA_MODE") or os.getenv("PRISM_DATA_MODE") or defaults["data_mode"],
        default=defaults["data_mode"],
        aliases=_DATA_ALIASES,
        allowed={"mock", "auto", "yfinance"},
    )
    screening_mode = _normalize(
        os.getenv("LECTURE_SCREENING_MODE") or defaults["screening_mode"],
        default=defaults["screening_mode"],
        aliases={"demo": "mock", "pykrx": "real", "yfinance": "real"},
        allowed={"mock", "fixture", "real"},
    )
    if profile in {"paper", "live"}:
        # Operating profiles may not be weakened into fixture/demo decisions
        # through ambient configuration. Provider errors must stay fail-closed.
        data_mode = "yfinance"
        screening_mode = "real"
    llm_mode = _normalize(
        os.getenv("LECTURE_LLM_MODE") or os.getenv("PRISM_LLM_MODE") or defaults["llm_mode"],
        default=defaults["llm_mode"],
        aliases=_LLM_ALIASES,
        allowed={"mock", "auto", "oauth", "openai"},
    )
    report_mode = _normalize(
        os.getenv("LECTURE_REPORT_MODE") or os.getenv("PRISM_REPORT_MODE") or defaults["report_mode"],
        default=defaults["report_mode"],
        aliases=_REPORT_ALIASES,
        allowed={"lite", "research"},
    )
    research_tools = _csv(os.getenv("LECTURE_RESEARCH_TOOLS", defaults["research_tools"]))
    trade_mode = _normalize(
        os.getenv("LECTURE_TRADE_MODE") or defaults["trade_mode"],
        default=defaults["trade_mode"],
        aliases=_TRADE_ALIASES,
        allowed={"simulation", "demo", "real"},
    )
    broker = selected_broker_name(default="kis")
    if broker == "kis":
        from brokers.kis import selected_kis_mode

        broker_mode = selected_kis_mode()
    elif broker == "kiwoom":
        broker_mode = normalize_mode(
            os.getenv("KIWOOM_MODE") or os.getenv("LECTURE_BROKER_MODE"),
            default="demo",
        )
    elif broker == "toss":
        broker_mode = normalize_mode(
            os.getenv("TOSS_SECURITIES_MODE") or os.getenv("LECTURE_BROKER_MODE"),
            default="demo",
        )
    else:
        broker_mode = normalize_mode(
            os.getenv("LECTURE_BROKER_MODE"),
            default="demo",
        )
    llm_enabled, oauth_requested = _llm_enabled(llm_mode)
    tool_ready = {tool: _tool_ready(tool) for tool in research_tools}
    live_broker_enabled = truthy(os.getenv("LECTURE_ENABLE_LIVE_BROKER")) or truthy(
        os.getenv(f"LECTURE_ENABLE_LIVE_{broker.upper()}")
    )
    real_broker_allowed = truthy(os.getenv("LECTURE_ALLOW_REAL_BROKER")) or truthy(
        os.getenv(f"LECTURE_ALLOW_REAL_{broker.upper()}")
    )

    return RuntimeConfig(
        profile=profile,
        data_mode=data_mode,
        screening_mode=screening_mode,
        llm_mode=llm_mode,
        report_mode=report_mode,
        research_tools=research_tools,
        trade_mode=trade_mode,
        broker=broker,
        broker_mode=broker_mode,
        llm_enabled=llm_enabled,
        chatgpt_oauth_requested=oauth_requested,
        tool_ready=tool_ready,
        live_broker_enabled=live_broker_enabled,
        real_broker_allowed=real_broker_allowed,
    )


def resolve_trade_dry_run(explicit_live: bool, explicit_dry_run: bool,
                          config: RuntimeConfig | None = None) -> bool:
    """Resolve whether `main.py` should stay in simulation mode."""

    cfg = config or load_runtime_config()
    if cfg.profile in _FIXED_SIMULATION_PROFILES:
        return True
    if explicit_live:
        return False
    if explicit_dry_run:
        return True
    return cfg.trade_mode == "simulation"
