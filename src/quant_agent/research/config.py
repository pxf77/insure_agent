from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class TemporalSplitConfig(BaseModel):
    train_start: date
    train_end: date
    valid_start: date
    valid_end: date
    test_start: date
    test_end: date

    @model_validator(mode="after")
    def validate_chronology(self) -> TemporalSplitConfig:
        values = (
            self.train_start,
            self.train_end,
            self.valid_start,
            self.valid_end,
            self.test_start,
            self.test_end,
        )
        if list(values) != sorted(values) or len(set(values)) != len(values):
            raise ValueError("temporal split dates must be strictly chronological")
        return self


class TemporalWindowConfig(BaseModel):
    train_days: int = Field(default=756, ge=1)
    valid_days: int = Field(default=252, ge=1)
    test_days: int = Field(default=252, ge=1)

    def resolve(self, trade_date: date) -> TemporalSplitConfig:
        test_end = trade_date
        test_start = test_end - timedelta(days=self.test_days - 1)
        valid_end = test_start - timedelta(days=1)
        valid_start = valid_end - timedelta(days=self.valid_days - 1)
        train_end = valid_start - timedelta(days=1)
        train_start = train_end - timedelta(days=self.train_days - 1)
        return TemporalSplitConfig(
            train_start=train_start,
            train_end=train_end,
            valid_start=valid_start,
            valid_end=valid_end,
            test_start=test_start,
            test_end=test_end,
        )


class ResearchDefinition(BaseModel):
    engine: Literal["deterministic_momentum", "qlib"]
    strategy_id: str
    universe: str = "CSI300"
    benchmark: str | None = "SH000300"
    label_horizon_days: int = Field(default=5, ge=1)
    execution_lag_days: int = Field(default=1, ge=1)
    rebalance_frequency: Literal["daily", "weekly"] = "weekly"


class PortfolioDefinition(BaseModel):
    topk: int = Field(default=10, ge=1)
    lookback_days: int = Field(default=20, ge=1)
    max_position_weight: float = Field(default=0.1, gt=0, le=1)


class CostDefinition(BaseModel):
    commission_bps: float = Field(default=3.0, ge=0)
    sell_stamp_duty_bps: float = Field(default=5.0, ge=0)
    transfer_fee_bps: float = Field(default=0.1, ge=0)
    slippage_bps: float = Field(default=10.0, ge=0)

    @property
    def conservative_round_trip_rate(self) -> float:
        total_bps = (
            (2 * self.commission_bps)
            + self.sell_stamp_duty_bps
            + (2 * self.transfer_fee_bps)
            + (2 * self.slippage_bps)
        )
        return total_bps / 10_000


class QlibDefinition(BaseModel):
    provider_uri: str | None = None
    region: str = "cn"
    experiment_name: str = "quant-agent-daily"
    task: dict[str, Any] = Field(default_factory=dict)
    port_analysis_config: dict[str, Any] | None = None


class StrictResearchConfig(BaseModel):
    research: ResearchDefinition
    temporal: TemporalSplitConfig
    portfolio: PortfolioDefinition = Field(default_factory=PortfolioDefinition)
    costs: CostDefinition = Field(default_factory=CostDefinition)
    qlib: QlibDefinition = Field(default_factory=QlibDefinition)

    @classmethod
    def from_yaml_text(
        cls,
        text: str,
        *,
        trade_date: date | None = None,
    ) -> StrictResearchConfig:
        data = yaml.safe_load(text) or {}
        if "temporal" not in data and "temporal_window" in data:
            if trade_date is None:
                raise ValueError("trade_date is required to resolve temporal_window")
            window = TemporalWindowConfig.model_validate(data.pop("temporal_window"))
            data["temporal"] = window.resolve(trade_date).model_dump(mode="json")
        return cls.model_validate(data)
