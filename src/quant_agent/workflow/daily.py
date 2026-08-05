from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from quant_agent.common.config import load_app_config
from quant_agent.common.io import (
    content_sha256,
    file_sha256,
    read_json,
    write_immutable_json,
    write_immutable_text,
)
from quant_agent.common.paths import ProjectPaths
from quant_agent.common.provenance import code_version, configuration_hash
from quant_agent.common.run_index import RunIndex
from quant_agent.common.run_store import RunManifestStore
from quant_agent.data.providers import MarketDataProvider, provider_from_config
from quant_agent.data.snapshots import DataSnapshotStore
from quant_agent.execution.config import PaperAccountSettings
from quant_agent.execution.ledger import PortfolioLedger
from quant_agent.execution.paper import LedgerPaperExecutor
from quant_agent.execution.planning import PortfolioOrderPlanner
from quant_agent.research.config import StrictResearchConfig
from quant_agent.research.daily_report import DailyReportWriter
from quant_agent.research.daily_snapshot_runner import SnapshotResearchRunner
from quant_agent.risk.approval import ApprovalStore
from quant_agent.risk.plan_engine import PlanRiskEngine
from quant_agent.schemas.data import DataManifest
from quant_agent.schemas.portfolio import (
    ApprovalRecord,
    ExecutionResult,
    OrderPlan,
)
from quant_agent.schemas.research import TargetPositionRequest
from quant_agent.schemas.risk import PlanRiskAssessment
from quant_agent.schemas.run import (
    Provenance,
    RunManifest,
    RunStatus,
    StageRecord,
    StageStatus,
)


@dataclass(frozen=True)
class DailyWorkflowResult:
    run_id: str
    status: RunStatus
    manifest_path: Path
    report_path: Path | None = None
    instruction: str | None = None


