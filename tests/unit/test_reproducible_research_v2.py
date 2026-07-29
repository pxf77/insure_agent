import importlib.util
import json
import struct
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from quant_agent.data.providers.sample_provider import SampleDataProvider
from quant_agent.data.qlib_binary import QlibBinaryConverter
from quant_agent.data.snapshots import DataSnapshotStore
from quant_agent.research.config import StrictResearchConfig
from quant_agent.research.engines import (
    DeterministicMomentumEngine,
    QlibWorkflowEngine,
    ResearchDependencyError,
)
from quant_agent.research.snapshot_runner import SnapshotResearchRunner
from quant_agent.schemas.research import TargetPositionRequest


def write_research_config(path: Path, *, engine: str = "deterministic_momentum") -> None:
    path.write_text(
        f"""
research:
  engine: {engine}
  strategy_id: daily_momentum_csi300_v1
  universe: CSI300
  benchmark: SH000300
  label_horizon_days: 1
  execution_lag_days: 1
  rebalance_frequency: weekly
temporal:
  train_start: 2026-07-20
  train_end: 2026-07-21
  valid_start: 2026-07-22
  valid_end: 2026-07-23
  test_start: 2026-07-24
  test_end: 2026-07-29
portfolio:
  topk: 3
  lookback_days: 2
  max_position_weight: 0.2
costs:
  commission_bps: 3
  sell_stamp_duty_bps: 5
  transfer_fee_bps: 0.1
  slippage_bps: 10
qlib:
  provider_uri: __snapshot__
  region: cn
  task: {{}}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def create_snapshot(tmp_path: Path):
    return DataSnapshotStore(tmp_path).synchronize(
        SampleDataProvider(),
        date(2026, 7, 29),
    )


def test_qlib_binary_converter_writes_true_feature_layout(tmp_path: Path):
    snapshot = create_snapshot(tmp_path)

    result = QlibBinaryConverter(tmp_path).convert(snapshot.manifest)

    assert result.calendar_path.is_file()
    assert result.instruments_path.is_file()
    assert "SH600519\t" in result.instruments_path.read_text(encoding="utf-8")
    feature_path = result.qlib_dir / "features" / "sh600519" / "close.day.bin"
    payload = feature_path.read_bytes()
    values = struct.unpack(f"<{len(payload) // 4}f", payload)
    assert values[0] == 0
    assert len(values) > 2

    feature_path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum mismatch"):
        QlibBinaryConverter(tmp_path).convert(snapshot.manifest)


def test_temporal_split_must_be_strictly_chronological():
    with pytest.raises(ValidationError, match="strictly chronological"):
        StrictResearchConfig.model_validate(
            {
                "research": {
                    "engine": "deterministic_momentum",
                    "strategy_id": "test",
                },
                "temporal": {
                    "train_start": "2026-01-01",
                    "train_end": "2026-02-01",
                    "valid_start": "2026-01-15",
                    "valid_end": "2026-03-01",
                    "test_start": "2026-04-01",
                    "test_end": "2026-05-01",
                },
            }
        )


def test_snapshot_research_is_reproducible_and_provenanced(tmp_path: Path):
    snapshot = create_snapshot(tmp_path)
    config_path = tmp_path / "research.yaml"
    write_research_config(config_path)
    runner = SnapshotResearchRunner(
        config_path=config_path,
        artifact_root=tmp_path,
        data_manifest_path=snapshot.manifest_path,
        run_id="daily-run-1",
        project_root=Path.cwd(),
    )

    first = runner.run()
    first_predictions = first.predictions_path.read_bytes()
    second = runner.run()

    assert second.predictions_path.read_bytes() == first_predictions
    targets = TargetPositionRequest.model_validate_json(
        first.target_positions_path.read_text(encoding="utf-8")
    )
    assert targets.data_version == snapshot.manifest.data_version
    assert targets.label_horizon_days == 1
    assert targets.execution_lag_days == 1
    assert len(targets.positions) == 3
    assert all(position.target_weight == 0.2 for position in targets.positions)
    metrics = json.loads(first.metrics_path.read_text(encoding="utf-8"))
    assert metrics["engine"] == "deterministic_momentum"
    assert metrics["promotion"]["automatic"] is False
    assert "baseline_annual_return" in metrics["metrics"]


def test_prediction_feature_cutoffs_do_not_exceed_prediction_dates(tmp_path: Path):
    snapshot = create_snapshot(tmp_path)
    config_path = tmp_path / "research.yaml"
    write_research_config(config_path)
    result = SnapshotResearchRunner(
        config_path=config_path,
        artifact_root=tmp_path,
        data_manifest_path=snapshot.manifest_path,
        run_id="daily-run-1",
    ).run()

    payload = json.loads(result.predictions_path.read_text(encoding="utf-8"))

    assert payload["predictions"]
    assert all(
        item["feature_cutoff"] <= item["trade_date"] for item in payload["predictions"]
    )


def test_momentum_return_starts_after_execution_lag():
    config = StrictResearchConfig.model_validate(
        {
            "research": {
                "engine": "deterministic_momentum",
                "strategy_id": "lag-check",
                "label_horizon_days": 1,
                "execution_lag_days": 1,
            },
            "temporal": {
                "train_start": "2026-01-01",
                "train_end": "2026-01-02",
                "valid_start": "2026-01-03",
                "valid_end": "2026-01-04",
                "test_start": "2026-02-02",
                "test_end": "2026-02-03",
            },
            "portfolio": {"topk": 1, "lookback_days": 1},
            "costs": {
                "commission_bps": 0,
                "sell_stamp_duty_bps": 0,
                "transfer_fee_bps": 0,
                "slippage_bps": 0,
            },
        }
    )
    daily = pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-02-01", periods=4),
            "symbol": ["600519.SH"] * 4,
            "close": [10.0, 20.0, 30.0, 60.0],
        }
    )

    result = DeterministicMomentumEngine().run(
        config=config,
        daily_bar=daily,
        provider_uri=None,
    )

    assert result.metrics["annual_return"] == 252.0


def test_qlib_engine_missing_dependency_fails_without_fallback(
    tmp_path: Path,
    monkeypatch,
):
    snapshot = create_snapshot(tmp_path)
    config_path = tmp_path / "research.yaml"
    write_research_config(config_path, engine="qlib")

    def missing_import(_name: str):
        raise ImportError

    monkeypatch.setattr(
        "quant_agent.research.engines.import_module",
        missing_import,
    )

    with pytest.raises(ResearchDependencyError, match="Qlib is not installed"):
        SnapshotResearchRunner(
            config_path=config_path,
            artifact_root=tmp_path,
            data_manifest_path=snapshot.manifest_path,
            run_id="daily-run-qlib",
        ).run()


def test_qlib_prediction_normalization():
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-07-28"), "SH600519"),
            (pd.Timestamp("2026-07-28"), "SZ000001"),
        ],
        names=["datetime", "instrument"],
    )
    predictions = pd.Series([0.2, 0.1], index=index, name="score")

    normalized = QlibWorkflowEngine._normalize_predictions(predictions)

    assert normalized[0].symbol == "600519.SH"
    assert normalized[0].rank == 1


@pytest.mark.skipif(
    importlib.util.find_spec("qlib") is None,
    reason="optional Qlib research extra is not installed",
)
def test_optional_qlib_can_read_generated_binary_snapshot(tmp_path: Path):
    import qlib
    from qlib.data import D

    snapshot = create_snapshot(tmp_path)
    result = QlibBinaryConverter(tmp_path).convert(snapshot.manifest)
    qlib.init(provider_uri=str(result.qlib_dir), region="cn")

    features = D.features(
        ["SH600519"],
        ["$close"],
        start_time="2026-07-20",
        end_time="2026-07-29",
        freq="day",
    )

    assert not features.empty
