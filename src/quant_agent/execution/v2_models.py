from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_agent.schemas.v2 import InstrumentId
from quant_agent.schemas.v2.primitives import AwareDateTime, Price


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(str, Enum):
    DAY = "DAY"
    IOC = "IOC"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


class EventType(str, Enum):
    VALIDATE = "VALIDATE"
    SUBMIT = "SUBMIT"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILL = "FILL"
    REQUEST_CANCEL = "REQUEST_CANCEL"
    CANCEL = "CANCEL"
    REJECT = "REJECT"
    EXPIRE = "EXPIRE"
    ERROR = "ERROR"


class CurrentHolding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentId
    quantity: int = Field(ge=0)
    reference_price: Price


class ExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    account_id: str = Field(min_length=1, max_length=100)
    strategy_id: str = Field(min_length=1, max_length=100)
    risk_decision_id: str = Field(min_length=1, max_length=200)
    account_value: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    created_at: AwareDateTime
    holdings: list[CurrentHolding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_holdings(self) -> ExecutionContext:
        instruments = [str(item.instrument) for item in self.holdings]
        if len(instruments) != len(set(instruments)):
            raise ValueError("execution context contains duplicate holdings")
        return self


class ExecutionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    intent_id: UUID
    run_id: str = Field(min_length=1, max_length=200)
    risk_decision_id: str = Field(min_length=1, max_length=200)
    account_id: str = Field(min_length=1, max_length=100)
    strategy_id: str = Field(min_length=1, max_length=100)
    instrument: InstrumentId
    side: OrderSide
    quantity: int = Field(gt=0, multiple_of=100)
    order_type: OrderType
    limit_price: Price | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")
    created_at: AwareDateTime

    @model_validator(mode="after")
    def validate_price(self) -> ExecutionIntent:
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit order requires limit_price")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market order must not include limit_price")
        return self


class OrderEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID
    order_id: UUID
    event_type: EventType
    occurred_at: AwareDateTime
    fill_quantity: int = Field(default=0, ge=0)
    fill_price: Price | None = None
    reason_code: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[A-Z0-9_]+$",
    )
    message: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_fill(self) -> OrderEvent:
        fill_events = {EventType.PARTIAL_FILL, EventType.FILL}
        if self.event_type in fill_events:
            if self.fill_quantity <= 0 or self.fill_price is None:
                raise ValueError("fill event requires positive quantity and price")
        elif self.fill_quantity != 0 or self.fill_price is not None:
            raise ValueError("non-fill event must not include fill fields")
        return self


class FillRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fill_id: UUID
    event_id: UUID
    order_id: UUID
    instrument: InstrumentId
    side: OrderSide
    quantity: int = Field(gt=0)
    price: Price
    occurred_at: AwareDateTime


class OrderAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    intent: ExecutionIntent
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: int = Field(default=0, ge=0)
    average_fill_price: Price | None = None
    processed_event_ids: list[UUID] = Field(default_factory=list)
    fills: list[FillRecord] = Field(default_factory=list)
    last_event_at: AwareDateTime | None = None
    terminal_reason_code: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[A-Z0-9_]+$",
    )

    @model_validator(mode="after")
    def validate_aggregate(self) -> OrderAggregate:
        if self.filled_quantity > self.intent.quantity:
            raise ValueError("filled quantity exceeds order quantity")
        if self.filled_quantity == 0 and self.average_fill_price is not None:
            raise ValueError("unfilled order must not have average_fill_price")
        if self.filled_quantity > 0 and self.average_fill_price is None:
            raise ValueError("filled order requires average_fill_price")
        if len(self.processed_event_ids) != len(set(self.processed_event_ids)):
            raise ValueError("processed event IDs must be unique")
        return self


class ReconciliationSeverity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class ReconciliationDiscrepancy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentId | None = None
    severity: ReconciliationSeverity
    reason_code: str = Field(min_length=1, max_length=100, pattern=r"^[A-Z0-9_]+$")
    expected: str
    actual: str
    message: str = Field(min_length=1, max_length=1000)


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    checked_at: AwareDateTime
    discrepancies: list[ReconciliationDiscrepancy] = Field(default_factory=list)

    @property
    def halted(self) -> bool:
        return any(
            item.severity == ReconciliationSeverity.CRITICAL
            for item in self.discrepancies
        )
