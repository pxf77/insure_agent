from __future__ import annotations

from datetime import datetime

from quant_agent.schemas.execution import OrdersPayload, TradeRecord, TradesPayload


class MockExecutionAdapter:
    def execute(self, orders: OrdersPayload) -> TradesPayload:
        traded_at = datetime.now().isoformat(timespec="seconds")
        trades = [
            TradeRecord(
                trade_id=f"trade-{order.client_order_id}",
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                price=order.price,
                volume=order.volume,
                traded_at=traded_at,
            )
            for order in orders.orders
        ]
        return TradesPayload(run_id=orders.run_id, strategy_id=orders.strategy_id, trades=trades)
