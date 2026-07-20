from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType

from .domain import (
    Candidate,
    EntryDecision,
    Regime,
    RegimePolicy,
    TriggerType,
)


def _decimal(value: str) -> Decimal:
    return Decimal(value)


_CONFIGURED_STRATEGY_FLOOR = Decimal("6")

_POLICIES = MappingProxyType(
    {
        Regime.STRONG_BULL: RegimePolicy(
            frozenset(
                {
                    TriggerType.BREAKOUT,
                    TriggerType.PULLBACK,
                    TriggerType.VOLUME_SURGE,
                    TriggerType.RELATIVE_STRENGTH,
                }
            ),
            _decimal("6.0"),
            _decimal("6"),
            _decimal("1.2"),
            _decimal("7"),
            _decimal("1.0"),
            10,
            _decimal("10"),
            _decimal("8"),
        ),
        Regime.MODERATE_BULL: RegimePolicy(
            frozenset(
                {
                    TriggerType.BREAKOUT,
                    TriggerType.PULLBACK,
                    TriggerType.VOLUME_SURGE,
                    TriggerType.RELATIVE_STRENGTH,
                }
            ),
            _decimal("6.5"),
            _decimal("6"),
            _decimal("1.3"),
            _decimal("7"),
            _decimal("0.8"),
            8,
            _decimal("20"),
            _decimal("8"),
        ),
        Regime.SIDEWAYS: RegimePolicy(
            frozenset(
                {
                    TriggerType.PULLBACK,
                    TriggerType.VOLUME_SURGE,
                    TriggerType.OVERSOLD_REBOUND,
                }
            ),
            _decimal("7.0"),
            _decimal("7"),
            _decimal("1.5"),
            _decimal("6"),
            _decimal("0.6"),
            6,
            _decimal("35"),
            _decimal("5"),
        ),
        Regime.MODERATE_BEAR: RegimePolicy(
            frozenset(
                {
                    TriggerType.OVERSOLD_REBOUND,
                    TriggerType.RELATIVE_STRENGTH,
                }
            ),
            _decimal("8.0"),
            _decimal("8"),
            _decimal("1.8"),
            _decimal("5"),
            _decimal("0.4"),
            3,
            _decimal("55"),
            _decimal("5"),
        ),
        Regime.STRONG_BEAR: RegimePolicy(
            frozenset({TriggerType.OVERSOLD_REBOUND}),
            _decimal("9.0"),
            _decimal("9"),
            _decimal("2.0"),
            _decimal("5"),
            _decimal("0.25"),
            1,
            _decimal("75"),
            _decimal("5"),
        ),
    }
)


def policy_for(regime: Regime) -> RegimePolicy:
    """Return the immutable entry policy for an explicit market regime."""

    if not isinstance(regime, Regime):
        raise ValueError("regime must be a Regime")
    return _POLICIES[regime]


def _analysis_decimal(value: Decimal | int) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise ValueError("analysis_score must be a Decimal or integer")
    score = value if isinstance(value, Decimal) else Decimal(value)
    if not score.is_finite() or score < 0:
        raise ValueError("analysis_score must be finite and non-negative")
    return score


def gate_entry(
    candidate: Candidate,
    *,
    analysis_score: Decimal | int,
    llm_enter: bool | None = None,
    policy: RegimePolicy | None = None,
) -> EntryDecision:
    """Apply every quantitative gate before allowing an optional LLM veto."""

    if not isinstance(candidate, Candidate):
        raise ValueError("candidate must be a Candidate")
    if llm_enter is not None and not isinstance(llm_enter, bool):
        raise ValueError("llm_enter must be a bool or None")
    selected_policy = policy_for(candidate.regime) if policy is None else policy
    if not isinstance(selected_policy, RegimePolicy):
        raise ValueError("policy must be a RegimePolicy")
    normalized_analysis_score = _analysis_decimal(analysis_score)
    analysis_floor = max(
        selected_policy.minimum_analysis_score,
        _CONFIGURED_STRATEGY_FLOOR,
    )
    stop_pct = (
        (candidate.reference_price - candidate.stop_price)
        / candidate.reference_price
        * Decimal("100")
    )

    reasons: list[str] = []
    if candidate.trigger_type not in selected_policy.active_triggers:
        reasons.append("trigger_not_active")
    if candidate.final_score < selected_policy.minimum_candidate_score:
        reasons.append("candidate_score_below_floor")
    if normalized_analysis_score < analysis_floor:
        reasons.append("analysis_score_below_floor")
    if candidate.risk_reward_ratio < selected_policy.minimum_risk_reward:
        reasons.append("risk_reward_below_floor")
    if stop_pct > selected_policy.maximum_stop_pct:
        reasons.append("stop_too_wide")
    if llm_enter is False:
        reasons.append("llm_veto")

    return EntryDecision(
        candidate=candidate,
        allowed=not reasons,
        analysis_score=normalized_analysis_score,
        reasons=tuple(reasons),
        policy=selected_policy,
    )
