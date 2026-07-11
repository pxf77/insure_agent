from __future__ import annotations

from pathlib import Path

import typer

from quant_agent.evals.risk import render_risk_eval_report, run_risk_evals


def main(
    suite: Path = Path("evals/risk/v0.4.yaml"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    report = run_risk_evals(suite)
    typer.echo(
        report.model_dump_json(indent=2)
        if json_output
        else render_risk_eval_report(report)
    )
    if not report.success:
        raise typer.Exit(1)


if __name__ == "__main__":
    typer.run(main)
