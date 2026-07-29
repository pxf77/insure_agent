from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from quant_agent.common.io import atomic_write_json, read_json, write_immutable_json
from quant_agent.execution.planning import order_plan_checksum
from quant_agent.schemas.portfolio import ApprovalRecord, OrderPlan
from quant_agent.schemas.risk import PlanRiskAssessment


class ApprovalError(RuntimeError):
    pass


class ApprovalStore:
    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root)
        self.approvals_root = self.artifact_root / "approvals"

    def grant(
        self,
        *,
        plan: OrderPlan,
        assessment: PlanRiskAssessment,
        approver: str,
        expires_in_minutes: int = 60,
        now: datetime | None = None,
    ) -> tuple[ApprovalRecord, Path]:
        if not approver.strip():
            raise ApprovalError("approver is required")
        if expires_in_minutes <= 0:
            raise ApprovalError("approval lifetime must be positive")
        if not assessment.approved or assessment.plan_checksum != plan.plan_checksum:
            raise ApprovalError("risk-approved plan checksum is required")
        if plan.plan_checksum != order_plan_checksum(plan):
            raise ApprovalError("order plan checksum is invalid")
        granted_at = (now or datetime.now().astimezone()).astimezone()
        expires_at = granted_at + timedelta(minutes=expires_in_minutes)
        record = ApprovalRecord(
            run_id=plan.run_id,
            trade_date=plan.trade_date,
            as_of=plan.as_of or plan.trade_date,
            data_version=plan.data_version,
            config_hash=plan.config_hash,
            code_version=plan.code_version,
            input_checksums={"order_plan": plan.plan_checksum},
            plan_checksum=plan.plan_checksum,
            approver=approver.strip(),
            granted_at=granted_at.isoformat(timespec="seconds"),
            expires_at=expires_at.isoformat(timespec="seconds"),
        )
        approval_dir = self.approvals_root / plan.run_id
        filename = (
            f"{plan.plan_checksum}-"
            f"{granted_at.strftime('%Y%m%dT%H%M%S%f%z')}.json"
        )
        approval_path = approval_dir / filename
        write_immutable_json(approval_path, record)
        atomic_write_json(
            approval_dir / "latest.json",
            {
                "run_id": plan.run_id,
                "plan_checksum": plan.plan_checksum,
                "approval": str(approval_path),
            },
        )
        return record, approval_path

    def latest(self, run_id: str) -> ApprovalRecord:
        pointer_path = self.approvals_root / run_id / "latest.json"
        if not pointer_path.exists():
            raise ApprovalError(f"no approval exists for run {run_id}")
        pointer = read_json(pointer_path)
        approval_path = Path(str(pointer["approval"]))
        return ApprovalRecord.model_validate(read_json(approval_path))

    def validate(
        self,
        *,
        plan: OrderPlan,
        approval: ApprovalRecord | None = None,
        now: datetime | None = None,
    ) -> ApprovalRecord:
        record = approval or self.latest(plan.run_id)
        if plan.plan_checksum != order_plan_checksum(plan):
            raise ApprovalError("order plan checksum is invalid")
        if record.run_id != plan.run_id:
            raise ApprovalError("approval belongs to a different run")
        if record.plan_checksum != plan.plan_checksum:
            raise ApprovalError("approval does not match the current order plan")
        if record.data_version and record.data_version != plan.data_version:
            raise ApprovalError("approval belongs to a different data version")
        if record.config_hash and record.config_hash != plan.config_hash:
            raise ApprovalError("approval belongs to a different configuration")
        if record.code_version and record.code_version != plan.code_version:
            raise ApprovalError("approval belongs to a different code version")
        current_time = (now or datetime.now().astimezone()).astimezone()
        expires_at = datetime.fromisoformat(record.expires_at).astimezone()
        if current_time >= expires_at:
            raise ApprovalError("approval has expired")
        return record
