from __future__ import annotations

from pathlib import Path

import typer

from quant_agent.cli import data_convert


def main(
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    data_convert(config=config, project_root=project_root)


if __name__ == "__main__":
    typer.run(main)
