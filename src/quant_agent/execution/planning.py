from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from quant_agent.common.io import content_sha256
from quant_agent.data.snapshots import DataSnapshotStore
from quant_agent.execution.config import FeeSchedule, PaperAccountSettings
from quant_agent.execution.ledger import PortfolioLedger
from quant_agent.risk.rules.kill_switch import check_kill_switch
from quant_agent.schemas.data import DataManifest
from quant_agent.schemas.portfolio import (
    OrderPlan,
    PlannedOrder,
    SkippedOrder,
)
from quant_agent.schemas.research import TargetPositionRequest


class ExecutionSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketState:
    prices: dict[str, float]
    suspended: dict[str, bool]
    limit_up: dict[str, float]
    limit_down: dict[str, float]

    def untradable_reason(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        *,
        proposed_price: float | None = None,
    ) -> str | None:
        if symbol not in self.suspended:
            return "INSTRUMENT_STATUS_UNAVAILABLE"
        if self.suspended[symbol]:
            return "SUSPENDED"
        if symbol not in self.limit_up or symbol not in self.limit_down:
            return "LIMIT_PRICE_UNAVAILABLE"
        price = self.prices[symbol] if proposed_price is None else proposed_price
        if side == "BUY" and price >= self.limit_up[symbol] - 1e-9:
            return "LIMIT_UP"
        if side == "SELL" and price <= self.limit_down[symbol] + 1e-9:
            return "LIMIT_DOWN"
        return None


def load_market_state(manifest: DataManifest) -> MarketState:
    daily = DataSnapshotStore.load_dataset(manifest, "daily_bar")
    status = DataSnapshotStore.load_dataset(manifest, "instrument_status")
    limits = DataSnapshotStore.load_dataset(manifest, "limit_price")
    trade_date = manifest.trade_date
    daily_for_date = daily[daily["trade_date"].astype(str) == trade_date]
    status_for_date = status[status["trade_date"].astype(str) == trade_date]
    limits_for_date = limits[limits["trade_date"].astype(str) == trade_date]
    prices = {
        str(row.symbol): float(row.close)
        for row in daily_for_date.itertuples(index=False)
    }
    if not prices:
        raise ExecutionSafetyError(f"no market prices for {trade_date}")
    return MarketState(
        prices=prices,
        suspended={
            str(row.symbol): bool(row.suspended)
            for row in status_for_date.itertuples(index=False)
        },
        limit_up={
            str(row.symbol): float(row.limit_up)
            for row in limits_for_date.itertuples(index=False)
        },
        limit_down={
            str(row.symbol): float(row.limit_down)
            for row in limits_for_date.itertuples(index=False)
        },
    )


def order_plan_semantic_payload(plan: OrderPlan) -> dict[str, object]:
    return {
        "schema_version": plan.schema_version,
        "run_id": plan.run_id,
        "strategy_id": plan.strategy_id,
        "trade_date": plan.trade_date,
        "account_id": plan.account_id,
        "data_version": plan.data_version,
        "config_hash": plan.config_hash,
        "code_version": plan.code_version,
        "as_of": plan.as_of,
        "input_checksums": dict(sorted(plan.input_checksums.items())),
        "account": plan.account.model_dump(mode="json"),
        "target_weights": dict(sorted(plan.target_weights.items())),
        "orders": [order.model_dump(mode="json") for order in plan.orders],
        "skipped": [item.model_dump(mode="json") for item in plan.skipped],
        "estimated_turnover": plan.estimated_turnover,
        "estimated_fees": plan.estimated_fees,
    }


def order_plan_checksum(plan: OrderPlan) -> str:
    return content_sha256(order_plan_semantic_payload(plan))


def make_planned_order(
    *,
    run_id: str,
    symbol: str,
    side: Literal["BUY", "SELL"],
    price: float,
    volume: int,
    fees: FeeSchedule,
    reason: str = "target_delta",
) -> PlannedOrder:
    expected_execution_price = fees.execution_price(side, price)
    value = round(expected_execution_price * volume, 6)
    identity = {
        "symbol": symbol,
        "side": side,
        "price": price,
        "volume": volume,
    }
    client_order_id = f"{run_id}-{content_sha256(identity)[:16]}"
    return PlannedOrder(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        price=price,
        volume=volume,
        estimated_value=value,
        estimated_fee=fees.estimate_fee(side, value),
        reason=reason,
    )


