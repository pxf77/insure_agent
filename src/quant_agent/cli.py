from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import typer

from quant_agent.common.config import load_app_config
from quant_agent.common.doctor import DoctorProfile, render_doctor_report, run_doctor
from quant_agent.common.paths import ProjectPaths
from quant_agent.common.run_index import RunIndex
from quant_agent.data.providers.base import MarketDataProvider
from quant_agent.data.providers.synthetic import SyntheticMarketDataProvider
from quant_agent.data.providers.synthetic_research import SyntheticResearchMarketDataProvider
from quant_agent.data.qlib_converter import QlibConverter
from quant_agent.data.snapshot import SnapshotBuilder
from quant_agent.evals.contracts import render_contract_eval_report, run_contract_evals
from quant_agent.evals.data import render_data_eval_report, run_data_evals
from quant_agent.evals.research import render_research_eval_report, run_research_evals
from quant_agent.execution.order_router import PaperTradingRunner
from quant_agent.research.qlib_runner import QlibRunner
from quant_agent.research.report_writer import ReportWriter
from quant_agent.research.snapshot_runner import SnapshotResearchRunner
from quant_agent.risk.engine import RiskEngine
from quant_agent.risk.reports import summarize_risk_decision
from quant_agent.schemas.exporter import export_contract_schemas

app = typer.Typer(help="A-share quant agent command line interface.")
data_app = typer.Typer(help="Data ingestion and conversion commands.")
research_app = typer.Typer(help="Research commands.")
risk_app = typer.Typer(help="Risk validation commands.")
paper_app = typer.Typer(help="Paper trading commands.")
report_app = typer.Typer(help="Report commands.")
run_app = typer.Typer(help="Pipeline commands.")
contracts_app = typer.Typer(help="Versioned contract commands.")
eval_app = typer.Typer(help="Evaluation suite commands.")
app.add_typer(data_app, name="data")
app.add_typer(research_app, name="research")
app.add_typer(risk_app, name="risk")
app.add_typer(paper_app, name="paper")
app.add_typer(report_app, name="report")
app.add_typer(run_app, name="run")
app.add_typer(contracts_app, name="contracts")
app.add_typer(eval_app, name="eval")


def _load_paths(config_path: Path, project_root: Path) -> tuple[ProjectPaths, str, bool]:
    config = load_app_config(config_path)
    paths = ProjectPaths.from_config(config, project_root=project_root)
    return paths, config.app.env, config.runtime.allow_live_trading


def _artifact_root(config_path: Path, project_root: Path) -> Path:
    paths, _, _ = _load_paths(config_path, project_root)
    return paths.artifact_dir


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter(f"invalid ISO-8601 datetime: {value}") from exc


def _market_data_provider(name: str) -> MarketDataProvider:
    if name == "synthetic":
        return SyntheticMarketDataProvider()
    if name == "synthetic-research":
        return SyntheticResearchMarketDataProvider()
    raise typer.BadParameter("provider must be one of: synthetic, synthetic-research")


@app.command()
def status(config: Path = Path("configs/env/dev.yaml")) -> None:
    """Show environment, data, risk, and execution status."""
    loaded = load_app_config(config)
    live_status = "enabled" if loaded.runtime.allow_live_trading else "disabled"
    typer.echo(f"env: {loaded.app.env}")
    typer.echo(f"artifact_dir: {loaded.app.artifact_dir}")
    typer.echo(f"communication_mode: {loaded.runtime.communication_mode}")
    typer.echo(f"live_trading: {live_status}")


