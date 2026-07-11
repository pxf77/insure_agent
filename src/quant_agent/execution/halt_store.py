from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from quant_agent.schemas.v2.primitives import AwareDateTime


class ExecutionHaltState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    active: bool = False
    reason_code: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[A-Z0-9_]+$",
    )
    message: str | None = Field(default=None, max_length=1000)
    changed_at: AwareDateTime | None = None
    changed_by: str | None = Field(default=None, max_length=200)
    run_id: str | None = Field(default=None, max_length=200)


class ExecutionHaltStore:
    """Serialized fail-closed halt state for paper execution submissions."""

    def __init__(self, path: str | Path, *, lock_timeout_seconds: float = 5.0):
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.lock_timeout_seconds = lock_timeout_seconds

    def read(self) -> ExecutionHaltState:
        if not self.path.exists():
            return ExecutionHaltState()
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("execution halt state path is unsafe")
        return ExecutionHaltState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def halt(
        self,
        *,
        reason_code: str,
        message: str,
        changed_by: str,
        run_id: str | None,
        changed_at: datetime | None = None,
    ) -> ExecutionHaltState:
        state = ExecutionHaltState(
            active=True,
            reason_code=reason_code,
            message=message,
            changed_at=changed_at or datetime.now(timezone.utc),
            changed_by=changed_by,
            run_id=run_id,
        )
        self._write(state)
        return state

    def clear(
        self,
        *,
        changed_by: str,
        message: str,
        changed_at: datetime | None = None,
    ) -> ExecutionHaltState:
        current = self.read()
        if not current.active:
            return current
        state = ExecutionHaltState(
            active=False,
            reason_code="MANUAL_CLEAR",
            message=message,
            changed_at=changed_at or datetime.now(timezone.utc),
            changed_by=changed_by,
            run_id=current.run_id,
        )
        self._write(state)
        return state

    def assert_open(self) -> None:
        state = self.read()
        if state.active:
            raise ValueError(
                f"execution halted: {state.reason_code or 'UNKNOWN'} - "
                f"{state.message or 'no message'}"
            )

    def _write(self, state: ExecutionHaltState) -> None:
        with self._locked():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.is_symlink():
                raise ValueError("execution halt state path is unsafe")
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
                    raise TimeoutError("timed out waiting for execution halt lock")
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
