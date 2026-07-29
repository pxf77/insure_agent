from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from quant_agent.data.symbol import normalize_symbol


class SymbolRecord(BaseModel):
    symbol: str

    @field_validator("symbol")
    @classmethod
    def normalize_a_share_symbol(cls, value: str) -> str:
        return normalize_symbol(value)


class DailyBarRecord(SymbolRecord):
    trade_date: str
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    amount: float = Field(ge=0)


class AdjustFactorRecord(SymbolRecord):
    trade_date: str
    adjust_factor: float = Field(gt=0)


class TradingCalendarRecord(BaseModel):
    trade_date: str
    is_open: bool


class InstrumentStatusRecord(SymbolRecord):
    trade_date: str
    suspended: bool = False
    status: str = "NORMAL"


class LimitPriceRecord(SymbolRecord):
    trade_date: str
    limit_up: float = Field(gt=0)
    limit_down: float = Field(gt=0)


class ListingRecord(SymbolRecord):
    list_date: str
    delist_date: str | None = None
    name: str | None = None


class UniverseMembershipRecord(SymbolRecord):
    universe: str
    effective_start: str
    effective_end: str | None = None
