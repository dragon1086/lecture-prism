import asyncio
import os
import unittest
from unittest import mock

import analysis
import research_tools


_ENV_KEYS = {
    "LECTURE_PROFILE",
    "LECTURE_DATA_MODE",
    "LECTURE_LLM_MODE",
    "LECTURE_REPORT_MODE",
    "LECTURE_RESEARCH_TOOLS",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "PRISM_OPENAI_AUTH_MODE",
}


class AnalysisRuntimeConfigTest(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        self._saved_research_builder = research_tools.build_research_context

    def tearDown(self):
        research_tools.build_research_context = self._saved_research_builder
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_llm_mock_mode_disables_llm_even_when_api_key_exists(self):
        os.environ["LECTURE_LLM_MODE"] = "mock"
        os.environ["OPENAI_API_KEY"] = "sk-test"

        self.assertFalse(analysis._llm_enabled())

    def test_json_extractor_skips_non_json_braces_before_object(self):
        text = '설명 {not-json}\n```json\n{"llm_veto": false, "risk": "없음"}\n```'

        self.assertEqual(
            analysis._extract_json(text),
            {"llm_veto": False, "risk": "없음"},
        )

    def test_legacy_multi_call_helpers_are_not_exposed(self):
        for name in (
            "_run_technical_agent",
            "_run_news_agent",
            "_run_strategy_agent",
        ):
            self.assertFalse(hasattr(analysis, name), name)

    def test_analysis_result_records_runtime_modes(self):
        os.environ["LECTURE_PROFILE"] = "mock"

        result = asyncio.run(analysis.run_analysis("005930"))

        self.assertEqual(result["runtime_profile"], "mock")
        self.assertEqual(result["data_mode"], "mock")
        self.assertEqual(result["report_mode"], "lite")
        self.assertEqual(result["research_tools"], [])
        self.assertIn("runtime_summary", result)

    def test_mock_analysis_derives_indicators_and_score_from_fixture_metrics(self):
        os.environ["LECTURE_PROFILE"] = "mock"

        result = asyncio.run(analysis.run_analysis("005930"))

        self.assertEqual(result["data_source"], "mock")
        self.assertIn("RSI", result["technical_summary"])
        self.assertIn("거래량", result["technical_summary"])
        self.assertEqual(result["buy_score"], 8)
        self.assertEqual(result["data_status"], "교육용 고정 시나리오")
        self.assertIn("현재 시장 정보가 아닙니다", result["data_notice"])
        self.assertIn("technical", result["section_provenance"])

    def test_fixture_metric_change_changes_shared_rule_score(self):
        fixture = {
            "source": "mock",
            "evidence_kind": "fixture",
            "price_vs_ma20": 3.0,
            "ma5": 102.0,
            "ma20": 100.0,
            "rsi": 55.0,
            "vol_ratio": 1.6,
            "finance": {"rev_growth": 5.0, "roe": 12.0},
            "supply": {"up_down_vol_ratio": 1.3},
        }

        strong_score = analysis._rule_based_score(fixture)["buy_score"]
        fixture.update({"price_vs_ma20": -3.0, "ma5": 98.0, "rsi": 78.0, "vol_ratio": 0.8})
        fixture["finance"] = {"rev_growth": -5.0, "roe": 3.0}
        fixture["supply"] = {"up_down_vol_ratio": 0.6}

        self.assertEqual(strong_score, 10)
        self.assertEqual(analysis._rule_based_score(fixture)["buy_score"], 2)

    def test_research_profile_adds_optional_research_context_to_news(self):
        os.environ["LECTURE_PROFILE"] = "research"
        os.environ["LECTURE_LLM_MODE"] = "mock"
        os.environ["PERPLEXITY_API_KEY"] = "pplx-test"

        research_tools.build_research_context = (
            lambda ticker, company_name, sector="": "실시간 리서치: HBM 수요와 환율 리스크"
        )

        result = asyncio.run(analysis.run_analysis("005930"))

        self.assertIn("실시간 리서치", result["news_summary"])

    def test_oauth_analysis_uses_exactly_one_structured_llm_call(self):
        os.environ["LECTURE_LLM_MODE"] = "oauth"
        payload = {
            "technical_summary": "기술 요약",
            "news_summary": "뉴스 요약",
            "llm_veto": False,
            "rationale": "추세와 실적이 함께 개선됨",
            "risk": "시장 레짐 악화",
        }
        with mock.patch(
            "analysis._llm_complete",
            new=mock.AsyncMock(return_value=__import__("json").dumps(payload)),
        ) as complete:
            result = asyncio.run(analysis.run_analysis("005930"))

        complete.assert_awaited_once()
        self.assertEqual(result["technical_summary"], "기술 요약")
        self.assertEqual(result["news_summary"], "뉴스 요약")
        self.assertEqual(result["buy_score"], 8)

    def test_llm_cannot_promote_quantitative_pass_or_control_prices(self):
        os.environ["LECTURE_LLM_MODE"] = "oauth"
        payload = {
            "technical_summary": "기술 요약",
            "news_summary": "뉴스 요약",
            "recommendation": "buy",
            "buy_score": 10,
            "target_price": 999999999,
            "stop_loss": 1,
            "llm_veto": False,
            "rationale": "근거",
            "risk": "위험",
        }
        with mock.patch(
            "analysis._llm_complete",
            new=mock.AsyncMock(return_value=__import__("json").dumps(payload)),
        ):
            result = asyncio.run(analysis.run_analysis("105560"))

        self.assertEqual(result["recommendation"], "PASS")
        self.assertEqual(result["decision"], "보류")
        self.assertEqual(result["buy_score"], 3)
        self.assertNotEqual(result["target_price"], 999999999)
        self.assertNotEqual(result["stop_loss"], 1)

    def test_llm_may_veto_but_never_upgrade_quantitative_buy(self):
        os.environ["LECTURE_LLM_MODE"] = "oauth"
        payload = {
            "technical_summary": "기술 요약",
            "news_summary": "뉴스 요약",
            "llm_veto": True,
            "rationale": "뉴스 근거가 불충분해 보류",
            "risk": "검증되지 않은 촉매",
        }
        with mock.patch(
            "analysis._llm_complete",
            new=mock.AsyncMock(return_value=__import__("json").dumps(payload)),
        ):
            result = asyncio.run(analysis.run_analysis("005930"))

        self.assertEqual(result["recommendation"], "HOLD")
        self.assertEqual(result["decision"], "보류")
        self.assertEqual(result["buy_score"], 8)


if __name__ == "__main__":
    unittest.main()
