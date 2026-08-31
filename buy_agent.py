"""모듈 3의 매수 시나리오 에이전트.

완성된 분석 보고서를 읽어 진입 여부를 제안한다. 정량 점수와 가격 배열은
규칙 엔진이 소유하며 LLM은 근거를 설명하거나 진입을 거부할 수만 있다.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

MIN_BUY_SCORE = 6

BUY_AGENT_PROMPT = """
당신은 종목 분석 보고서를 읽는 매수 시나리오 에이전트입니다.
여섯 분석 영역과 핵심 요약을 종합해 지금 Enter 또는 No Entry 중 하나를
선택하세요. 제공된 정량 점수·목표가·손절가를 변경하지 마세요.
근거가 충돌하거나 중대한 위험, 출처 부족이 있으면 No Entry를 선택하세요.
응답은 다음 JSON 하나만 출력하세요.
{"decision":"Enter|No Entry","rationale":"판단 근거","risk":"주요 위험","rejection_reason":"미진입 이유 또는 빈 문자열"}
""".strip()


def _llm_enabled() -> bool:
    from runtime_config import load_runtime_config

    return load_runtime_config().llm_enabled


async def _llm_complete(system_prompt: str, user_msg: str) -> str:
    from llm_provider import LLMProviderError, provider_for
    from runtime_config import load_runtime_config

    provider = provider_for(load_runtime_config())
    if provider is None:
        raise LLMProviderError("활성화된 LLM 공급자가 없습니다")
    return await provider.complete(system_prompt, user_msg)


async def run_buy_agent(report: dict) -> dict:
    """분석 보고서에 규칙 기반 진입 시나리오와 선택 LLM 검토를 더한다."""
    evidence = report.get("_decision_evidence", {})
    strategy = _rule_based_score(evidence)
    strategy["current_price"] = report["current_price"]
    strategy["atr"] = evidence.get("atr14")
    strategy["rationale"] = report.get("executive_summary", "")
    strategy["risk"] = "시장 급락 시 동반 조정 및 수급 이탈 가능성."

    if _llm_enabled():
        message = {
            "report": {key: value for key, value in report.items() if not key.startswith("_")},
            "quantitative_guardrails": strategy,
        }
        try:
            parsed = _extract_json(
                await _llm_complete(BUY_AGENT_PROMPT, json.dumps(message, ensure_ascii=False, default=str))
            )
            strategy = _apply_llm_review(strategy, parsed)
        except Exception as exc:  # noqa: BLE001 - 규칙 시나리오로 안전 폴백
            log.warning("매수 에이전트 실패 → 규칙 시나리오 폴백: %s", type(exc).__name__)

    return _build_scenario(report, strategy)


def _extract_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("응답에 JSON 객체 없음")


def _apply_llm_review(strategy: dict, parsed: dict) -> dict:
    result = dict(strategy)
    decision = str(parsed.get("decision", "")).strip().lower()
    veto = parsed.get("llm_veto") is True or decision in {"no entry", "no_entry", "보류"}
    if veto and result.get("recommendation") == "BUY":
        result["recommendation"] = "HOLD"
    for key in ("rationale", "risk", "rejection_reason"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    return result


def _rule_based_score(data: dict) -> dict:
    """공유 정량 근거로 매수 점수 0~10을 계산한다."""
    if not data.get("structured_evidence"):
        return {"recommendation": "PASS", "buy_score": 0,
                "expected_return_pct": 12, "expected_loss_pct": 6, "investment_period": "중기"}
    score = 5.0
    if data.get("price_vs_ma20") is not None:
        score += 1.2 if data["price_vs_ma20"] >= 0 else -1.0
    if data.get("ma5") and data.get("ma20"):
        score += 0.8 if data["ma5"] >= data["ma20"] else -0.8
    rsi = data.get("rsi")
    if rsi is not None:
        score += -1.0 if rsi >= 75 else 0.5 if rsi <= 30 else 0
    if data.get("vol_ratio") is not None and data["vol_ratio"] >= 1.5:
        score += 1.0
    finance = data.get("finance", {})
    if finance.get("rev_growth") is not None and finance["rev_growth"] > 0:
        score += 0.7
    if finance.get("roe") is not None and finance["roe"] >= 10:
        score += 0.5
    supply = data.get("supply", {})
    if supply.get("up_down_vol_ratio") is not None and supply["up_down_vol_ratio"] >= 1:
        score += 0.5
    buy_score = int(max(0, min(10, round(score))))
    recommendation = "BUY" if buy_score >= 7 else "HOLD" if buy_score >= 5 else "PASS"
    return {"recommendation": recommendation, "buy_score": buy_score,
            "expected_return_pct": 12, "expected_loss_pct": 6, "investment_period": "중기"}


def _round_to(value: float, unit: int) -> int:
    return int(round(value / unit) * unit)


def _build_scenario(report: dict, strategy: dict) -> dict:
    price = strategy.get("current_price") or report["current_price"]
    recommendation = strategy.get("recommendation", "HOLD").upper()
    buy_score = int(strategy.get("buy_score", 0))
    expected_return = float(strategy.get("expected_return_pct", 12))
    expected_loss = float(strategy.get("expected_loss_pct", 6)) or 6
    target = _round_to(price * (1 + expected_return / 100), 100)
    stop = _round_to(price * (1 - expected_loss / 100), 100)
    upside = max(target - price, 0) / price * 100
    downside = max(price - stop, 1) / price * 100
    scenario = {key: value for key, value in report.items() if not key.startswith("_")}
    scenario.update({
        "recommendation": recommendation,
        "decision": "진입" if recommendation == "BUY" and buy_score >= MIN_BUY_SCORE else "보류",
        "buy_score": buy_score,
        "min_score": MIN_BUY_SCORE,
        "target_price": target,
        "stop_loss": stop,
        "risk_reward_ratio": round(upside / downside, 1) if downside else 0.0,
        "expected_return_pct": round(upside, 1),
        "expected_loss_pct": round(downside, 1),
        "atr": strategy.get("atr"),
        "investment_period": strategy.get("investment_period", "중기"),
        "rationale": strategy.get("rationale", ""),
        "risk": strategy.get("risk", ""),
        "rejection_reason": strategy.get("rejection_reason", ""),
    })
    return scenario


if __name__ == "__main__":
    import asyncio
    import sys
    from analysis import run_analysis_report

    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"

    async def _main() -> dict:
        report = await run_analysis_report(ticker)
        return await run_buy_agent(report)

    decision = asyncio.run(_main())
    print(json.dumps(decision, ensure_ascii=False, indent=2, default=str))
