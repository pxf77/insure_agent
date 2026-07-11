from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from quant_agent.execution.v2_models import EventType, ExecutionIntent, OrderEvent


class PaperScenario(str, Enum):
    FULL_FILL = "FULL_FILL"
    PARTIAL_FILL = "PARTIAL_FILL"
    NO_FILL = "NO_FILL"
    REJECT = "REJECT"
    DUPLICATE_FILL = "DUPLICATE_FILL"
    OUT_OF_ORDER_FILL = "OUT_OF_ORDER_FILL"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class PaperFillConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: PaperScenario = PaperScenario.FULL_FILL
    partial_ratio: Decimal = Field(default=Decimal("0.5"), gt=0, lt=1)
    price_multiplier: Decimal = Field(default=Decimal("1"), gt=0)


class DeterministicPaperGateway:
    """Generate deterministic exchange events without network or broker access."""

    def events(
        self,
        *,
        intent: ExecutionIntent,
        order_id: UUID,
        config: PaperFillConfig,
    ) -> list[OrderEvent]:
        start = intent.created_at + timedelta(milliseconds=10)
        if config.scenario == PaperScenario.REJECT:
            return [
                self._event(
                    order_id=order_id,
                    intent=intent,
                    sequence=1,
                    event_type=EventType.REJECT,
                    occurred_at=start,
                    reason_code="PAPER_REJECT",
                    message="deterministic paper rejection",
                )
            ]

        acknowledge = self._event(
            order_id=order_id,
            intent=intent,
            sequence=1,
            event_type=EventType.ACKNOWLEDGE,
            occurred_at=start,
        )
        if config.scenario == PaperScenario.NO_FILL:
            return [acknowledge]
        if config.scenario == PaperScenario.ERROR:
            return [
                acknowledge,
                self._event(
                    order_id=order_id,
                    intent=intent,
                    sequence=2,
                    event_type=EventType.ERROR,
                    occurred_at=start + timedelta(milliseconds=10),
                    reason_code="PAPER_GATEWAY_ERROR",
                    message="deterministic paper gateway error",
                ),
            ]
        if config.scenario == PaperScenario.CANCELLED:
            return [
                acknowledge,
                self._event(
                    order_id=order_id,
                    intent=intent,
                    sequence=2,
                    event_type=EventType.REQUEST_CANCEL,
                    occurred_at=start + timedelta(milliseconds=10),
                ),
                self._event(
                    order_id=order_id,
                    intent=intent,
                    sequence=3,
                    event_type=EventType.CANCEL,
                    occurred_at=start + timedelta(milliseconds=20),
                    reason_code="PAPER_CANCELLED",
                    message="deterministic paper cancellation",
                ),
            ]

        assert intent.limit_price is not None
        fill_price = intent.limit_price * config.price_multiplier
        if config.scenario == PaperScenario.PARTIAL_FILL:
            partial = int(
                (Decimal(intent.quantity) * config.partial_ratio).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
            partial = max(1, min(partial, intent.quantity - 1))
            return [
                acknowledge,
                self._event(
                    order_id=order_id,
                    intent=intent,
                    sequence=2,
                    event_type=EventType.PARTIAL_FILL,
                    occurred_at=start + timedelta(milliseconds=10),
                    fill_quantity=partial,
                    fill_price=fill_price,
                ),
            ]

        fill = self._event(
            order_id=order_id,
            intent=intent,
            sequence=2,
            event_type=EventType.FILL,
            occurred_at=start + timedelta(milliseconds=10),
            fill_quantity=intent.quantity,
            fill_price=fill_price,
        )
        if config.scenario == PaperScenario.DUPLICATE_FILL:
            return [acknowledge, fill, fill]
        if config.scenario == PaperScenario.OUT_OF_ORDER_FILL:
            early_fill = fill.model_copy(
                update={"occurred_at": start - timedelta(milliseconds=1)}
            )
            return [acknowledge, early_fill]
        return [acknowledge, fill]

    @staticmethod
    def _event(
        *,
        order_id: UUID,
        intent: ExecutionIntent,
        sequence: int,
        event_type: EventType,
        occurred_at,
        fill_quantity: int = 0,
        fill_price=None,
        reason_code: str | None = None,
        message: str | None = None,
    ) -> OrderEvent:
        event_id = uuid5(
            NAMESPACE_URL,
            f"paper-event:{order_id}:{sequence}:{event_type.value}",
        )
        return OrderEvent(
            event_id=event_id,
            order_id=order_id,
            event_type=event_type,
            occurred_at=occurred_at,
            fill_quantity=fill_quantity,
            fill_price=fill_price,
            reason_code=reason_code,
            message=message,
        )
