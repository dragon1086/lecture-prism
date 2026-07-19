from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import threading
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

    def test_accepted_exit_resumes_when_quote_no_longer_signals(self):
        broker = self._broker()
        self._fill(broker, us_order("seed:AAPL:BUY"), "seed-fill")
        accepted = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("160")}
        ).run("run-2", [], auto_fill=False)
        self.assertEqual(accepted.exit_orders[0].status, OrderStatus.ACCEPTED)
        self.assertEqual(
            accepted.exit_orders[0].intent.order_type, OrderType.MARKET
        )
        self.assertIsNone(accepted.exit_orders[0].intent.limit_price)

        restarted = self._broker()
        resumed = TradingCycle(
            restarted, {(Market.US, "AAPL"): Decimal("190")}
        ).run("run-2", [], auto_fill=True)

        self.assertEqual(resumed.exit_orders[0].status, OrderStatus.FILLED)
        self.assertEqual(resumed.exit_orders[0].average_fill_price, Decimal("190"))
        self.assertEqual(restarted.get_positions(), [])

    def test_partial_buy_is_canceled_before_stop_liquidation(self):
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
            broker, {(Market.US, "AAPL"): Decimal("160")}
        ).run("run-2", [], auto_fill=True)

        self.assertEqual(
            broker.get_order(entry.client_order_id).status,
            OrderStatus.CANCELED,
        )
        self.assertEqual(result.exit_orders[0].status, OrderStatus.FILLED)
        self.assertEqual(result.exit_orders[0].intent.quantity, Decimal("1"))
        self.assertEqual(broker.get_positions(), [])

    def test_stopped_partial_buy_intent_cannot_resume_in_entry_phase(self):
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
            broker, {(Market.US, "AAPL"): Decimal("160")}
        ).run("run-2", [entry], auto_fill=True)

        self.assertEqual(result.entry_orders, [])
        self.assertEqual(broker.get_positions(), [])
        self.assertEqual(
            broker.get_order(entry.client_order_id).status,
            OrderStatus.CANCELED,
        )

    def test_unknown_partial_buy_reports_blocked_liquidation(self):
        broker = self._broker()
        entry = us_order("partial:AAPL:BUY", quantity=Decimal("2"))
        broker.submit_order(entry)
        broker.fill_order(
            entry.client_order_id,
            "partial-fill",
            Decimal("1"),
            Decimal("180"),
        )
        broker.mark_unknown(entry.client_order_id)

        result = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("160")}
        ).run("run-2", [entry], auto_fill=True)

        self.assertEqual(result.exit_orders, [])
        self.assertEqual(result.entry_orders, [])
        self.assertEqual(result.blocked[0].reason, "unknown_buy_order")
        self.assertEqual(broker.get_positions()[0].quantity, Decimal("1"))

    def test_buy_completion_race_rebinds_exit_to_current_position(self):
        broker = self._broker()
        entry = us_order("partial:AAPL:BUY", quantity=Decimal("2"))
        broker.submit_order(entry)
        broker.fill_order(
            entry.client_order_id,
            "partial-fill",
            Decimal("1"),
            Decimal("180"),
        )
        real_cancel = broker.cancel_order
        raced = False

        def complete_then_cancel(client_order_id):
            nonlocal raced
            if not raced:
                raced = True
                PaperBroker(Ledger(self.path)).fill_order(
                    entry.client_order_id,
                    "racing-fill",
                    Decimal("1"),
                    Decimal("170"),
                )
            return real_cancel(client_order_id)

        with patch.object(broker, "cancel_order", side_effect=complete_then_cancel):
            result = TradingCycle(
                broker, {(Market.US, "AAPL"): Decimal("160")}
            ).run("run-2", [], auto_fill=True)

        self.assertEqual(result.exit_orders[0].intent.quantity, Decimal("2"))
        self.assertEqual(broker.get_positions(), [])

    def test_terminal_stale_exit_does_not_shadow_residual_stop(self):
        broker = self._broker()
        self._fill(
            broker,
            us_order("seed:AAPL:BUY", quantity=Decimal("2")),
            "seed-fill",
        )
        stale = OrderIntent(
            "run-2:US:AAPL:SELL",
            Market.US,
            "AAPL",
            OrderSide.SELL,
            OrderType.MARKET,
            Decimal("1"),
            None,
            "USD",
            reason="stop",
        )
        broker.submit_order(stale)
        broker.fill_order(
            stale.client_order_id,
            "stale-fill",
            Decimal("1"),
            Decimal("160"),
        )

        result = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("150")}
        ).run("run-2", [], auto_fill=True)

        self.assertNotEqual(
            result.exit_orders[0].intent.client_order_id,
            stale.client_order_id,
        )
        self.assertEqual(result.exit_orders[0].intent.quantity, Decimal("1"))
        self.assertEqual(broker.get_positions(), [])

    def test_same_symbol_stop_excludes_same_cycle_entry(self):
        broker = self._broker()
        self._fill(broker, us_order("seed:AAPL:BUY"), "seed-fill")
        replacement = us_order("run-2:AAPL:BUY")

        result = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("160")}
        ).run("run-2", [replacement], auto_fill=True)

        self.assertEqual(result.entry_orders, [])
        self.assertEqual(broker.get_positions(), [])

    def test_overlapping_same_run_is_explicitly_blocked(self):
        broker1 = self._broker()
        self._fill(broker1, us_order("seed:AAPL:BUY"), "seed-fill")
        broker2 = self._broker()
        entered = threading.Event()
        release = threading.Event()
        first_result = {}
        real_reconcile = broker1.reconcile

        def pause_reconcile():
            entered.set()
            if not release.wait(2):
                raise TimeoutError("overlap test did not release first cycle")
            return real_reconcile()

        def run_first():
            try:
                first_result["value"] = TradingCycle(
                    broker1, {(Market.US, "AAPL"): Decimal("160")}
                ).run("run-2", [], auto_fill=False)
            except Exception as exc:
                first_result["error"] = exc

        with patch.object(broker1, "reconcile", side_effect=pause_reconcile):
            worker = threading.Thread(target=run_first)
            worker.start()
            self.assertTrue(entered.wait(2), "first cycle did not acquire fence")
            blocked = TradingCycle(
                broker2, {(Market.US, "AAPL"): Decimal("155")}
            ).run("run-2", [], auto_fill=False)
            release.set()
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertNotIn("error", first_result)
        self.assertEqual(blocked.blocked[0].reason, "cycle_overlap")
        self.assertEqual(
            self._rows("SELECT COUNT(*) FROM broker_orders WHERE side='SELL'"),
            [(1,)],
        )

    def test_concurrent_position_disappearance_skips_high_water(self):
        broker = self._broker()
        self._fill(broker, us_order("seed:AAPL:BUY"), "seed-fill")
        real_update = broker.ledger.update_high_water

        def close_then_update(market, symbol, price):
            closer = PaperBroker(Ledger(self.path))
            close = OrderIntent(
                "concurrent:AAPL:SELL",
                Market.US,
                "AAPL",
                OrderSide.SELL,
                OrderType.MARKET,
                Decimal("1"),
                None,
                "USD",
            )
            closer.submit_order(close)
            closer.fill_order(
                close.client_order_id,
                "concurrent-close",
                Decimal("1"),
                Decimal("180"),
            )
            return real_update(market, symbol, price)

        with patch.object(
            broker.ledger, "update_high_water", side_effect=close_then_update
        ):
            result = TradingCycle(
                broker, {(Market.US, "AAPL"): Decimal("190")}
            ).run("run-2", [], auto_fill=True)

        self.assertEqual(result.exit_orders, [])
        self.assertEqual(broker.get_positions(), [])

    def test_all_high_waters_commit_before_any_exit_response_can_be_lost(self):
        broker = self._broker()
        self._fill(broker, us_order("seed:AAPL:BUY"), "seed-aapl")
        self._fill(
            broker,
            us_order(
                "seed:MSFT:BUY", "MSFT", price=Decimal("300")
            ),
            "seed-msft",
        )
        real_fill = broker.fill_order

        def fill_exit_then_lose_response(*args, **kwargs):
            record = real_fill(*args, **kwargs)
            if record.intent.side is OrderSide.SELL:
                raise TimeoutError("simulated lost exit response")
            return record

        with patch.object(
            broker, "fill_order", side_effect=fill_exit_then_lose_response
        ):
            with self.assertRaisesRegex(TimeoutError, "lost exit response"):
                TradingCycle(
                    broker,
                    {
                        (Market.US, "AAPL"): Decimal("160"),
                        (Market.US, "MSFT"): Decimal("330"),
                    },
                ).run("run-2", [], auto_fill=True)

        positions = {
            position.symbol: position for position in broker.get_positions()
        }
        self.assertNotIn("AAPL", positions)
        self.assertEqual(
            positions["MSFT"].high_since_entry, Decimal("330")
        )

    def test_exit_fill_conflict_stops_when_target_position_is_gone(self):
        broker = self._broker()
        self._fill(broker, us_order("seed:AAPL:BUY"), "seed-aapl")
        self._fill(
            broker,
            us_order(
                "seed:MSFT:BUY", "MSFT", price=Decimal("300")
            ),
            "seed-msft",
        )
        real_fill = broker.fill_order
        raced = False

        def close_target_then_fill_stale(*args, **kwargs):
            nonlocal raced
            record = broker.get_order(args[0])
            if record.intent.side is OrderSide.SELL and not raced:
                raced = True
                closer = PaperBroker(Ledger(self.path))
                concurrent = OrderIntent(
                    "concurrent:AAPL:SELL",
                    Market.US,
                    "AAPL",
                    OrderSide.SELL,
                    OrderType.MARKET,
                    Decimal("1"),
                    None,
                    "USD",
                )
                closer.submit_order(concurrent)
                closer.fill_order(
                    concurrent.client_order_id,
                    "concurrent-fill",
                    Decimal("1"),
                    Decimal("160"),
                )
            return real_fill(*args, **kwargs)

        with (
            patch.object(
                broker,
                "submit_exit_order",
                wraps=broker.submit_exit_order,
            ) as submit_exit,
            patch.object(
                broker,
                "fill_order",
                side_effect=close_target_then_fill_stale,
            ),
        ):
            result = TradingCycle(
                broker,
                {
                    (Market.US, "AAPL"): Decimal("160"),
                    (Market.US, "MSFT"): Decimal("300"),
                },
            ).run("run-2", [], auto_fill=True)

        self.assertEqual(result.exit_orders, [])
        self.assertEqual(submit_exit.call_count, 1)
        self.assertEqual(
            [position.symbol for position in broker.get_positions()],
            ["MSFT"],
        )

    def test_non_marketable_limit_entry_remains_accepted(self):
        broker = self._broker()
        entry = us_order("run-1:AAPL:BUY", price=Decimal("180"))

        result = TradingCycle(
            broker, {(Market.US, "AAPL"): Decimal("181")}
        ).run("run-1", [entry], auto_fill=True)

        self.assertEqual(result.entry_orders[0].status, OrderStatus.ACCEPTED)
        self.assertEqual(broker.get_positions(), [])

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
        self.assertEqual(result.event_order, ["RECONCILE", "BLOCKED"])
        self.assertEqual(result.blocked[0].reason, "unknown_exit_order")
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

        self.assertEqual(replay.entry_orders, [])
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
