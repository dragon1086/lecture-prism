import os
import unittest

import data_source


_ENV_KEYS = {
    "LECTURE_PROFILE",
    "LECTURE_DATA_MODE",
    "LECTURE_RESEARCH_TOOLS",
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


if __name__ == "__main__":
    unittest.main()
