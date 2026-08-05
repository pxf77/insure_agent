from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class AppSettings(BaseModel):
    env: str = "dev"
    timezone: str = "Asia/Shanghai"
    artifact_dir: Path = Path("artifacts")
    log_level: str = "INFO"


class RuntimeSettings(BaseModel):
    communication_mode: str = "file"
    allow_live_trading: bool = False
    allow_live_shadow: bool = False
    require_manual_approval: bool = True


class StorageSettings(BaseModel):
    database_url: str = "sqlite:///artifacts/portfolio.db"
    mlflow_tracking_uri: str = "artifacts/mlruns"


class PathSettings(BaseModel):
    raw_data: Path = Path("artifacts/data/raw")
    qlib_data: Path = Path("artifacts/data/qlib/cn_data")
    research_runs: Path = Path("artifacts/research_runs")
    risk_runs: Path = Path("artifacts/risk_runs")
    execution_runs: Path = Path("artifacts/execution_runs")
    reports: Path = Path("artifacts/reports")


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: AppSettings = Field(default_factory=AppSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    paths: PathSettings = Field(default_factory=PathSettings)


def load_app_config(config_path: str | Path) -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle) or {}
    return AppConfig.model_validate(data)
