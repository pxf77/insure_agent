from __future__ import annotations

from pydantic import BaseModel, Field


class OrderRequest(BaseModel):
    client_order_id: str
    symbol: str
    side: str
    order_type: str = "LIMIT"
    price: float = Field(gt=0)
    volume: int = Field(gt=0)


class OrdersPayload(BaseModel):
    run_id: str
    strategy_id: str
    orders: list[OrderRequest]


class TradeRecord(BaseModel):
    trade_id: str
    client_order_id: str
    symbol: str
    side: str
    price: float = Field(gt=0)
    volume: int = Field(gt=0)
    traded_at: str


class TradesPayload(BaseModel):
    run_id: str
    strategy_id: str
    trades: list[TradeRecord]
