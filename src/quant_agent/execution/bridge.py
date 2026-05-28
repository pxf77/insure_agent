from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_agent.data.adapters.local_csv_adapter import LocalCsvAdapter
from quant_agent.schemas.execution import OrderRequest, OrdersPayload
from quant_agent.schemas.risk import RiskDecision


class ExecutionBridge:
    def __init__(self, raw_data_dir: str | Path, account_value: float = 1_000_000):
        self.raw_data_dir = Path(raw_data_dir)
        self.account_value = account_value

    def build_orders(self, decision: RiskDecision) -> OrdersPayload:
        if not decision.approved:
            raise ValueError("risk decision is not approved")

        prices = self._latest_prices()
        orders = []
        for position in decision.positions:
            if position.target_weight <= 0:
                continue
            price = prices[position.symbol]
            target_value = self.account_value * position.target_weight
            lot_count = int(target_value // (price * 100))
            volume = lot_count * 100
            if volume <= 0:
                continue
            orders.append(
                OrderRequest(
                    client_order_id=f"{decision.run_id}-{position.symbol}-buy",
                    symbol=position.symbol,
                    side="BUY",
                    price=price,
                    volume=volume,
                )
            )
        return OrdersPayload(
            run_id=decision.run_id,
            strategy_id=decision.strategy_id,
            orders=orders,
        )

    def _latest_prices(self) -> dict[str, float]:
        frame = LocalCsvAdapter(self.raw_data_dir)._read_table("daily_bar")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        latest = frame.sort_values("trade_date").groupby("symbol", as_index=False).tail(1)
        return {str(row.symbol): float(row.close) for row in latest.itertuples(index=False)}
