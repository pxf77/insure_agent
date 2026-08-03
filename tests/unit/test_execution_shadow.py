from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_agent.cli import app
from quant_agent.execution.gateway import JsonFileReadOnlyGateway
from quant_agent.execution.shadow import LiveShadowRunner

runner = CliRunner()


def write_broker_snapshot(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "provider_id": "supermind-sidecar",
                "as_of": "2026-05-22T07:30:00Z",
                "account": {
                    "account_id": "shadow-account",
                    "cash": "500000",
                    "total_equity": "1000000",
                },
                "positions": [
                    {
                        "instrument": "SH600519",
                        "quantity": 100,
                        "sellable_quantity": 0,
                        "market_value": "150000",
                    }
                ],
                "orders": [
                    {
                        "external_order_id": "broker-order-1",
                        "client_order_id": "shadow-order-1",
                        "instrument": "600519.SH",
                        "side": "BUY",
                        "status": "FILLED",
                        "quantity": 100,
                        "filled_quantity": 100,
                        "limit_price": "1500",
                    }
                ],
                "trades": [
                    {
                        "external_trade_id": "broker-trade-1",
                        "external_order_id": "broker-order-1",
                        "instrument": "600519.SH",
                        "side": "BUY",
                        "quantity": 100,
                        "price": "1500",
                        "traded_at": "2026-05-22T07:15:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_live_shadow_persists_immutable_read_only_snapshot(tmp_path: Path) -> None:
    gateway = JsonFileReadOnlyGateway(write_broker_snapshot(tmp_path / "snapshot.json"))
    runner_instance = LiveShadowRunner(
        artifact_root=tmp_path / "artifacts",
        allow_live_shadow=True,
    )

    first = runner_instance.run(gateway)
    second = runner_instance.run(gateway)

    assert not first.reused
    assert second.reused
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["mode"] == "live_shadow"
    assert manifest["can_submit_orders"] is False
    snapshot = json.loads(first.snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["positions"][0]["instrument"] == "600519.SH"
    assert stat.S_IMODE(first.artifact_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(first.snapshot_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(first.manifest_path.stat().st_mode) == 0o600


def test_live_shadow_fails_closed_when_disabled(tmp_path: Path) -> None:
    gateway = JsonFileReadOnlyGateway(write_broker_snapshot(tmp_path / "snapshot.json"))

    with pytest.raises(ValueError, match="disabled"):
        LiveShadowRunner(
            artifact_root=tmp_path / "artifacts",
            allow_live_shadow=False,
        ).run(gateway)


def test_live_shadow_rejects_live_trading_configuration(tmp_path: Path) -> None:
    gateway = JsonFileReadOnlyGateway(write_broker_snapshot(tmp_path / "snapshot.json"))

    with pytest.raises(ValueError, match="live trading is enabled"):
        LiveShadowRunner(
            artifact_root=tmp_path / "artifacts",
            allow_live_shadow=True,
            allow_live_trading=True,
        ).run(gateway)


def test_json_gateway_rejects_oversized_snapshot(tmp_path: Path) -> None:
    snapshot = write_broker_snapshot(tmp_path / "snapshot.json")
    gateway = JsonFileReadOnlyGateway(snapshot, max_snapshot_bytes=10)

    with pytest.raises(ValueError, match="size limit"):
        gateway.read_snapshot()


def test_live_shadow_cli_never_exposes_order_submission(tmp_path: Path) -> None:
    snapshot = write_broker_snapshot(tmp_path / "snapshot.json")

    result = runner.invoke(
        app,
        [
            "execution",
            "shadow",
            "--snapshot",
            str(snapshot),
            "--config",
            "configs/env/live_shadow.yaml",
            "--project-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "can_submit_orders: false" in result.stdout
    assert list((tmp_path / "artifacts" / "shadow_runs").glob("*/manifest.json"))