class DailyWorkflow:
    def __init__(
        self,
        *,
        project_root: str | Path = ".",
        env_config_path: str | Path = "configs/env/dev.yaml",
        research_config_path: str | Path = "configs/research/daily_momentum.yaml",
        risk_config_path: str | Path = "configs/risk/default.yaml",
        execution_config_path: str | Path = "configs/execution/paper_daily.yaml",
    ):
        self.project_root = Path(project_root)
        self.env_config_path = self._config_path(env_config_path)
        self.research_config_path = self._config_path(research_config_path)
        self.risk_config_path = self._config_path(risk_config_path)
        self.execution_config_path = self._config_path(execution_config_path)
        app_config = load_app_config(self.env_config_path)
        self.paths = ProjectPaths.from_config(app_config, project_root=self.project_root)
        self.paths.ensure()
        self.store = RunManifestStore(self.paths.artifact_dir)
        self.ledger = PortfolioLedger(self.paths.artifact_dir / "portfolio.db")

    def start(
        self,
        *,
        trade_date: date,
        provider_name: str = "sample",
    ) -> DailyWorkflowResult:
        provider = self._provider(provider_name)
        snapshot = DataSnapshotStore(self.paths.artifact_dir).synchronize(
            provider,
            trade_date,
        )
        resolved_config, settings = self._resolved_config(
            trade_date=trade_date,
            provider_name=provider_name,
        )
        resolved_hash = configuration_hash(resolved_config)
        revision = code_version(self.project_root)
        strategy_id = str(resolved_config["research"]["research"]["strategy_id"])
        identity_hash = content_sha256(
            {
                "trade_date": trade_date.isoformat(),
                "data_version": snapshot.manifest.data_version,
                "config_hash": resolved_hash,
            }
        )[:8]
        run_id = (
            f"{trade_date.strftime('%Y%m%d')}-daily-{strategy_id}-{identity_hash}"
        )
        manifest = self.store.create(
            run_id=run_id,
            trade_date=trade_date.isoformat(),
            provenance=Provenance(
                data_version=snapshot.manifest.data_version,
                config_hash=resolved_hash,
                code_version=revision,
                resolved_config=resolved_config,
                input_checksums={
                    "data_manifest": file_sha256(snapshot.manifest_path),
                },
            ),
        )
        if manifest.status == RunStatus.COMPLETED:
            return self._completed_result(manifest)
        if manifest.status == RunStatus.AWAITING_APPROVAL:
            self.store.verify_artifacts(manifest)
            return self._result(
                manifest,
                instruction=self._approval_instruction(run_id),
            )
        self._complete_data_stages(
            run_id=run_id,
            snapshot_manifest_path=snapshot.manifest_path,
        )
        return self._continue(run_id, settings=settings)

    def resume(self, run_id: str) -> DailyWorkflowResult:
        manifest = self.store.load(run_id)
        if manifest.status == RunStatus.COMPLETED:
            return self._completed_result(manifest)
        if manifest.status == RunStatus.AWAITING_APPROVAL:
            self.store.verify_artifacts(manifest)
            return self._result(
                manifest,
                instruction=self._approval_instruction(run_id),
            )
        if manifest.error and manifest.error.startswith("RISK_REJECTED"):
            return self._result(manifest, instruction="Risk rejected this run.")
        settings = self._settings_from_manifest(manifest)
        return self._continue(run_id, settings=settings)

    def show(self, run_id: str) -> RunManifest:
        return self.store.load(run_id)

    def grant_approval(
        self,
        *,
        run_id: str,
        approver: str,
        expires_in_minutes: int = 60,
    ) -> tuple[ApprovalRecord, Path]:
        manifest = self.store.load(run_id)
        self.store.verify_artifacts(manifest)
        if manifest.status == RunStatus.COMPLETED:
            raise ValueError("cannot grant approval for a completed run")
        assessment = self._risk_assessment(manifest)
        if not assessment.approved or assessment.adjusted_plan is None:
            raise ValueError("cannot approve a risk-rejected run")
        stage = self._stage(manifest, "APPROVAL")
        self.store.start_stage(
            run_id,
            "APPROVAL",
            retry_completed=stage.status == StageStatus.COMPLETED,
        )
        try:
            record, path = ApprovalStore(self.paths.artifact_dir).grant(
                plan=assessment.adjusted_plan,
                assessment=assessment,
                approver=approver,
                expires_in_minutes=expires_in_minutes,
            )
            self.store.complete_stage(
                run_id,
                "APPROVAL",
                artifacts={"approval": path},
            )
        except BaseException as exc:
            self.store.fail_stage(run_id, "APPROVAL", str(exc))
            raise
        return record, path

    def execute(self, run_id: str) -> DailyWorkflowResult:
        manifest = self.store.load(run_id)
        self.store.verify_artifacts(manifest)
        approval_stage = self._stage(manifest, "APPROVAL")
        if approval_stage.status != StageStatus.COMPLETED:
            raise ValueError(self._approval_instruction(run_id))
        return self._continue(
            run_id,
            settings=self._settings_from_manifest(manifest),
        )

    def _continue(
        self,
        run_id: str,
        *,
        settings: PaperAccountSettings,
    ) -> DailyWorkflowResult:
        while True:
            manifest = self.store.load(run_id)
            self.store.verify_artifacts(manifest)
            if manifest.status == RunStatus.COMPLETED:
                return self._completed_result(manifest)
            next_stage = self.store.next_incomplete_stage(run_id)
            if next_stage is None:
                completed = self.store.complete_run(run_id)
                RunIndex(self.paths.artifact_dir).publish_completed(completed)
                return self._result(completed)
            if next_stage == "RESEARCH":
                self._run_stage(run_id, "RESEARCH", self._research_stage)
            elif next_stage == "PLAN":
                self._run_stage(
                    run_id,
                    "PLAN",
                    lambda current: self._plan_stage(current, settings),
                )
            elif next_stage == "RISK":
                self._run_stage(
                    run_id,
                    "RISK",
                    lambda current: self._risk_stage(current, settings),
                )
            elif next_stage == "REPORT_PRE":
                self._run_stage(run_id, "REPORT_PRE", self._pre_report_stage)
            elif next_stage == "APPROVAL":
                assessment = self._risk_assessment(manifest)
                if not assessment.approved:
                    terminated = self.store.terminate_run(
                        run_id,
                        f"RISK_REJECTED: {assessment.decision}",
                    )
                    return self._result(
                        terminated,
                        instruction="Risk rejected this run.",
                    )
                awaiting = self.store.mark_awaiting_approval(run_id)
                return self._result(
                    awaiting,
                    instruction=self._approval_instruction(run_id),
                )
            elif next_stage == "EXECUTION":
                self._run_stage(
                    run_id,
                    "EXECUTION",
                    lambda current: self._execution_stage(current, settings),
                )
            elif next_stage == "REPORT_FINAL":
                self._run_stage(run_id, "REPORT_FINAL", self._final_report_stage)
            elif next_stage in {"DATA_SYNC", "DATA_VALIDATE"}:
                raise ValueError(
                    f"run {run_id} is missing initial data stage {next_stage}; "
                    "start a new daily run"
                )
            else:
                raise KeyError(f"unsupported workflow stage: {next_stage}")

    def _complete_data_stages(
        self,
        *,
        run_id: str,
        snapshot_manifest_path: Path,
    ) -> None:
        manifest = self.store.load(run_id)
        if self._stage(manifest, "DATA_SYNC").status != StageStatus.COMPLETED:
            self.store.start_stage(
                run_id,
                "DATA_SYNC",
                input_checksums={"request": manifest.trade_date},
            )
            self.store.complete_stage(
                run_id,
                "DATA_SYNC",
                artifacts={"data_manifest": snapshot_manifest_path},
            )
        manifest = self.store.load(run_id)
        if self._stage(manifest, "DATA_VALIDATE").status != StageStatus.COMPLETED:
            data_manifest = DataManifest.model_validate(read_json(snapshot_manifest_path))
            health_path = self.store.run_dir(run_id) / "data_health.json"
            self.store.start_stage(
                run_id,
                "DATA_VALIDATE",
                input_checksums={"data_manifest": file_sha256(snapshot_manifest_path)},
            )
            try:
                write_immutable_json(
                    health_path,
                    {
                        "schema_version": "1.0",
                        "run_id": run_id,
                        "trade_date": data_manifest.trade_date,
                        "data_version": data_manifest.data_version,
                        "valid": data_manifest.valid,
                        "validations": [
                            item.model_dump(mode="json")
                            for item in data_manifest.validations
                        ],
                    },
                )
                if not data_manifest.valid:
                    raise ValueError("data validation is not valid")
                self.store.complete_stage(
                    run_id,
                    "DATA_VALIDATE",
                    artifacts={"data_health": health_path},
                )
            except BaseException as exc:
                self.store.fail_stage(run_id, "DATA_VALIDATE", str(exc))
                raise

    def _research_stage(self, manifest: RunManifest) -> dict[str, Path]:
        data_manifest_path = Path(manifest.artifacts["data_manifest"].path)
        research_config_path = self._resolved_config_snapshot(
            manifest,
            section="research",
        )
        result = SnapshotResearchRunner(
            config_path=research_config_path,
            artifact_root=self.paths.artifact_dir,
            data_manifest_path=data_manifest_path,
            run_id=manifest.run_id,
            project_root=self.project_root,
            config_hash_override=manifest.provenance.config_hash,
            code_version_override=manifest.provenance.code_version,
        ).run()
        return {
            "predictions": result.predictions_path,
            "target_positions": result.target_positions_path,
            "metrics": result.metrics_path,
            "research_report": result.report_path,
        }

    def _plan_stage(
        self,
        manifest: RunManifest,
        settings: PaperAccountSettings,
    ) -> dict[str, Path]:
        target_path = Path(manifest.artifacts["target_positions"].path)
        targets = TargetPositionRequest.model_validate_json(
            target_path.read_text(encoding="utf-8")
        )
        data_manifest = self._data_manifest(manifest)
        plan = PortfolioOrderPlanner(
            ledger=self.ledger,
            settings=settings,
            artifact_root=self.paths.artifact_dir,
        ).build(targets=targets, manifest=data_manifest)
        output_dir = self.paths.execution_runs / manifest.run_id
        plan_path = output_dir / "order_plan.json"
        write_immutable_json(plan_path, plan)
        return {"order_plan": plan_path}

    def _risk_stage(
        self,
        manifest: RunManifest,
        settings: PaperAccountSettings,
    ) -> dict[str, Path]:
        plan = self._order_plan(manifest)
        assessment = PlanRiskEngine.from_config(
            config_path=self._resolved_config_snapshot(
                manifest,
                section="risk",
            ),
            artifact_root=self.paths.artifact_dir,
            ledger=self.ledger,
            settings=settings,
        ).evaluate(plan=plan, manifest=self._data_manifest(manifest))
        output_dir = self.paths.risk_runs / manifest.run_id
        assessment_path = output_dir / "risk_assessment.json"
        write_immutable_json(assessment_path, assessment)
        artifacts = {"risk_assessment": assessment_path}
        if assessment.adjusted_plan:
            approved_path = output_dir / "approved_order_plan.json"
            write_immutable_json(approved_path, assessment.adjusted_plan)
            artifacts["approved_order_plan"] = approved_path
        return artifacts

    def _pre_report_stage(self, manifest: RunManifest) -> dict[str, Path]:
        report_path = self._write_daily_report(manifest, kind="pre")
        return {"pre_report": report_path}

    def _execution_stage(
        self,
        manifest: RunManifest,
        settings: PaperAccountSettings,
    ) -> dict[str, Path]:
        result_path = self.paths.execution_runs / manifest.run_id / "execution_result.json"
        if result_path.exists():
            existing = ExecutionResult.model_validate(read_json(result_path))
            plan = self._approved_plan(manifest)
            if (
                existing.run_id != manifest.run_id
                or existing.plan_checksum != plan.plan_checksum
                or existing.data_version != plan.data_version
                or existing.config_hash != plan.config_hash
                or existing.code_version != plan.code_version
            ):
                raise ValueError(
                    "existing execution result is not bound to the current run"
                )
            return {"execution_result": result_path}
        plan = self._approved_plan(manifest)
        approval = ApprovalStore(self.paths.artifact_dir).latest(manifest.run_id)
        result = LedgerPaperExecutor(
            ledger=self.ledger,
            settings=settings,
            artifact_root=self.paths.artifact_dir,
        ).execute(
            plan=plan,
            manifest=self._data_manifest(manifest),
            approval=approval,
        )
        write_immutable_json(result_path, result)
        return {"execution_result": result_path}

    def _final_report_stage(self, manifest: RunManifest) -> dict[str, Path]:
        report_path = self._write_daily_report(manifest, kind="final")
        return {"report": report_path, "final_report": report_path}

    def _write_daily_report(self, manifest: RunManifest, *, kind: str) -> Path:
        metrics = read_json(manifest.artifacts["metrics"].path)
        targets = TargetPositionRequest.model_validate(
            read_json(manifest.artifacts["target_positions"].path)
        )
        assessment = self._risk_assessment(manifest)
        plan = self._approved_plan(manifest)
        approval = None
        try:
            approval = ApprovalStore(self.paths.artifact_dir).latest(manifest.run_id)
        except RuntimeError:
            pass
        execution = (
            ExecutionResult.model_validate(
                read_json(manifest.artifacts["execution_result"].path)
            )
            if "execution_result" in manifest.artifacts
            else None
        )
        if kind not in {"pre", "final"}:
            raise ValueError(f"unsupported report kind: {kind}")
        return DailyReportWriter(self.paths.artifact_dir).write(
            kind="pre" if kind == "pre" else "final",
            manifest=self._data_manifest(manifest),
            metrics=metrics,
            targets=targets,
            plan=plan,
            assessment=assessment,
            approval=approval,
            execution=execution,
        )

    def _run_stage(
        self,
        run_id: str,
        stage_name: str,
        action: Callable[[RunManifest], dict[str, Path]],
    ) -> None:
        manifest = self.store.load(run_id)
        if self._stage(manifest, stage_name).status == StageStatus.COMPLETED:
            return
        self.store.start_stage(
            run_id,
            stage_name,
            input_checksums={
                name: reference.sha256
                for name, reference in sorted(manifest.artifacts.items())
            },
        )
        try:
            artifacts = action(self.store.load(run_id))
            self.store.complete_stage(
                run_id,
                stage_name,
                artifacts=artifacts,
            )
        except BaseException as exc:
            self.store.fail_stage(run_id, stage_name, str(exc))
            raise

    def _resolved_config(
        self,
        *,
        trade_date: date,
        provider_name: str,
    ) -> tuple[dict[str, Any], PaperAccountSettings]:
        app = load_app_config(self.env_config_path)
        research_text = self.research_config_path.read_text(encoding="utf-8")
        research = StrictResearchConfig.from_yaml_text(
            research_text,
            trade_date=trade_date,
        )
        risk = self._yaml(self.risk_config_path)
        execution = self._yaml(self.execution_config_path)
        account_values = dict(execution.get("account", {}))
        account_values["fees"] = execution.get("fees", {})
        settings = PaperAccountSettings.model_validate(account_values)
        resolved = {
            "environment": app.model_dump(mode="json"),
            "research": research.model_dump(mode="json"),
            "risk": risk,
            "execution": settings.model_dump(mode="json"),
            "workflow": {
                "provider": provider_name,
            },
        }
        return resolved, settings

    @staticmethod
    def _settings_from_manifest(manifest: RunManifest) -> PaperAccountSettings:
        values = manifest.provenance.resolved_config.get("execution")
        if not isinstance(values, dict):
            raise ValueError("run manifest is missing resolved execution settings")
        return PaperAccountSettings.model_validate(values)

    def _data_manifest(self, manifest: RunManifest) -> DataManifest:
        return DataManifest.model_validate(
            read_json(manifest.artifacts["data_manifest"].path)
        )

    @staticmethod
    def _order_plan(manifest: RunManifest) -> OrderPlan:
        return OrderPlan.model_validate(read_json(manifest.artifacts["order_plan"].path))

    @staticmethod
    def _approved_plan(manifest: RunManifest) -> OrderPlan:
        key = (
            "approved_order_plan"
            if "approved_order_plan" in manifest.artifacts
            else "order_plan"
        )
        return OrderPlan.model_validate(read_json(manifest.artifacts[key].path))

    @staticmethod
    def _risk_assessment(manifest: RunManifest) -> PlanRiskAssessment:
        return PlanRiskAssessment.model_validate(
            read_json(manifest.artifacts["risk_assessment"].path)
        )

    def _result(
        self,
        manifest: RunManifest,
        *,
        instruction: str | None = None,
    ) -> DailyWorkflowResult:
        report_path = None
        for key in ("final_report", "pre_report"):
            if key in manifest.artifacts:
                report_path = Path(manifest.artifacts[key].path)
                break
        return DailyWorkflowResult(
            run_id=manifest.run_id,
            status=manifest.status,
            manifest_path=self.store.manifest_path(manifest.run_id),
            report_path=report_path,
            instruction=instruction,
        )

    def _completed_result(self, manifest: RunManifest) -> DailyWorkflowResult:
        self.store.verify_artifacts(manifest)
        RunIndex(self.paths.artifact_dir).publish_completed(manifest)
        return self._result(manifest)

    @staticmethod
    def _stage(manifest: RunManifest, name: str) -> StageRecord:
        for stage in manifest.stages:
            if stage.name == name:
                return stage
        raise KeyError(name)

    def _config_path(self, value: str | Path) -> Path:
        candidate = Path(value)
        if candidate.is_absolute() or candidate.exists():
            return candidate
        return self.project_root / candidate

    def _resolved_config_snapshot(
        self,
        manifest: RunManifest,
        *,
        section: str,
    ) -> Path:
        values = manifest.provenance.resolved_config.get(section)
        if not isinstance(values, dict):
            raise ValueError(f"run manifest is missing resolved {section} settings")
        path = self.store.run_dir(manifest.run_id) / "config" / f"{section}.yaml"
        write_immutable_text(
            path,
            yaml.safe_dump(values, sort_keys=True, allow_unicode=True),
        )
        return path

    def _provider(self, name: str) -> MarketDataProvider:
        return provider_from_config(
            name,
            config_dir=self.project_root / "configs" / "data",
        )

    @staticmethod
    def _yaml(path: Path) -> dict[str, Any]:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"configuration must contain a mapping: {path}")
        return data

    @staticmethod
    def _approval_instruction(run_id: str) -> str:
        return f"quant-agent approval grant --run-id {run_id} --approver <name>"
