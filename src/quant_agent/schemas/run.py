from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class StageStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class Provenance(BaseModel):
    data_version: str | None = None
    config_hash: str
    code_version: str
    resolved_config: dict[str, Any] = Field(default_factory=dict)
    input_checksums: dict[str, str] = Field(default_factory=dict)


class ArtifactReference(BaseModel):
    name: str
    path: str
    sha256: str
    stage: str


class StageAttempt(BaseModel):
    attempt: int = Field(ge=1)
    started_at: str
    ended_at: str | None = None
    status: StageStatus = StageStatus.RUNNING
    error: str | None = None
    input_checksums: dict[str, str] = Field(default_factory=dict)
    output_checksums: dict[str, str] = Field(default_factory=dict)


class StageRecord(BaseModel):
    name: str
    status: StageStatus = StageStatus.PENDING
    attempts: list[StageAttempt] = Field(default_factory=list)


class RunManifest(BaseModel):
    schema_version: str = "2.0"
    run_id: str
    trade_date: str
    created_at: str
    updated_at: str
    status: RunStatus = RunStatus.PENDING
    current_stage: str | None = None
    provenance: Provenance
    stages: list[StageRecord]
    artifacts: dict[str, ArtifactReference] = Field(default_factory=dict)
    error: str | None = None
