from __future__ import annotations

from pathlib import Path

import typer

from quant_agent.cli import init as init_command


def main(
    config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    init_command(config=config, project_root=project_root)


if __name__ == "__main__":
    typer.run(main)
