from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from quant_agent.risk.v2_models import KillSwitchRecord, KillSwitchScope


class KillSwitchState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    records: list[KillSwitchRecord] = Field(default_factory=list)


class KillSwitchStore:
    """Atomic local persistence for global, account, and strategy kill switches."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def read(self) -> KillSwitchState:
        if not self.path.exists():
            return KillSwitchState()
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("kill-switch state path is unsafe")
        return KillSwitchState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def write(self, state: KillSwitchState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def set(
        self,
        *,
        scope: KillSwitchScope,
        scope_id: str | None,
        active: bool,
        reduce_only: bool,
        reason_code: str,
        message: str,
        changed_by: str,
        changed_at: datetime | None = None,
    ) -> KillSwitchRecord:
        timestamp = changed_at or datetime.now(timezone.utc)
        switch_id = self._switch_id(scope, scope_id)
        record = KillSwitchRecord(
            switch_id=switch_id,
            scope=scope,
            scope_id=scope_id,
            active=active,
            reduce_only=reduce_only,
            reason_code=reason_code,
            message=message,
            changed_at=timestamp,
            changed_by=changed_by,
        )
        state = self.read()
        records = [item for item in state.records if item.switch_id != switch_id]
        records.append(record)
        records.sort(key=lambda item: item.switch_id)
        self.write(KillSwitchState(records=records))
        return record

    def active_for(self, *, account_id: str, strategy_id: str) -> list[KillSwitchRecord]:
        records = []
        for record in self.read().records:
            if not record.active:
                continue
            if record.scope == KillSwitchScope.GLOBAL:
                records.append(record)
            elif record.scope == KillSwitchScope.ACCOUNT and record.scope_id == account_id:
                records.append(record)
            elif record.scope == KillSwitchScope.STRATEGY and record.scope_id == strategy_id:
                records.append(record)
        return sorted(records, key=lambda item: item.switch_id)

    @staticmethod
    def _switch_id(scope: KillSwitchScope, scope_id: str | None) -> str:
        return scope.value.lower() if scope_id is None else f"{scope.value.lower()}:{scope_id}"
