from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

WatchlistStatus = Literal["active", "blocked"]
SignalStatus = Literal["risk_passed", "risk_blocked", "accepted", "rejected", "ignored"]
ManualDecision = Literal["accepted", "rejected", "ignored"]


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not symbol:
        msg = "symbol must not be empty"
        raise ValueError(msg)
    return symbol


class WatchlistCreate(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None
    note: str | None = None
    status: WatchlistStatus = "active"

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return normalize_symbol(value)


class WatchlistUpdate(BaseModel):
    name: str | None = None
    sector: str | None = None
    note: str | None = None
    status: WatchlistStatus | None = None


class WatchlistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str | None
    sector: str | None
    note: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class SignalCandidate(BaseModel):
    symbol: str
    action: Literal["buy", "sell", "hold"]
    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    risk_level: Literal["low", "medium", "high"]
    price_range: tuple[float, float] | None
    stop_loss: float | None
    take_profit: float | None
    max_position_pct: float = Field(gt=0)
    reasons: list[str]
    risks: list[str]
    manual_checklist: list[str]

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return normalize_symbol(value)


class AccountState(BaseModel):
    total_position_pct: float = 0.0
    daily_loss_pct: float = 0.0


class MarketState(BaseModel):
    symbol: str
    last_price: float
    turnover_cny: float
    is_st: bool = False
    is_limit_up: bool = False


class RiskConfig(BaseModel):
    min_signal_score: int = 70
    max_single_position_pct: float = 5.0
    max_total_position_pct: float = 50.0
    max_daily_loss_pct: float = 2.0
    min_reward_risk_ratio: float = 1.5
    block_st: bool = True
    min_turnover_cny: float = 100_000_000
    block_limit_up_buy: bool = True


class RiskCheckResult(BaseModel):
    passed: bool
    blocked_reason: str | None = None


class SignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    action: str
    score: int
    confidence: float
    risk_level: str
    price_low: float | None
    price_high: float | None
    stop_loss: float | None
    take_profit: float | None
    max_position_pct: float
    status: str
    reasons_text: str
    risks_text: str
    manual_checklist_text: str
    generated_at: datetime


class ScanRequest(BaseModel):
    account: AccountState = Field(default_factory=AccountState)


class SignalScanResult(BaseModel):
    symbol: str
    signal_id: int | None = None
    risk_passed: bool = False
    blocked_reason: str | None = None
    error: str | None = None


class ScanResponse(BaseModel):
    results: list[SignalScanResult]


class ManualReviewCreate(BaseModel):
    decision: ManualDecision
    note: str | None = None


class ManualReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_id: int
    decision: str
    note: str | None
    created_at: datetime


class DailyReviewResponse(BaseModel):
    date: str
    total_signals: int
    risk_passed: int
    risk_blocked: int
    accepted: int
    rejected: int
    ignored: int
    summary: str
