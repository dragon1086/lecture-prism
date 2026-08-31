from __future__ import annotations

from datetime import date
import unittest
from unittest import mock


class FakeReadOnlyClient:
    def __init__(self, prices, flows, *, failure=None, failures=None):
        self.prices = prices
        self.flows = flows
        self.failure = failure
        self.failures = list(failures or [])
        self.calls = []
        self.order_calls = []

    def get_daily_prices(self, ticker, start_date, end_date):
        self.calls.append(("daily_prices", ticker, start_date, end_date))
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        if self.failure:
            raise self.failure
        return self.prices

    def get_investor_flow(self, ticker, as_of_date):
        self.calls.append(("investor_flow", ticker, as_of_date))
        return self.flows

    def place_cash_order(self, *args, **kwargs):
        self.order_calls.append(("order", args, kwargs))

    def cancel_order(self, *args, **kwargs):
        self.order_calls.append(("cancel", args, kwargs))

    def get_balance(self, *args, **kwargs):
        self.order_calls.append(("balance", args, kwargs))


class KISMarketDataSnapshotTest(unittest.TestCase):
    def test_snapshot_joins_latest_common_business_date_without_mutations(self):
        from kis_market_data import fetch_kis_snapshot

        client = FakeReadOnlyClient(
            prices=[
                {"stck_bsop_date": "20260808", "stck_clpr": "71500"},
                {"stck_bsop_date": "20260807", "stck_clpr": "70800"},
            ],
            flows=[
                {
                    "as_of": "2026-08-07",
                    "institution_net_buy": 1200,
                    "foreign_net_buy": -500,
                    "individual_net_buy": -700,
                    "source": "kis.investor-trade-by-stock-daily",
                },
                {
                    "as_of": "2026-08-08",
                    "institution_net_buy": 1500,
                    "foreign_net_buy": 3500,
                    "individual_net_buy": -5000,
                    "source": "kis.investor-trade-by-stock-daily",
                },
            ],
        )

        snapshot = fetch_kis_snapshot(
            "005930", "paper", client=client, today=date(2026, 8, 11)
        )

        self.assertEqual(snapshot, {
            "environment": "paper",
            "source": "KIS Open API",
            "ticker": "005930",
            "as_of": "2026-08-08",
            "price": 71500,
            "institution_net_buy": 1500,
            "foreign_net_buy": 3500,
            "individual_net_buy": -5000,
            "order_calls": 0,
        })
        self.assertEqual(client.calls, [
            ("daily_prices", "005930", "20260728", "20260811"),
            ("investor_flow", "005930", "20260811"),
        ])
        self.assertEqual(client.order_calls, [])

    def test_snapshot_does_not_mix_price_and_flow_dates(self):
        from kis_market_data import KISMarketDataError, fetch_kis_snapshot

        client = FakeReadOnlyClient(
            prices=[{"stck_bsop_date": "20260808", "stck_clpr": "71500"}],
            flows=[{
                "as_of": "2026-08-07",
                "institution_net_buy": 1,
                "foreign_net_buy": 1,
                "individual_net_buy": -2,
                "source": "kis.investor-trade-by-stock-daily",
            }],
        )

        with self.assertRaisesRegex(KISMarketDataError, "common business date"):
            fetch_kis_snapshot(
                "005930", "real", client=client, today=date(2026, 8, 11)
            )

        self.assertEqual(client.order_calls, [])

    def test_snapshot_retries_transient_read_only_failure_on_same_client(self):
        from brokers.kis_client import KISRequestError
        from kis_market_data import fetch_kis_snapshot

        client = FakeReadOnlyClient(
            prices=[{"stck_bsop_date": "20260808", "stck_clpr": "71500"}],
            flows=[{
                "as_of": "2026-08-08",
                "institution_net_buy": 1500,
                "foreign_net_buy": 3500,
                "individual_net_buy": -5000,
            }],
            failures=[KISRequestError("temporary network failure", retryable=True)],
        )

        with mock.patch("kis_market_data.time.sleep") as sleep:
            snapshot = fetch_kis_snapshot(
                "005930", "paper", client=client, today=date(2026, 8, 11),
                max_attempts=2,
            )

        self.assertEqual(snapshot["as_of"], "2026-08-08")
        self.assertEqual(
            [call[0] for call in client.calls],
            ["daily_prices", "daily_prices", "investor_flow"],
        )
        sleep.assert_called_once_with(1.0)
        self.assertEqual(client.order_calls, [])

    def test_snapshot_does_not_retry_non_retryable_kis_failure(self):
        from brokers.kis_client import KISRequestError
        from kis_market_data import KISMarketDataError, fetch_kis_snapshot

        client = FakeReadOnlyClient(
            prices=[],
            flows=[],
            failure=KISRequestError("forbidden", retryable=False, status=403),
        )

        with mock.patch("kis_market_data.time.sleep") as sleep:
            with self.assertRaisesRegex(KISMarketDataError, "HTTP 403"):
                fetch_kis_snapshot(
                    "005930", "paper", client=client, today=date(2026, 8, 11),
                    max_attempts=3,
                )

        self.assertEqual(len(client.calls), 1)
        sleep.assert_not_called()
        self.assertEqual(client.order_calls, [])

    def test_snapshot_failure_does_not_echo_provider_secret(self):
        from kis_market_data import KISMarketDataError, fetch_kis_snapshot

        client = FakeReadOnlyClient(
            prices=[],
            flows=[],
            failure=RuntimeError("provider echoed app-secret access-token account-no"),
        )

        with self.assertRaises(KISMarketDataError) as raised:
            fetch_kis_snapshot(
                "005930", "paper", client=client, today=date(2026, 8, 11)
            )

        rendered = str(raised.exception)
        self.assertNotIn("app-secret", rendered)
        self.assertNotIn("access-token", rendered)
        self.assertNotIn("account-no", rendered)
        self.assertEqual(client.order_calls, [])

    def test_formatted_snapshot_shows_date_values_and_zero_mutations(self):
        from kis_market_data import format_snapshot

        rendered = format_snapshot({
            "environment": "real",
            "source": "KIS Open API",
            "ticker": "005930",
            "as_of": "2026-08-08",
            "price": 71500,
            "institution_net_buy": 1500,
            "foreign_net_buy": 3500,
            "individual_net_buy": -5000,
            "order_calls": 0,
        })

        for phrase in (
            "real",
            "KIS Open API",
            "005930",
            "2026-08-08",
            "71,500원",
            "기관 순매수 1,500주",
            "외국인 순매수 3,500주",
            "개인 순매수 -5,000주",
            "주문·취소·계좌 호출 0건",
        ):
            self.assertIn(phrase, rendered)


if __name__ == "__main__":
    unittest.main()
