import unittest
from unittest.mock import patch

import analysis
import data_source


class _Series:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return list(self._values)


class _IndexValue:
    def __init__(self, value):
        self._value = value

    def date(self):
        return self

    def isoformat(self):
        return self._value


class _History:
    empty = False

    def __init__(self, last_date):
        self.index = [_IndexValue("2026-07-09"), _IndexValue(last_date)]
        self._columns = {
            "Close": _Series([100.0, 110.0]),
            "Volume": _Series([1000.0, 1500.0]),
        }

    def dropna(self, subset=None):
        return self

    def __len__(self):
        return 2

    def __getitem__(self, key):
        return self._columns[key]


class _Ticker:
    fast_info = {"exchange": "KSC", "lastPrice": 110.0}
    info = {}
    news = []

    def history(self, period):
        return _History("2026-07-10")


class _YFinance:
    @staticmethod
    def Ticker(symbol):
        return _Ticker()


class MarketDataAsOfTests(unittest.IsolatedAsyncioTestCase):
    def test_yfinance_result_uses_latest_history_date_not_wall_clock(self):
        result = data_source._fetch_symbol(_YFinance(), "005930", "005930.KS")

        self.assertEqual("yfinance", result["data_source"])
        self.assertEqual("2026-07-10", result["data_as_of"])

    def test_mock_result_is_honest_about_missing_market_date(self):
        result = data_source._fetch_mock("005930")

        self.assertEqual("mock", result["data_source"])
        self.assertIsNone(result["data_as_of"])

    async def test_analysis_preserves_data_provenance(self):
        stock = data_source._fetch_symbol(_YFinance(), "005930", "005930.KS")

        with patch("analysis.data_source.fetch_stock_data", return_value=stock), patch(
            "analysis.data_source.fetch_market_index", return_value=None
        ):
            result = await analysis.run_analysis("005930")

        self.assertEqual("yfinance", result["data_source"])
        self.assertEqual("2026-07-10", result["data_as_of"])


if __name__ == "__main__":
    unittest.main()
