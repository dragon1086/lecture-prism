import os
import unittest

import research_tools


_ENV_KEYS = {
    "PERPLEXITY_API_KEY",
    "PERPLEXITY_MODEL",
    "FIRECRAWL_API_KEY",
}


class ResearchToolsTest(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        self._saved_post = research_tools._post_json

    def tearDown(self):
        research_tools._post_json = self._saved_post
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_perplexity_query_uses_sonar_endpoint_and_returns_citations(self):
        os.environ["PERPLEXITY_API_KEY"] = "pplx-test"
        calls = []

        def fake_post(url, payload, headers, timeout):
            calls.append((url, payload, headers, timeout))
            return {
                "choices": [{"message": {"content": "반도체 수요 회복"}}],
                "citations": ["https://example.com/news"],
            }

        research_tools._post_json = fake_post

        result = research_tools.perplexity_query("삼성전자 최근 호재")

        self.assertEqual(result["content"], "반도체 수요 회복")
        self.assertEqual(result["citations"], ["https://example.com/news"])
        self.assertEqual(calls[0][0], "https://api.perplexity.ai/v1/sonar")
        self.assertEqual(calls[0][1]["model"], "sonar-pro")
        self.assertEqual(calls[0][2]["Authorization"], "Bearer pplx-test")

    def test_firecrawl_scrape_uses_v2_scrape_endpoint(self):
        os.environ["FIRECRAWL_API_KEY"] = "fc-test"
        calls = []

        def fake_post(url, payload, headers, timeout):
            calls.append((url, payload, headers, timeout))
            return {"success": True, "data": {"markdown": "뉴스 본문"}}

        research_tools._post_json = fake_post

        result = research_tools.firecrawl_scrape("https://finance.naver.com/item/news.naver?code=005930")

        self.assertEqual(result, "뉴스 본문")
        self.assertEqual(calls[0][0], "https://api.firecrawl.dev/v2/scrape")
        self.assertEqual(calls[0][1]["formats"], ["markdown"])
        self.assertEqual(calls[0][2]["Authorization"], "Bearer fc-test")

    def test_build_research_context_degrades_to_empty_without_keys(self):
        result = research_tools.build_research_context("005930", "삼성전자", "반도체")

        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
