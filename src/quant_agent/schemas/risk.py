from __future__ import annotations

from pydantic import BaseModel, Field

from quant_agent.schemas.portfolio import OrderPlan


class RiskViolation(BaseModel):
    rule_id: str
    severity: str
    symbol: str | None = None
    message: str


class RiskRuleResult(BaseModel):
    rule_id: str
    passed: bool
    severity: str
    message: str
    symbol: str | None = None
    observed: float | str | bool | None = None
    limit: float | str | bool | None = None


class ApprovedPosition(BaseModel):
    symbol: str
    target_weight: float = Field(ge=0)
    adjusted: bool = False
    reason: str | None = None


class RiskDecision(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    strategy_id: str
    approved: bool
    decision: str
    positions: list[ApprovedPosition]
    violations: list[RiskViolation] = Field(default_factory=list)
    trade_date: str | None = None
    plan_checksum: str | None = None
    rule_results: list[RiskRuleResult] = Field(default_factory=list)
    metadata: dict[str, str | float | bool | None] = Field(default_factory=dict)


class PlanRiskAssessment(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    approved: bool
    decision: str
    original_plan_checksum: str
    plan_checksum: str | None = None
    adjusted_plan: OrderPlan | None = None
    rule_results: list[RiskRuleResult] = Field(default_factory=list)
    violations: list[RiskViolation] = Field(default_factory=list)
