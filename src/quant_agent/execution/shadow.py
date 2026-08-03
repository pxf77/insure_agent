from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from quant_agent.execution.gateway import BrokerSnapshot, ReadOnlyExecutionGateway


class ShadowRunResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    shadow_run_id: str
    artifact_dir: Path
    snapshot_path: Path
    manifest_path: Path
    reused: bool


def _canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class LiveShadowRunner:
    """Capture broker truth through a capability-limited, read-only gateway."""

    def __init__(
        self,
        *,
        artifact_root: str | Path,
        allow_live_shadow: bool,
        allow_live_trading: bool = False,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.allow_live_shadow = allow_live_shadow
        self.allow_live_trading = allow_live_trading

    def run(self, gateway: ReadOnlyExecutionGateway) -> ShadowRunResult:
        if not self.allow_live_shadow:
            raise ValueError("live_shadow is disabled by environment configuration")
        if self.allow_live_trading:
            raise ValueError("live_shadow cannot run while live trading is enabled")
        health = gateway.health()
        if not health.connected or not health.read_only:
            raise ValueError(f"read-only gateway is not healthy: {health.message}")
        snapshot = gateway.read_snapshot()
        if snapshot.provider_id != health.provider_id:
            raise ValueError("gateway health and snapshot provider IDs do not match")
        return self._persist(snapshot)

    def _persist(self, snapshot: BrokerSnapshot) -> ShadowRunResult:
        snapshot_content = _canonical_json(snapshot.model_dump(mode="json"))
        identity = {
            "schema_version": "1.0",
            "mode": "live_shadow",
            "provider_id": snapshot.provider_id,
            "account_id": snapshot.account.account_id,
            "as_of": snapshot.as_of.isoformat(),
            "snapshot_sha256": _sha256(snapshot_content),
            "can_submit_orders": False,
        }
        manifest_content = _canonical_json(identity)
        shadow_run_id = f"shadow-{_sha256(manifest_content)[:20]}"
        artifact_dir = self.artifact_root / "shadow_runs" / shadow_run_id
        if artifact_dir.exists():
            self._verify_existing(artifact_dir, snapshot_content, manifest_content)
            return self._result(artifact_dir, shadow_run_id, reused=True)

        temporary = artifact_dir.parent / f".{shadow_run_id}.{uuid4().hex}.tmp"
        try:
            artifact_dir.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(artifact_dir.parent, 0o700)
            temporary.mkdir(mode=0o700, exist_ok=False)
            snapshot_path = temporary / "broker_snapshot.json"
            manifest_path = temporary / "manifest.json"
            snapshot_path.write_bytes(snapshot_content)
            manifest_path.write_bytes(manifest_content)
            os.chmod(snapshot_path, 0o600)
            os.chmod(manifest_path, 0o600)
            os.rename(temporary, artifact_dir)
        except FileExistsError:
            if temporary.exists():
                shutil.rmtree(temporary)
            self._verify_existing(artifact_dir, snapshot_content, manifest_content)
            return self._result(artifact_dir, shadow_run_id, reused=True)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        return self._result(artifact_dir, shadow_run_id, reused=False)

    @staticmethod
    def _verify_existing(
        artifact_dir: Path,
        snapshot_content: bytes,
        manifest_content: bytes,
    ) -> None:
        if artifact_dir.is_symlink() or not artifact_dir.is_dir():
            raise ValueError("live-shadow artifact path is unsafe")
        snapshot_path = artifact_dir / "broker_snapshot.json"
        manifest_path = artifact_dir / "manifest.json"
        if stat.S_IMODE(artifact_dir.stat().st_mode) & 0o077:
            raise ValueError("live-shadow artifact directory permissions are unsafe")
        for path in (snapshot_path, manifest_path):
            if path.is_symlink() or not path.is_file():
                raise ValueError("live-shadow artifact file is unsafe")
            if stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise ValueError("live-shadow artifact file permissions are unsafe")
        if snapshot_path.read_bytes() != snapshot_content:
            raise ValueError("live-shadow snapshot integrity check failed")
        if manifest_path.read_bytes() != manifest_content:
            raise ValueError("live-shadow manifest integrity check failed")

    @staticmethod
    def _result(artifact_dir: Path, shadow_run_id: str, *, reused: bool) -> ShadowRunResult:
        return ShadowRunResult(
            shadow_run_id=shadow_run_id,
            artifact_dir=artifact_dir,
            snapshot_path=artifact_dir / "broker_snapshot.json",
            manifest_path=artifact_dir / "manifest.json",
            reused=reused,
        )
