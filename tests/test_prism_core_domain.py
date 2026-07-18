from decimal import Decimal
import unittest

from prism_core.domain import (
    Market, OrderIntent, OrderSide, OrderStatus, OrderType,
    validate_transition,
)


class PrismCoreDomainTest(unittest.TestCase):
    def test_us_order_requires_usd_and_keeps_decimal_price(self):
        order = OrderIntent(
            client_order_id="cycle-1:AAPL:BUY",
            market=Market.US,
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.5"),
            limit_price=Decimal("181.25"),
            currency="USD",
        )
        self.assertEqual(order.limit_price, Decimal("181.25"))

    def test_us_order_rejects_krw_currency(self):
        with self.assertRaisesRegex(ValueError, "US order currency must be USD"):
            OrderIntent(
                client_order_id="bad",
                market=Market.US,
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                limit_price=Decimal("180"),
                currency="KRW",
            )

    def test_kr_full_share_order_rejects_fractional_quantity(self):
        with self.assertRaisesRegex(ValueError, "KR quantity must be a whole number"):
            OrderIntent(
                client_order_id="bad-kr",
                market=Market.KR,
                symbol="005930",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1.5"),
                limit_price=Decimal("70000"),
                currency="KRW",
            )

    def test_unknown_can_only_move_to_reconciled_terminal_state(self):
        self.assertTrue(validate_transition(OrderStatus.UNKNOWN, OrderStatus.FILLED))
        self.assertTrue(validate_transition(OrderStatus.UNKNOWN, OrderStatus.REJECTED))
        self.assertFalse(validate_transition(OrderStatus.UNKNOWN, OrderStatus.SUBMITTED))


if __name__ == "__main__":
    unittest.main()
