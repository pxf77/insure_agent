from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from quant_agent.risk.v2_models import ApprovalEvidence


class ApprovalState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    records: list[ApprovalEvidence] = Field(default_factory=list)
    revoked_ids: list[UUID] = Field(default_factory=list)

    def trusted(self, approval_id: UUID) -> ApprovalEvidence | None:
        if approval_id in self.revoked_ids:
            return None
        return next(
            (record for record in self.records if record.approval_id == approval_id),
            None,
        )


class ApprovalStore:
    """Trusted local approval registry with serialized immutable issuance."""

    def __init__(self, path: str | Path, *, lock_timeout_seconds: float = 5.0):
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.lock_timeout_seconds = lock_timeout_seconds

    def read(self) -> ApprovalState:
        return self._read_unlocked()

    def write(self, state: ApprovalState) -> None:
        with self._locked():
            self._write_unlocked(state)

    def issue(self, approval: ApprovalEvidence) -> ApprovalEvidence:
        with self._locked():
            state = self._read_unlocked()
            existing = next(
                (
                    record
                    for record in state.records
                    if record.approval_id == approval.approval_id
                ),
                None,
            )
            if existing is not None:
                if existing != approval:
                    raise ValueError("approval_id is already bound to different evidence")
                if approval.approval_id in state.revoked_ids:
                    raise ValueError("revoked approval_id cannot be reissued")
                return existing
            records = sorted(
                [*state.records, approval],
                key=lambda item: str(item.approval_id),
            )
            self._write_unlocked(
                ApprovalState(records=records, revoked_ids=state.revoked_ids)
            )
        return approval

    def revoke(self, approval_id: UUID) -> None:
        with self._locked():
            state = self._read_unlocked()
            if not any(record.approval_id == approval_id for record in state.records):
                raise ValueError("cannot revoke unknown approval_id")
            revoked = sorted(set([*state.revoked_ids, approval_id]), key=str)
            self._write_unlocked(
                ApprovalState(records=state.records, revoked_ids=revoked)
            )

    def _read_unlocked(self) -> ApprovalState:
        if not self.path.exists():
            return ApprovalState()
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("approval state path is unsafe")
        return ApprovalState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def _write_unlocked(self, state: ApprovalState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.is_symlink():
            raise ValueError("approval state path is unsafe")
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(
                state.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out waiting for approval state lock")
                time.sleep(0.02)
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            yield
        finally:
            os.close(descriptor)
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
