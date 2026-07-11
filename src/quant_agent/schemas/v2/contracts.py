from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from quant_agent.schemas.v2.primitives import (
    AwareDateTime,
    InstrumentId,
    NonNegativeBps,
    PositiveQuantity,
    Price,
    Score,
    Weight,
)


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date

    @model_validator(mode="after")
    def validate_order(self) -> DateRange:
        if self.end < self.start:
            raise ValueError("date range end must not precede start")
        return self


class ResearchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    spec_id: UUID = Field(default_factory=uuid4)
    strategy_id: str = Field(min_length=1, max_length=100)
    data_snapshot_id: str = Field(min_length=1, max_length=200)
    universe: str = Field(min_length=1, max_length=100)
    benchmark: str | None = Field(default=None, max_length=100)
    feature_set: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=100)
    train: DateRange
    validation: DateRange
    test: DateRange
    random_seed: int = Field(ge=0, le=2**31 - 1)
    transaction_cost_bps: NonNegativeBps = Decimal("0")
    created_at: AwareDateTime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_time_splits(self) -> ResearchSpec:
        if self.train.end >= self.validation.start:
            raise ValueError("train range must end before validation range starts")
        if self.validation.end >= self.test.start:
            raise ValueError("validation range must end before test range starts")
        return self


class TargetPositionV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentId
    target_weight: Weight
    score: Score
    rank: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class TargetPortfolio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    run_id: str = Field(min_length=1, max_length=200)
    strategy_id: str = Field(min_length=1, max_length=100)
    trade_date: date
    generated_at: AwareDateTime
    universe: str = Field(min_length=1, max_length=100)
    benchmark: str | None = Field(default=None, max_length=100)
    positions: list[TargetPositionV2] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_positions(self) -> TargetPortfolio:
        instruments = [str(position.instrument) for position in self.positions]
        if len(instruments) != len(set(instruments)):
            raise ValueError("target portfolio contains duplicate instruments")
        ranks = [position.rank for position in self.positions]
        if len(ranks) != len(set(ranks)):
            raise ValueError("target portfolio contains duplicate ranks")
        total_weight = sum(
            (position.target_weight for position in self.positions),
            start=Decimal("0"),
        )
        if total_weight > Decimal("1"):
            raise ValueError("target portfolio total weight must not exceed 1")
        return self


class RiskDecisionType(str, Enum):
    APPROVE = "APPROVE"
    ADJUST = "ADJUST"
    REJECT = "REJECT"


class RuleOutcome(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    ADJUST = "ADJUST"
    REJECT = "REJECT"


class RiskRuleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=100)
    rule_version: str = Field(min_length=1, max_length=50)
    outcome: RuleOutcome
    reason_code: str = Field(min_length=1, max_length=100, pattern=r"^[A-Z0-9_]+$")
    message: str = Field(min_length=1, max_length=1000)
    instrument: InstrumentId | None = None
    original_value: str | None = None
    threshold: str | None = None
    adjusted_value: str | None = None


class ApprovedTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentId
    target_weight: Weight
    adjusted: bool = False
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]+$")


class RiskDecisionV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    run_id: str = Field(min_length=1, max_length=200)
    strategy_id: str = Field(min_length=1, max_length=100)
    policy_version: str = Field(min_length=1, max_length=100)
    decision: RiskDecisionType
    approved: bool
    decided_at: AwareDateTime
    positions: list[ApprovedTarget] = Field(default_factory=list)
    rule_results: list[RiskRuleResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision_consistency(self) -> RiskDecisionV2:
        outcomes = {result.outcome for result in self.rule_results}
        if self.decision == RiskDecisionType.REJECT:
            if self.approved or self.positions:
                raise ValueError("rejected decision cannot be approved or contain positions")
            if RuleOutcome.REJECT not in outcomes:
                raise ValueError("rejected decision requires at least one REJECT rule result")
            return self

        if not self.approved:
            raise ValueError("approved or adjusted decision must set approved=true")
        if RuleOutcome.REJECT in outcomes:
            raise ValueError("non-rejected decision cannot contain a REJECT rule result")

        if self.decision == RiskDecisionType.APPROVE:
            has_adjusted_positions = any(position.adjusted for position in self.positions)
            if RuleOutcome.ADJUST in outcomes or has_adjusted_positions:
                raise ValueError("approved decision cannot contain adjustments")
            return self

        if not self.positions:
            raise ValueError("adjusted decision requires approved positions")
        if RuleOutcome.ADJUST not in outcomes:
            raise ValueError("adjusted decision requires at least one ADJUST rule result")
        return self


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(str, Enum):
    DAY = "DAY"


class OrderIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    intent_id: UUID = Field(default_factory=uuid4)
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    run_id: str = Field(min_length=1, max_length=200)
    strategy_id: str = Field(min_length=1, max_length=100)
    account_id: str = Field(min_length=1, max_length=100)
    instrument: InstrumentId
    side: OrderSide
    order_type: OrderType
    quantity: PositiveQuantity
    lot_size: Literal[100] = 100
    limit_price: Price | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    approval_id: UUID | None = None
    created_at: AwareDateTime

    @model_validator(mode="after")
    def validate_order_semantics(self) -> OrderIntent:
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit order requires limit_price")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market order must not include limit_price")
        if self.side == OrderSide.BUY and self.quantity % self.lot_size != 0:
            raise ValueError("A-share buy quantity must be a multiple of lot_size")
        return self
