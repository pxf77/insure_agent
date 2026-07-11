from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from quant_agent.execution.v2_models import (
    EventType,
    FillRecord,
    OrderAggregate,
    OrderEvent,
    OrderStatus,
)


class InvalidOrderTransition(ValueError):
    pass


class OutOfOrderOrderEvent(ValueError):
    pass


_TERMINAL = {
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
    OrderStatus.ERROR,
}

_ALLOWED: dict[EventType, set[OrderStatus]] = {
    EventType.VALIDATE: {OrderStatus.CREATED},
    EventType.SUBMIT: {OrderStatus.VALIDATED},
    EventType.ACKNOWLEDGE: {OrderStatus.SUBMITTED},
    EventType.PARTIAL_FILL: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.CANCEL_PENDING,
    },
    EventType.FILL: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.CANCEL_PENDING,
    },
    EventType.REQUEST_CANCEL: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
    },
    EventType.CANCEL: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.CANCEL_PENDING,
    },
    EventType.REJECT: {
        OrderStatus.CREATED,
        OrderStatus.VALIDATED,
        OrderStatus.SUBMITTED,
    },
    EventType.EXPIRE: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.CANCEL_PENDING,
    },
    EventType.ERROR: set(OrderStatus) - _TERMINAL,
}


class OrderStateMachine:
    """Pure deterministic transition function with duplicate-event idempotency."""

    def apply(self, aggregate: OrderAggregate, event: OrderEvent) -> OrderAggregate:
        if event.order_id != aggregate.order_id:
            raise InvalidOrderTransition("event order_id does not match aggregate")
        if event.event_id in aggregate.processed_event_ids:
            return aggregate
        if aggregate.status in _TERMINAL:
            raise InvalidOrderTransition(
                f"terminal order {aggregate.status.value} cannot accept new events"
            )
        if aggregate.last_event_at is not None and event.occurred_at < aggregate.last_event_at:
            raise OutOfOrderOrderEvent("event occurred before the aggregate last_event_at")
        if aggregate.status not in _ALLOWED[event.event_type]:
            raise InvalidOrderTransition(
                f"event {event.event_type.value} is invalid from {aggregate.status.value}"
            )

        status = self._next_status(aggregate, event)
        filled_quantity = aggregate.filled_quantity
        average_price = aggregate.average_fill_price
        fills = list(aggregate.fills)
        if event.event_type in {EventType.PARTIAL_FILL, EventType.FILL}:
            next_filled = filled_quantity + event.fill_quantity
            if next_filled > aggregate.intent.quantity:
                raise InvalidOrderTransition("fill exceeds remaining order quantity")
            if event.event_type == EventType.FILL and next_filled != aggregate.intent.quantity:
                raise InvalidOrderTransition("FILL event must complete the order quantity")
            assert event.fill_price is not None
            previous_notional = (
                Decimal(filled_quantity) * average_price
                if average_price is not None
                else Decimal("0")
            )
            next_notional = previous_notional + Decimal(event.fill_quantity) * event.fill_price
            filled_quantity = next_filled
            average_price = next_notional / Decimal(filled_quantity)
            fill_id = uuid5(NAMESPACE_URL, f"fill:{event.order_id}:{event.event_id}")
            fills.append(
                FillRecord(
                    fill_id=fill_id,
                    event_id=event.event_id,
                    order_id=event.order_id,
                    instrument=aggregate.intent.instrument,
                    side=aggregate.intent.side,
                    quantity=event.fill_quantity,
                    price=event.fill_price,
                    occurred_at=event.occurred_at,
                )
            )
            status = (
                OrderStatus.FILLED
                if filled_quantity == aggregate.intent.quantity
                else OrderStatus.PARTIALLY_FILLED
            )

        terminal_reason = aggregate.terminal_reason_code
        if status in {
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.ERROR,
        }:
            terminal_reason = event.reason_code or status.value
        return aggregate.model_copy(
            update={
                "status": status,
                "filled_quantity": filled_quantity,
                "average_fill_price": average_price,
                "fills": fills,
                "processed_event_ids": [*aggregate.processed_event_ids, event.event_id],
                "last_event_at": event.occurred_at,
                "terminal_reason_code": terminal_reason,
            }
        )

    @staticmethod
    def _next_status(aggregate: OrderAggregate, event: OrderEvent) -> OrderStatus:
        mapping = {
            EventType.VALIDATE: OrderStatus.VALIDATED,
            EventType.SUBMIT: OrderStatus.SUBMITTED,
            EventType.ACKNOWLEDGE: OrderStatus.ACKNOWLEDGED,
            EventType.REQUEST_CANCEL: OrderStatus.CANCEL_PENDING,
            EventType.CANCEL: OrderStatus.CANCELLED,
            EventType.REJECT: OrderStatus.REJECTED,
            EventType.EXPIRE: OrderStatus.EXPIRED,
            EventType.ERROR: OrderStatus.ERROR,
        }
        return mapping.get(event.event_type, aggregate.status)
