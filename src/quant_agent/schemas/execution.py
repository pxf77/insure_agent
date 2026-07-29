from __future__ import annotations

from pydantic import BaseModel, Field


class OrderRequest(BaseModel):
    client_order_id: str
    symbol: str
    side: str
    order_type: str = "LIMIT"
    price: float = Field(gt=0)
    volume: int = Field(gt=0)
    estimated_fee: float | None = Field(default=None, ge=0)
    reason: str | None = None


class OrdersPayload(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    strategy_id: str
    orders: list[OrderRequest]
    trade_date: str | None = None
    plan_checksum: str | None = None


class TradeRecord(BaseModel):
    trade_id: str
    client_order_id: str
    symbol: str
    side: str
    price: float = Field(gt=0)
    volume: int = Field(gt=0)
    traded_at: str


class TradesPayload(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    strategy_id: str
    trades: list[TradeRecord]
    trade_date: str | None = None
    plan_checksum: str | None = None