@app.command()
def doctor(
    profile: str = typer.Option("mvp", help="Check profile: mvp, research, or execution."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Validate the local environment and trading safety defaults."""
    try:
        selected_profile = DoctorProfile(profile.lower())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in DoctorProfile)
        raise typer.BadParameter(f"profile must be one of: {allowed}") from exc

    report = run_doctor(
        config_path=config,
        project_root=project_root,
        profile=selected_profile,
    )
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(render_doctor_report(report))
    if report.has_failures:
        raise typer.Exit(1)


@app.command()
def init(
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Create local artifact directories."""
    paths, _, _ = _load_paths(config, project_root)
    paths.ensure()
    typer.echo(f"initialized artifacts under {paths.artifact_dir}")


@contracts_app.command("export")
def contracts_export(
    output: Path = Path("artifacts/contracts"),
) -> None:
    """Export deterministic JSON Schemas for versioned contracts."""
    result = export_contract_schemas(output)
    typer.echo(f"exported {len(result.schema_paths)} contract schemas")
    typer.echo(f"index.json: {result.index_path}")


@eval_app.command("contracts")
def eval_contracts_command(
    suite: Path = Path("evals/contracts/v0.1.yaml"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Run the versioned contract evaluation suite."""
    report = run_contract_evals(suite)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(render_contract_eval_report(report))
    if not report.success:
        raise typer.Exit(1)


@eval_app.command("data")
def eval_data_command(
    suite: Path = Path("evals/data/v0.2.yaml"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Run the data-quality and point-in-time evaluation suite."""
    report = run_data_evals(suite)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(render_data_eval_report(report))
    if not report.success:
        raise typer.Exit(1)


@eval_app.command("research")
def eval_research_command(
    suite: Path = Path("evals/research/v0.3.yaml"),
    config: Path = Path("configs/research/snapshot_baseline.yaml"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Run the reproducibility and leakage research evaluation suite."""
    report = run_research_evals(suite, config_path=config)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(render_research_eval_report(report))
    if not report.success:
        raise typer.Exit(1)


@data_app.command("pull")
def data_pull(
    sample: bool = typer.Option(False, "--sample", help="Generate deterministic sample data."),
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Pull or generate raw market data."""
    if not sample:
        raise typer.BadParameter("Phase 1 only supports --sample; real data providers are disabled")

    paths, _, _ = _load_paths(config, project_root)
    paths.ensure()
    sample_frame = pd.DataFrame(
        [
            {
                "trade_date": "2026-05-20",
                "symbol": "600519.SH",
                "open": 100.0,
                "high": 110.0,
                "low": 99.0,
                "close": 105.0,
                "volume": 1000,
                "amount": 105000.0,
            },
            {
                "trade_date": "2026-05-20",
                "symbol": "000001.SZ",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 2000,
                "amount": 21000.0,
            },
            {
                "trade_date": "2026-05-21",
                "symbol": "300750.SZ",
                "open": 200.0,
                "high": 210.0,
                "low": 198.0,
                "close": 205.0,
                "volume": 1200,
                "amount": 246000.0,
            },
        ]
    )
    output_path = paths.raw_data / "daily_bar.csv"
    sample_frame.to_csv(output_path, index=False)
    typer.echo(f"wrote sample daily bars to {output_path}")


@data_app.command("snapshot")
def data_snapshot(
    as_of: str = typer.Option(
        "2026-05-22T16:00:00+08:00",
        help="Point-in-time cutoff as an aware ISO-8601 datetime.",
    ),
    provider: str = typer.Option(
        "synthetic",
        help="Provider: synthetic or synthetic-research.",
    ),
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Build an immutable point-in-time daily-bar snapshot."""
    paths, _, _ = _load_paths(config, project_root)
    result = SnapshotBuilder(
        snapshot_root=paths.artifact_dir / "data" / "snapshots"
    ).build_daily_bars(
        _market_data_provider(provider),
        as_of=_parse_datetime(as_of),
    )
    action = "reused" if result.reused else "created"
    typer.echo(f"snapshot {action}: {result.manifest.snapshot_id}")
    typer.echo(f"visible_rows: {result.manifest.visible_rows}")
    typer.echo(f"snapshot_dir: {result.snapshot_dir}")
    typer.echo(f"manifest.json: {result.manifest_path}")


@data_app.command("convert")
def data_convert(
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Convert raw market data into the local Qlib layout."""
    paths, _, _ = _load_paths(config, project_root)
    paths.ensure()
    result = QlibConverter(raw_dir=paths.raw_data, qlib_dir=paths.qlib_data).convert()
    typer.echo(f"converted {result.rows} rows for {len(result.symbols)} symbols")
    typer.echo(f"instruments: {result.instrument_path}")
    typer.echo(f"metadata: {result.metadata_path}")


@research_app.command("qlib")
def research_qlib(
    config: Path = Path("configs/research/baseline_lgb_alpha158.yaml"),
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Run deterministic local v1 research and generate target positions."""
    paths, _, _ = _load_paths(env_config, project_root)
    result = QlibRunner(
        config_path=config,
        artifact_root=paths.artifact_dir,
        raw_data_dir=paths.raw_data,
    ).run_backtest()
    typer.echo(f"research_run: {result.run_id}")
    typer.echo(f"target_positions.json: {result.target_positions_path}")
    typer.echo(f"metrics.json: {result.metrics_path}")


@research_app.command("snapshot")
def research_snapshot(
    snapshot: Path = typer.Option(..., "--snapshot", help="Verified snapshot directory."),
    config: Path = Path("configs/research/snapshot_baseline.yaml"),
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Run the reproducible v2 snapshot-backed research baseline."""
    paths, _, _ = _load_paths(env_config, project_root)
    result = SnapshotResearchRunner(
        snapshot_dir=snapshot,
        config_path=config,
        artifact_root=paths.artifact_dir,
    ).run()
    action = "reused" if result.reused else "created"
    typer.echo(f"research {action}: {result.run_id}")
    typer.echo(f"artifact_dir: {result.artifact_dir}")
    typer.echo(f"target_portfolio.json: {result.target_portfolio_path}")
    typer.echo(f"metrics.json: {result.metrics_path}")


@risk_app.command("validate")
def risk_validate(
    target: Path | None = None,
    config: Path = Path("configs/risk/default.yaml"),
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Validate target positions and write approved positions."""
    artifact_root = _artifact_root(env_config, project_root)
    target_path = target or Path(RunIndex(artifact_root).require("target_positions"))
    decision, output_path = RiskEngine.from_config(config, artifact_root).validate_file(target_path)
    typer.echo(summarize_risk_decision(decision))
    typer.echo(f"approved_positions.json: {output_path}")
    if not decision.approved:
        raise typer.Exit(2)


@paper_app.command("run")
def paper_run(
    approved: Path | None = None,
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
    account_value: float = 1_000_000,
) -> None:
    """Run local mock paper execution from approved positions."""
    paths, _, _ = _load_paths(env_config, project_root)
    approved_path = approved or Path(RunIndex(paths.artifact_dir).require("approved_positions"))
    orders_path, trades_path = PaperTradingRunner(
        artifact_root=paths.artifact_dir,
        raw_data_dir=paths.raw_data,
        account_value=account_value,
    ).run(approved_path)
    typer.echo(f"orders.json: {orders_path}")
    typer.echo(f"trades.json: {trades_path}")


@report_app.command("generate")
def report_generate(
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Generate a markdown report for the latest local MVP run."""
    artifact_root = _artifact_root(env_config, project_root)
    latest = RunIndex(artifact_root).read()
    report_path = ReportWriter(artifact_root).write_from_files(
        metrics_path=Path(str(latest["metrics"])),
        approved_positions_path=Path(str(latest["approved_positions"])),
        orders_path=Path(str(latest["orders"])) if latest.get("orders") else None,
        trades_path=Path(str(latest["trades"])) if latest.get("trades") else None,
    )
    typer.echo(f"report.md: {report_path}")


@report_app.command("latest")
def report_latest(
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Print the latest report path."""
    artifact_root = _artifact_root(env_config, project_root)
    typer.echo(RunIndex(artifact_root).require("report"))


@app.command()
def latest(
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Show latest run artifact index."""
    artifact_root = _artifact_root(config, project_root)
    data: dict[str, Any] = RunIndex(artifact_root).read()
    if not data:
        typer.echo("No runs found")
        return
    for key in sorted(data):
        typer.echo(f"{key}: {data[key]}")


@run_app.command("pipeline")
def run_pipeline(
    mode: str = "paper",
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Run the full local MVP file-based pipeline."""
    if mode != "paper":
        raise typer.BadParameter("local MVP pipeline only supports --mode paper")
    init(config=config, project_root=project_root)
    data_pull(sample=True, config=config, project_root=project_root)
    data_convert(config=config, project_root=project_root)
    research_qlib(env_config=config, project_root=project_root)
    risk_validate(env_config=config, project_root=project_root)
    paper_run(env_config=config, project_root=project_root)
    report_generate(env_config=config, project_root=project_root)
    latest(config=config, project_root=project_root)


if __name__ == "__main__":
    app()
