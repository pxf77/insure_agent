from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from quant_agent.risk.approval_store import ApprovalStore
from quant_agent.risk.kill_switch_store import KillSwitchStore
from quant_agent.risk.v2_models import ApprovalEvidence, KillSwitchScope
from quant_agent.risk.v2_service import RiskDecisionService

app = typer.Typer(help="Deterministic A-share risk-control v2 commands.")
kill_switch_app = typer.Typer(help="Persistent kill-switch commands.")
approval_app = typer.Typer(help="Trusted manual-approval registry commands.")
app.add_typer(kill_switch_app, name="kill-switch")
app.add_typer(approval_app, name="approval")


@app.command("validate")
def validate(
    target: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    context: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    policy: Annotated[Path, typer.Option(exists=True, dir_okay=False)] = Path(
        "configs/risk/paper_v2.yaml"
    ),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts"),
    kill_switch_state: Annotated[Path, typer.Option()] = Path(
        "artifacts/risk_state/kill_switches.json"
    ),
    approval_state: Annotated[Path, typer.Option()] = Path(
        "artifacts/risk_state/approvals.json"
    ),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Evaluate a v2 target portfolio against deterministic risk controls."""
    decision, artifact_dir, reused = RiskDecisionService(
        artifact_root=artifact_root,
        kill_switch_path=kill_switch_state,
        approval_path=approval_state,
    ).evaluate_files(
        target_path=target,
        context_path=context,
        policy_path=policy,
    )
    if json_output:
        typer.echo(decision.model_dump_json(indent=2))
    else:
        action = "reused" if reused else "created"
        typer.echo(f"decision: {decision.decision.value}")
        typer.echo(f"approved: {decision.approved}")
        typer.echo(f"artifact {action}: {artifact_dir}")
        for result in decision.rule_results:
            typer.echo(
                f"[{result.outcome.value}] {result.rule_id}: "
                f"{result.reason_code} - {result.message}"
            )
    if not decision.approved:
        raise typer.Exit(2)


@kill_switch_app.command("set")
def set_kill_switch(
    scope: Annotated[KillSwitchScope, typer.Option(case_sensitive=False)],
    changed_by: Annotated[str, typer.Option()],
    scope_id: Annotated[str | None, typer.Option()] = None,
    active: Annotated[bool, typer.Option()] = True,
    reduce_only: Annotated[bool, typer.Option()] = False,
    reason_code: Annotated[str, typer.Option()] = "MANUAL_KILL_SWITCH",
    message: Annotated[str, typer.Option()] = "manual operator action",
    state_path: Annotated[Path, typer.Option()] = Path(
        "artifacts/risk_state/kill_switches.json"
    ),
) -> None:
    """Atomically activate, update, or deactivate a kill switch."""
    record = KillSwitchStore(state_path).set(
        scope=scope,
        scope_id=scope_id,
        active=active,
        reduce_only=reduce_only,
        reason_code=reason_code,
        message=message,
        changed_by=changed_by,
    )
    typer.echo(record.model_dump_json(indent=2))


@kill_switch_app.command("list")
def list_kill_switches(
    state_path: Annotated[Path, typer.Option()] = Path(
        "artifacts/risk_state/kill_switches.json"
    ),
) -> None:
    """List persisted kill-switch state."""
    typer.echo(KillSwitchStore(state_path).read().model_dump_json(indent=2))


@approval_app.command("issue")
def issue_approval(
    evidence: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    state_path: Annotated[Path, typer.Option()] = Path(
        "artifacts/risk_state/approvals.json"
    ),
) -> None:
    """Issue immutable approval evidence from a reviewed JSON document."""
    approval = ApprovalEvidence.model_validate_json(evidence.read_text(encoding="utf-8"))
    issued = ApprovalStore(state_path).issue(approval)
    typer.echo(issued.model_dump_json(indent=2))


@approval_app.command("revoke")
def revoke_approval(
    approval_id: Annotated[UUID, typer.Option()],
    state_path: Annotated[Path, typer.Option()] = Path(
        "artifacts/risk_state/approvals.json"
    ),
) -> None:
    """Revoke an issued approval ID."""
    ApprovalStore(state_path).revoke(approval_id)
    typer.echo(f"revoked: {approval_id}")


@approval_app.command("list")
def list_approvals(
    state_path: Annotated[Path, typer.Option()] = Path(
        "artifacts/risk_state/approvals.json"
    ),
) -> None:
    """List trusted and revoked approval records."""
    typer.echo(ApprovalStore(state_path).read().model_dump_json(indent=2))


if __name__ == "__main__":
    app()
