from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from quant_agent.cli import app
from quant_agent.data.providers.synthetic_research import SyntheticResearchMarketDataProvider
from quant_agent.data.snapshot import SnapshotBuilder
from quant_agent.research.snapshot_runner import SnapshotResearchRunner, build_lagged_features

runner = CliRunner()


def build_snapshot(tmp_path: Path) -> Path:
    result = SnapshotBuilder(snapshot_root=tmp_path / "snapshots").build_daily_bars(
        SyntheticResearchMarketDataProvider(),
        as_of=pd.Timestamp("2026-05-22T16:00:00+08:00").to_pydatetime(),
    )
    return result.snapshot_dir


def test_lagged_features_do_not_use_same_day_close() -> None:
    dates = pd.bdate_range("2026-01-02", periods=12)
    rows = []
    for day_index, trade_date in enumerate(dates):
        rows.append(
            {
                "trade_date": trade_date.strftime("%Y-%m-%d"),
                "symbol": "600519.SH",
                "open": 100.0 + day_index,
                "high": 102.0 + day_index,
                "low": 99.0 + day_index,
                "close": 101.0 + day_index,
                "volume": 1000 + day_index,
                "amount": 100000 + day_index,
                "available_at": trade_date.strftime("%Y-%m-%d") + "T15:05:00+08:00",
            }
        )
    original = pd.DataFrame(rows)
    changed = original.copy()
    target_date = dates[-1].strftime("%Y-%m-%d")
    changed.loc[changed["trade_date"] == target_date, "close"] = 9999.0

    left = build_lagged_features(original)
    right = build_lagged_features(changed)
    columns = [
        "feature_return_1",
        "feature_return_5",
        "feature_volatility_5",
        "feature_volume_ratio_5",
        "score",
    ]

    left_row = left.loc[left["trade_date"] == pd.Timestamp(target_date), columns]
    right_row = right.loc[right["trade_date"] == pd.Timestamp(target_date), columns]
    assert left_row.reset_index(drop=True).equals(right_row.reset_index(drop=True))


def test_snapshot_research_creates_auditable_reproducible_artifacts(tmp_path: Path) -> None:
    snapshot_dir = build_snapshot(tmp_path)
    runner_instance = SnapshotResearchRunner(
        snapshot_dir=snapshot_dir,
        config_path=Path("configs/research/snapshot_baseline.yaml"),
        artifact_root=tmp_path / "artifacts",
    )

    first = runner_instance.run()
    second = runner_instance.run()

    assert not first.reused
    assert second.reused
    assert first.run_id == second.run_id
    for path in (
        first.spec_path,
        first.metrics_path,
        first.predictions_path,
        first.daily_returns_path,
        first.target_portfolio_path,
        first.report_path,
        first.result_manifest_path,
    ):
        assert path.is_file()

    metrics = json.loads(first.metrics_path.read_text(encoding="utf-8"))
    assert metrics["metrics"]["observations"] > 100
    assert metrics["metrics"]["total_cost"] > 0
    assert metrics["metrics"]["net_cumulative_return"] < metrics["metrics"][
        "gross_cumulative_return"
    ]

    target = json.loads(first.target_portfolio_path.read_text(encoding="utf-8"))
    assert target["schema_version"] == "2.0"
    assert target["run_id"] == first.run_id
    assert len(target["positions"]) == 3
    assert sum(float(item["target_weight"]) for item in target["positions"]) <= 1.0

    predictions = pd.read_csv(first.predictions_path)
    assert (pd.to_datetime(predictions["feature_as_of"]) < pd.to_datetime(predictions["trade_date"])).all()


def test_snapshot_research_cli_runs_from_verified_snapshot(tmp_path: Path) -> None:
    snapshot_dir = build_snapshot(tmp_path)

    result = runner.invoke(
        app,
        [
            "research",
            "snapshot",
            "--snapshot",
            str(snapshot_dir),
            "--config",
            "configs/research/snapshot_baseline.yaml",
            "--env-config",
            "configs/env/dev.yaml",
            "--project-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "research created:" in result.stdout
    result_directories = list((tmp_path / "artifacts" / "research_v2").glob("research-*"))
    assert len(result_directories) == 1
