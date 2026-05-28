from __future__ import annotations

from pathlib import Path

import typer

from quant_agent.cli import paper_run


def main(
    approved: Path | None = None,
    env_config: Path = Path("configs/env/dev.yaml"),
    project_root: Path = Path("."),
    account_value: float = 1_000_000,
) -> None:
    paper_run(
        approved=approved,
        env_config=env_config,
        project_root=project_root,
        account_value=account_value,
    )


if __name__ == "__main__":
    typer.run(main)
