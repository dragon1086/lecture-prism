import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard


class DashboardSeedRegressionTest(unittest.TestCase):
    def test_fresh_dashboard_database_seeds_trade_analysis_and_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "prism.db"
            with patch.object(dashboard, "DB_PATH", db_path), patch.object(
                dashboard.data_source,
                "fetch_market_index",
                side_effect=AssertionError("dashboard seed must not fetch market index"),
            ):
                dashboard._init_db()
                data = dashboard.get_data()

        self.assertTrue(data["trades"])
        self.assertTrue(data["analyses"])
        self.assertTrue(data["lessons"])

        sections = json.loads(data["analyses"][0]["sections"])
        self.assertEqual(
            {
                "technical_summary",
                "supply_summary",
                "financial_summary",
                "industry_summary",
                "news_summary",
                "market_condition",
            },
            set(sections),
        )

    def test_fresh_dashboard_seed_never_calls_optional_research(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "LECTURE_PROFILE": "research",
                "LECTURE_REPORT_MODE": "research",
                "LECTURE_RESEARCH_TOOLS": "perplexity",
                "PERPLEXITY_API_KEY": "pplx-test-fixture-only",
            },
            clear=False,
        ), patch.object(
            dashboard.data_source,
            "fetch_market_index",
            side_effect=AssertionError("dashboard seed must not fetch market index"),
        ), patch("research_tools.build_research_context", return_value="") as build_context, patch(
            "research_tools.build_research_sections", return_value={}, create=True
        ) as build_sections, patch.object(
            dashboard, "DB_PATH", Path(tmp) / "prism.db"
        ):
            dashboard._init_db()

        build_context.assert_not_called()
        build_sections.assert_not_called()


if __name__ == "__main__":
    unittest.main()
