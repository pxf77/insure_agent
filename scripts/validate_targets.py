from __future__ import annotations

from pathlib import Path

import typer

from quant_agent.cli import risk_validate


def main(
    target: Path | None = None,
    config: Path = Path("configs/risk/default.yaml"),
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
) -> None:
    risk_validate(target=target, config=config, env_config=env_config, project_root=project_root)


if __name__ == "__main__":
    typer.run(main)
