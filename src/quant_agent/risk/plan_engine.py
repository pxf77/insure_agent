from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from quant_agent.execution.config import PaperAccountSettings
from quant_agent.execution.ledger import PortfolioLedger
from quant_agent.execution.planning import (
    ExecutionSafetyError,
    load_market_state,
    make_planned_order,
    order_plan_checksum,
    replace_plan_orders,
)
from quant_agent.risk.rules.kill_switch import check_kill_switch
from quant_agent.schemas.data import DataManifest
from quant_agent.schemas.portfolio import OrderPlan, PlannedOrder
from quant_agent.schemas.risk import (
    PlanRiskAssessment,
    RiskRuleResult,
    RiskViolation,
)


class PlanRiskEngine:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        ledger: PortfolioLedger,
        settings: PaperAccountSettings,
        max_single_weight: float = 0.2,
        max_gross_exposure: float = 0.8,
        max_turnover: float = 0.5,
        max_order_value: float = 200_000,
        max_drawdown: float = 0.15,
        kill_switch_file: str = "KILL_SWITCH",
    ):
        self.artifact_root = Path(artifact_root)
        self.ledger = ledger
        self.settings = settings
        self.max_single_weight = max_single_weight
        self.max_gross_exposure = max_gross_exposure
        self.max_turnover = max_turnover
        self.max_order_value = max_order_value
        self.max_drawdown = max_drawdown
        self.kill_switch_file = kill_switch_file

    @classmethod
    def from_config(
        cls,
        *,
        config_path: str | Path,
        artifact_root: str | Path,
        ledger: PortfolioLedger,
        settings: PaperAccountSettings,
    ) -> PlanRiskEngine:
        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        limits = cast(dict[str, Any], config.get("limits", {}))
        kill_switch = cast(dict[str, Any], config.get("kill_switch", {}))
        return cls(
            artifact_root=artifact_root,
            ledger=ledger,
            settings=settings,
            max_single_weight=float(limits.get("max_single_weight", 0.2)),
            max_gross_exposure=float(limits.get("max_gross_exposure", 0.8)),
            max_turnover=float(limits.get("max_turnover", 0.5)),
            max_order_value=float(limits.get("max_order_value", 200_000)),
            max_drawdown=float(limits.get("max_drawdown", 0.15)),
            kill_switch_file=str(kill_switch.get("file_path", "KILL_SWITCH")),
        )

    def evaluate(
        self,
        *,
        plan: OrderPlan,
        manifest: DataManifest,
    ) -> PlanRiskAssessment:
        if plan.plan_checksum != order_plan_checksum(plan):
            raise ExecutionSafetyError("order plan checksum is invalid")
        rules: list[RiskRuleResult] = []
        violations: list[RiskViolation] = []

        kill_violation = check_kill_switch(
            self.artifact_root,
            self.kill_switch_file,
        )
        self._record(
            rules,
            violations,
            rule_id="KILL_SWITCH",
            passed=kill_violation is None,
            severity="ERROR",
            message=(
                "kill switch is inactive"
                if kill_violation is None
                else kill_violation.message
            ),
        )
        self._record(
            rules,
            violations,
            rule_id="DATA_VALID",
            passed=manifest.valid,
            severity="ERROR",
            message="data manifest is valid" if manifest.valid else "data manifest is invalid",
        )
        fresh = (
            plan.trade_date == manifest.trade_date
            and plan.data_version == manifest.data_version
        )
        self._record(
            rules,
            violations,
            rule_id="DATA_FRESHNESS",
            passed=fresh,
            severity="ERROR",
            message=(
                "order plan is bound to the requested data cutoff"
                if fresh
                else "order plan and data cutoff/version differ"
            ),
        )
        try:
            market = load_market_state(manifest)
        except ExecutionSafetyError as exc:
            market = None
            self._record(
                rules,
                violations,
                rule_id="TRADABILITY",
                passed=False,
                severity="ERROR",
                message=str(exc),
            )
        if market:
            for order in plan.orders:
                reason = market.untradable_reason(
                    order.symbol,
                    order.side,
                    proposed_price=order.estimated_value / order.volume,
                )
                self._record(
                    rules,
                    violations,
                    rule_id="TRADABILITY",
                    passed=reason is None,
                    severity="ERROR",
                    message=(
                        f"{order.symbol} is tradable"
                        if reason is None
                        else f"{order.symbol} is not tradable: {reason}"
                    ),
                    symbol=order.symbol,
                )

        projected_values = {
            position.symbol: position.market_value
            for position in plan.account.positions
        }
        for order in plan.orders:
            delta = order.price * order.volume
            projected_values[order.symbol] = projected_values.get(order.symbol, 0.0) + (
                delta if order.side == "BUY" else -delta
            )
        projected_weights = {
            symbol: max(value, 0.0) / plan.account.total_equity
            for symbol, value in projected_values.items()
            if plan.account.total_equity > 0 and value > 1e-9
        }
        gross_exposure = sum(projected_weights.values())
        self._record(
            rules,
            violations,
            rule_id="GROSS_EXPOSURE",
            passed=gross_exposure <= self.max_gross_exposure + 1e-12,
            severity="ERROR",
            message=(
                f"gross target exposure {gross_exposure:.4f}; "
                f"limit {self.max_gross_exposure:.4f}"
            ),
            observed=gross_exposure,
            limit=self.max_gross_exposure,
        )
        for symbol, weight in sorted(projected_weights.items()):
            self._record(
                rules,
                violations,
                rule_id="MAX_SINGLE_WEIGHT",
                passed=weight <= self.max_single_weight + 1e-12,
                severity="ERROR",
                message=(
                    f"{symbol} target weight {weight:.4f}; "
                    f"limit {self.max_single_weight:.4f}"
                ),
                symbol=symbol,
                observed=weight,
                limit=self.max_single_weight,
            )
        self._record(
            rules,
            violations,
            rule_id="TURNOVER",
            passed=plan.estimated_turnover <= self.max_turnover + 1e-12,
            severity="ERROR",
            message=(
                f"estimated turnover {plan.estimated_turnover:.4f}; "
                f"limit {self.max_turnover:.4f}"
            ),
            observed=plan.estimated_turnover,
            limit=self.max_turnover,
        )
        projected_cash = plan.account.cash
        for order in plan.orders:
            cash_delta = order.estimated_value - order.estimated_fee
            projected_cash += cash_delta if order.side == "SELL" else -(
                order.estimated_value + order.estimated_fee
            )
        self._record(
            rules,
            violations,
            rule_id="CASH_SUFFICIENCY",
            passed=projected_cash >= -1e-9,
            severity="ERROR",
            message=f"projected cash after plan is {projected_cash:.2f}",
            observed=projected_cash,
            limit=0.0,
        )
        latest_nav = self.ledger.latest_nav(
            plan.account_id,
            before_trade_date=plan.trade_date,
        )
        drawdown = latest_nav.drawdown if latest_nav else 0.0
        self._record(
            rules,
            violations,
            rule_id="DRAWDOWN",
            passed=drawdown >= -self.max_drawdown,
            severity="ERROR",
            message=f"latest drawdown {drawdown:.4f}; limit {-self.max_drawdown:.4f}",
            observed=drawdown,
            limit=-self.max_drawdown,
        )

        adjusted_orders: list[PlannedOrder] = []
        adjusted = False
        for order in plan.orders:
            if order.estimated_value <= self.max_order_value + 1e-9:
                adjusted_orders.append(order)
                self._record(
                    rules,
                    violations,
                    rule_id="MAX_ORDER_VALUE",
                    passed=True,
                    severity="WARN",
                    message=f"{order.client_order_id} is within the order-value limit",
                    symbol=order.symbol,
                    observed=order.estimated_value,
                    limit=self.max_order_value,
                )
                continue
            estimated_unit_value = order.estimated_value / order.volume
            capped_volume = int(
                self.max_order_value
                // (estimated_unit_value * self.settings.lot_size)
            ) * self.settings.lot_size
            if capped_volume <= 0:
                self._record(
                    rules,
                    violations,
                    rule_id="MAX_ORDER_VALUE",
                    passed=False,
                    severity="ERROR",
                    message=f"{order.symbol} cannot fit one lot under the order-value limit",
                    symbol=order.symbol,
                    observed=order.estimated_value,
                    limit=self.max_order_value,
                )
                continue
            adjusted = True
            self._record(
                rules,
                violations,
                rule_id="MAX_ORDER_VALUE",
                passed=False,
                severity="WARN",
                message=(
                    f"{order.symbol} order reduced from {order.volume} "
                    f"to {capped_volume} shares"
                ),
                symbol=order.symbol,
                observed=order.estimated_value,
                limit=self.max_order_value,
            )
            adjusted_orders.append(
                make_planned_order(
                    run_id=plan.run_id,
                    symbol=order.symbol,
                    side=order.side,
                    price=order.price,
                    volume=capped_volume,
                    fees=self.settings.fees,
                    reason="risk_capped_max_order_value",
                )
            )

        hard_failures = [
            result
            for result in rules
            if not result.passed and result.severity == "ERROR"
        ]
        if hard_failures:
            return PlanRiskAssessment(
                run_id=plan.run_id,
                approved=False,
                decision="REJECT",
                original_plan_checksum=plan.plan_checksum,
                rule_results=rules,
                violations=violations,
            )
        adjusted_plan = (
            replace_plan_orders(
                plan,
                adjusted_orders,
                metadata={"risk_adjustment": "max_order_value"},
            )
            if adjusted
            else plan
        )
        return PlanRiskAssessment(
            run_id=plan.run_id,
            approved=True,
            decision="ADJUST" if adjusted else "APPROVE",
            original_plan_checksum=plan.plan_checksum,
            plan_checksum=adjusted_plan.plan_checksum,
            adjusted_plan=adjusted_plan,
            rule_results=rules,
            violations=violations,
        )

    @staticmethod
    def _record(
        rules: list[RiskRuleResult],
        violations: list[RiskViolation],
        *,
        rule_id: str,
        passed: bool,
        severity: str,
        message: str,
        symbol: str | None = None,
        observed: float | str | bool | None = None,
        limit: float | str | bool | None = None,
    ) -> None:
        rules.append(
            RiskRuleResult(
                rule_id=rule_id,
                passed=passed,
                severity=severity,
                message=message,
                symbol=symbol,
                observed=observed,
                limit=limit,
            )
        )
        if not passed:
            violations.append(
                RiskViolation(
                    rule_id=rule_id,
                    severity=severity,
                    symbol=symbol,
                    message=message,
                )
            )
