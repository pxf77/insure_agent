from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DataValidationResult(BaseModel):
    rule_id: str
    passed: bool
    severity: str
    dataset: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DatasetManifest(BaseModel):
    name: str
    schema_version: str = "1.0"
    path: str
    rows: int = Field(ge=0)
    sha256: str
    columns: list[str]


class DataManifest(BaseModel):
    schema_version: str = "1.0"
    run_id: str | None = None
    data_version: str
    provider: str
    trade_date: str
    as_of: str | None = None
    config_hash: str | None = None
    code_version: str | None = None
    input_checksums: dict[str, str] = Field(default_factory=dict)
    retrieved_at: str
    valid: bool
    snapshot_dir: str
    datasets: dict[str, DatasetManifest]
    validations: list[DataValidationResult] = Field(default_factory=list)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
