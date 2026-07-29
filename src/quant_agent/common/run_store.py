from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from quant_agent.common.io import atomic_write_json, file_sha256
from quant_agent.schemas.run import (
    ArtifactReference,
    Provenance,
    RunManifest,
    RunStatus,
    StageAttempt,
    StageRecord,
    StageStatus,
)

DEFAULT_DAILY_STAGES = (
    "DATA_SYNC",
    "DATA_VALIDATE",
    "RESEARCH",
    "PLAN",
    "RISK",
    "REPORT_PRE",
    "APPROVAL",
    "EXECUTION",
    "REPORT_FINAL",
)


def utc_now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class RunManifestStore:
    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root)
        self.runs_dir = self.artifact_root / "runs"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "manifest.json"

    def create(
        self,
        *,
        run_id: str,
        trade_date: str,
        provenance: Provenance,
        stages: tuple[str, ...] = DEFAULT_DAILY_STAGES,
    ) -> RunManifest:
        path = self.manifest_path(run_id)
        if path.exists():
            existing = self.load(run_id)
            if existing.trade_date != trade_date or existing.provenance.config_hash != (
                provenance.config_hash
            ):
                raise ValueError(f"run_id already exists with different provenance: {run_id}")
            return existing
        now = utc_now_text()
        manifest = RunManifest(
            run_id=run_id,
            trade_date=trade_date,
            created_at=now,
            updated_at=now,
            provenance=provenance,
            stages=[StageRecord(name=name) for name in stages],
        )
        self._save(manifest)
        return manifest

    def load(self, run_id: str) -> RunManifest:
        path = self.manifest_path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"run manifest not found: {path}")
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def start_stage(
        self,
        run_id: str,
        stage_name: str,
        *,
        input_checksums: dict[str, str] | None = None,
        retry_completed: bool = False,
    ) -> RunManifest:
        manifest = self.load(run_id)
        stage_index, stage = self._stage(manifest, stage_name)
        for previous in manifest.stages[:stage_index]:
            if previous.status not in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
                raise ValueError(
                    f"cannot start {stage_name}; previous stage {previous.name} "
                    f"is {previous.status.value}"
                )
        if stage.status == StageStatus.COMPLETED and not retry_completed:
            return manifest
        if stage.status == StageStatus.COMPLETED:
            completed_followers = [
                follower.name
                for follower in manifest.stages[stage_index + 1 :]
                if follower.status == StageStatus.COMPLETED
            ]
            if completed_followers:
                raise ValueError(
                    f"cannot retry {stage_name}; later stages are completed: "
                    f"{completed_followers}"
                )
        if stage.status == StageStatus.RUNNING:
            raise ValueError(f"stage is already running: {stage_name}")
        attempt = StageAttempt(
            attempt=len(stage.attempts) + 1,
            started_at=utc_now_text(),
            input_checksums=input_checksums or {},
        )
        stage.attempts.append(attempt)
        stage.status = StageStatus.RUNNING
        manifest.status = RunStatus.RUNNING
        manifest.current_stage = stage_name
        manifest.error = None
        return self._save(manifest)

    def complete_stage(
        self,
        run_id: str,
        stage_name: str,
        *,
        artifacts: Mapping[str, str | Path] | None = None,
        output_checksums: dict[str, str] | None = None,
    ) -> RunManifest:
        manifest = self.load(run_id)
        _, stage = self._stage(manifest, stage_name)
        attempt = self._running_attempt(stage)
        registered_checksums = dict(output_checksums or {})
        for name, artifact_path_value in (artifacts or {}).items():
            artifact_path = Path(artifact_path_value)
            if not artifact_path.exists():
                raise FileNotFoundError(f"stage artifact not found: {artifact_path}")
            checksum = file_sha256(artifact_path)
            registered_checksums[name] = checksum
            manifest.artifacts[name] = ArtifactReference(
                name=name,
                path=str(artifact_path),
                sha256=checksum,
                stage=stage_name,
            )
        attempt.status = StageStatus.COMPLETED
        attempt.ended_at = utc_now_text()
        attempt.output_checksums = registered_checksums
        stage.status = StageStatus.COMPLETED
        manifest.current_stage = None
        manifest.status = RunStatus.RUNNING
        return self._save(manifest)

    def skip_stage(self, run_id: str, stage_name: str) -> RunManifest:
        manifest = self.load(run_id)
        stage_index, stage = self._stage(manifest, stage_name)
        for previous in manifest.stages[:stage_index]:
            if previous.status not in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
                raise ValueError(f"cannot skip {stage_name} before {previous.name}")
        if stage.status == StageStatus.COMPLETED:
            return manifest
        stage.status = StageStatus.SKIPPED
        manifest.current_stage = None
        return self._save(manifest)

    def fail_stage(self, run_id: str, stage_name: str, error: str) -> RunManifest:
        manifest = self.load(run_id)
        _, stage = self._stage(manifest, stage_name)
        attempt = self._running_attempt(stage)
        attempt.status = StageStatus.FAILED
        attempt.ended_at = utc_now_text()
        attempt.error = error
        stage.status = StageStatus.FAILED
        manifest.status = RunStatus.FAILED
        manifest.current_stage = stage_name
        manifest.error = error
        return self._save(manifest)

    def mark_awaiting_approval(self, run_id: str) -> RunManifest:
        manifest = self.load(run_id)
        _, approval = self._stage(manifest, "APPROVAL")
        if approval.status not in {StageStatus.PENDING, StageStatus.FAILED}:
            raise ValueError(f"approval stage is {approval.status.value}")
        manifest.status = RunStatus.AWAITING_APPROVAL
        manifest.current_stage = "APPROVAL"
        manifest.error = None
        return self._save(manifest)

    def set_data_version(self, run_id: str, data_version: str) -> RunManifest:
        manifest = self.load(run_id)
        existing = manifest.provenance.data_version
        if existing is not None and existing != data_version:
            raise ValueError("run is already bound to a different data version")
        manifest.provenance.data_version = data_version
        return self._save(manifest)

    def next_incomplete_stage(self, run_id: str) -> str | None:
        manifest = self.load(run_id)
        for stage in manifest.stages:
            if stage.status not in {StageStatus.COMPLETED, StageStatus.SKIPPED}:
                return stage.name
        return None

    def complete_run(self, run_id: str) -> RunManifest:
        manifest = self.load(run_id)
        self.verify_artifacts(manifest)
        incomplete = [
            stage.name
            for stage in manifest.stages
            if stage.status not in {StageStatus.COMPLETED, StageStatus.SKIPPED}
        ]
        if incomplete:
            raise ValueError(f"cannot complete run; incomplete stages: {incomplete}")
        manifest.status = RunStatus.COMPLETED
        manifest.current_stage = None
        manifest.error = None
        return self._save(manifest)

    @staticmethod
    def verify_artifacts(manifest: RunManifest) -> None:
        for name, reference in manifest.artifacts.items():
            path = Path(reference.path)
            if not path.is_file():
                raise FileNotFoundError(
                    f"run artifact is missing: {name} ({path})"
                )
            actual = file_sha256(path)
            if actual != reference.sha256:
                raise ValueError(
                    f"run artifact checksum mismatch: {name} ({path})"
                )

    def terminate_run(self, run_id: str, error: str) -> RunManifest:
        manifest = self.load(run_id)
        for stage in manifest.stages:
            if stage.status == StageStatus.PENDING:
                stage.status = StageStatus.SKIPPED
        manifest.status = RunStatus.FAILED
        manifest.current_stage = None
        manifest.error = error
        return self._save(manifest)

    def _save(self, manifest: RunManifest) -> RunManifest:
        manifest.updated_at = utc_now_text()
        atomic_write_json(self.manifest_path(manifest.run_id), manifest)
        return manifest

    @staticmethod
    def _stage(manifest: RunManifest, name: str) -> tuple[int, StageRecord]:
        for index, stage in enumerate(manifest.stages):
            if stage.name == name:
                return index, stage
        raise KeyError(f"unknown run stage: {name}")

    @staticmethod
    def _running_attempt(stage: StageRecord) -> StageAttempt:
        if not stage.attempts or stage.attempts[-1].status != StageStatus.RUNNING:
            raise ValueError(f"stage is not running: {stage.name}")
        return stage.attempts[-1]
