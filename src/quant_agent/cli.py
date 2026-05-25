from __future__ import annotations

from pathlib import Path

import pandas as pd
import typer

from quant_agent.common.config import load_app_config
from quant_agent.common.paths import ProjectPaths
from quant_agent.data.qlib_converter import QlibConverter

app = typer.Typer(help="A-share quant agent command line interface.")
data_app = typer.Typer(help="Data ingestion and conversion commands.")
app.add_typer(data_app, name="data")


def _load_paths(config_path: Path, project_root: Path) -> tuple[ProjectPaths, str, bool]:
    config = load_app_config(config_path)
    paths = ProjectPaths.from_config(config, project_root=project_root)
    return paths, config.app.env, config.runtime.allow_live_trading


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


if __name__ == "__main__":
    app()
