from __future__ import annotations

from pydantic import BaseModel, Field


class RiskViolation(BaseModel):
    rule_id: str
    severity: str
    symbol: str | None = None
    message: str


class ApprovedPosition(BaseModel):
    symbol: str
    target_weight: float = Field(ge=0)
    adjusted: bool = False
    reason: str | None = None


class RiskDecision(BaseModel):
    run_id: str
    strategy_id: str
    approved: bool
    decision: str
    positions: list[ApprovedPosition]
    violations: list[RiskViolation] = Field(default_factory=list)
