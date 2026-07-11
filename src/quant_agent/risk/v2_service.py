from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml

from quant_agent.risk.kill_switch_store import KillSwitchStore
from quant_agent.risk.v2_engine import DeterministicRiskEngine
from quant_agent.risk.v2_models import RiskContext, RiskPolicy
from quant_agent.schemas.v2 import RiskDecisionV2, TargetPortfolio

_REQUIRED_FILES = {
    "target_portfolio.json",
    "risk_context.json",
    "risk_policy.yaml",
    "risk_decision.json",
}


def _canonical_json(payload: object) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_component(value: str) -> str:
    return "".join(character if character.isalnum() or character in "_.-" else "_" for character in value)


class RiskDecisionService:
    def __init__(self, *, artifact_root: str | Path, kill_switch_path: str | Path):
        self.artifact_root = Path(artifact_root)
        self.kill_switch_store = KillSwitchStore(kill_switch_path)

    def evaluate_files(
        self,
        *,
        target_path: str | Path,
        context_path: str | Path,
        policy_path: str | Path,
    ) -> tuple[RiskDecisionV2, Path, bool]:
        target_content = Path(target_path).read_bytes()
        context_content = Path(context_path).read_bytes()
        policy_content = Path(policy_path).read_bytes()
        target = TargetPortfolio.model_validate_json(target_content)
        context = RiskContext.model_validate_json(context_content)
        policy_payload = yaml.safe_load(policy_content.decode("utf-8")) or {}
        policy = RiskPolicy.model_validate(policy_payload)
        decision = DeterministicRiskEngine(
            policy=policy,
            kill_switch_store=self.kill_switch_store,
        ).evaluate(target, context)
        decision_content = _canonical_json(decision.model_dump(mode="json"))
        identity = {
            "schema_version": "1.0",
            "target_sha256": _sha256(target_content),
            "context_sha256": _sha256(context_content),
            "policy_sha256": _sha256(policy_content),
            "kill_switch_state_sha256": self._kill_switch_state_hash(),
            "decision_sha256": _sha256(decision_content),
        }
        decision_id = f"risk-{_sha256(_canonical_json(identity))[:20]}"
        artifact_dir = (
            self.artifact_root
            / "risk_v2"
            / _safe_component(target.run_id)
            / decision_id
        )
        if artifact_dir.exists():
            self._verify_existing(artifact_dir, decision_id)
            return decision, artifact_dir, True

        files = {
            "target_portfolio.json": target_content,
            "risk_context.json": context_content,
            "risk_policy.yaml": policy_content,
            "risk_decision.json": decision_content,
        }
        temporary = artifact_dir.parent / f".{decision_id}.{uuid4().hex}.tmp"
        try:
            temporary.mkdir(parents=True, exist_ok=False)
            for relative_path, content in files.items():
                (temporary / relative_path).write_bytes(content)
            manifest = {
                "schema_version": "1.0",
                "decision_id": decision_id,
                "target_run_id": target.run_id,
                "policy_version": policy.policy_version,
                "identity": identity,
                "files": {
                    name: _sha256(content)
                    for name, content in sorted(files.items())
                },
            }
            (temporary / "manifest.json").write_bytes(_canonical_json(manifest))
            artifact_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(temporary, artifact_dir)
            except FileExistsError:
                shutil.rmtree(temporary)
                self._verify_existing(artifact_dir, decision_id)
                return decision, artifact_dir, True
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        return decision, artifact_dir, False

    def _kill_switch_state_hash(self) -> str:
        state = self.kill_switch_store.read()
        return _sha256(_canonical_json(state.model_dump(mode="json")))

    @staticmethod
    def _verify_existing(artifact_dir: Path, decision_id: str) -> None:
        manifest_path = artifact_dir / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("risk artifact directory is incomplete or unsafe")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("decision_id") != decision_id or artifact_dir.name != decision_id:
            raise ValueError("risk artifact decision_id mismatch")
        expected_hashes = cast(dict[str, str], payload.get("files", {}))
        if set(expected_hashes) != _REQUIRED_FILES:
            raise ValueError("risk artifact manifest contains an unexpected artifact set")
        actual_files: set[str] = set()
        for path in artifact_dir.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"risk artifact contains a symbolic link: {path}")
            if path.is_file():
                actual_files.add(path.relative_to(artifact_dir).as_posix())
        if actual_files != _REQUIRED_FILES | {"manifest.json"}:
            raise ValueError("risk artifact contains missing or unexpected files")
        for name, expected_hash in expected_hashes.items():
            path = artifact_dir / name
            if not path.is_file() or _sha256(path.read_bytes()) != expected_hash:
                raise ValueError(f"risk artifact failed integrity check: {name}")
        identity = cast(dict[str, Any], payload.get("identity", {}))
        recomputed = {
            "schema_version": "1.0",
            "target_sha256": _sha256((artifact_dir / "target_portfolio.json").read_bytes()),
            "context_sha256": _sha256((artifact_dir / "risk_context.json").read_bytes()),
            "policy_sha256": _sha256((artifact_dir / "risk_policy.yaml").read_bytes()),
            "kill_switch_state_sha256": identity.get("kill_switch_state_sha256"),
            "decision_sha256": _sha256((artifact_dir / "risk_decision.json").read_bytes()),
        }
        if identity != recomputed or f"risk-{_sha256(_canonical_json(recomputed))[:20]}" != decision_id:
            raise ValueError("risk artifact failed identity verification")
