from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TargetPosition(BaseModel):
    symbol: str
    target_weight: float = Field(ge=0)
    score: float
    rank: int = Field(ge=1)
    reason: str | None = None


class TargetPositionRequest(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    strategy_id: str
    trade_date: str
    generated_at: str
    universe: str
    benchmark: str | None = None
    positions: list[TargetPosition]
    metadata: dict[str, Any] = Field(default_factory=dict)
