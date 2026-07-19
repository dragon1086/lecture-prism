from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from prism_core.cycle import TradingCycle
from prism_core.domain import (
    Market,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
)
from prism_core.ledger import Ledger
from prism_core.paper_broker import PaperBroker


def us_order(
    order_id: str,
    symbol: str = "AAPL",
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("1"),
    price: Decimal = Decimal("180"),
) -> OrderIntent:
    return OrderIntent(
        order_id,
        Market.US,
        symbol,
        side,
        OrderType.LIMIT,
        quantity,
        price,
        "USD",
    )


def kr_order(order_id: str, price: Decimal) -> OrderIntent:
    return OrderIntent(
        order_id,
        Market.KR,
        "005930",
        OrderSide.BUY,
        OrderType.LIMIT,
        Decimal("1"),
        price,
        "KRW",
    )


class TradingCycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cycle.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _broker(self) -> PaperBroker:
        return PaperBroker(Ledger(self.path))

    def _rows(self, sql: str):
        with sqlite3.connect(self.path) as conn:
            return conn.execute(sql).fetchall()

    @staticmethod
    def _fill(broker: PaperBroker, intent: OrderIntent, key: str) -> None:
        broker.submit_order(intent)
        broker.fill_order(
            intent.client_order_id,
            key,
            intent.quantity,
            intent.limit_price,
        )

    def test_restart_entry_hold_exit_and_realized_feedback(self):
        entry = us_order(
            "run-1:AAPL:BUY", quantity=Decimal("2"), price=Decimal("180")
        )
        result1 = TradingCycle(
            self._broker(), {(Market.US, "AAPL"): Decimal("180")}
        ).run("run-1", [entry], auto_fill=True)
        self.assertEqual(result1.entry_orders[0].status, OrderStatus.FILLED)

        broker2 = self._broker()
        result2 = TradingCycle(
            broker2, {(Market.US, "AAPL"): Decimal("195")}
        ).run("run-2", [], auto_fill=True)
        self.assertEqual(result2.exit_orders, [])
        self.assertEqual(
            broker2.get_positions()[0].high_since_entry, Decimal("195")
        )

        broker3 = self._broker()
        result3 = TradingCycle(
            broker3, {(Market.US, "AAPL"): Decimal("175")}
        ).run("run-3", [], auto_fill=True)
        self.assertEqual(result3.exit_orders[0].intent.side, OrderSide.SELL)
        self.assertEqual(broker3.get_positions(), [])
        self.assertEqual(broker3.ledger.count_realized_trades(), 1)

    def test_exit_orders_are_processed_before_new_entries(self):
        broker = self._broker()
        self._fill(
            broker,
            us_order("seed:AAPL:BUY", price=Decimal("180")),
            "seed-fill",
        )
        new_entry = us_order(
            "run-2:MSFT:BUY", "MSFT", price=Decimal("300")
        )

        result = TradingCycle(
            broker,
            {
                (Market.US, "AAPL"): Decimal("160"),
                (Market.US, "MSFT"): Decimal("300"),
            },
        ).run("run-2", [new_entry], auto_fill=True)

        self.assertEqual(result.event_order, ["RECONCILE", "EXIT", "ENTRY"])
        self.assertEqual(result.exit_orders[0].intent.symbol, "AAPL")
        self.assertEqual(result.entry_orders[0].intent.symbol, "MSFT")

    def test_unknown_order_without_position_blocks_new_entry(self):
        broker = self._broker()
        unresolved = us_order("prior:AAPL:BUY")
        broker.submit_order(unresolved)
        broker.mark_unknown(unresolved.client_order_id)
        replacement = us_order("run-2:AAPL:BUY")

        result = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("180")}
        ).run("run-2", [replacement], auto_fill=True)

        self.assertEqual(result.entry_orders, [])
        self.assertEqual(result.event_order, ["RECONCILE"])
        with self.assertRaises(KeyError):
            broker.ledger.get_order(replacement.client_order_id)
        self.assertEqual(broker.get_positions(), [])

    def test_open_order_without_position_blocks_new_entry(self):
        broker = self._broker()
        prior = us_order("prior:AAPL:BUY")
        broker.submit_order(prior)
        replacement = us_order("run-2:AAPL:BUY")

        result = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("180")}
        ).run("run-2", [replacement], auto_fill=True)

        self.assertEqual(result.entry_orders, [])
        with self.assertRaises(KeyError):
            broker.ledger.get_order(replacement.client_order_id)

    def test_exact_accepted_entry_resumes_auto_fill_after_restart(self):
        entry = us_order("run-1:AAPL:BUY")
        self._broker().submit_order(entry)

        restarted = self._broker()
        result = TradingCycle(
            restarted, {(Market.US, "AAPL"): Decimal("180")}
        ).run("run-1", [entry], auto_fill=True)

        self.assertEqual(result.entry_orders[0].status, OrderStatus.FILLED)
        self.assertEqual(restarted.get_positions()[0].quantity, Decimal("1"))

    def test_exact_accepted_exit_resumes_when_quote_changes(self):
        broker = self._broker()
        self._fill(broker, us_order("seed:AAPL:BUY"), "seed-fill")
        accepted = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("160")}
        ).run("run-2", [], auto_fill=False)
        self.assertEqual(accepted.exit_orders[0].status, OrderStatus.ACCEPTED)

        restarted = self._broker()
        resumed = TradingCycle(
            restarted, {(Market.US, "AAPL"): Decimal("155")}
        ).run("run-2", [], auto_fill=True)

        self.assertEqual(resumed.exit_orders[0].status, OrderStatus.FILLED)
        self.assertEqual(
            resumed.exit_orders[0].intent.limit_price, Decimal("160")
        )
        self.assertEqual(
            resumed.exit_orders[0].average_fill_price, Decimal("155")
        )
        self.assertEqual(restarted.get_positions(), [])

    def test_unresolved_partial_order_does_not_hide_new_high_water(self):
        broker = self._broker()
        entry = us_order("partial:AAPL:BUY", quantity=Decimal("2"))
        broker.submit_order(entry)
        broker.fill_order(
            entry.client_order_id,
            "partial-fill",
            Decimal("1"),
            Decimal("180"),
        )

        result = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("195")}
        ).run("run-2", [], auto_fill=True)

        self.assertEqual(result.exit_orders, [])
        self.assertEqual(
            broker.get_positions()[0].high_since_entry, Decimal("195")
        )

    def test_unknown_exit_is_fail_closed_without_duplicate_sell(self):
        broker = self._broker()
        self._fill(broker, us_order("seed:AAPL:BUY"), "seed-fill")
        unresolved_exit = us_order(
            "prior:AAPL:SELL", side=OrderSide.SELL, price=Decimal("160")
        )
        broker.submit_order(unresolved_exit)
        broker.mark_unknown(unresolved_exit.client_order_id)

        result = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("160")}
        ).run("run-2", [], auto_fill=True)

        self.assertEqual(result.exit_orders, [])
        self.assertEqual(result.event_order, ["RECONCILE"])
        self.assertEqual(len(broker.get_positions()), 1)
        self.assertEqual(
            self._rows("SELECT COUNT(*) FROM broker_orders WHERE side='SELL'"),
            [(1,)],
        )

    def test_missing_or_invalid_entry_quote_has_no_side_effect(self):
        invalid_quotes = (
            None,
            180,
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("0"),
            Decimal("-1"),
        )
        for index, quote in enumerate(invalid_quotes):
            with self.subTest(quote=quote):
                path = Path(self.tmp.name) / f"bad-entry-{index}.db"
                broker = PaperBroker(Ledger(path))
                intent = us_order(f"run-{index}:AAPL:BUY")
                quotes = {} if quote is None else {(Market.US, "AAPL"): quote}

                result = TradingCycle(broker, quotes).run(
                    f"run-{index}", [intent], auto_fill=True
                )

                self.assertEqual(result.entry_orders, [])
                self.assertEqual(broker.get_positions(), [])
                with self.assertRaises(KeyError):
                    broker.ledger.get_order(intent.client_order_id)

    def test_missing_or_invalid_position_quote_does_not_mutate_high_water(self):
        invalid_quotes = (None, Decimal("NaN"), Decimal("0"))
        for index, quote in enumerate(invalid_quotes):
            with self.subTest(quote=quote):
                path = Path(self.tmp.name) / f"bad-position-{index}.db"
                broker = PaperBroker(Ledger(path))
                self._fill(
                    broker,
                    us_order(f"seed-{index}:AAPL:BUY"),
                    f"seed-fill-{index}",
                )
                quotes = {} if quote is None else {(Market.US, "AAPL"): quote}

                result = TradingCycle(broker, quotes).run(
                    f"run-{index}", [], auto_fill=True
                )

                self.assertEqual(result.exit_orders, [])
                self.assertEqual(
                    broker.get_positions()[0].high_since_entry, Decimal("180")
                )
                self.assertEqual(broker.ledger.count_realized_trades(), 0)

    def test_fractional_kr_quote_has_no_side_effect(self):
        broker = self._broker()
        intent = kr_order("run-1:005930:BUY", Decimal("70000"))

        result = TradingCycle(
            broker, {(Market.KR, "005930"): Decimal("69999.5")}
        ).run("run-1", [intent], auto_fill=True)

        self.assertEqual(result.entry_orders, [])
        with self.assertRaises(KeyError):
            broker.ledger.get_order(intent.client_order_id)

    def test_auto_fill_identity_is_deterministic_across_restart(self):
        entry = us_order("run-1:AAPL:BUY")
        broker1 = self._broker()
        real_fill = broker1.fill_order

        def fill_then_lose_response(*args, **kwargs):
            real_fill(*args, **kwargs)
            raise TimeoutError("simulated lost response after committed fill")

        with patch.object(
            broker1, "fill_order", side_effect=fill_then_lose_response
        ):
            with self.assertRaisesRegex(TimeoutError, "lost response"):
                TradingCycle(
                    broker1, {(Market.US, "AAPL"): Decimal("180")}
                ).run("run-1", [entry], auto_fill=True)

        broker2 = self._broker()
        replay = TradingCycle(
            broker2, {(Market.US, "AAPL"): Decimal("180")}
        ).run("run-1", [entry], auto_fill=True)

        self.assertEqual(replay.entry_orders[0].status, OrderStatus.FILLED)
        self.assertEqual(
            self._rows("SELECT fill_id FROM fills"),
            [
                (
                    f"paper:{len(entry.client_order_id)}:"
                    f"{entry.client_order_id}:auto-fill",
                )
            ],
        )
        self.assertEqual(broker2.get_positions()[0].quantity, Decimal("1"))

    def test_already_filled_order_is_returned_without_refill(self):
        broker = self._broker()
        entry = us_order("run-1:AAPL:BUY")
        self._fill(broker, entry, "original-entry")
        exit_intent = us_order(
            "run-2:AAPL:SELL", side=OrderSide.SELL, price=Decimal("190")
        )
        self._fill(broker, exit_intent, "original-exit")
        self.assertEqual(broker.get_positions(), [])

        result = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("180")}
        ).run("run-1", [entry], auto_fill=True)

        self.assertEqual(result.entry_orders[0].status, OrderStatus.FILLED)
        self.assertEqual(broker.get_positions(), [])
        self.assertEqual(self._rows("SELECT COUNT(*) FROM fills"), [(2,)])


if __name__ == "__main__":
    unittest.main()
