from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .domain import (
    Market,
    OrderIntent,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from .paper_broker import PaperBroker


_AUTO_FILL_EXECUTION_KEY = "auto-fill"
_AUTO_FILLABLE = frozenset(
    {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}
)


@dataclass(frozen=True)
class CycleResult:
    run_id: str
    exit_orders: list[OrderRecord]
    entry_orders: list[OrderRecord]
    event_order: list[str]


def _valid_quote(market: Market, quote: object) -> bool:
    if (
        not isinstance(quote, Decimal)
        or not quote.is_finite()
        or quote <= 0
    ):
        return False
    return market is not Market.KR or quote == quote.to_integral_value()


class TradingCycle:
    def __init__(
        self,
        broker: PaperBroker,
        quotes: dict[tuple[Market, str], Decimal],
    ):
        self.broker = broker
        self.quotes = quotes

    def _quote_for(self, market: Market, symbol: str) -> Decimal | None:
        quote = self.quotes.get((market, symbol))
        return quote if _valid_quote(market, quote) else None

    def _submit(
        self, intent: OrderIntent, quote: Decimal, auto_fill: bool
    ) -> OrderRecord | None:
        record = self.broker.submit_order_if_admissible(intent)
        if record is None:
            return None
        if auto_fill and record.status in _AUTO_FILLABLE:
            remaining = intent.quantity - record.filled_quantity
            record = self.broker.fill_order(
                intent.client_order_id,
                _AUTO_FILL_EXECUTION_KEY,
                remaining,
                quote,
            )
        return record

    def _exit_intent(
        self, run_id: str, position: Position, quote: Decimal, reason: str
    ) -> OrderIntent:
        client_order_id = (
            f"{run_id}:{position.market.value}:{position.symbol}:SELL"
        )
        try:
            persisted = self.broker.get_order(client_order_id).intent
        except KeyError:
            persisted = None
        if persisted is not None and (
            persisted.market,
            persisted.symbol,
            persisted.side,
        ) == (position.market, position.symbol, OrderSide.SELL):
            return persisted
        return OrderIntent(
            client_order_id=client_order_id,
            market=position.market,
            symbol=position.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=position.quantity,
            limit_price=quote,
            currency=position.currency,
            strategy_id=position.strategy_id,
            reason=reason,
        )

    def run(
        self,
        run_id: str,
        entry_intents: list[OrderIntent],
        *,
        auto_fill: bool = False,
    ) -> CycleResult:
        event_order = ["RECONCILE"]
        exit_intents: list[tuple[OrderIntent, Decimal]] = []

        for reconciled in self.broker.reconcile():
            quote = self._quote_for(reconciled.market, reconciled.symbol)
            if quote is None:
                continue
            position = self.broker.ledger.update_high_water(
                reconciled.market, reconciled.symbol, quote
            )
            stop_hit = quote <= position.average_price * Decimal("0.93")
            trail_armed = (
                position.high_since_entry
                >= position.average_price * Decimal("1.05")
            )
            trail_hit = quote <= position.high_since_entry * Decimal("0.92")
            if stop_hit or (trail_armed and trail_hit):
                reason = "stop" if stop_hit else "trailing_stop"
                exit_intents.append(
                    (self._exit_intent(run_id, position, quote, reason), quote)
                )

        exit_orders: list[OrderRecord] = []
        for intent, quote in exit_intents:
            record = self._submit(intent, quote, auto_fill)
            if record is not None:
                exit_orders.append(record)
        if exit_orders:
            event_order.append("EXIT")

        entry_orders: list[OrderRecord] = []
        for intent in entry_intents:
            if intent.side is not OrderSide.BUY:
                continue
            quote = self._quote_for(intent.market, intent.symbol)
            if quote is None:
                continue
            record = self._submit(intent, quote, auto_fill)
            if record is not None:
                entry_orders.append(record)

        if entry_orders:
            event_order.append("ENTRY")

        return CycleResult(
            run_id=run_id,
            exit_orders=exit_orders,
            entry_orders=entry_orders,
            event_order=event_order,
        )
