from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class Watchlist(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    name: str | None = None
    sector: str | None = None
    note: str | None = None
    status: str = Field(default="active", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Signal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    action: str
    score: int
    confidence: float
    risk_level: str
    price_low: float | None = None
    price_high: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    max_position_pct: float
    status: str = Field(default="pending_review", index=True)
    reasons_text: str
    risks_text: str
    manual_checklist_text: str
    generated_at: datetime = Field(default_factory=utc_now, index=True)


class RiskCheck(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    signal_id: int = Field(foreign_key="signal.id", index=True)
    passed: bool = Field(index=True)
    blocked_reason: str | None = None
    checked_at: datetime = Field(default_factory=utc_now, index=True)


class ManualReview(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    signal_id: int = Field(foreign_key="signal.id", index=True)
    decision: str = Field(index=True)
    note: str | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)
