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
    PositionFillConflict,
)
from .paper_broker import PaperBroker


_AUTO_FILL_EXECUTION_KEY = "auto-fill"
_AUTO_FILLABLE = frozenset(
    {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}
)
_CANCELABLE = frozenset(
    {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}
)
_SUBMITTING = frozenset(
    {OrderStatus.CREATED, OrderStatus.PREVIEWED, OrderStatus.SUBMITTED}
)


@dataclass(frozen=True)
class CycleBlock:
    market: Market | None
    symbol: str | None
    reason: str


@dataclass(frozen=True)
class CycleResult:
    run_id: str
    exit_orders: list[OrderRecord]
    entry_orders: list[OrderRecord]
    event_order: list[str]
    blocked: list[CycleBlock]


@dataclass(frozen=True)
class _ExitDecision:
    market: Market
    symbol: str
    quote: Decimal
    reason: str


def _valid_quote(market: Market, quote: object) -> bool:
    if (
        not isinstance(quote, Decimal)
        or not quote.is_finite()
        or quote <= 0
    ):
        return False
    return market is not Market.KR or quote == quote.to_integral_value()


def _marketable(record: OrderRecord, quote: Decimal) -> bool:
    intent = record.intent
    if intent.order_type is OrderType.MARKET:
        return True
    if intent.side is OrderSide.BUY:
        return quote <= intent.limit_price
    return quote >= intent.limit_price


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

    def _maybe_auto_fill(
        self, record: OrderRecord, quote: Decimal, auto_fill: bool
    ) -> OrderRecord:
        if (
            not auto_fill
            or record.status not in _AUTO_FILLABLE
            or not _marketable(record, quote)
        ):
            return record
        remaining = record.intent.quantity - record.filled_quantity
        return self.broker.fill_order(
            record.intent.client_order_id,
            _AUTO_FILL_EXECUTION_KEY,
            remaining,
            quote,
        )

    def _submit_entry(
        self, intent: OrderIntent, quote: Decimal, auto_fill: bool
    ) -> OrderRecord | None:
        record = self.broker.submit_order_if_admissible(intent)
        if record is None:
            return None
        return self._maybe_auto_fill(record, quote, auto_fill)

    def _clear_unresolved_buys(
        self, market: Market, symbol: str
    ) -> str | None:
        unresolved = self.broker.list_unresolved_orders(market, symbol)
        for observed in unresolved:
            if observed.intent.side is not OrderSide.BUY:
                continue
            if observed.status is OrderStatus.UNKNOWN:
                return "unknown_buy_order"
            record = observed
            if record.status in _SUBMITTING:
                record = self.broker.submit_order(record.intent)
            if record.status in _CANCELABLE:
                try:
                    self.broker.cancel_order(record.intent.client_order_id)
                except ValueError:
                    current = self.broker.get_order(
                        record.intent.client_order_id
                    )
                    if current.status is OrderStatus.UNKNOWN:
                        return "unknown_buy_order"
                    if current.status in _SUBMITTING | _CANCELABLE:
                        return "unreconcilable_buy_order"

        remaining = [
            order
            for order in self.broker.list_unresolved_orders(market, symbol)
            if order.intent.side is OrderSide.BUY
        ]
        if any(order.status is OrderStatus.UNKNOWN for order in remaining):
            return "unknown_buy_order"
        if remaining:
            return "unreconcilable_buy_order"
        return None

    def _liquidate(
        self,
        run_id: str,
        market: Market,
        symbol: str,
        quote: Decimal,
        reason: str,
        auto_fill: bool,
    ) -> tuple[list[OrderRecord], str | None]:
        records: list[OrderRecord] = []
        seen_ids: set[str] = set()
        while True:
            record, blocked_reason = self.broker.submit_exit_order(
                run_id, market, symbol, reason
            )
            if blocked_reason is not None:
                return records, blocked_reason
            if record is None:
                return records, None
            if record.intent.client_order_id in seen_ids:
                return records, "unreconcilable_exit_order"
            seen_ids.add(record.intent.client_order_id)

            try:
                record = self._maybe_auto_fill(record, quote, auto_fill)
            except PositionFillConflict:
                current = self.broker.get_order(
                    record.intent.client_order_id
                )
                if current.status in _CANCELABLE:
                    self.broker.cancel_order(current.intent.client_order_id)
                target_exists = any(
                    position.market is market and position.symbol == symbol
                    for position in self.broker.get_positions()
                )
                if not target_exists:
                    return records, None
                continue

            records.append(record)
            if not auto_fill or record.status is not OrderStatus.FILLED:
                return records, None
            if not any(
                position.market is market and position.symbol == symbol
                for position in self.broker.get_positions()
            ):
                return records, None

    def _run_locked(
        self,
        run_id: str,
        entry_intents: list[OrderIntent],
        auto_fill: bool,
    ) -> CycleResult:
        event_order = ["RECONCILE"]
        blocked: list[CycleBlock] = []
        initial_positions = self.broker.reconcile()
        excluded = {
            (position.market, position.symbol)
            for position in initial_positions
        }
        exit_orders: list[OrderRecord] = []
        exit_decisions: list[_ExitDecision] = []

        # Phase 1: persist every valid high-water before any exit can fail.
        for reconciled in initial_positions:
            key = (reconciled.market, reconciled.symbol)
            quote = self._quote_for(*key)
            if quote is None:
                continue
            try:
                position = self.broker.update_high_water(*key, quote)
            except KeyError:
                continue

            unresolved = self.broker.list_unresolved_orders(*key)
            pending_exit = any(
                order.intent.side is OrderSide.SELL
                for order in unresolved
            )
            stop_hit = quote <= position.average_price * Decimal("0.93")
            trail_armed = (
                position.high_since_entry
                >= position.average_price * Decimal("1.05")
            )
            trail_hit = quote <= position.high_since_entry * Decimal("0.92")
            if not (pending_exit or stop_hit or (trail_armed and trail_hit)):
                continue

            reason = "resume_exit"
            if stop_hit:
                reason = "stop"
            elif trail_armed and trail_hit:
                reason = "trailing_stop"

            exit_decisions.append(_ExitDecision(*key, quote, reason))

        # Phase 2: perform cancellation and liquidation writes only after the
        # portfolio-wide high-water pass is complete.
        for decision in exit_decisions:
            key = (decision.market, decision.symbol)
            blocked_reason = self._clear_unresolved_buys(*key)
            if blocked_reason is not None:
                blocked.append(CycleBlock(*key, blocked_reason))
                continue

            records, blocked_reason = self._liquidate(
                run_id,
                *key,
                decision.quote,
                decision.reason,
                auto_fill,
            )
            exit_orders.extend(records)
            if blocked_reason is not None:
                blocked.append(CycleBlock(*key, blocked_reason))

        if exit_orders:
            event_order.append("EXIT")
        if blocked:
            event_order.append("BLOCKED")

        entry_orders: list[OrderRecord] = []
        for intent in entry_intents:
            key = (intent.market, intent.symbol)
            if intent.side is not OrderSide.BUY or key in excluded:
                continue
            quote = self._quote_for(*key)
            if quote is None:
                continue
            record = self._submit_entry(intent, quote, auto_fill)
            if record is not None:
                entry_orders.append(record)

        if entry_orders:
            event_order.append("ENTRY")

        return CycleResult(
            run_id=run_id,
            exit_orders=exit_orders,
            entry_orders=entry_orders,
            event_order=event_order,
            blocked=blocked,
        )

    def run(
        self,
        run_id: str,
        entry_intents: list[OrderIntent],
        *,
        auto_fill: bool = False,
    ) -> CycleResult:
        with self.broker.cycle_fence() as acquired:
            if not acquired:
                return CycleResult(
                    run_id=run_id,
                    exit_orders=[],
                    entry_orders=[],
                    event_order=["BLOCKED"],
                    blocked=[CycleBlock(None, None, "cycle_overlap")],
                )
            return self._run_locked(run_id, entry_intents, auto_fill)
