from pathlib import Path

import pytest

from quant_agent.common.io import content_sha256
from quant_agent.common.run_index import RunIndex
from quant_agent.common.run_store import RunManifestStore
from quant_agent.schemas.run import Provenance, RunStatus, StageStatus


def provenance() -> Provenance:
    return Provenance(
        config_hash="config-sha",
        code_version="code-sha",
        resolved_config={"mode": "paper"},
    )


def test_run_store_records_failed_and_resumed_attempts(tmp_path: Path):
    store = RunManifestStore(tmp_path)
    store.create(
        run_id="run-1",
        trade_date="2026-07-29",
        provenance=provenance(),
        stages=("DATA", "RESEARCH"),
    )

    store.start_stage("run-1", "DATA", input_checksums={"request": "abc"})
    store.fail_stage("run-1", "DATA", "provider unavailable")
    failed = store.load("run-1")
    assert failed.status == RunStatus.FAILED
    assert failed.stages[0].attempts[0].error == "provider unavailable"

    store.start_stage("run-1", "DATA")
    artifact = tmp_path / "daily.csv"
    artifact.write_text("symbol,close\n600519.SH,100\n", encoding="utf-8")
    store.complete_stage("run-1", "DATA", artifacts={"daily": artifact})
    store.start_stage("run-1", "RESEARCH")
    store.complete_stage("run-1", "RESEARCH")
    completed = store.complete_run("run-1")

    assert completed.status == RunStatus.COMPLETED
    assert len(completed.stages[0].attempts) == 2
    assert completed.stages[0].status == StageStatus.COMPLETED
    assert completed.artifacts["daily"].sha256


def test_run_store_rejects_out_of_order_stage(tmp_path: Path):
    store = RunManifestStore(tmp_path)
    store.create(
        run_id="run-1",
        trade_date="2026-07-29",
        provenance=provenance(),
        stages=("DATA", "RESEARCH"),
    )

    with pytest.raises(ValueError, match="previous stage DATA"):
        store.start_stage("run-1", "RESEARCH")


def test_only_completed_run_is_published_as_latest(tmp_path: Path):
    store = RunManifestStore(tmp_path)
    index = RunIndex(tmp_path)
    first = store.create(
        run_id="run-complete",
        trade_date="2026-07-28",
        provenance=provenance(),
        stages=("DATA",),
    )
    store.start_stage(first.run_id, "DATA")
    store.complete_stage(first.run_id, "DATA")
    published = store.complete_run(first.run_id)
    index.publish_completed(published)

    store.create(
        run_id="run-partial",
        trade_date="2026-07-29",
        provenance=provenance(),
        stages=("DATA",),
    )
    index.update(target_positions="/legacy/target.json")

    assert index.read()["completed_run"] == "run-complete"
    assert index.read_legacy()["target_positions"] == "/legacy/target.json"
    with pytest.raises(ValueError, match="only a completed run"):
        index.publish_completed(store.load("run-partial"))


def test_content_checksum_is_order_independent():
    assert content_sha256({"a": 1, "b": 2}) == content_sha256({"b": 2, "a": 1})


def test_latest_completed_run_does_not_regress_by_trade_date(tmp_path: Path):
    store = RunManifestStore(tmp_path)
    index = RunIndex(tmp_path)
    for run_id, trade_date in (
        ("newer", "2026-07-30"),
        ("older", "2026-07-29"),
    ):
        store.create(
            run_id=run_id,
            trade_date=trade_date,
            provenance=provenance(),
            stages=("DATA",),
        )
        store.start_stage(run_id, "DATA")
        store.complete_stage(run_id, "DATA")
        index.publish_completed(store.complete_run(run_id))

    assert index.read()["completed_run"] == "newer"
