from __future__ import annotations

from pathlib import Path

import typer

from quant_agent.cli import data_pull


def main(
    sample: bool = typer.Option(False, "--sample", help="Generate deterministic sample data."),
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    data_pull(sample=sample, config=config, project_root=project_root)


if __name__ == "__main__":
    typer.run(main)
