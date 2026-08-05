from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PortfolioPosition(BaseModel):
    symbol: str
    total_volume: int = Field(ge=0)
    available_volume: int = Field(ge=0)
    average_cost: float = Field(ge=0)
    market_price: float = Field(gt=0)
    market_value: float = Field(ge=0)


class PortfolioSnapshot(BaseModel):
    schema_version: str = "1.0"
    run_id: str | None = None
    account_id: str
    trade_date: str
    as_of: str | None = None
    data_version: str | None = None
    config_hash: str | None = None
    code_version: str | None = None
    input_checksums: dict[str, str] = Field(default_factory=dict)
    cash: float = Field(ge=0)
    market_value: float = Field(ge=0)
    total_equity: float = Field(ge=0)
    positions: list[PortfolioPosition] = Field(default_factory=list)


class SkippedOrder(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"] | None = None
    reason: str
    requested_volume: int = Field(default=0, ge=0)


class PlannedOrder(BaseModel):
    client_order_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    price: float = Field(gt=0)
    volume: int = Field(gt=0)
    estimated_value: float = Field(ge=0)
    estimated_fee: float = Field(ge=0)
    reason: str = "target_delta"


class OrderPlan(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    strategy_id: str
    trade_date: str
    generated_at: str
    account_id: str
    data_version: str
    config_hash: str
    code_version: str
    as_of: str | None = None
    input_checksums: dict[str, str] = Field(default_factory=dict)
    account: PortfolioSnapshot
    target_weights: dict[str, float]
    orders: list[PlannedOrder]
    skipped: list[SkippedOrder] = Field(default_factory=list)
    estimated_turnover: float = Field(ge=0)
    estimated_fees: float = Field(ge=0)
    plan_checksum: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalRecord(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    trade_date: str | None = None
    as_of: str | None = None
    data_version: str | None = None
    config_hash: str | None = None
    code_version: str | None = None
    input_checksums: dict[str, str] = Field(default_factory=dict)
    plan_checksum: str
    approver: str
    granted_at: str
    expires_at: str


class ExecutionOutcome(BaseModel):
    client_order_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    requested_volume: int = Field(gt=0)
    filled_volume: int = Field(ge=0)
    price: float = Field(gt=0)
    fee: float = Field(ge=0)
    status: Literal["FILLED", "UNFILLED", "DUPLICATE"]
    reason: str | None = None
    trade_id: str | None = None


class NavSnapshot(BaseModel):
    account_id: str
    trade_date: str
    cash: float = Field(ge=0)
    market_value: float = Field(ge=0)
    total_equity: float = Field(ge=0)
    daily_return: float
    drawdown: float = Field(le=0)


class ExecutionResult(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    strategy_id: str
    trade_date: str
    as_of: str | None = None
    data_version: str | None = None
    config_hash: str | None = None
    code_version: str | None = None
    input_checksums: dict[str, str] = Field(default_factory=dict)
    plan_checksum: str
    executed_at: str
    outcomes: list[ExecutionOutcome]
    nav: NavSnapshot
    metadata: dict[str, Any] = Field(default_factory=dict)
