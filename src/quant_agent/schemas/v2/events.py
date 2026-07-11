from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from quant_agent.schemas.v2.primitives import AwareDateTime


class EventEnvelope(BaseModel):
    """Auditable envelope for cross-module events."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9_.-]+$")
    occurred_at: AwareDateTime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    correlation_id: UUID = Field(default_factory=uuid4)
    causation_id: UUID | None = None
    producer: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
