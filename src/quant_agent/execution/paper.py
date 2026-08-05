from __future__ import annotations

from datetime import datetime
from pathlib import Path

from quant_agent.execution.config import PaperAccountSettings
from quant_agent.execution.ledger import PortfolioLedger
from quant_agent.execution.planning import (
    ExecutionSafetyError,
    load_market_state,
    order_plan_checksum,
)
from quant_agent.risk.approval import ApprovalStore
from quant_agent.risk.rules.kill_switch import check_kill_switch
from quant_agent.schemas.data import DataManifest
from quant_agent.schemas.portfolio import ApprovalRecord, ExecutionResult, OrderPlan


class LedgerPaperExecutor:
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

    def execute(
        self,
        *,
        plan: OrderPlan,
        manifest: DataManifest,
        approval: ApprovalRecord | None = None,
        require_approval: bool = True,
    ) -> ExecutionResult:
        violation = check_kill_switch(self.artifact_root)
        if violation:
            raise ExecutionSafetyError(violation.message)
        if plan.plan_checksum != order_plan_checksum(plan):
            raise ExecutionSafetyError("order plan checksum is invalid")
        if plan.data_version != manifest.data_version or plan.trade_date != manifest.trade_date:
            raise ExecutionSafetyError("order plan is not bound to the supplied data snapshot")
        self.settings.fees.validate_trade_date(plan.trade_date)
        if require_approval:
            ApprovalStore(self.artifact_root).validate(
                plan=plan,
                approval=approval,
            )
        market = load_market_state(manifest)
        violation = check_kill_switch(self.artifact_root)
        if violation:
            raise ExecutionSafetyError(violation.message)
        self.ledger.begin_execution_session(
            account_id=plan.account_id,
            trade_date=plan.trade_date,
            run_id=plan.run_id,
            plan_checksum=plan.plan_checksum,
        )
        outcomes = []
        for order in plan.orders:
            execution_price = self.settings.fees.execution_price(order.side, order.price)
            reason = market.untradable_reason(
                order.symbol,
                order.side,
                proposed_price=execution_price,
            )
            outcomes.append(
                self.ledger.execute_order(
                    account_id=plan.account_id,
                    run_id=plan.run_id,
                    plan_checksum=plan.plan_checksum,
                    trade_date=plan.trade_date,
                    order=order,
                    execution_price=execution_price,
                    fee_schedule=self.settings.fees,
                    unfilled_reason=reason,
                )
            )
        nav = self.ledger.record_nav(
            account_id=plan.account_id,
            trade_date=plan.trade_date,
            prices=market.prices,
        )
        self.ledger.complete_execution_session(
            account_id=plan.account_id,
            trade_date=plan.trade_date,
            run_id=plan.run_id,
            plan_checksum=plan.plan_checksum,
        )
        return ExecutionResult(
            run_id=plan.run_id,
            strategy_id=plan.strategy_id,
            trade_date=plan.trade_date,
            as_of=plan.trade_date,
            data_version=plan.data_version,
            config_hash=plan.config_hash,
            code_version=plan.code_version,
            input_checksums={
                **plan.input_checksums,
                "order_plan": plan.plan_checksum,
            },
            plan_checksum=plan.plan_checksum,
            executed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            outcomes=outcomes,
            nav=nav,
            metadata={"simulation": "daily_bar_full_fill_or_unfilled"},
        )
