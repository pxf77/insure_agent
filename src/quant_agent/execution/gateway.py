from __future__ import annotations

import os
import stat
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_agent.schemas.v2.contracts import OrderSide
from quant_agent.schemas.v2.primitives import AwareDateTime, InstrumentId, Price


class BrokerOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class GatewayHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1, max_length=100)
    connected: bool
    read_only: bool = True
    message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def enforce_read_only(self) -> GatewayHealth:
        if not self.read_only:
            raise ValueError("live-shadow gateways must be read-only")
        return self


class BrokerAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=100)
    cash: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    total_equity: Decimal = Field(ge=0, max_digits=24, decimal_places=8)


class BrokerPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentId
    quantity: int = Field(ge=0)
    sellable_quantity: int = Field(ge=0)
    market_value: Decimal = Field(ge=0, max_digits=24, decimal_places=8)

    @model_validator(mode="after")
    def validate_sellable_quantity(self) -> BrokerPosition:
        if self.sellable_quantity > self.quantity:
            raise ValueError("sellable_quantity must not exceed quantity")
        return self


class BrokerOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_order_id: str = Field(min_length=1, max_length=200)
    client_order_id: str | None = Field(default=None, max_length=200)
    instrument: InstrumentId
    side: OrderSide
    status: BrokerOrderStatus
    quantity: int = Field(gt=0)
    filled_quantity: int = Field(ge=0)
    limit_price: Price | None = None

    @model_validator(mode="after")
    def validate_filled_quantity(self) -> BrokerOrder:
        if self.filled_quantity > self.quantity:
            raise ValueError("filled_quantity must not exceed quantity")
        return self


class BrokerTrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_trade_id: str = Field(min_length=1, max_length=200)
    external_order_id: str = Field(min_length=1, max_length=200)
    instrument: InstrumentId
    side: OrderSide
    quantity: int = Field(gt=0)
    price: Price
    traded_at: AwareDateTime


class BrokerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    provider_id: str = Field(min_length=1, max_length=100)
    as_of: AwareDateTime
    account: BrokerAccount
    positions: list[BrokerPosition] = Field(default_factory=list)
    orders: list[BrokerOrder] = Field(default_factory=list)
    trades: list[BrokerTrade] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_records(self) -> BrokerSnapshot:
        instruments = [str(item.instrument) for item in self.positions]
        if len(instruments) != len(set(instruments)):
            raise ValueError("broker snapshot contains duplicate positions")
        order_ids = [item.external_order_id for item in self.orders]
        if len(order_ids) != len(set(order_ids)):
            raise ValueError("broker snapshot contains duplicate orders")
        trade_ids = [item.external_trade_id for item in self.trades]
        if len(trade_ids) != len(set(trade_ids)):
            raise ValueError("broker snapshot contains duplicate trades")
        return self


class ReadOnlyExecutionGateway(Protocol):
    @property
    def provider_id(self) -> str: ...

    def health(self) -> GatewayHealth: ...

    def read_snapshot(self) -> BrokerSnapshot: ...


class JsonFileReadOnlyGateway:
    """Read a vendor-sidecar snapshot without exposing any order submission method."""

    def __init__(self, path: str | Path, *, max_snapshot_bytes: int = 10 * 1024 * 1024) -> None:
        if max_snapshot_bytes < 1:
            raise ValueError("max_snapshot_bytes must be positive")
        self.path = Path(path)
        self.max_snapshot_bytes = max_snapshot_bytes

    @property
    def provider_id(self) -> str:
        return self.read_snapshot().provider_id

    def health(self) -> GatewayHealth:
        try:
            snapshot = self.read_snapshot()
        except (OSError, ValueError) as exc:
            return GatewayHealth(
                provider_id="unknown",
                connected=False,
                message=f"snapshot unavailable: {exc}",
            )
        return GatewayHealth(
            provider_id=snapshot.provider_id,
            connected=True,
            message="validated read-only snapshot",
        )

    def read_snapshot(self) -> BrokerSnapshot:
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("broker snapshot path must be a regular non-symlink file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("broker snapshot path must be a regular file")
            if metadata.st_size > self.max_snapshot_bytes:
                raise ValueError("broker snapshot exceeds the configured size limit")
            content = handle.read(self.max_snapshot_bytes + 1)
        if len(content) > self.max_snapshot_bytes:
            raise ValueError("broker snapshot exceeds the configured size limit")
        return BrokerSnapshot.model_validate_json(content)
