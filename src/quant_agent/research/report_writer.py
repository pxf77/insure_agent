from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_agent.common.run_index import RunIndex
from quant_agent.schemas.execution import OrdersPayload, TradesPayload
from quant_agent.schemas.risk import RiskDecision


class ReportWriter:
    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root)

    def write_report(
        self,
        *,
        run_id: str,
        strategy_id: str,
        metrics: dict[str, Any],
        risk_decision: RiskDecision,
        orders_payload: OrdersPayload | None,
        trades_payload: TradesPayload | None,
    ) -> Path:
        report_dir = self.artifact_root / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{run_id}_report.md"
        report_path.write_text(
            self._render(
                run_id=run_id,
                strategy_id=strategy_id,
                metrics=metrics,
                risk_decision=risk_decision,
                orders_payload=orders_payload,
                trades_payload=trades_payload,
            ),
            encoding="utf-8",
        )
        RunIndex(self.artifact_root).update(report=str(report_path), report_run=run_id)
        return report_path

    def write_from_files(
        self,
        *,
        metrics_path: str | Path,
        approved_positions_path: str | Path,
        orders_path: str | Path | None,
        trades_path: str | Path | None,
    ) -> Path:
        metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
        risk_decision = RiskDecision.model_validate_json(
            Path(approved_positions_path).read_text(encoding="utf-8")
        )
        orders_payload = (
            OrdersPayload.model_validate_json(Path(orders_path).read_text(encoding="utf-8"))
            if orders_path
            else None
        )
        trades_payload = (
            TradesPayload.model_validate_json(Path(trades_path).read_text(encoding="utf-8"))
            if trades_path
            else None
        )
        return self.write_report(
            run_id=str(metrics["run_id"]),
            strategy_id=str(metrics["strategy_id"]),
            metrics=metrics,
            risk_decision=risk_decision,
            orders_payload=orders_payload,
            trades_payload=trades_payload,
        )

    @staticmethod
    def _render(
        *,
        run_id: str,
        strategy_id: str,
        metrics: dict[str, Any],
        risk_decision: RiskDecision,
        orders_payload: OrdersPayload | None,
        trades_payload: TradesPayload | None,
    ) -> str:
        order_count = len(orders_payload.orders) if orders_payload else 0
        trade_count = len(trades_payload.trades) if trades_payload else 0
        metrics_text = json.dumps(metrics.get("metrics", {}), indent=2, ensure_ascii=False)
        violations = "\n".join(
            f"- `{violation.rule_id}` {violation.symbol or ''}: {violation.message}"
            for violation in risk_decision.violations
        ) or "- None"
        return (
            f"# Local MVP Run Report\n\n"
            f"## Summary\n\n"
            f"- run_id: `{run_id}`\n"
            f"- strategy_id: `{strategy_id}`\n"
            f"- orders: {order_count}\n"
            f"- trades: {trade_count}\n\n"
            f"## Metrics\n\n```json\n{metrics_text}\n```\n\n"
            f"## Risk Decision\n\n"
            f"- decision: `{risk_decision.decision}`\n"
            f"- approved: `{risk_decision.approved}`\n"
            f"- positions: {len(risk_decision.positions)}\n\n"
            f"## Risk Violations\n\n{violations}\n"
        )
