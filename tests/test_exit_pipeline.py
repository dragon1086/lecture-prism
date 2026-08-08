import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from brokers.base import BrokerQuote
import db
import trading


def _buy_analysis(ticker: str, price: int) -> dict:
    return {
        "ticker": ticker,
        "company_name": ticker,
        "recommendation": "BUY",
        "decision": "진입",
        "buy_score": 8,
        "current_price": price,
        "target_price": int(price * 1.15),
        "stop_loss": int(price * 0.93),
        "risk_reward_ratio": 2.1,
        "rationale": "거래량을 동반한 추세 돌파",
        "risk": "시장 급락 시 동반 조정",
    }


class ExitPortfolioTest(unittest.TestCase):
    def test_open_holdings_uses_latest_buy_or_sell_per_ticker(self):
        self.assertTrue(
            hasattr(db, "get_open_holdings"),
            "청산 파이프라인이 읽을 db.get_open_holdings()가 필요합니다.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prism.db"
            with mock.patch.object(db, "DB_PATH", path):
                db.save_trade(
                    {
                        "ticker": "005930",
                        "action": "BUY",
                        "price": 70_000,
                        "quantity": 2,
                    }
                )
                db.save_trade(
                    {
                        "ticker": "005930",
                        "action": "SELL",
                        "price": 65_000,
                        "quantity": 2,
                    }
                )
                db.save_trade(
                    {
                        "ticker": "000660",
                        "action": "BUY",
                        "price": 180_000,
                        "quantity": 1,
                    }
                )

                self.assertEqual(
                    db.get_open_holdings(),
                    [
                        {
                            "ticker": "000660",
                            "entry_price": 180_000,
                            "quantity": 1,
                            "high_since_entry": 180_000,
                        }
                    ],
                )

    def test_high_since_entry_is_persisted_and_never_moves_lower(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prism.db"
            with mock.patch.object(db, "DB_PATH", path):
                db.save_trade(
                    {
                        "ticker": "005930",
                        "action": "BUY",
                        "price": 70_000,
                        "quantity": 2,
                    }
                )

                db.update_holding_high("005930", 78_000)
                db.update_holding_high("005930", 74_000)

                self.assertEqual(
                    db.get_open_holdings()[0]["high_since_entry"],
                    78_000,
                )


class ExitTradingCycleTest(unittest.TestCase):
    def test_simulation_exit_price_lookup_preserves_data_source_fallback(self):
        holdings = [{"ticker": "005930", "entry_price": 80_000, "quantity": 2}]

        with mock.patch(
            "data_source.fetch_stock_data",
            return_value={"current_price": 72_000},
        ) as fetch:
            prices = asyncio.run(
                trading._load_holding_prices(holdings, dry_run=True)
            )

        self.assertEqual(prices, {"005930": 72_000})
        fetch.assert_called_once_with("005930")

    def test_broker_mode_exit_uses_fresh_broker_quote_and_not_data_source(self):
        observed = datetime.now(timezone.utc)
        holdings = [
            {
                "ticker": "005930",
                "entry_price": 80_000,
                "quantity": 2,
                "high_since_entry": 82_000,
            }
        ]

        class Adapter:
            async def get_quote(self, ticker):
                return BrokerQuote(
                    ticker=ticker,
                    price=72_000,
                    currency="KRW",
                    market="KRX",
                    observed_at=observed,
                    source="fixture",
                )

        with mock.patch(
            "trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
        ), mock.patch(
            "trading._get_current_portfolio",
            new=mock.AsyncMock(
                return_value={"cash": 10_000_000, "slots_used": 1, "holdings": holdings}
            ),
        ), mock.patch(
            "brokers.factory.get_broker_adapter",
            return_value=Adapter(),
        ), mock.patch(
            "data_source.fetch_stock_data",
            side_effect=AssertionError("paper/live exits must not use data_source"),
        ):
            results = asyncio.run(trading.run_trading([], dry_run=False))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["action"], "SELL")
        self.assertEqual(results[0]["price"], 72_000)
        self.assertEqual(results[0]["mode"], "live_blocked")

    def test_paper_profile_exit_price_lookup_defaults_to_broker_quote(self):
        observed = datetime.now(timezone.utc)
        holdings = [{"ticker": "005930", "entry_price": 80_000, "quantity": 2}]

        class Adapter:
            async def get_quote(self, ticker):
                return BrokerQuote(
                    ticker=ticker,
                    price=72_000,
                    currency="KRW",
                    market="KRX",
                    observed_at=observed,
                    source="fixture",
                )

        with mock.patch.dict("os.environ", {"LECTURE_PROFILE": "paper"}), mock.patch(
            "brokers.factory.get_broker_adapter",
            return_value=Adapter(),
        ), mock.patch(
            "data_source.fetch_stock_data",
            side_effect=AssertionError("paper profile exits must not use data_source"),
        ):
            prices = asyncio.run(trading._load_holding_prices(holdings))

        self.assertEqual(prices, {"005930": 72_000})

    def test_broker_mode_exit_blocks_invalid_quote_without_order_post(self):
        observed = datetime(2026, 7, 20, 1, 5, tzinfo=timezone.utc)
        holdings = [{"ticker": "005930", "entry_price": 80_000, "quantity": 2}]

        class Adapter:
            place_order = mock.AsyncMock(
                side_effect=AssertionError("invalid quote must not submit order")
            )

            async def get_quote(self, ticker):
                return BrokerQuote(
                    ticker=ticker,
                    price=-1,
                    currency="KRW",
                    market="KRX",
                    observed_at=observed,
                    source="fixture",
                )

        adapter = Adapter()
        with mock.patch(
            "trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
        ), mock.patch(
            "brokers.factory.get_broker_adapter",
            return_value=adapter,
        ), mock.patch(
            "data_source.fetch_stock_data",
            side_effect=AssertionError("paper/live exits must not use data_source"),
        ):
            results = asyncio.run(trading.run_trading([], dry_run=False))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "blocked")
        self.assertEqual(results[0]["mode"], "broker_quote_invalid")
        self.assertIn("005930", results[0]["message"])
        adapter.place_order.assert_not_awaited()

    def test_broker_mode_exit_blocks_missing_quote_capability(self):
        holdings = [{"ticker": "005930", "entry_price": 80_000, "quantity": 2}]

        with mock.patch(
            "trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
        ), mock.patch(
            "brokers.factory.get_broker_adapter",
            return_value=object(),
        ), mock.patch(
            "data_source.fetch_stock_data",
            side_effect=AssertionError("paper/live exits must not use data_source"),
        ):
            results = asyncio.run(trading.run_trading([], dry_run=False))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "blocked")
        self.assertEqual(results[0]["mode"], "broker_quote_unavailable")

    def test_broker_mode_exit_blocks_stale_quote(self):
        observed = datetime(2026, 7, 20, 1, 5, tzinfo=timezone.utc)
        holdings = [{"ticker": "005930", "entry_price": 80_000, "quantity": 2}]

        class Adapter:
            async def get_quote(self, ticker):
                return BrokerQuote(
                    ticker=ticker,
                    price=72_000,
                    currency="KRW",
                    market="KRX",
                    observed_at=observed - timedelta(minutes=10),
                    source="fixture",
                )

        with mock.patch(
            "trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
        ), mock.patch(
            "brokers.factory.get_broker_adapter",
            return_value=Adapter(),
        ):
            results = asyncio.run(trading.run_trading([], dry_run=False))

        self.assertEqual(results[0]["status"], "blocked")
        self.assertEqual(results[0]["mode"], "broker_quote_invalid")

    def test_current_portfolio_counts_actual_open_holdings(self):
        holdings = [
            {"ticker": "005930", "entry_price": 70_000, "quantity": 2},
            {"ticker": "000660", "entry_price": 180_000, "quantity": 1},
        ]

        with mock.patch(
            "trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
        ):
            portfolio = asyncio.run(trading._get_current_portfolio())

        self.assertEqual(portfolio["slots_used"], 2)
        self.assertEqual(portfolio["holdings"], holdings)

    def test_run_trading_injects_relevant_memory_into_entry_record(self):
        with mock.patch(
            "trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=[]),
        ), mock.patch(
            "trading._load_holding_prices",
            new=mock.AsyncMock(return_value={}),
        ), mock.patch(
            "trading._persist_holding_highs",
            new=mock.AsyncMock(),
        ), mock.patch(
            "trading._get_current_portfolio",
            new=mock.AsyncMock(
                return_value={"cash": 10_000_000, "slots_used": 0, "holdings": []}
            ),
        ), mock.patch(
            "memory.get_relevant_memories",
            return_value=["같은 종목 최근 손절 뒤에는 재진입 조건을 다시 확인한다."],
        ):
            results = asyncio.run(
                trading.run_trading([_buy_analysis("005930", 70_000)], dry_run=True)
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["memory_lessons"]), 1)

    def test_exit_runs_before_entry_and_same_cycle_reentry_is_blocked(self):
        holdings = [{"ticker": "005930", "entry_price": 80_000, "quantity": 2}]
        analyses = [
            _buy_analysis("005930", 70_000),
            _buy_analysis("000660", 180_000),
        ]
        entry_portfolio = {"cash": 10_000_000, "slots_used": 3, "holdings": []}

        with mock.patch(
            "trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
            create=True,
        ), mock.patch(
            "trading._load_holding_prices",
            new=mock.AsyncMock(return_value={"005930": 70_000}),
            create=True,
        ), mock.patch(
            "trading._persist_holding_highs",
            new=mock.AsyncMock(),
            create=True,
        ), mock.patch(
            "trading._get_current_portfolio",
            new=mock.AsyncMock(return_value=entry_portfolio),
        ):
            results = asyncio.run(trading.run_trading(analyses, dry_run=True))

        self.assertEqual([row["action"] for row in results], ["SELL", "BUY"])
        self.assertEqual([row["ticker"] for row in results], ["005930", "000660"])
        self.assertTrue(all(row["mode"] == "simulation" for row in results))

    def test_trailing_stop_uses_persisted_high_water(self):
        holdings = [
            {
                "ticker": "005930",
                "entry_price": 80_000,
                "quantity": 2,
                "high_since_entry": 100_000,
            }
        ]

        with mock.patch(
            "trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
        ), mock.patch(
            "trading._load_holding_prices",
            new=mock.AsyncMock(return_value={"005930": 90_000}),
        ), mock.patch(
            "trading._persist_holding_highs",
            new=mock.AsyncMock(),
            create=True,
        ), mock.patch(
            "trading._get_current_portfolio",
            new=mock.AsyncMock(
                return_value={"cash": 10_000_000, "slots_used": 4, "holdings": []}
            ),
        ):
            results = asyncio.run(trading.run_trading([], dry_run=True))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["action"], "SELL")
        self.assertIn("트레일링 스탑", results[0]["reason"])

    def test_existing_holding_is_not_bought_again_without_exit(self):
        holdings = [
            {
                "ticker": "005930",
                "entry_price": 70_000,
                "quantity": 2,
                "high_since_entry": 72_000,
            }
        ]

        with mock.patch(
            "trading._get_exit_holdings",
            new=mock.AsyncMock(return_value=holdings),
        ), mock.patch(
            "trading._load_holding_prices",
            new=mock.AsyncMock(return_value={"005930": 71_000}),
        ), mock.patch(
            "trading._persist_holding_highs",
            new=mock.AsyncMock(),
        ), mock.patch(
            "trading._get_current_portfolio",
            new=mock.AsyncMock(
                return_value={"cash": 10_000_000, "slots_used": 1, "holdings": []}
            ),
        ):
            results = asyncio.run(
                trading.run_trading(
                    [_buy_analysis("005930", 71_000)],
                    dry_run=True,
                )
            )

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
