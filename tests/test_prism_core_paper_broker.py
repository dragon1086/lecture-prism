from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from prism_core.domain import (
    Market,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
)
from prism_core.ledger import Ledger
from prism_core.paper_broker import PaperBroker


class PaperBrokerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "paper.db"
        self.ledger = Ledger(self.path)
        self.broker = PaperBroker(self.ledger)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _kr_order(order_id="cycle-1:005930:BUY", quantity=Decimal("3")):
        return OrderIntent(
            order_id,
            Market.KR,
            "005930",
            OrderSide.BUY,
            OrderType.LIMIT,
            quantity,
            Decimal("70000"),
            "KRW",
        )

    @staticmethod
    def _us_order(order_id="cycle-1:AAPL:BUY", quantity=Decimal("2")):
        return OrderIntent(
            order_id,
            Market.US,
            "AAPL",
            OrderSide.BUY,
            OrderType.LIMIT,
            quantity,
            Decimal("181.25"),
            "USD",
        )

    def _advance_to(self, intent, status):
        record = self.ledger.create_order(intent)
        next_status = {
            OrderStatus.CREATED: OrderStatus.PREVIEWED,
            OrderStatus.PREVIEWED: OrderStatus.SUBMITTED,
            OrderStatus.SUBMITTED: OrderStatus.ACCEPTED,
        }
        while record.status is not status:
            record = self.ledger.transition_order(
                intent.client_order_id, next_status[record.status]
            )
        return record

    def _rows(self, sql, parameters=()):
        with sqlite3.connect(self.path) as conn:
            return conn.execute(sql, parameters).fetchall()

    def test_preview_is_side_effect_free(self):
        intent = self._kr_order()

        self.assertIs(self.broker.preview_order(intent), intent)
        self.assertEqual(self._rows("SELECT * FROM broker_orders"), [])
        self.assertEqual(self._rows("SELECT * FROM order_events"), [])

    def test_submit_progresses_to_accepted_without_fill_or_position(self):
        intent = self._kr_order()

        record = self.broker.submit_order(intent)

        self.assertEqual(record.status, OrderStatus.ACCEPTED)
        self.assertEqual(record.filled_quantity, Decimal("0"))
        self.assertEqual(self.broker.get_positions(), [])
        self.assertEqual(self._rows("SELECT * FROM fills"), [])
        self.assertEqual(
            self._rows(
                "SELECT status FROM order_events "
                "WHERE client_order_id=? ORDER BY id",
                (intent.client_order_id,),
            ),
            [
                (OrderStatus.CREATED.value,),
                (OrderStatus.PREVIEWED.value,),
                (OrderStatus.SUBMITTED.value,),
                (OrderStatus.ACCEPTED.value,),
            ],
        )

    def test_exact_submit_retry_resumes_every_intermediate_state_once(self):
        for index, initial in enumerate(
            (
                OrderStatus.CREATED,
                OrderStatus.PREVIEWED,
                OrderStatus.SUBMITTED,
                OrderStatus.ACCEPTED,
            )
        ):
            with self.subTest(initial=initial):
                intent = self._us_order(f"resume-{index}:AAPL:BUY")
                self._advance_to(intent, initial)

                restarted = PaperBroker(Ledger(self.path))
                first = restarted.submit_order(intent)
                second = restarted.submit_order(intent)

                self.assertEqual(first, second)
                self.assertEqual(first.status, OrderStatus.ACCEPTED)
                self.assertEqual(
                    self._rows(
                        "SELECT COUNT(*) FROM broker_orders "
                        "WHERE client_order_id=?",
                        (intent.client_order_id,),
                    ),
                    [(1,)],
                )
                self.assertEqual(
                    self._rows(
                        "SELECT status,COUNT(*) FROM order_events "
                        "WHERE client_order_id=? GROUP BY status",
                        (intent.client_order_id,),
                    ),
                    [
                        (OrderStatus.ACCEPTED.value, 1),
                        (OrderStatus.CREATED.value, 1),
                        (OrderStatus.PREVIEWED.value, 1),
                        (OrderStatus.SUBMITTED.value, 1),
                    ],
                )

    def test_submit_retry_rejects_same_id_with_different_payload(self):
        intent = self._us_order()
        original = self.broker.submit_order(intent)
        collision = self._us_order(quantity=Decimal("3"))

        with self.assertRaisesRegex(ValueError, "order id collision"):
            self.broker.submit_order(collision)

        self.assertEqual(self.ledger.get_order(intent.client_order_id), original)

    def test_us_partial_then_full_fill_is_cumulative_and_restartable(self):
        intent = self._us_order(quantity=Decimal("2.00"))
        self.broker.submit_order(intent)

        partial = self.broker.fill_order(
            intent.client_order_id,
            "execution-1",
            Decimal("1.25"),
            Decimal("180.10"),
        )
        restarted = PaperBroker(Ledger(self.path))
        full = restarted.fill_order(
            intent.client_order_id,
            "execution-2",
            Decimal("0.75"),
            Decimal("181.10"),
        )

        self.assertEqual(partial.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(partial.filled_quantity, Decimal("1.25"))
        self.assertEqual(full.status, OrderStatus.FILLED)
        self.assertEqual(full.filled_quantity, Decimal("2.00"))
        self.assertEqual(full.average_fill_price, Decimal("180.475"))
        self.assertEqual(restarted.get_positions()[0].quantity, Decimal("2.00"))
        self.assertEqual(
            self._rows(
                "SELECT fill_id FROM fills "
                "WHERE client_order_id=? ORDER BY rowid",
                (intent.client_order_id,),
            ),
            [
                (f"paper:{len(intent.client_order_id)}:{intent.client_order_id}:execution-1",),
                (f"paper:{len(intent.client_order_id)}:{intent.client_order_id}:execution-2",),
            ],
        )

    def test_lost_response_replay_keeps_one_partial_fill_after_restart(self):
        intent = self._us_order("lost-response:AAPL:BUY", Decimal("2"))
        self.broker.submit_order(intent)
        first = self.broker.fill_order(
            intent.client_order_id,
            "execution-1",
            Decimal("1"),
            Decimal("180"),
        )
        first_position = self.broker.get_positions()[0]

        restarted = PaperBroker(Ledger(self.path))
        replay = restarted.fill_order(
            intent.client_order_id,
            "execution-1",
            Decimal("1.0"),
            Decimal("180.00"),
        )

        self.assertEqual(replay, first)
        self.assertEqual(restarted.get_positions(), [first_position])
        self.assertEqual(
            self._rows(
                "SELECT COUNT(*) FROM fills WHERE client_order_id=?",
                (intent.client_order_id,),
            ),
            [(1,)],
        )

    def test_same_execution_key_with_conflicting_payload_is_rejected(self):
        intent = self._us_order("collision:AAPL:BUY", Decimal("3"))
        self.broker.submit_order(intent)
        self.broker.fill_order(
            intent.client_order_id,
            "execution-1",
            Decimal("1"),
            Decimal("180"),
        )
        before_order = self.ledger.get_order(intent.client_order_id)
        before_position = self.broker.get_positions()[0]

        for label, quantity, price in (
            ("quantity", Decimal("2"), Decimal("180")),
            ("price", Decimal("1"), Decimal("181")),
        ):
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "fill id collision"):
                    self.broker.fill_order(
                        intent.client_order_id,
                        "execution-1",
                        quantity,
                        price,
                    )
                self.assertEqual(
                    self.ledger.get_order(intent.client_order_id), before_order
                )
                self.assertEqual(self.broker.get_positions(), [before_position])
                self.assertEqual(
                    self._rows("SELECT COUNT(*) FROM fills"), [(1,)]
                )

    def test_distinct_execution_keys_allow_identical_fills(self):
        intent = self._us_order("two-executions:AAPL:BUY", Decimal("2"))
        self.broker.submit_order(intent)

        self.broker.fill_order(
            intent.client_order_id,
            "execution-1",
            Decimal("1"),
            Decimal("180"),
        )
        record = self.broker.fill_order(
            intent.client_order_id,
            "execution-2",
            Decimal("1"),
            Decimal("180"),
        )

        self.assertEqual(record.status, OrderStatus.FILLED)
        self.assertEqual(record.filled_quantity, Decimal("2"))
        self.assertEqual(self.broker.get_positions()[0].quantity, Decimal("2"))
        self.assertEqual(self._rows("SELECT COUNT(*) FROM fills"), [(2,)])

    def test_final_fill_replay_is_idempotent_after_order_is_filled(self):
        intent = self._us_order("final-replay:AAPL:BUY", Decimal("1"))
        self.broker.submit_order(intent)
        first = self.broker.fill_order(
            intent.client_order_id,
            "execution-final",
            Decimal("1"),
            Decimal("180"),
        )

        restarted = PaperBroker(Ledger(self.path))
        replay = restarted.fill_order(
            intent.client_order_id,
            "execution-final",
            Decimal("1.00"),
            Decimal("180.00"),
        )

        self.assertEqual(replay, first)
        self.assertEqual(restarted.get_positions()[0].quantity, Decimal("1"))
        self.assertEqual(self._rows("SELECT COUNT(*) FROM fills"), [(1,)])

    def test_new_execution_cannot_cross_concurrent_unknown_transition(self):
        intent = self._us_order("unknown-race:AAPL:BUY", Decimal("2"))
        self.broker.submit_order(intent)
        read_accepted = threading.Event()
        unknown_committed = threading.Event()
        result = {}
        real_get_order = self.ledger.get_order

        def pause_after_accepted_read(client_order_id):
            record = real_get_order(client_order_id)
            if not read_accepted.is_set():
                read_accepted.set()
                if not unknown_committed.wait(2):
                    raise TimeoutError("UNKNOWN transition did not commit")
            return record

        def attempt_fill():
            try:
                result["value"] = self.broker.fill_order(
                    intent.client_order_id,
                    "execution-racing",
                    Decimal("1"),
                    Decimal("180"),
                )
            except Exception as exc:
                result["error"] = exc

        with patch.object(
            self.ledger, "get_order", side_effect=pause_after_accepted_read
        ):
            worker = threading.Thread(target=attempt_fill)
            worker.start()
            self.assertTrue(read_accepted.wait(2), "broker did not read ACCEPTED")
            Ledger(self.path).transition_order(
                intent.client_order_id, OrderStatus.UNKNOWN
            )
            unknown_committed.set()
            worker.join(2)
            self.assertFalse(worker.is_alive(), "fill attempt did not finish")

        self.assertIsInstance(result.get("error"), ValueError)
        self.assertRegex(
            str(result["error"]), "order cannot be filled from UNKNOWN"
        )
        self.assertNotIn("value", result)
        self.assertEqual(self._rows("SELECT COUNT(*) FROM fills"), [(0,)])
        self.assertEqual(self.broker.get_positions(), [])
        self.assertEqual(
            self.ledger.get_order(intent.client_order_id).status,
            OrderStatus.UNKNOWN,
        )

    def test_kr_full_fill_creates_position_only_through_ledger(self):
        intent = self._kr_order()
        self.broker.submit_order(intent)

        record = self.broker.fill_order(
            intent.client_order_id,
            "execution-full",
            Decimal("3"),
            Decimal("69900"),
        )

        self.assertEqual(record.status, OrderStatus.FILLED)
        position = self.broker.get_positions()[0]
        self.assertEqual(position.market, Market.KR)
        self.assertEqual(position.quantity, Decimal("3"))
        self.assertEqual(position.average_price, Decimal("69900"))

    def test_fill_is_rejected_from_every_nonfillable_state(self):
        states = (
            OrderStatus.CREATED,
            OrderStatus.PREVIEWED,
            OrderStatus.SUBMITTED,
            OrderStatus.UNKNOWN,
            OrderStatus.REJECTED,
            OrderStatus.CANCELED,
            OrderStatus.FILLED,
        )
        for index, status in enumerate(states):
            with self.subTest(status=status):
                intent = self._us_order(f"blocked-{index}:AAPL:BUY", Decimal("1"))
                if status in {
                    OrderStatus.CREATED,
                    OrderStatus.PREVIEWED,
                    OrderStatus.SUBMITTED,
                }:
                    self._advance_to(intent, status)
                elif status is OrderStatus.REJECTED:
                    self.ledger.create_order(intent)
                    self.ledger.transition_order(intent.client_order_id, status)
                else:
                    self.broker.submit_order(intent)
                    if status is OrderStatus.UNKNOWN:
                        self.broker.mark_unknown(intent.client_order_id)
                    elif status is OrderStatus.CANCELED:
                        self.broker.cancel_order(intent.client_order_id)
                    else:
                        self.broker.fill_order(
                            intent.client_order_id,
                            "execution-original",
                            Decimal("1"),
                            Decimal("180"),
                        )
                fills_before = len(self._rows("SELECT fill_id FROM fills"))

                with self.assertRaisesRegex(
                    ValueError, f"order cannot be filled from {status.value}"
                ):
                    self.broker.fill_order(
                        intent.client_order_id,
                        "execution-new",
                        Decimal("1"),
                        Decimal("180"),
                    )

                self.assertEqual(
                    len(self._rows("SELECT fill_id FROM fills")), fills_before
                )

    def test_overfill_is_rejected_without_partial_writes(self):
        intent = self._us_order(quantity=Decimal("2"))
        accepted = self.broker.submit_order(intent)

        with self.assertRaisesRegex(ValueError, "fill quantity exceeds order quantity"):
            self.broker.fill_order(
                intent.client_order_id,
                "execution-overfill",
                Decimal("2.01"),
                Decimal("180"),
            )

        self.assertEqual(self.ledger.get_order(intent.client_order_id), accepted)
        self.assertEqual(self.broker.get_positions(), [])
        self.assertEqual(self._rows("SELECT * FROM fills"), [])

    def test_kr_fill_contract_rejects_fractional_execution_values(self):
        for label, quantity, price, message in (
            (
                "quantity",
                Decimal("0.5"),
                Decimal("69900"),
                "KR fill quantity must be a whole number",
            ),
            (
                "price",
                Decimal("1"),
                Decimal("69900.5"),
                "KR fill price must be a whole number",
            ),
        ):
            with self.subTest(label=label):
                intent = self._kr_order(f"kr-{label}:005930:BUY")
                self.broker.submit_order(intent)
                with self.assertRaisesRegex(ValueError, message):
                    self.broker.fill_order(
                        intent.client_order_id,
                        f"execution-{label}",
                        quantity,
                        price,
                    )
                self.assertEqual(
                    self.ledger.get_order(intent.client_order_id).status,
                    OrderStatus.ACCEPTED,
                )

    def test_cancel_only_accepts_accepted_or_partially_filled_orders(self):
        accepted_intent = self._us_order("cancel-accepted:AAPL:BUY")
        self.broker.submit_order(accepted_intent)
        self.assertEqual(
            self.broker.cancel_order(accepted_intent.client_order_id).status,
            OrderStatus.CANCELED,
        )

        partial_intent = self._us_order("cancel-partial:AAPL:BUY")
        self.broker.submit_order(partial_intent)
        self.broker.fill_order(
            partial_intent.client_order_id,
            "execution-partial",
            Decimal("1"),
            Decimal("180"),
        )
        self.assertEqual(
            self.broker.cancel_order(partial_intent.client_order_id).status,
            OrderStatus.CANCELED,
        )

        for index, status in enumerate(
            (OrderStatus.CREATED, OrderStatus.PREVIEWED, OrderStatus.SUBMITTED)
        ):
            with self.subTest(status=status):
                intent = self._us_order(f"no-cancel-{index}:AAPL:BUY")
                self._advance_to(intent, status)
                with self.assertRaisesRegex(
                    ValueError, f"order cannot be canceled from {status.value}"
                ):
                    self.broker.cancel_order(intent.client_order_id)

        for intent in (accepted_intent, partial_intent):
            with self.subTest(status=OrderStatus.CANCELED):
                with self.assertRaisesRegex(
                    ValueError, "order cannot be canceled from CANCELED"
                ):
                    self.broker.cancel_order(intent.client_order_id)

    def test_unknown_is_fail_closed_and_only_uses_domain_transitions(self):
        accepted_intent = self._us_order("unknown:AAPL:BUY")
        self.broker.submit_order(accepted_intent)

        unknown = self.broker.mark_unknown(accepted_intent.client_order_id)
        retried = PaperBroker(Ledger(self.path)).submit_order(accepted_intent)

        self.assertEqual(unknown.status, OrderStatus.UNKNOWN)
        self.assertEqual(retried, unknown)
        self.assertEqual(self.broker.get_positions(), [])

        created_intent = self._us_order("unknown-created:AAPL:BUY")
        self.ledger.create_order(created_intent)
        with self.assertRaisesRegex(
            ValueError, "invalid order transition: CREATED -> UNKNOWN"
        ):
            self.broker.mark_unknown(created_intent.client_order_id)

    def test_reconcile_reads_persisted_positions_after_restart(self):
        intent = self._us_order(quantity=Decimal("1.5"))
        self.broker.submit_order(intent)
        self.broker.fill_order(
            intent.client_order_id,
            "execution-full",
            Decimal("1.5"),
            Decimal("180.125"),
        )

        restarted = PaperBroker(Ledger(self.path))

        self.assertEqual(restarted.reconcile(), restarted.get_positions())
        self.assertEqual(restarted.reconcile(), self.broker.get_positions())

    def test_unresolved_order_query_is_exposed_by_broker(self):
        intent = self._us_order("unresolved:AAPL:BUY")
        self.broker.submit_order(intent)
        self.broker.mark_unknown(intent.client_order_id)

        self.assertTrue(
            PaperBroker(Ledger(self.path)).has_unresolved_order(
                Market.US, "AAPL"
            )
        )


if __name__ == "__main__":
    unittest.main()
