from __future__ import annotations

import hashlib
from decimal import ROUND_DOWN, Decimal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_agent.execution.v2_models import (
    ExecutionContext,
    ExecutionIntent,
    OrderSide,
    OrderType,
    TimeInForce,
)
from quant_agent.schemas.v2 import InstrumentId, RiskDecisionType, RiskDecisionV2
from quant_agent.schemas.v2.primitives import Price


class InstrumentExecutionPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentId
    reference_price: Price


class PlanningInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ExecutionContext
    prices: list[InstrumentExecutionPrice]

    @model_validator(mode="after")
    def validate_prices(self) -> PlanningInput:
        instruments = [str(item.instrument) for item in self.prices]
        if len(instruments) != len(set(instruments)):
            raise ValueError("planning input contains duplicate execution prices")
        return self


class RebalancePlanner:
    """Convert one approved complete target portfolio into deterministic order intents."""

    def plan(
        self,
        *,
        decision: RiskDecisionV2,
        planning: PlanningInput,
    ) -> list[ExecutionIntent]:
        if not decision.approved or decision.decision == RiskDecisionType.REJECT:
            raise ValueError("execution requires an approved risk decision")
        if decision.strategy_id != planning.context.strategy_id:
            raise ValueError("risk decision strategy does not match execution context")
        if decision.run_id == "":
            raise ValueError("risk decision run_id is required")

        current = {
            str(item.instrument): item.quantity for item in planning.context.holdings
        }
        for instrument, quantity in current.items():
            if quantity % 100 != 0:
                raise ValueError(
                    f"current holding {instrument} is not compatible with 100-share lots"
                )
        prices = {
            str(item.instrument): item.reference_price for item in planning.prices
        }
        target_weights = {
            str(item.instrument): item.target_weight for item in decision.positions
        }
        instruments = sorted(set(current) | set(target_weights))
        missing_prices = sorted(set(instruments) - set(prices))
        if missing_prices:
            raise ValueError(f"missing execution prices for instruments: {missing_prices}")

        intents: list[ExecutionIntent] = []
        for instrument in instruments:
            target_weight = target_weights.get(instrument, Decimal("0"))
            price = prices[instrument]
            raw_quantity = planning.context.account_value * target_weight / price
            target_quantity = int(
                (raw_quantity / Decimal("100")).to_integral_value(rounding=ROUND_DOWN)
            ) * 100
            delta = target_quantity - current.get(instrument, 0)
            if delta == 0:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            quantity = abs(delta)
            idempotency_key = self._idempotency_key(
                run_id=decision.run_id,
                risk_decision_id=planning.context.risk_decision_id,
                account_id=planning.context.account_id,
                instrument=instrument,
                target_quantity=target_quantity,
            )
            intent_id = uuid5(NAMESPACE_URL, idempotency_key)
            intents.append(
                ExecutionIntent(
                    intent_id=intent_id,
                    run_id=decision.run_id,
                    risk_decision_id=planning.context.risk_decision_id,
                    account_id=planning.context.account_id,
                    strategy_id=planning.context.strategy_id,
                    instrument=instrument,
                    side=side,
                    quantity=quantity,
                    order_type=OrderType.LIMIT,
                    limit_price=price,
                    time_in_force=TimeInForce.DAY,
                    idempotency_key=idempotency_key,
                    created_at=planning.context.created_at,
                )
            )
        return intents

    @staticmethod
    def _idempotency_key(
        *,
        run_id: str,
        risk_decision_id: str,
        account_id: str,
        instrument: str,
        target_quantity: int,
    ) -> str:
        payload = ":".join(
            (
                run_id,
                risk_decision_id,
                account_id,
                instrument,
                str(target_quantity),
            )
        )
        return f"rebalance:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
