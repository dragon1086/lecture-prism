from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from prism_core.domain import Fill, Market, OrderIntent, OrderSide, OrderStatus, OrderType
from prism_core.ledger import Ledger


def buy_intent(order_id="run-1:AAPL:BUY"):
    return OrderIntent(
        order_id,
        Market.US,
        "AAPL",
        OrderSide.BUY,
        OrderType.LIMIT,
        Decimal("2"),
        Decimal("180.25"),
        "USD",
    )


class PrismCoreLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.db"
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fill_creates_position_only_after_fill(self):
        intent = buy_intent()
        self.ledger.create_order(intent)
        self.ledger.transition_order(intent.client_order_id, OrderStatus.PREVIEWED)
        self.ledger.transition_order(intent.client_order_id, OrderStatus.SUBMITTED)
        self.assertEqual(self.ledger.list_positions(), [])

        self.ledger.record_fill(
            Fill(
                "fill-1",
                intent.client_order_id,
                Market.US,
                "AAPL",
                OrderSide.BUY,
                Decimal("2"),
                Decimal("179.50"),
                "USD",
            )
        )

        position = self.ledger.list_positions()[0]
        self.assertEqual(position.quantity, Decimal("2"))
        self.assertEqual(position.average_price, Decimal("179.50"))

        restarted = Ledger(self.path)
        self.assertEqual(restarted.list_positions(), [position])

    def test_duplicate_order_id_is_idempotent(self):
        intent = buy_intent()
        self.ledger.create_order(intent)
        self.ledger.create_order(intent)
        self.assertEqual(
            self.ledger.get_order(intent.client_order_id).status,
            OrderStatus.CREATED,
        )

    def test_invalid_reverse_transition_is_rejected(self):
        intent = buy_intent()
        self.ledger.create_order(intent)
        self.ledger.transition_order(intent.client_order_id, OrderStatus.PREVIEWED)
        with self.assertRaisesRegex(ValueError, "invalid order transition"):
            self.ledger.transition_order(intent.client_order_id, OrderStatus.CREATED)


if __name__ == "__main__":
    unittest.main()
