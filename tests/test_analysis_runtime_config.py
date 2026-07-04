import asyncio
import os
import unittest

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

    def test_analysis_result_records_runtime_modes(self):
        os.environ["LECTURE_PROFILE"] = "mock"

        result = asyncio.run(analysis.run_analysis("005930"))

        self.assertEqual(result["runtime_profile"], "mock")
        self.assertEqual(result["data_mode"], "mock")
        self.assertEqual(result["report_mode"], "lite")
        self.assertEqual(result["research_tools"], [])
        self.assertIn("runtime_summary", result)

    def test_research_profile_adds_optional_research_context_to_news(self):
        os.environ["LECTURE_PROFILE"] = "research"
        os.environ["LECTURE_LLM_MODE"] = "mock"
        os.environ["PERPLEXITY_API_KEY"] = "pplx-test"

        research_tools.build_research_context = (
            lambda ticker, company_name, sector="": "실시간 리서치: HBM 수요와 환율 리스크"
        )

        result = asyncio.run(analysis.run_analysis("005930"))

        self.assertIn("실시간 리서치", result["news_summary"])


if __name__ == "__main__":
    unittest.main()
