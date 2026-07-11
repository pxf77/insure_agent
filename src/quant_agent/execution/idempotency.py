from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from quant_agent.execution.v2_models import ExecutionIntent


class IdempotencyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str
    order_id: UUID
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IdempotencyState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    records: list[IdempotencyRecord] = Field(default_factory=list)


class IdempotencyStore:
    def __init__(self, path: str | Path, *, lock_timeout_seconds: float = 5.0):
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.lock_timeout_seconds = lock_timeout_seconds

    def claim(self, intent: ExecutionIntent) -> tuple[UUID, bool]:
        intent_hash = hashlib.sha256(
            (
                json.dumps(
                    intent.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        ).hexdigest()
        order_id = uuid5(NAMESPACE_URL, f"order:{intent.idempotency_key}")
        with self._locked():
            state = self._read_unlocked()
            existing = next(
                (
                    record
                    for record in state.records
                    if record.idempotency_key == intent.idempotency_key
                ),
                None,
            )
            if existing is not None:
                if existing.intent_sha256 != intent_hash or existing.order_id != order_id:
                    raise ValueError("idempotency key is already bound to a different intent")
                return existing.order_id, True
            records = [
                *state.records,
                IdempotencyRecord(
                    idempotency_key=intent.idempotency_key,
                    order_id=order_id,
                    intent_sha256=intent_hash,
                ),
            ]
            records.sort(key=lambda item: item.idempotency_key)
            self._write_unlocked(IdempotencyState(records=records))
        return order_id, False

    def read(self) -> IdempotencyState:
        return self._read_unlocked()

    def _read_unlocked(self) -> IdempotencyState:
        if not self.path.exists():
            return IdempotencyState()
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("idempotency state path is unsafe")
        return IdempotencyState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def _write_unlocked(self, state: IdempotencyState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.is_symlink():
            raise ValueError("idempotency state path is unsafe")
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
                    raise TimeoutError("timed out waiting for idempotency lock")
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
