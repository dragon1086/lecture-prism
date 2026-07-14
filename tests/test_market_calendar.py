import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import db
from market_calendar import KST, MarketGate


class _FakeKISClient:
    def __init__(self, result=None, error=None):
        self.result = result or {"opnd_yn": "Y"}
        self.error = error
        self.calls = []

    def get_market_day(self, business_date):
        self.calls.append(business_date)
        if self.error is not None:
            raise self.error
        return dict(self.result)


class MarketCalendarTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._temp_dir.name) / "prism.db"

    def tearDown(self):
        db.DB_PATH = self._original_db_path
        self._temp_dir.cleanup()

    def test_weekend_blocks_order_but_not_analysis(self):
        client = _FakeKISClient()
        gate = MarketGate(client, clock=lambda: None)

        status = gate.check(datetime(2026, 7, 18, 10, tzinfo=KST))

        self.assertFalse(status.order_allowed)
        self.assertTrue(status.analysis_allowed)
        self.assertEqual("market_closed", status.reason)
        self.assertEqual([], client.calls)

    def test_open_day_inside_kst_window_allows_order_and_uses_same_day_cache(self):
        client = _FakeKISClient({"opnd_yn": "Y"})
        now = datetime(2026, 7, 15, 10, tzinfo=KST)
        gate = MarketGate(client, clock=lambda: now)

        first = gate.check()
        second = gate.check(now)

        self.assertTrue(first.order_allowed)
        self.assertEqual("market_open", first.reason)
        self.assertTrue(second.order_allowed)
        self.assertEqual(["2026-07-15"], client.calls)
        cached = db.get_market_day("kis", "KRX", "2026-07-15")
        self.assertTrue(cached["is_open"])
        self.assertEqual("kis_api", cached["source"])

    def test_cached_closed_day_blocks_without_calling_api(self):
        db.save_market_day(
            {
                "broker": "kis",
                "market": "KRX",
                "business_date": "2026-07-15",
                "is_open": False,
                "source": "kis_api",
            }
        )
        client = _FakeKISClient(error=AssertionError("API must not be called"))
        gate = MarketGate(client)

        status = gate.check(datetime(2026, 7, 15, 10, tzinfo=KST))

        self.assertFalse(status.order_allowed)
        self.assertTrue(status.analysis_allowed)
        self.assertEqual("market_closed", status.reason)
        self.assertEqual("cache", status.source)
        self.assertEqual([], client.calls)

    def test_api_and_cache_uncertainty_blocks_order_not_analysis(self):
        client = _FakeKISClient(error=RuntimeError("holiday API unavailable"))
        gate = MarketGate(client)

        status = gate.check(datetime(2026, 7, 15, 10, tzinfo=KST))

        self.assertFalse(status.order_allowed)
        self.assertTrue(status.analysis_allowed)
        self.assertIsNone(status.is_open)
        self.assertEqual("market_status_unknown", status.reason)

    def test_kst_window_is_applied_after_open_day_check(self):
        db.save_market_day(
            {
                "broker": "kis",
                "market": "KRX",
                "business_date": "2026-07-15",
                "is_open": True,
                "source": "kis_api",
            }
        )
        client = _FakeKISClient(error=AssertionError("cache should be used"))
        gate = MarketGate(client)

        before_open = gate.check(datetime(2026, 7, 15, 8, 59, tzinfo=KST))
        after_close = gate.check(datetime(2026, 7, 15, 6, 30, tzinfo=timezone.utc))

        self.assertEqual("outside_order_window", before_open.reason)
        self.assertFalse(before_open.order_allowed)
        self.assertEqual("outside_order_window", after_close.reason)
        self.assertFalse(after_close.order_allowed)
        self.assertEqual([], client.calls)

    def test_kis_opnd_yn_n_is_cached_as_closed(self):
        client = _FakeKISClient({"opnd_yn": "N"})
        gate = MarketGate(client)

        status = gate.check(datetime(2026, 7, 15, 10, tzinfo=KST))

        self.assertFalse(status.order_allowed)
        self.assertEqual("market_closed", status.reason)
        self.assertFalse(
            db.get_market_day("kis", "KRX", "2026-07-15")["is_open"]
        )


if __name__ == "__main__":
    unittest.main()
