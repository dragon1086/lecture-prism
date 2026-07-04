import os
import sys
import types
import unittest

import data_source


_ENV_KEYS = {
    "LECTURE_PROFILE",
    "LECTURE_DATA_MODE",
    "LECTURE_RESEARCH_TOOLS",
    "KRX_ID",
    "KRX_PW",
}


class DataSourceModeTest(unittest.TestCase):
    def setUp(self):
        self._saved_env = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        self._saved_fetch_real = data_source._fetch_real
        self._saved_server = sys.modules.get("kospi_kosdaq_stock_server")

    def tearDown(self):
        data_source._fetch_real = self._saved_fetch_real
        if self._saved_server is None:
            sys.modules.pop("kospi_kosdaq_stock_server", None)
        else:
            sys.modules["kospi_kosdaq_stock_server"] = self._saved_server
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

    def test_kospi_kosdaq_mode_uses_optional_server_when_available(self):
        os.environ["LECTURE_DATA_MODE"] = "kospi_kosdaq"
        server = types.SimpleNamespace()
        server.get_stock_ohlcv = lambda start, end, ticker: {
            "20260701": {"Close": 70000, "Volume": 1000},
            "20260702": {"Close": 71000, "Volume": 2000},
            "20260703": {"Close": 72000, "Volume": 5000},
        }
        server.get_stock_trading_volume = lambda start, end, ticker: {
            "20260703": {"foreign": 1200, "institution": 800, "individual": -2000}
        }
        sys.modules["kospi_kosdaq_stock_server"] = server

        result = data_source.fetch_stock_data("005930")

        self.assertEqual(result["source"], "kospi_kosdaq")
        self.assertEqual(result["current_price"], 72000)
        self.assertEqual(result["supply"]["investor_flow_available"], True)
        self.assertIn("foreign", result["supply"]["latest_investor_flow"])


if __name__ == "__main__":
    unittest.main()
