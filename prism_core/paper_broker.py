from __future__ import annotations

from decimal import Decimal

from .domain import Fill, Market, OrderIntent, OrderRecord, OrderStatus, Position
from .ledger import Ledger


_SUBMIT_PROGRESS = {
    OrderStatus.CREATED: OrderStatus.PREVIEWED,
    OrderStatus.PREVIEWED: OrderStatus.SUBMITTED,
    OrderStatus.SUBMITTED: OrderStatus.ACCEPTED,
}
_FILLABLE = frozenset(
    {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}
)
_CANCELABLE = {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}


def _fill_id(client_order_id: str, execution_key: str) -> str:
    if not isinstance(execution_key, str) or not execution_key.strip():
        raise ValueError("execution_key is required")
    return f"paper:{len(client_order_id)}:{client_order_id}:{execution_key}"


class PaperBroker:
    name = "paper"
    mode = "paper"

    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def preview_order(self, intent: OrderIntent) -> OrderIntent:
        return intent

    def submit_order(self, intent: OrderIntent) -> OrderRecord:
        record = self.ledger.create_order(intent)
        while record.status in _SUBMIT_PROGRESS:
            record = self.ledger.transition_order(
                intent.client_order_id, _SUBMIT_PROGRESS[record.status]
            )
        return record

    def submit_order_if_admissible(
        self, intent: OrderIntent
    ) -> OrderRecord | None:
        record = self.ledger.create_order_if_admissible(intent)
        if record is None:
            return None
        while record.status in _SUBMIT_PROGRESS:
            record = self.ledger.transition_order(
                intent.client_order_id, _SUBMIT_PROGRESS[record.status]
            )
        return record

    def fill_order(
        self,
        client_order_id: str,
        execution_key: str,
        quantity: Decimal,
        price: Decimal,
    ) -> OrderRecord:
        record = self.ledger.get_order(client_order_id)
        if not isinstance(quantity, Decimal) or not quantity.is_finite():
            raise ValueError("fill quantity must be a finite Decimal")
        if not isinstance(price, Decimal) or not price.is_finite():
            raise ValueError("fill price must be a finite Decimal")

        fill = Fill(
            fill_id=_fill_id(client_order_id, execution_key),
            client_order_id=client_order_id,
            market=record.intent.market,
            symbol=record.intent.symbol,
            side=record.intent.side,
            quantity=quantity,
            price=price,
            currency=record.intent.currency,
        )
        self.ledger.record_fill(fill, allowed_statuses=_FILLABLE)
        return self.ledger.get_order(client_order_id)

    def cancel_order(self, client_order_id: str) -> OrderRecord:
        record = self.ledger.get_order(client_order_id)
        if record.status not in _CANCELABLE:
            raise ValueError(
                f"order cannot be canceled from {record.status.value}"
            )
        return self.ledger.transition_order(
            client_order_id, OrderStatus.CANCELED
        )

    def mark_unknown(self, client_order_id: str) -> OrderRecord:
        return self.ledger.transition_order(
            client_order_id, OrderStatus.UNKNOWN
        )

    def get_positions(self) -> list[Position]:
        return self.ledger.list_positions()

    def get_order(self, client_order_id: str) -> OrderRecord:
        return self.ledger.get_order(client_order_id)

    def has_unresolved_order(self, market: Market, symbol: str) -> bool:
        return self.ledger.has_unresolved_order(market, symbol)

    def reconcile(self) -> list[Position]:
        return self.ledger.list_positions()
