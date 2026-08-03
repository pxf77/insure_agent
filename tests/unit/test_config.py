from datetime import datetime, timezone
from pathlib import Path

from quant_agent.common.config import load_app_config
from quant_agent.common.ids import generate_run_id
from quant_agent.common.paths import ProjectPaths


def test_load_dev_config_from_yaml():
    config = load_app_config(Path("configs/env/dev.yaml"))

    assert config.app.env == "dev"
    assert config.app.artifact_dir == Path("artifacts")
    assert config.runtime.allow_live_trading is False
    assert config.runtime.allow_live_shadow is False
    assert config.runtime.require_manual_approval is True
    assert config.paths.raw_data == Path("artifacts/data/raw")


def test_live_shadow_config_is_read_only() -> None:
    config = load_app_config(Path("configs/env/live_shadow.yaml"))

    assert config.app.env == "live_shadow"
    assert config.runtime.allow_live_shadow is True
    assert config.runtime.allow_live_trading is False


def test_project_paths_create_expected_artifact_directories(tmp_path):
    config = load_app_config(Path("configs/env/dev.yaml"))
    paths = ProjectPaths.from_config(config, project_root=tmp_path)

    paths.ensure()

    assert paths.raw_data.is_dir()
    assert paths.qlib_data.is_dir()
    assert paths.research_runs.is_dir()
    assert paths.risk_runs.is_dir()
    assert paths.execution_runs.is_dir()
    assert paths.reports.is_dir()


def test_generate_run_id_is_reproducible_when_time_and_hash_are_supplied():
    now = datetime(2026, 5, 24, 9, 30, tzinfo=timezone.utc)

    run_id = generate_run_id(
        mode="research",
        strategy_id="lgb_alpha158",
        now=now,
        short_hash="a1b2c3",
    )

    assert run_id == "20260524-093000-research-lgb_alpha158-a1b2c3"
