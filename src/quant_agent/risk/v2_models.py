from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_agent.schemas.v2 import InstrumentId
from quant_agent.schemas.v2.primitives import AwareDateTime, Price, Weight


class KillSwitchScope(str, Enum):
    GLOBAL = "GLOBAL"
    ACCOUNT = "ACCOUNT"
    STRATEGY = "STRATEGY"


class KillSwitchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    switch_id: str = Field(min_length=1, max_length=200)
    scope: KillSwitchScope
    scope_id: str | None = Field(default=None, max_length=200)
    active: bool = True
    reduce_only: bool = False
    reason_code: str = Field(min_length=1, max_length=100, pattern=r"^[A-Z0-9_]+$")
    message: str = Field(min_length=1, max_length=1000)
    changed_at: AwareDateTime
    changed_by: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_scope_id(self) -> KillSwitchRecord:
        if self.scope == KillSwitchScope.GLOBAL and self.scope_id is not None:
            raise ValueError("global kill switch must not include scope_id")
        if self.scope != KillSwitchScope.GLOBAL and not self.scope_id:
            raise ValueError("account and strategy kill switches require scope_id")
        return self


class ApprovalEvidence(BaseModel):
    """Immutable manual approval bound to one risk decision context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    approval_id: UUID
    status: Literal["APPROVED"] = "APPROVED"
    account_id: str = Field(min_length=1, max_length=100)
    strategy_id: str = Field(min_length=1, max_length=100)
    target_run_id: str = Field(min_length=1, max_length=200)
    policy_version: str = Field(min_length=1, max_length=100)
    approved_at: AwareDateTime
    expires_at: AwareDateTime
    approvers: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_approval(self) -> ApprovalEvidence:
        if self.expires_at <= self.approved_at:
            raise ValueError("approval expires_at must be after approved_at")
        if len(self.approvers) != len(set(self.approvers)):
            raise ValueError("approval approvers must be unique")
        return self


class CurrentPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentId
    current_weight: Weight
    sellable_weight: Weight
    industry: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_sellable(self) -> CurrentPosition:
        if self.sellable_weight > self.current_weight:
            raise ValueError("sellable_weight must not exceed current_weight")
        return self


class InstrumentRiskState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentId
    industry: str = Field(min_length=1, max_length=100)
    last_price: Price
    suspended: bool = False
    is_st: bool = False
    limit_up: bool = False
    limit_down: bool = False
    max_liquidity_weight: Weight = Decimal("1")


class RiskContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    account_id: str = Field(min_length=1, max_length=100)
    strategy_id: str = Field(min_length=1, max_length=100)
    evaluated_at: AwareDateTime
    snapshot_as_of: AwareDateTime
    account_value: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    cash: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    daily_loss: Decimal = Field(ge=0, le=1, max_digits=12, decimal_places=10)
    drawdown: Decimal = Field(ge=0, le=1, max_digits=12, decimal_places=10)
    approval: ApprovalEvidence | None = None
    # Retained for schema compatibility only. A bare ID is not trusted evidence.
    approval_id: UUID | None = None
    current_positions: list[CurrentPosition] = Field(default_factory=list)
    instruments: list[InstrumentRiskState]

    @model_validator(mode="after")
    def validate_unique_instruments(self) -> RiskContext:
        if (
            self.approval is not None
            and self.approval_id is not None
            and self.approval.approval_id != self.approval_id
        ):
            raise ValueError("approval and approval_id must reference the same approval")
        position_ids = [str(item.instrument) for item in self.current_positions]
        if len(position_ids) != len(set(position_ids)):
            raise ValueError("risk context contains duplicate current positions")
        market_ids = [str(item.instrument) for item in self.instruments]
        if len(market_ids) != len(set(market_ids)):
            raise ValueError("risk context contains duplicate instrument states")
        if self.cash > self.account_value:
            raise ValueError("cash must not exceed account_value")
        return self


class RiskPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    policy_version: str = Field(min_length=1, max_length=100)
    max_data_age_minutes: int = Field(ge=0, le=7 * 24 * 60)
    max_single_weight: Weight
    max_total_weight: Weight
    max_industry_weight: Weight
    minimum_cash_weight: Weight
    max_daily_loss: Decimal = Field(ge=0, le=1, max_digits=12, decimal_places=10)
    max_drawdown: Decimal = Field(ge=0, le=1, max_digits=12, decimal_places=10)
    allow_st: bool = False
    require_approval: bool = True

    @model_validator(mode="after")
    def validate_limits(self) -> RiskPolicy:
        if self.max_single_weight > self.max_total_weight:
            raise ValueError("max_single_weight must not exceed max_total_weight")
        if self.max_industry_weight > self.max_total_weight:
            raise ValueError("max_industry_weight must not exceed max_total_weight")
        if self.max_total_weight + self.minimum_cash_weight > Decimal("1"):
            raise ValueError("max_total_weight plus minimum_cash_weight must not exceed 1")
        return self
