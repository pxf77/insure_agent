from __future__ import annotations

from pathlib import Path

import typer

from quant_agent.risk.kill_switch_store import KillSwitchStore
from quant_agent.risk.v2_models import KillSwitchScope
from quant_agent.risk.v2_service import RiskDecisionService

app = typer.Typer(help="Deterministic A-share risk-control v2 commands.")
kill_switch_app = typer.Typer(help="Persistent kill-switch commands.")
app.add_typer(kill_switch_app, name="kill-switch")


@app.command("validate")
def validate(
    target: Path = typer.Option(..., exists=True, dir_okay=False),
    context: Path = typer.Option(..., exists=True, dir_okay=False),
    policy: Path = typer.Option(
        Path("configs/risk/paper_v2.yaml"),
        exists=True,
        dir_okay=False,
    ),
    artifact_root: Path = typer.Option(Path("artifacts")),
    kill_switch_state: Path = typer.Option(Path("artifacts/risk_state/kill_switches.json")),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Evaluate a v2 target portfolio against deterministic risk controls."""
    decision, artifact_dir, reused = RiskDecisionService(
        artifact_root=artifact_root,
        kill_switch_path=kill_switch_state,
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
    scope: KillSwitchScope = typer.Option(..., case_sensitive=False),
    scope_id: str | None = typer.Option(None),
    active: bool = typer.Option(True),
    reduce_only: bool = typer.Option(False),
    reason_code: str = typer.Option("MANUAL_KILL_SWITCH"),
    message: str = typer.Option("manual operator action"),
    changed_by: str = typer.Option(...),
    state_path: Path = typer.Option(Path("artifacts/risk_state/kill_switches.json")),
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
    state_path: Path = typer.Option(Path("artifacts/risk_state/kill_switches.json")),
) -> None:
    """List persisted kill-switch state."""
    typer.echo(KillSwitchStore(state_path).read().model_dump_json(indent=2))


if __name__ == "__main__":
    app()
