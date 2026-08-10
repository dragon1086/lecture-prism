import os
import unittest
from unittest import mock

import data_source


_ENV_KEYS = {
    "LECTURE_PROFILE",
    "LECTURE_DATA_MODE",
    "LECTURE_RESEARCH_TOOLS",
    "LECTURE_SUPPLY_SOURCE",
}


class DataSourceModeTest(unittest.TestCase):
    def setUp(self):
        self._saved_env = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        self._saved_fetch_real = data_source._fetch_real

    def tearDown(self):
        data_source._fetch_real = self._saved_fetch_real
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_mock_mode_never_calls_yfinance_fetcher(self):
        os.environ["LECTURE_DATA_MODE"] = "mock"

        def fail_if_called(ticker):
            raise AssertionError(f"real fetch should not run for {ticker}")

        data_source._fetch_real = fail_if_called

        result = data_source.fetch_stock_data("005930")

        self.assertEqual(result["source"], "mock")
        self.assertEqual(result["ticker"], "005930")
        self.assertEqual(result["name"], "삼성전자")

    def test_yfinance_mode_falls_back_to_mock_when_real_fetch_fails(self):
        os.environ["LECTURE_DATA_MODE"] = "yfinance"

        data_source._fetch_real = lambda ticker: None

        result = data_source.fetch_stock_data("005930")

        self.assertEqual(result["source"], "mock")
        self.assertEqual(result["name"], "삼성전자")

    def test_kis_enrichment_replaces_only_yfinance_supply(self):
        os.environ["LECTURE_DATA_MODE"] = "yfinance"
        os.environ["LECTURE_SUPPLY_SOURCE"] = "kis"
        base = data_source._fetch_mock("005930")
        base["source"] = "yfinance"
        base["evidence_kind"] = "market_data"
        original_price = base["current_price"]
        original_finance = dict(base["finance"])
        data_source._fetch_real = lambda ticker: base
        snapshot = {
            "environment": "real",
            "source": "KIS Open API",
            "ticker": "005930",
            "as_of": "2026-08-08",
            "price": 71500,
            "institution_net_buy": 1500,
            "foreign_net_buy": 3500,
            "individual_net_buy": -5000,
            "order_calls": 0,
        }

        with mock.patch("data_source._fetch_kis_snapshot", return_value=snapshot):
            result = data_source.fetch_stock_data("005930")

        self.assertEqual(result["source"], "yfinance")
        self.assertEqual(result["current_price"], original_price)
        self.assertEqual(result["finance"], original_finance)
        self.assertEqual(result["supply"], {
            "source": "kis",
            "environment": "real",
            "as_of": "2026-08-08",
            "institution_net_buy": 1500,
            "foreign_net_buy": 3500,
            "individual_net_buy": -5000,
        })

    def test_kis_enrichment_failure_keeps_the_existing_proxy(self):
        os.environ["LECTURE_DATA_MODE"] = "yfinance"
        os.environ["LECTURE_SUPPLY_SOURCE"] = "kis"
        base = data_source._fetch_mock("005930")
        base["source"] = "yfinance"
        base["evidence_kind"] = "market_data"
        original_supply = dict(base["supply"])
        data_source._fetch_real = lambda ticker: base

        with mock.patch(
            "data_source._fetch_kis_snapshot", side_effect=RuntimeError("unavailable")
        ):
            result = data_source.fetch_stock_data("005930")

        self.assertEqual(result["supply"], original_supply)

    def test_mock_mode_never_calls_kis_enrichment(self):
        os.environ["LECTURE_DATA_MODE"] = "mock"
        os.environ["LECTURE_SUPPLY_SOURCE"] = "kis"

        with mock.patch("data_source._fetch_kis_snapshot") as fetch_kis:
            result = data_source.fetch_stock_data("005930")

        self.assertEqual(result["source"], "mock")
        fetch_kis.assert_not_called()


if __name__ == "__main__":
    unittest.main()