def replace_plan_orders(
    plan: OrderPlan,
    orders: list[PlannedOrder],
    *,
    metadata: dict[str, object] | None = None,
) -> OrderPlan:
    estimated_value = sum(order.estimated_value for order in orders)
    updated = plan.model_copy(
        update={
            "orders": orders,
            "estimated_turnover": (
                estimated_value / plan.account.total_equity
                if plan.account.total_equity
                else 0.0
            ),
            "estimated_fees": sum(order.estimated_fee for order in orders),
            "plan_checksum": "pending",
            "metadata": {**plan.metadata, **(metadata or {})},
        }
    )
    return updated.model_copy(update={"plan_checksum": order_plan_checksum(updated)})


class PortfolioOrderPlanner:
    def __init__(
        self,
        *,
        ledger: PortfolioLedger,
        settings: PaperAccountSettings,
        artifact_root: str | Path,
    ):
        self.ledger = ledger
        self.settings = settings
        self.artifact_root = Path(artifact_root)

    def build(
        self,
        *,
        targets: TargetPositionRequest,
        manifest: DataManifest,
    ) -> OrderPlan:
        violation = check_kill_switch(self.artifact_root)
        if violation:
            raise ExecutionSafetyError(violation.message)
        if not manifest.valid:
            raise ExecutionSafetyError("order planning requires a valid data manifest")
        if targets.run_id == "" or targets.run_id is None:
            raise ValueError("target positions require a run_id")
        if targets.trade_date != manifest.trade_date:
            raise ValueError("target positions and data snapshot have different trade dates")
        if targets.data_version and targets.data_version != manifest.data_version:
            raise ValueError("target positions and data snapshot have different data versions")
        if not targets.config_hash or not targets.code_version:
            raise ValueError("strict order planning requires config_hash and code_version")
        self.settings.fees.validate_trade_date(manifest.trade_date)

        market = load_market_state(manifest)
        self.ledger.ensure_account(
            self.settings.account_id,
            self.settings.initial_cash,
        )
        self.ledger.validate_trade_date_ordering(
            account_id=self.settings.account_id,
            trade_date=manifest.trade_date,
        )
        account = self.ledger.portfolio_snapshot(
            account_id=self.settings.account_id,
            trade_date=manifest.trade_date,
            prices=market.prices,
        ).model_copy(
            update={
                "run_id": targets.run_id,
                "as_of": manifest.trade_date,
                "data_version": manifest.data_version,
                "config_hash": targets.config_hash,
                "code_version": targets.code_version,
                "input_checksums": dict(targets.input_checksums),
            }
        )
        target_weights = {
            position.symbol: float(position.target_weight)
            for position in targets.positions
        }
        current = {position.symbol: position for position in account.positions}
        desired_volumes: dict[str, int] = {}
        for symbol, weight in target_weights.items():
            if symbol not in market.prices:
                raise ExecutionSafetyError(f"missing target price for {symbol}")
            target_value = account.total_equity * weight
            desired_volumes[symbol] = (
                int(target_value // (market.prices[symbol] * self.settings.lot_size))
                * self.settings.lot_size
            )
        for symbol in current:
            desired_volumes.setdefault(symbol, 0)

        orders: list[PlannedOrder] = []
        skipped: list[SkippedOrder] = []
        projected_cash = account.cash
        for symbol in sorted(desired_volumes):
            current_position = current.get(symbol)
            current_volume = current_position.total_volume if current_position else 0
            delta = desired_volumes[symbol] - current_volume
            if delta >= 0:
                continue
            requested = abs(delta)
            available = current_position.available_volume if current_position else 0
            volume = min(requested, available)
            if volume < requested:
                skipped.append(
                    SkippedOrder(
                        symbol=symbol,
                        side="SELL",
                        reason="T1_LOCKED",
                        requested_volume=requested - volume,
                    )
                )
            if volume <= 0:
                continue
            expected_execution_price = self.settings.fees.execution_price(
                "SELL",
                market.prices[symbol],
            )
            reason = market.untradable_reason(
                symbol,
                "SELL",
                proposed_price=expected_execution_price,
            )
            if reason:
                skipped.append(
                    SkippedOrder(
                        symbol=symbol,
                        side="SELL",
                        reason=reason,
                        requested_volume=volume,
                    )
                )
                continue
            order = make_planned_order(
                run_id=targets.run_id,
                symbol=symbol,
                side="SELL",
                price=market.prices[symbol],
                volume=volume,
                fees=self.settings.fees,
            )
            orders.append(order)
            projected_cash += order.estimated_value - order.estimated_fee

        for symbol in sorted(desired_volumes):
            current_position = current.get(symbol)
            current_volume = current_position.total_volume if current_position else 0
            desired_delta = desired_volumes[symbol] - current_volume
            if desired_delta <= 0:
                continue
            expected_execution_price = self.settings.fees.execution_price(
                "BUY",
                market.prices[symbol],
            )
            reason = market.untradable_reason(
                symbol,
                "BUY",
                proposed_price=expected_execution_price,
            )
            if reason:
                skipped.append(
                    SkippedOrder(
                        symbol=symbol,
                        side="BUY",
                        reason=reason,
                        requested_volume=desired_delta,
                    )
                )
                continue
            volume = self._affordable_volume(
                desired_volume=desired_delta,
                price=market.prices[symbol],
                budget=projected_cash,
            )
            if volume < desired_delta:
                skipped.append(
                    SkippedOrder(
                        symbol=symbol,
                        side="BUY",
                        reason="CASH_REDUCED",
                        requested_volume=desired_delta - volume,
                    )
                )
            if volume <= 0:
                continue
            order = make_planned_order(
                run_id=targets.run_id,
                symbol=symbol,
                side="BUY",
                price=market.prices[symbol],
                volume=volume,
                fees=self.settings.fees,
            )
            orders.append(order)
            projected_cash -= order.estimated_value + order.estimated_fee

        orders.sort(key=lambda order: (0 if order.side == "SELL" else 1, order.symbol))
        estimated_value = sum(order.estimated_value for order in orders)
        estimated_fees = sum(order.estimated_fee for order in orders)
        draft = OrderPlan(
            run_id=targets.run_id,
            strategy_id=targets.strategy_id,
            trade_date=manifest.trade_date,
            generated_at=targets.generated_at,
            account_id=self.settings.account_id,
            data_version=manifest.data_version,
            config_hash=targets.config_hash,
            code_version=targets.code_version,
            as_of=manifest.trade_date,
            input_checksums=dict(targets.input_checksums),
            account=account,
            target_weights=target_weights,
            orders=orders,
            skipped=skipped,
            estimated_turnover=(
                estimated_value / account.total_equity if account.total_equity else 0.0
            ),
            estimated_fees=estimated_fees,
            plan_checksum="pending",
            metadata={
                "data_manifest": str(Path(manifest.snapshot_dir) / "data_manifest.json"),
                "projected_cash": round(projected_cash, 6),
                "fee_schedule": self.settings.fees.model_dump(mode="json"),
            },
        )
        return draft.model_copy(update={"plan_checksum": order_plan_checksum(draft)})

    def _affordable_volume(
        self,
        *,
        desired_volume: int,
        price: float,
        budget: float,
    ) -> int:
        volume = min(
            desired_volume,
            int(
                budget
                // (
                    self.settings.fees.execution_price("BUY", price)
                    * self.settings.lot_size
                )
            )
            * self.settings.lot_size,
        )
        while volume > 0:
            value = self.settings.fees.execution_price("BUY", price) * volume
            fee = self.settings.fees.estimate_fee("BUY", value)
            if value + fee <= budget + 1e-9:
                return volume
            volume -= self.settings.lot_size
        return 0
