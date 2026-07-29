from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import typer

from quant_agent.common.config import load_app_config
from quant_agent.common.paths import ProjectPaths
from quant_agent.common.run_index import RunIndex
from quant_agent.data.providers import MarketDataProvider, provider_from_config
from quant_agent.data.qlib_converter import QlibConverter
from quant_agent.data.snapshots import DataQualityError, DataSnapshotStore
from quant_agent.execution.order_router import PaperTradingRunner
from quant_agent.research.qlib_runner import QlibRunner
from quant_agent.research.report_writer import ReportWriter
from quant_agent.risk.engine import RiskEngine
from quant_agent.risk.reports import summarize_risk_decision
from quant_agent.workflow.daily import DailyWorkflow, DailyWorkflowResult

app = typer.Typer(help="A-share quant agent command line interface.")
data_app = typer.Typer(help="Data ingestion and conversion commands.")
research_app = typer.Typer(help="Research commands.")
risk_app = typer.Typer(help="Risk validation commands.")
paper_app = typer.Typer(help="Paper trading commands.")
report_app = typer.Typer(help="Report commands.")
run_app = typer.Typer(help="Pipeline commands.")
approval_app = typer.Typer(help="Manual approval commands.")
app.add_typer(data_app, name="data")
app.add_typer(research_app, name="research")
app.add_typer(risk_app, name="risk")
app.add_typer(paper_app, name="paper")
app.add_typer(report_app, name="report")
app.add_typer(run_app, name="run")
app.add_typer(approval_app, name="approval")


def _load_paths(config_path: Path, project_root: Path) -> tuple[ProjectPaths, str, bool]:
    config = load_app_config(config_path)
    paths = ProjectPaths.from_config(config, project_root=project_root)
    return paths, config.app.env, config.runtime.allow_live_trading


def _artifact_root(config_path: Path, project_root: Path) -> Path:
    paths, _, _ = _load_paths(config_path, project_root)
    return paths.artifact_dir


def _market_data_provider(
    name: str,
    *,
    project_root: Path = Path("."),
) -> MarketDataProvider:
    try:
        return provider_from_config(
            name,
            config_dir=project_root / "configs" / "data",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _echo_daily_result(result: DailyWorkflowResult) -> None:
    typer.echo(f"run_id: {result.run_id}")
    typer.echo(f"status: {result.status.value}")
    typer.echo(f"manifest: {result.manifest_path}")
    if result.report_path:
        typer.echo(f"report: {result.report_path}")
    if result.instruction:
        typer.echo(f"next: {result.instruction}")


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
def init(
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Create local artifact directories."""
    paths, _, _ = _load_paths(config, project_root)
    paths.ensure()
    typer.echo(f"initialized artifacts under {paths.artifact_dir}")


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


@data_app.command("sync")
def data_sync(
    trade_date: str = typer.Option(..., "--trade-date", help="Snapshot cutoff date."),
    provider: str = typer.Option(
        "sample",
        "--provider",
        help="sample, akshare, or tushare",
    ),
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Synchronize and validate an immutable canonical market-data snapshot."""
    paths, _, _ = _load_paths(config, project_root)
    paths.ensure()
    try:
        requested_date = date.fromisoformat(trade_date)
        result = DataSnapshotStore(paths.artifact_dir).synchronize(
            _market_data_provider(provider, project_root=project_root),
            requested_date,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except DataQualityError as exc:
        typer.echo(f"data_version: {exc.manifest.data_version}")
        typer.echo(f"valid: {exc.manifest.valid}")
        typer.echo(f"snapshot: {exc.manifest.snapshot_dir}")
        raise typer.Exit(2) from exc
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"data_version: {result.manifest.data_version}")
    typer.echo(f"valid: {result.manifest.valid}")
    typer.echo(f"reused: {result.reused}")
    typer.echo(f"manifest: {result.manifest_path}")


@research_app.command("qlib")
def research_qlib(
    config: Path = Path("configs/research/baseline_lgb_alpha158.yaml"),
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Run deterministic local research baseline and generate target positions."""
    paths, _, _ = _load_paths(env_config, project_root)
    result = QlibRunner(
        config_path=config,
        artifact_root=paths.artifact_dir,
        raw_data_dir=paths.raw_data,
    ).run_backtest()
    typer.echo(f"research_run: {result.run_id}")
    typer.echo(f"target_positions.json: {result.target_positions_path}")
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
    run_id: str | None = None,
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
    account_value: float = 1_000_000,
) -> None:
    """Run local mock paper execution from approved positions."""
    if run_id:
        result = DailyWorkflow(
            project_root=project_root,
            env_config_path=env_config,
        ).execute(run_id)
        _echo_daily_result(result)
        return
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
    index = RunIndex(artifact_root)
    latest = index.read_legacy() or index.read()
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


@run_app.command("daily")
def run_daily(
    trade_date: str = typer.Option(..., "--trade-date"),
    provider: str = typer.Option("sample", "--provider"),
    config: Path = Path("configs/env/dev.yaml"),
    research_config: Path = Path("configs/research/daily_momentum.yaml"),
    risk_config: Path = Path("configs/risk/default.yaml"),
    execution_config: Path = Path("configs/execution/paper_daily.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Run the strict daily workflow until manual approval is required."""
    try:
        requested_date = date.fromisoformat(trade_date)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    result = DailyWorkflow(
        project_root=project_root,
        env_config_path=config,
        research_config_path=research_config,
        risk_config_path=risk_config,
        execution_config_path=execution_config,
    ).start(
        trade_date=requested_date,
        provider_name=provider,
    )
    _echo_daily_result(result)


@run_app.command("resume")
def run_resume(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Resume the first failed or incomplete stage of a strict daily run."""
    result = DailyWorkflow(
        project_root=project_root,
        env_config_path=config,
    ).resume(run_id)
    _echo_daily_result(result)


@run_app.command("show")
def run_show(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Show a strict daily run manifest."""
    manifest = DailyWorkflow(
        project_root=project_root,
        env_config_path=config,
    ).show(run_id)
    typer.echo(manifest.model_dump_json(indent=2))


@approval_app.command("grant")
def approval_grant(
    run_id: str = typer.Option(..., "--run-id"),
    approver: str = typer.Option(..., "--approver"),
    expires_in_minutes: int = typer.Option(60, "--expires-in-minutes", min=1),
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    """Grant an expiring approval for the exact risk-approved order plan."""
    record, path = DailyWorkflow(
        project_root=project_root,
        env_config_path=config,
    ).grant_approval(
        run_id=run_id,
        approver=approver,
        expires_in_minutes=expires_in_minutes,
    )
    typer.echo(f"run_id: {record.run_id}")
    typer.echo(f"plan_checksum: {record.plan_checksum}")
    typer.echo(f"expires_at: {record.expires_at}")
    typer.echo(f"approval: {path}")


if __name__ == "__main__":
    app()
