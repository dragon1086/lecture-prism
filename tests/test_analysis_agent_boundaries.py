import asyncio
import json
import os
import unittest
from unittest import mock

import analysis


_DECISION_FIELDS = {
    "recommendation",
    "decision",
    "buy_score",
    "target_price",
    "stop_loss",
    "risk_reward_ratio",
}


class AnalysisAgentBoundaryTest(unittest.TestCase):
    def setUp(self):
        self._llm_mode = os.environ.get("LECTURE_LLM_MODE")
        os.environ["LECTURE_LLM_MODE"] = "mock"

    def tearDown(self):
        if self._llm_mode is None:
            os.environ.pop("LECTURE_LLM_MODE", None)
        else:
            os.environ["LECTURE_LLM_MODE"] = self._llm_mode

    def test_report_contains_no_buy_decision_fields(self):
        report = asyncio.run(analysis.run_analysis_report("005930"))

        self.assertTrue(_DECISION_FIELDS.isdisjoint(report))
        self.assertIn("executive_summary", report)
        for key in (
            "technical_summary",
            "supply_summary",
            "financial_summary",
            "industry_summary",
            "news_summary",
            "market_condition",
        ):
            self.assertIn(key, report)

    def test_six_specialists_and_editor_use_seven_independent_calls(self):
        os.environ["LECTURE_LLM_MODE"] = "oauth"
        calls = []

        async def complete(system_prompt, user_message):
            calls.append(system_prompt)
            if "보고서 편집장" in system_prompt:
                return json.dumps({"executive_summary": "여섯 보고서 핵심 요약"})
            return json.dumps({"summary": "입력 근거에 한정한 전문 분석"})

        with mock.patch("analysis._llm_complete", side_effect=complete):
            report = asyncio.run(analysis.run_analysis_report("005930"))

        self.assertEqual(len(calls), 7)
        self.assertEqual(sum("보고서 편집장" in prompt for prompt in calls), 1)
        self.assertEqual(report["executive_summary"], "여섯 보고서 핵심 요약")

    def test_one_specialist_failure_falls_back_without_canceling_others(self):
        os.environ["LECTURE_LLM_MODE"] = "oauth"

        async def complete(system_prompt, user_message):
            if "수급 분석가" in system_prompt:
                raise RuntimeError("section unavailable")
            if "보고서 편집장" in system_prompt:
                return json.dumps({"executive_summary": "나머지 보고서로 작성한 요약"})
            return json.dumps({"summary": "개별 에이전트 결과"})

        with mock.patch("analysis._llm_complete", side_effect=complete):
            report = asyncio.run(analysis.run_analysis_report("005930"))

        self.assertIn("거래량", report["supply_summary"])
        self.assertEqual(report["technical_summary"], "개별 에이전트 결과")
        self.assertEqual(report["executive_summary"], "나머지 보고서로 작성한 요약")

    def test_legacy_run_analysis_still_returns_buy_scenario_shape(self):
        result = asyncio.run(analysis.run_analysis("005930"))

        self.assertTrue(_DECISION_FIELDS.issubset(result))
        self.assertIn("technical_summary", result)


if __name__ == "__main__":
    unittest.main()
