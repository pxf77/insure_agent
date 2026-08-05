from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from quant_agent.common.io import (
    read_json,
    write_immutable_json,
    write_immutable_text,
)
from quant_agent.common.provenance import code_version, configuration_hash
from quant_agent.data.adjustment import apply_forward_adjustment
from quant_agent.data.qlib_binary import QlibBinaryConverter
from quant_agent.data.snapshots import DataSnapshotStore
from quant_agent.research.config import StrictResearchConfig
from quant_agent.research.engines import (
    DeterministicMomentumEngine,
    QlibWorkflowEngine,
    ResearchEngineOutput,
)
from quant_agent.schemas.data import DataManifest
from quant_agent.schemas.research import (
    PredictionsPayload,
    TargetPosition,
    TargetPositionRequest,
)


@dataclass(frozen=True)
class SnapshotResearchResult:
    run_id: str
    artifact_dir: Path
    predictions_path: Path
    target_positions_path: Path
    metrics_path: Path
    report_path: Path
    config_hash: str
    code_version: str


class SnapshotResearchRunner:
    def __init__(
        self,
        *,
        config_path: str | Path,
        artifact_root: str | Path,
        data_manifest_path: str | Path,
        run_id: str,
        project_root: str | Path = ".",
        config_hash_override: str | None = None,
        code_version_override: str | None = None,
    ):
        self.config_path = Path(config_path)
        self.artifact_root = Path(artifact_root)
        self.data_manifest_path = Path(data_manifest_path)
        self.run_id = run_id
        self.project_root = Path(project_root)
        self.config_hash_override = config_hash_override
        self.code_version_override = code_version_override

    def run(self) -> SnapshotResearchResult:
        config_text = self.config_path.read_text(encoding="utf-8")
        manifest = DataManifest.model_validate(read_json(self.data_manifest_path))
        config = StrictResearchConfig.from_yaml_text(
            config_text,
            trade_date=date.fromisoformat(manifest.trade_date),
        )
        resolved_config = config.model_dump(mode="json")
        resolved_config_hash = self.config_hash_override or configuration_hash(
            resolved_config
        )
        revision = self.code_version_override or code_version(self.project_root)
        if not manifest.valid:
            raise ValueError("research requires a valid data manifest")
        if config.temporal.test_end.isoformat() > manifest.trade_date:
            raise ValueError(
                "research test_end cannot be later than the bound snapshot trade_date"
            )
        daily_bar = DataSnapshotStore.load_dataset(manifest, "daily_bar")
        adjust_factor = DataSnapshotStore.load_dataset(manifest, "adjust_factor")
        adjusted_daily_bar = apply_forward_adjustment(daily_bar, adjust_factor)
        provider_uri: Path | None = None
        if config.research.engine == "deterministic_momentum":
            output = DeterministicMomentumEngine().run(
                config=config,
                daily_bar=adjusted_daily_bar,
                provider_uri=None,
            )
        else:
            provider_uri = self._resolve_qlib_provider(config, manifest)
            output = QlibWorkflowEngine().run(
                config=config,
                daily_bar=adjusted_daily_bar,
                provider_uri=provider_uri,
            )
        positions = self._build_targets(output, config)
        generated_at = manifest.retrieved_at
        target_payload = TargetPositionRequest(
            run_id=self.run_id,
            strategy_id=config.research.strategy_id,
            trade_date=manifest.trade_date,
            generated_at=generated_at,
            universe=config.research.universe,
            benchmark=config.research.benchmark,
            positions=positions,
            metadata={
                "engine": output.engine,
                "data_manifest": str(self.data_manifest_path),
                "temporal": config.temporal.model_dump(mode="json"),
                "costs": config.costs.model_dump(mode="json"),
            },
            as_of=manifest.trade_date,
            data_version=manifest.data_version,
            config_hash=resolved_config_hash,
            code_version=revision,
            input_checksums={"data_snapshot": manifest.data_version},
            label_horizon_days=config.research.label_horizon_days,
            execution_lag_days=config.research.execution_lag_days,
        )
        predictions = PredictionsPayload(
            run_id=self.run_id,
            strategy_id=config.research.strategy_id,
            engine=output.engine,
            data_version=manifest.data_version,
            config_hash=resolved_config_hash,
            code_version=revision,
            label_horizon_days=config.research.label_horizon_days,
            execution_lag_days=config.research.execution_lag_days,
            predictions=output.predictions,
        )
        metrics: dict[str, Any] = {
            "schema_version": "2.0",
            "run_id": self.run_id,
            "strategy_id": config.research.strategy_id,
            "engine": output.engine,
            "universe": config.research.universe,
            "benchmark": config.research.benchmark,
            "data_version": manifest.data_version,
            "config_hash": resolved_config_hash,
            "code_version": revision,
            "temporal": config.temporal.model_dump(mode="json"),
            "label_horizon_days": config.research.label_horizon_days,
            "execution_lag_days": config.research.execution_lag_days,
            "cost_assumptions": config.costs.model_dump(mode="json"),
            "metrics": output.metrics,
            "promotion": {
                "automatic": False,
                "reason": "strategy promotion requires human review of sample-out evidence",
            },
        }
        artifact_dir = self.artifact_root / "research_runs" / self.run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        predictions_path = artifact_dir / "predictions.json"
        target_positions_path = artifact_dir / "target_positions.json"
        metrics_path = artifact_dir / "metrics.json"
        report_path = artifact_dir / "report.md"
        write_immutable_json(predictions_path, predictions)
        write_immutable_json(target_positions_path, target_payload)
        write_immutable_json(metrics_path, metrics)
        write_immutable_text(artifact_dir / "config_snapshot.yaml", config_text)
        write_immutable_text(
            report_path,
            self._render_report(metrics, target_payload, generated_at),
        )
        return SnapshotResearchResult(
            run_id=self.run_id,
            artifact_dir=artifact_dir,
            predictions_path=predictions_path,
            target_positions_path=target_positions_path,
            metrics_path=metrics_path,
            report_path=report_path,
            config_hash=resolved_config_hash,
            code_version=revision,
        )

    def _resolve_qlib_provider(
        self,
        config: StrictResearchConfig,
        manifest: DataManifest,
    ) -> Path:
        configured = config.qlib.provider_uri
        if configured and configured != "__snapshot__":
            candidate = Path(configured)
            if not candidate.is_absolute():
                candidate = self.project_root / candidate
            return candidate
        return QlibBinaryConverter(self.artifact_root).convert(manifest).qlib_dir

    @staticmethod
    def _build_targets(
        output: ResearchEngineOutput,
        config: StrictResearchConfig,
    ) -> list[TargetPosition]:
        if not output.predictions:
            raise ValueError("research engine produced no predictions")
        latest_date = max(item.trade_date for item in output.predictions)
        latest = sorted(
            (item for item in output.predictions if item.trade_date == latest_date),
            key=lambda item: (item.rank, item.symbol),
        )[: config.portfolio.topk]
        if not latest:
            raise ValueError("research engine produced no latest-date predictions")
        weight = min(1 / len(latest), config.portfolio.max_position_weight)
        return [
            TargetPosition(
                symbol=item.symbol,
                target_weight=weight,
                score=item.score,
                rank=index + 1,
                reason=f"{output.engine} score at feature cutoff {item.feature_cutoff}",
            )
            for index, item in enumerate(latest)
        ]

    @staticmethod
    def _render_report(
        metrics: dict[str, Any],
        targets: TargetPositionRequest,
        generated_at: str,
    ) -> str:
        values = metrics["metrics"]
        return (
            "# Reproducible Research Report\n\n"
            f"- run_id: `{metrics['run_id']}`\n"
            f"- engine: `{metrics['engine']}`\n"
            f"- data_version: `{metrics['data_version']}`\n"
            f"- generated_at: `{generated_at}`\n"
            f"- label_horizon_days: {metrics['label_horizon_days']}\n"
            f"- execution_lag_days: {metrics['execution_lag_days']}\n"
            f"- target_positions: {len(targets.positions)}\n"
            f"- automatic_promotion: `False`\n\n"
            "## Sample-out Metrics\n\n"
            f"```json\n{values}\n```\n"
        )
