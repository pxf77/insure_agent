from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from quant_agent.common.io import atomic_write_json
from quant_agent.schemas.run import RunManifest, RunStatus


class RunIndex:
    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root)
        self.path = self.artifact_root / "latest.json"
        self.legacy_path = self.artifact_root / "latest_legacy.json"

    def read(self) -> dict[str, Any]:
        selected = self.path if self.path.exists() else self.legacy_path
        if not selected.exists():
            return {}
        data = json.loads(selected.read_text(encoding="utf-8"))
        return cast(dict[str, Any], data)

    def read_legacy(self) -> dict[str, Any]:
        if not self.legacy_path.exists():
            return {}
        data = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        return cast(dict[str, Any], data)

    def update(self, **entries: Any) -> dict[str, Any]:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        data = self.read_legacy()
        data.update({key: value for key, value in entries.items() if value is not None})
        atomic_write_json(self.legacy_path, data)
        return data

    def require(self, key: str) -> Any:
        data = self.read_legacy() or self.read()
        if key not in data:
            raise FileNotFoundError(f"latest run index does not contain {key!r}")
        return data[key]

    def publish_completed(self, manifest: RunManifest) -> dict[str, Any]:
        if manifest.status != RunStatus.COMPLETED:
            raise ValueError("only a completed run may be published")
        existing = self.read()
        existing_trade_date = existing.get("trade_date")
        if (
            isinstance(existing_trade_date, str)
            and existing_trade_date > manifest.trade_date
        ):
            return existing
        data: dict[str, Any] = {
            "schema_version": "2.0",
            "completed_run": manifest.run_id,
            "trade_date": manifest.trade_date,
            "data_version": manifest.provenance.data_version,
            "run_manifest": str(
                self.artifact_root / "runs" / manifest.run_id / "manifest.json"
            ),
        }
        data.update(
            {name: reference.path for name, reference in sorted(manifest.artifacts.items())}
        )
        atomic_write_json(self.path, data)
        return data
