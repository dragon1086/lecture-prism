import json
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
                return_value={
                    "source": "fixture",
                    "KOSPI": {"last": 2835.4, "ret_20d": 2.4},
                    "KOSDAQ": {"last": 764.8, "ret_20d": -1.1},
                },
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


if __name__ == "__main__":
    unittest.main()
