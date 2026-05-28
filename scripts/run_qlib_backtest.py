from __future__ import annotations

from pathlib import Path

import typer

from quant_agent.cli import research_qlib


def main(
    config: Path = Path("configs/research/baseline_lgb_alpha158.yaml"),
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    research_qlib(config=config, env_config=env_config, project_root=project_root)


if __name__ == "__main__":
    typer.run(main)
