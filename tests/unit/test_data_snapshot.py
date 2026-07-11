from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from quant_agent.cli import app
from quant_agent.data.quality import evaluate_daily_bar_quality
from quant_agent.data.snapshot import SnapshotBuilder

runner = CliRunner()


class RowsProvider:
    provider_id = "test-provider"
    provider_version = "1"

    def __init__(self, rows: list[dict[str, object]]):
        self.rows = rows

    def fetch_daily_bars(self, *, as_of: datetime) -> pd.DataFrame:
        del as_of
        return pd.DataFrame(self.rows)


def valid_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "trade_date": "2026-05-20",
        "symbol": "SH600519",
        "open": 100.0,
        "high": 110.0,
        "low": 99.0,
        "close": 105.0,
        "volume": 1000,
        "amount": 105000.0,
        "available_at": "2026-05-20T15:05:00+08:00",
    }
    row.update(updates)
    return row


def test_quality_detects_normalized_duplicate_and_bad_ohlc() -> None:
    frame = pd.DataFrame(
        [
            valid_row(),
            valid_row(symbol="600519.SH", high=101.0),
        ]
    )

    report = evaluate_daily_bar_quality(frame)
    check_ids = {issue.check_id for issue in report.issues}

    assert report.blocked
    assert "DUPLICATE_PRIMARY_KEY" in check_ids
    assert "INVALID_OHLC" in check_ids


def test_snapshot_filters_future_rows_and_normalizes_symbols(tmp_path: Path) -> None:
    provider = RowsProvider(
        [
            valid_row(),
            valid_row(
                trade_date="2026-05-21",
                symbol="000001.sz",
                open=10.0,
                high=11.0,
                low=9.0,
                close=10.5,
                volume=2000,
                amount=21000.0,
                available_at="2026-05-21T15:05:00+08:00",
            ),
        ]
    )
    builder = SnapshotBuilder(snapshot_root=tmp_path / "snapshots")

    result = builder.build_daily_bars(
        provider,
        as_of=datetime.fromisoformat("2026-05-20T16:00:00+08:00"),
    )

    assert result.manifest.visible_rows == 1
    assert result.manifest.input_rows == 2
    assert result.manifest.symbols == ["600519.SH"]
    normalized = pd.read_csv(result.normalized_path)
    assert normalized["symbol"].tolist() == ["600519.SH"]
    assert result.manifest.as_of.isoformat() == "2026-05-20T08:00:00+00:00"


def test_snapshot_is_deterministic_and_reused(tmp_path: Path) -> None:
    builder = SnapshotBuilder(snapshot_root=tmp_path / "snapshots")
    provider = RowsProvider([valid_row()])
    as_of = datetime.fromisoformat("2026-05-20T16:00:00+08:00")

    first = builder.build_daily_bars(provider, as_of=as_of)
    second = builder.build_daily_bars(provider, as_of=as_of)

    assert not first.reused
    assert second.reused
    assert first.manifest.snapshot_id == second.manifest.snapshot_id
    assert first.manifest.files == second.manifest.files


def test_snapshot_detects_artifact_tampering(tmp_path: Path) -> None:
    builder = SnapshotBuilder(snapshot_root=tmp_path / "snapshots")
    provider = RowsProvider([valid_row()])
    as_of = datetime.fromisoformat("2026-05-20T16:00:00+08:00")
    result = builder.build_daily_bars(provider, as_of=as_of)
    result.normalized_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="integrity check"):
        builder.build_daily_bars(provider, as_of=as_of)


def test_snapshot_rejects_naive_as_of(tmp_path: Path) -> None:
    builder = SnapshotBuilder(snapshot_root=tmp_path / "snapshots")

    with pytest.raises(ValueError, match="timezone"):
        builder.build_daily_bars(
            RowsProvider([valid_row()]),
            as_of=datetime.fromisoformat("2026-05-20T16:00:00"),
        )


def test_snapshot_cli_builds_manifest(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "data",
            "snapshot",
            "--config",
            "configs/env/dev.yaml",
            "--project-root",
            str(tmp_path),
            "--as-of",
            "2026-05-21T16:00:00+08:00",
        ],
    )

    assert result.exit_code == 0, result.output
    manifests = list((tmp_path / "artifacts" / "data" / "snapshots").glob("*/manifest.json"))
    assert len(manifests) == 1
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["visible_rows"] == 3
    assert "snapshot created" in result.stdout
