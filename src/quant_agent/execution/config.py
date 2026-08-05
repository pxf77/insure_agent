from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class FeeSchedule(BaseModel):
    effective_from: date = date(2023, 8, 28)
    commission_bps: float = Field(default=3.0, ge=0)
    minimum_commission: float = Field(default=5.0, ge=0)
    sell_stamp_duty_bps: float = Field(default=5.0, ge=0)
    transfer_fee_bps: float = Field(default=0.1, ge=0)
    slippage_bps: float = Field(default=10.0, ge=0)

    def validate_trade_date(self, trade_date: str) -> None:
        if date.fromisoformat(trade_date) < self.effective_from:
            raise ValueError(
                f"fee schedule effective from {self.effective_from}; "
                f"no schedule covers {trade_date}"
            )

    def execution_price(self, side: Literal["BUY", "SELL"], reference_price: float) -> float:
        slippage = self.slippage_bps / 10_000
        multiplier = 1 + slippage if side == "BUY" else 1 - slippage
        return round(reference_price * multiplier, 6)

    def estimate_fee(self, side: Literal["BUY", "SELL"], value: float) -> float:
        commission = max(value * self.commission_bps / 10_000, self.minimum_commission)
        transfer = value * self.transfer_fee_bps / 10_000
        stamp_duty = value * self.sell_stamp_duty_bps / 10_000 if side == "SELL" else 0.0
        return round(commission + transfer + stamp_duty, 6)


class PaperAccountSettings(BaseModel):
    account_id: str = "paper-main"
    initial_cash: float = Field(default=1_000_000, gt=0)
    lot_size: int = Field(default=100, ge=1)
    fees: FeeSchedule = Field(default_factory=FeeSchedule)
