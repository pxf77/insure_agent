from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from quant_agent.schemas.v2 import RiskDecisionV2

_REQUIRED_RISK_FILES = {
    "target_portfolio.json",
    "risk_context.json",
    "risk_policy.yaml",
    "kill_switch_state.json",
    "approval_state.json",
    "risk_decision.json",
}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _decision_id(identity: dict[str, str]) -> str:
    return f"risk-{_sha256(_canonical_json(identity))[:20]}"


@dataclass(frozen=True)
class VerifiedRiskDecision:
    decision_id: str
    decision: RiskDecisionV2
    artifact_dir: Path
    manifest: dict[str, object]


class TrustedRiskDecisionLoader:
    """Verify a risk artifact before execution consumes its decision."""

    def load(self, artifact_dir: str | Path) -> VerifiedRiskDecision:
        directory = Path(artifact_dir)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("risk artifact directory is missing or unsafe")
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("risk artifact manifest is missing or unsafe")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        decision_id = str(manifest.get("decision_id", ""))
        if not decision_id or directory.name != decision_id:
            raise ValueError("risk artifact decision_id does not match directory")
        hashes = cast(dict[str, str], manifest.get("files", {}))
        if set(hashes) != _REQUIRED_RISK_FILES:
            raise ValueError("risk artifact manifest contains an unexpected artifact set")
        actual_files: set[str] = set()
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"risk artifact contains a symbolic link: {path}")
            if path.is_file():
                actual_files.add(path.relative_to(directory).as_posix())
        if actual_files != _REQUIRED_RISK_FILES | {"manifest.json"}:
            raise ValueError("risk artifact contains missing or unexpected files")
        for name, expected_hash in hashes.items():
            path = directory / name
            if not path.is_file() or _sha256(path.read_bytes()) != expected_hash:
                raise ValueError(f"risk artifact failed integrity check: {name}")

        recomputed_identity = {
            "schema_version": "1.0",
            "target_sha256": _sha256((directory / "target_portfolio.json").read_bytes()),
            "context_sha256": _sha256((directory / "risk_context.json").read_bytes()),
            "policy_sha256": _sha256((directory / "risk_policy.yaml").read_bytes()),
            "kill_switch_state_sha256": _sha256(
                (directory / "kill_switch_state.json").read_bytes()
            ),
            "approval_state_sha256": _sha256(
                (directory / "approval_state.json").read_bytes()
            ),
            "decision_sha256": _sha256((directory / "risk_decision.json").read_bytes()),
        }
        if manifest.get("identity") != recomputed_identity:
            raise ValueError("risk artifact identity does not match persisted inputs")
        if _decision_id(recomputed_identity) != decision_id:
            raise ValueError("risk artifact decision_id failed identity verification")

        decision = RiskDecisionV2.model_validate_json(
            (directory / "risk_decision.json").read_text(encoding="utf-8")
        )
        if not decision.approved or decision.decision.value == "REJECT":
            raise ValueError("execution requires an approved risk decision")
        return VerifiedRiskDecision(
            decision_id=decision_id,
            decision=decision,
            artifact_dir=directory,
            manifest=cast(dict[str, object], manifest),
        )
