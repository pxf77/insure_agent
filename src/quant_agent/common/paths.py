from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quant_agent.common.config import AppConfig


def resolve_project_path(project_root: str | Path, path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path(project_root) / candidate


@dataclass(frozen=True)
class ProjectPaths:
    project_root: Path
    artifact_dir: Path
    raw_data: Path
    qlib_data: Path
    research_runs: Path
    risk_runs: Path
    execution_runs: Path
    reports: Path

    @classmethod
    def from_config(cls, config: AppConfig, project_root: str | Path = ".") -> ProjectPaths:
        root = Path(project_root)
        return cls(
            project_root=root,
            artifact_dir=resolve_project_path(root, config.app.artifact_dir),
            raw_data=resolve_project_path(root, config.paths.raw_data),
            qlib_data=resolve_project_path(root, config.paths.qlib_data),
            research_runs=resolve_project_path(root, config.paths.research_runs),
            risk_runs=resolve_project_path(root, config.paths.risk_runs),
            execution_runs=resolve_project_path(root, config.paths.execution_runs),
            reports=resolve_project_path(root, config.paths.reports),
        )

    def ensure(self) -> None:
        for path in (
            self.artifact_dir,
            self.raw_data,
            self.qlib_data,
            self.research_runs,
            self.risk_runs,
            self.execution_runs,
            self.reports,
        ):
            path.mkdir(parents=True, exist_ok=True)
