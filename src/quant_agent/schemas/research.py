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
    as_of: str | None = None
    data_version: str | None = None
    config_hash: str | None = None
    code_version: str | None = None
    input_checksums: dict[str, str] = Field(default_factory=dict)
    label_horizon_days: int | None = Field(default=None, ge=1)
    execution_lag_days: int | None = Field(default=None, ge=1)


class PredictionScore(BaseModel):
    trade_date: str
    symbol: str
    score: float
    rank: int = Field(ge=1)
    feature_cutoff: str


class PredictionsPayload(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    strategy_id: str
    engine: str
    data_version: str
    config_hash: str
    code_version: str
    label_horizon_days: int = Field(ge=1)
    execution_lag_days: int = Field(ge=1)
    predictions: list[PredictionScore]
