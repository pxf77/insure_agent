from __future__ import annotations

from pathlib import Path

import typer

from quant_agent.cli import report_generate


def main(
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    report_generate(env_config=env_config, project_root=project_root)


if __name__ == "__main__":
    typer.run(main)
