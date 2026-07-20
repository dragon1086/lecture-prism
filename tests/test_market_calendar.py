import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from market_calendar import MarketGate


KST = ZoneInfo("Asia/Seoul")


class FakeCalendarClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def get_market_day(self, market_date):
        self.calls.append(market_date)
        if self.error is not None:
            raise self.error
        return self.result


class FakeCalendarCache:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.get_calls = []
        self.save_calls = []

    def get(self, *args, **kwargs):
        self.get_calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.value

    def save(self, *args, **kwargs):
        self.save_calls.append((args, kwargs))


def cached_day(checked_at, *, market_date="20260720", is_open=True):
    return {
        "market_date": market_date,
        "is_open": is_open,
        "checked_at": checked_at,
    }


class MarketGateTest(unittest.TestCase):
    def gate(self, client=None, cache=None):
        selected_cache = cache or FakeCalendarCache()
        return MarketGate(
            client or FakeCalendarClient(),
            cache_get=selected_cache.get,
            cache_save=selected_cache.save,
            mode="paper",
            cache_ttl=timedelta(hours=24),
        )

    def test_requires_timezone_aware_datetime(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.gate().check(datetime(2026, 7, 20, 10, 0))

    def test_utc_input_is_converted_to_kst(self):
        now = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
        cache = FakeCalendarCache(cached_day(now))

        status = self.gate(cache=cache).check(now)

        self.assertTrue(status.order_allowed)
        self.assertEqual(status.checked_at.tzinfo, KST)
        self.assertEqual(status.checked_at.hour, 9)
        self.assertEqual(status.market_date, "20260720")

    def test_weekend_blocks_without_cache_or_api(self):
        client = FakeCalendarClient(error=AssertionError("API must not run"))
        cache = FakeCalendarCache(error=AssertionError("cache must not run"))

        status = self.gate(client, cache).check(
            datetime(2026, 7, 18, 10, 0, tzinfo=KST)
        )

        self.assertFalse(status.order_allowed)
        self.assertFalse(status.is_business_day)
        self.assertEqual(status.reason, "weekend")
        self.assertEqual(client.calls, [])
        self.assertEqual(cache.get_calls, [])

    def test_outside_regular_session_blocks_without_cache_or_api(self):
        for now in (
            datetime(2026, 7, 20, 8, 59, 59, tzinfo=KST),
            datetime(2026, 7, 20, 15, 30, 0, tzinfo=KST),
        ):
            with self.subTest(now=now):
                client = FakeCalendarClient(error=AssertionError("API must not run"))
                cache = FakeCalendarCache(error=AssertionError("cache must not run"))

                status = self.gate(client, cache).check(now)

                self.assertFalse(status.order_allowed)
                self.assertFalse(status.in_session)
                self.assertEqual(status.reason, "outside_regular_session")
                self.assertEqual(client.calls, [])
                self.assertEqual(cache.get_calls, [])

    def test_session_boundaries_allow_with_fresh_open_cache(self):
        for now in (
            datetime(2026, 7, 20, 9, 0, 0, tzinfo=KST),
            datetime(2026, 7, 20, 15, 29, 59, tzinfo=KST),
        ):
            with self.subTest(now=now):
                cache = FakeCalendarCache(cached_day(now - timedelta(minutes=1)))
                client = FakeCalendarClient(error=AssertionError("fresh cache must win"))

                status = self.gate(client, cache).check(now)

                self.assertTrue(status.order_allowed)
                self.assertTrue(status.is_business_day)
                self.assertTrue(status.in_session)
                self.assertEqual(status.reason, "open")
                self.assertEqual(status.source, "cache")
                self.assertEqual(client.calls, [])

    def test_fresh_cached_holiday_blocks(self):
        now = datetime(2026, 7, 20, 10, 0, tzinfo=KST)
        cache = FakeCalendarCache(
            cached_day(now - timedelta(minutes=1), is_open=False)
        )
        client = FakeCalendarClient(error=AssertionError("fresh cache must win"))

        status = self.gate(client, cache).check(now)

        self.assertFalse(status.order_allowed)
        self.assertFalse(status.is_business_day)
        self.assertEqual(status.reason, "holiday")
        self.assertEqual(status.source, "cache")
        self.assertEqual(client.calls, [])

    def test_cache_miss_fetches_api_saves_and_allows(self):
        now = datetime(2026, 7, 20, 10, 0, tzinfo=KST)
        cache = FakeCalendarCache()
        client = FakeCalendarClient(
            {"market_date": "20260720", "is_open": True, "opnd_yn": "Y"}
        )

        status = self.gate(client, cache).check(now)

        self.assertTrue(status.order_allowed)
        self.assertEqual(status.source, "api")
        self.assertEqual(client.calls, ["20260720"])
        self.assertEqual(len(cache.save_calls), 1)

    def test_stale_cache_and_api_exception_fail_closed(self):
        now = datetime(2026, 7, 20, 10, 0, tzinfo=KST)
        cache = FakeCalendarCache(cached_day(now - timedelta(hours=25)))
        client = FakeCalendarClient(error=TimeoutError("calendar timeout"))

        status = self.gate(client, cache).check(now)

        self.assertFalse(status.order_allowed)
        self.assertIsNone(status.is_business_day)
        self.assertEqual(status.reason, "calendar_unavailable")
        self.assertEqual(client.calls, ["20260720"])
        self.assertEqual(cache.save_calls, [])

    def test_future_cache_is_ignored_and_valid_api_wins(self):
        now = datetime(2026, 7, 20, 10, 0, tzinfo=KST)
        cache = FakeCalendarCache(cached_day(now + timedelta(seconds=1)))
        client = FakeCalendarClient(
            {"market_date": "20260720", "is_open": True, "opnd_yn": "Y"}
        )

        status = self.gate(client, cache).check(now)

        self.assertTrue(status.order_allowed)
        self.assertEqual(status.source, "api")
        self.assertEqual(client.calls, ["20260720"])

    def test_cache_date_or_opnd_mismatch_is_never_trusted(self):
        now = datetime(2026, 7, 20, 10, 0, tzinfo=KST)
        bad_records = (
            cached_day(now, market_date="20260721"),
            {
                "market_date": "20260720",
                "is_open": True,
                "opnd_yn": "N",
                "checked_at": now,
            },
        )
        for record in bad_records:
            with self.subTest(record=record):
                cache = FakeCalendarCache(record)
                client = FakeCalendarClient(
                    {
                        "market_date": "20260720",
                        "is_open": False,
                        "opnd_yn": "N",
                    }
                )

                status = self.gate(client, cache).check(now)

                self.assertFalse(status.order_allowed)
                self.assertEqual(status.source, "api")

    def test_corrupt_cache_and_malformed_api_fail_closed(self):
        now = datetime(2026, 7, 20, 10, 0, tzinfo=KST)
        cache = FakeCalendarCache({"market_date": "20260720", "is_open": "yes"})
        client = FakeCalendarClient({"market_date": "20260720", "is_open": "yes"})

        status = self.gate(client, cache).check(now)

        self.assertFalse(status.order_allowed)
        self.assertEqual(status.reason, "calendar_unavailable")
        self.assertEqual(cache.save_calls, [])

    def test_api_date_mismatch_fails_closed(self):
        now = datetime(2026, 7, 20, 10, 0, tzinfo=KST)
        cache = FakeCalendarCache()
        client = FakeCalendarClient(
            {"market_date": "20260721", "is_open": True, "opnd_yn": "Y"}
        )

        status = self.gate(client, cache).check(now)

        self.assertFalse(status.order_allowed)
        self.assertEqual(status.reason, "calendar_unavailable")
        self.assertEqual(cache.save_calls, [])

    def test_cache_exception_can_recover_from_valid_api(self):
        now = datetime(2026, 7, 20, 10, 0, tzinfo=KST)
        cache = FakeCalendarCache(error=OSError("cache unavailable"))
        client = FakeCalendarClient(
            {"market_date": "20260720", "is_open": True, "opnd_yn": "Y"}
        )

        status = self.gate(client, cache).check(now)

        self.assertTrue(status.order_allowed)
        self.assertEqual(status.source, "api")


if __name__ == "__main__":
    unittest.main()
