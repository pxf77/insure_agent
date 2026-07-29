from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from quant_agent.common.io import write_immutable_text
from quant_agent.schemas.data import DataManifest
from quant_agent.schemas.portfolio import ApprovalRecord, ExecutionResult, OrderPlan
from quant_agent.schemas.research import TargetPositionRequest
from quant_agent.schemas.risk import PlanRiskAssessment


class DailyReportWriter:
    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root)

    def write(
        self,
        *,
        kind: Literal["pre", "final"],
        manifest: DataManifest,
        metrics: dict[str, object],
        targets: TargetPositionRequest,
        plan: OrderPlan,
        assessment: PlanRiskAssessment,
        approval: ApprovalRecord | None = None,
        execution: ExecutionResult | None = None,
    ) -> Path:
        run_ids = {targets.run_id, plan.run_id, assessment.run_id}
        metric_run_id = metrics.get("run_id")
        if isinstance(metric_run_id, str):
            run_ids.add(metric_run_id)
        if approval:
            run_ids.add(approval.run_id)
        if execution:
            run_ids.add(execution.run_id)
        if len(run_ids) != 1:
            raise ValueError(f"report inputs contain mixed run IDs: {sorted(run_ids)}")
        if manifest.data_version != plan.data_version:
            raise ValueError("report data manifest and order plan versions differ")
        if targets.data_version and targets.data_version != plan.data_version:
            raise ValueError("report targets and order plan data versions differ")
        if assessment.plan_checksum and assessment.plan_checksum != plan.plan_checksum:
            raise ValueError("report risk assessment and order plan checksums differ")
        if execution and execution.plan_checksum != plan.plan_checksum:
            raise ValueError("report execution and order plan checksums differ")
        if kind == "final" and execution is None:
            raise ValueError("final report requires an execution result")
        report_dir = self.artifact_root / "reports"
        report_path = report_dir / f"{plan.run_id}_{kind}_report.md"
        write_immutable_text(
            report_path,
            self._render(
                kind=kind,
                manifest=manifest,
                metrics=metrics,
                targets=targets,
                plan=plan,
                assessment=assessment,
                approval=approval,
                execution=execution,
            ),
        )
        return report_path

    @staticmethod
    def _render(
        *,
        kind: str,
        manifest: DataManifest,
        metrics: dict[str, object],
        targets: TargetPositionRequest,
        plan: OrderPlan,
        assessment: PlanRiskAssessment,
        approval: ApprovalRecord | None,
        execution: ExecutionResult | None,
    ) -> str:
        quality_lines = [
            (
                f"- `{result.severity}` `{result.rule_id}` "
                f"({result.dataset or 'snapshot'}): {result.message}"
            )
            for result in manifest.validations
            if not result.passed
        ] or ["- All configured critical checks passed."]
        target_lines = [
            f"- `{symbol}`: {weight:.2%}"
            for symbol, weight in sorted(plan.target_weights.items())
        ] or ["- No target positions."]
        holding_lines = [
            (
                f"- `{position.symbol}`: {position.total_volume} shares, "
                f"available {position.available_volume}, value {position.market_value:.2f}"
            )
            for position in plan.account.positions
        ] or ["- No current holdings."]
        order_lines = [
            (
                f"- `{order.side}` `{order.symbol}` {order.volume} @ {order.price:.4f}; "
                f"value {order.estimated_value:.2f}; estimated fee {order.estimated_fee:.2f}"
            )
            for order in plan.orders
        ] or ["- No orders."]
        skipped_lines = [
            (
                f"- `{item.symbol}` {item.side or ''}: {item.reason} "
                f"({item.requested_volume} shares)"
            )
            for item in plan.skipped
        ] or ["- None."]
        risk_lines = [
            (
                f"- `{'PASS' if result.passed else result.severity}` "
                f"`{result.rule_id}`: {result.message}"
            )
            for result in assessment.rule_results
        ] or ["- No rules recorded."]
        approval_lines = (
            [
                "- status: `APPROVED`",
                f"- approver: `{approval.approver}`",
                f"- expires_at: `{approval.expires_at}`",
                f"- plan_checksum: `{approval.plan_checksum}`",
            ]
            if approval
            else [
                "- status: `AWAITING_APPROVAL`",
                f"- plan_checksum: `{plan.plan_checksum}`",
            ]
        )
        execution_lines = (
            [
                (
                    f"- `{outcome.status}` `{outcome.side}` `{outcome.symbol}`: "
                    f"{outcome.filled_volume}/{outcome.requested_volume}, "
                    f"fee {outcome.fee:.2f}"
                    + (f", reason {outcome.reason}" if outcome.reason else "")
                )
                for outcome in execution.outcomes
            ]
            if execution
            else ["- Not executed."]
        )
        nav_lines = (
            [
                f"- cash: {execution.nav.cash:.2f}",
                f"- market_value: {execution.nav.market_value:.2f}",
                f"- total_equity: {execution.nav.total_equity:.2f}",
                f"- daily_return: {execution.nav.daily_return:.4%}",
                f"- drawdown: {execution.nav.drawdown:.4%}",
            ]
            if execution
            else ["- NAV will be calculated after execution."]
        )
        metric_values = metrics.get("metrics", {})
        return "\n".join(
            [
                f"# Daily Research Assistant Report ({kind})",
                "",
                "## Provenance",
                "",
                f"- run_id: `{plan.run_id}`",
                f"- trade_date: `{plan.trade_date}`",
                f"- strategy_id: `{plan.strategy_id}`",
                f"- data_version: `{manifest.data_version}`",
                f"- config_hash: `{plan.config_hash}`",
                f"- code_version: `{plan.code_version}`",
                f"- benchmark: `{metrics.get('benchmark')}`",
                "",
                "## Data Health",
                "",
                *quality_lines,
                "",
                "## Research And Baseline",
                "",
                "```json",
                json.dumps(metric_values, ensure_ascii=False, sort_keys=True, indent=2),
                "```",
                "",
                "## Current Holdings",
                "",
                *holding_lines,
                "",
                "## Target Holdings",
                "",
                *target_lines,
                "",
                "## Proposed Deltas And Estimated Costs",
                "",
                *order_lines,
                f"- estimated_turnover: {plan.estimated_turnover:.4%}",
                f"- estimated_fees: {plan.estimated_fees:.2f}",
                "",
                "## Skipped Or Reduced Orders",
                "",
                *skipped_lines,
                "",
                "## Risk",
                "",
                f"- decision: `{assessment.decision}`",
                f"- approved: `{assessment.approved}`",
                *risk_lines,
                "",
                "## Approval",
                "",
                *approval_lines,
                "",
                "## Execution",
                "",
                *execution_lines,
                "",
                "## NAV",
                "",
                *nav_lines,
                "",
            ]
        )
