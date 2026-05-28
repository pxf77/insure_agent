from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast


class RunIndex:
    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root)
        self.path = self.artifact_root / "latest.json"

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return cast(dict[str, Any], data)

    def update(self, **entries: Any) -> dict[str, Any]:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        data = self.read()
        data.update({key: value for key, value in entries.items() if value is not None})
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data

    def require(self, key: str) -> Any:
        data = self.read()
        if key not in data:
            raise FileNotFoundError(f"latest run index does not contain {key!r}")
        return data[key]
