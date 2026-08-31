import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "lecture" / "fixtures" / "dart-samsung-company-rss.xml"


class DartRssQualityGateTests(unittest.TestCase):
    def _module(self):
        self.assertTrue((ROOT / "dart_rss.py").is_file())
        import dart_rss

        return dart_rss

    def test_fixture_parses_three_bounded_disclosure_records(self):
        dart_rss = self._module()

        records = dart_rss.parse_company_rss(FIXTURE.read_bytes())

        self.assertEqual(3, len(records))
        self.assertEqual(
            {"title", "link", "pubDate"},
            set(records[0]),
        )
        self.assertRegex(records[0]["link"], r"rcpNo=\d{14}$")

    def test_personal_holding_feed_is_excluded_without_inventing_a_claim(self):
        dart_rss = self._module()
        records = dart_rss.parse_company_rss(FIXTURE.read_bytes())

        result = dart_rss.review_disclosures(
            records,
            target_company="삼성전자",
            as_of=datetime(2026, 8, 28, tzinfo=timezone.utc),
        )

        self.assertEqual(0, result["counts"]["include"])
        self.assertEqual(3, result["counts"]["exclude"])
        self.assertEqual(0, result["counts"]["needs_review"])
        self.assertEqual([], result["llm_input"])
        self.assertTrue(
            all(item["reason"] == "임원 개인 사건" for item in result["items"])
        )

    def test_relevant_title_waits_for_original_confirmation(self):
        dart_rss = self._module()
        records = [
            {
                "title": "(유가)삼성전자 - 분기보고서 (2026.03)",
                "link": "https://dart.fss.or.kr/api/link.jsp?rcpNo=20260515007870",
                "pubDate": "Fri, 15 May 2026 06:00:00 GMT",
            }
        ]

        result = dart_rss.review_disclosures(
            records,
            target_company="삼성전자",
            as_of=datetime(2026, 5, 16, tzinfo=timezone.utc),
        )

        self.assertEqual(1, result["counts"]["needs_review"])
        self.assertEqual([], result["llm_input"])
        self.assertEqual("원문 확인 필요", result["items"][0]["reason"])

    def test_failed_live_request_uses_fixture_once_without_retry(self):
        dart_rss = self._module()
        calls = []

        def failing_opener(request, timeout):
            calls.append((request.full_url, timeout))
            raise URLError("dns blocked")

        loaded = dart_rss.load_company_rss(
            "https://dart.fss.or.kr/api/companyRSS.xml?crpCd=00126380",
            FIXTURE,
            opener=failing_opener,
        )

        self.assertEqual(1, len(calls))
        self.assertEqual("fixture", loaded["source"])
        self.assertIn("dns blocked", loaded["error"])
        self.assertEqual(3, len(loaded["records"]))


if __name__ == "__main__":
    unittest.main()
