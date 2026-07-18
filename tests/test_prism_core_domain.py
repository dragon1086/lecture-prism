from decimal import Decimal
import unittest

from prism_core.domain import (
    Market, OrderIntent, OrderSide, OrderStatus, OrderType,
    validate_transition,
)


class PrismCoreDomainTest(unittest.TestCase):
    def test_validate_transition_is_available_from_package(self):
        from prism_core import validate_transition as package_validate_transition

        self.assertIs(package_validate_transition, validate_transition)

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

    def test_runtime_market_string_cannot_bypass_currency_validation(self):
        with self.assertRaisesRegex(ValueError, "market must be a Market"):
            OrderIntent(
                client_order_id="bad-runtime-market",
                market="US",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                limit_price=Decimal("180"),
                currency="KRW",
            )

    def test_none_market_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "market must be a Market"):
            OrderIntent(
                client_order_id="bad-none-market",
                market=None,
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                limit_price=Decimal("180"),
                currency="USD",
            )

    def test_runtime_side_string_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "side must be an OrderSide"):
            OrderIntent(
                client_order_id="bad-runtime-side",
                market=Market.US,
                symbol="AAPL",
                side="BUY",
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                limit_price=Decimal("180"),
                currency="USD",
            )

    def test_runtime_order_type_string_cannot_bypass_limit_price_validation(self):
        with self.assertRaisesRegex(ValueError, "order_type must be an OrderType"):
            OrderIntent(
                client_order_id="bad-runtime-type",
                market=Market.US,
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type="LIMIT",
                quantity=Decimal("1"),
                limit_price=None,
                currency="USD",
            )

    def test_quantity_requires_a_finite_decimal(self):
        for quantity in (1.0, Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(quantity=quantity):
                with self.assertRaisesRegex(ValueError, "quantity must be a finite Decimal"):
                    OrderIntent(
                        client_order_id="bad-quantity",
                        market=Market.US,
                        symbol="AAPL",
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=quantity,
                        limit_price=Decimal("180"),
                        currency="USD",
                    )

    def test_non_none_limit_price_requires_a_finite_decimal(self):
        for limit_price in (180.0, Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(limit_price=limit_price):
                with self.assertRaisesRegex(ValueError, "limit_price must be a finite Decimal"):
                    OrderIntent(
                        client_order_id="bad-limit-price",
                        market=Market.US,
                        symbol="AAPL",
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=Decimal("1"),
                        limit_price=limit_price,
                        currency="USD",
                    )

    def test_unknown_reconciles_only_to_explicit_observed_states(self):
        allowed = {
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.REJECTED,
            OrderStatus.CANCELED,
        }
        disallowed = {
            OrderStatus.CREATED,
            OrderStatus.PREVIEWED,
            OrderStatus.SUBMITTED,
        }

        for target in allowed:
            with self.subTest(target=target):
                self.assertTrue(validate_transition(OrderStatus.UNKNOWN, target))
        for target in disallowed:
            with self.subTest(target=target):
                self.assertFalse(validate_transition(OrderStatus.UNKNOWN, target))


if __name__ == "__main__":
    unittest.main()
