from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from quant_agent.data.providers.synthetic_research import SyntheticResearchMarketDataProvider
from quant_agent.data.snapshot import SnapshotBuilder
from quant_agent.research.snapshot_runner import SnapshotResearchRunner, build_lagged_features


class ResearchEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    action: Literal[
        "feature_lag",
        "deterministic_run",
        "cost_monotonicity",
        "target_constraints",
        "snapshot_tamper",
    ]
    tags: list[str] = Field(default_factory=list)
    severity: str = "normal"


class ResearchEvalOutcome(BaseModel):
    case_id: str
    passed: bool
    action: str
    details: str | None = None


class ResearchEvalReport(BaseModel):
    suite_version: str
    total: int
    passed: int
    failed: int
    outcomes: list[ResearchEvalOutcome]

    @property
    def success(self) -> bool:
        return self.failed == 0


def load_research_cases(suite_path: str | Path) -> tuple[str, list[ResearchEvalCase]]:
    path = Path(suite_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    suite_version = str(payload.get("suite_version", "unknown"))
    cases = [ResearchEvalCase.model_validate(item) for item in payload.get("cases", [])]
    if not cases:
        raise ValueError(f"research evaluation suite contains no cases: {path}")
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("research evaluation case IDs must be unique")
    return suite_version, cases


def _build_snapshot(root: Path) -> Path:
    result = SnapshotBuilder(snapshot_root=root / "snapshots").build_daily_bars(
        SyntheticResearchMarketDataProvider(),
        as_of=pd.Timestamp("2026-05-22T16:00:00+08:00").to_pydatetime(),
    )
    return result.snapshot_dir


def _write_cost_config(base_config: Path, destination: Path, total_bps: float) -> None:
    payload = yaml.safe_load(base_config.read_text(encoding="utf-8")) or {}
    payload["costs"] = {
        "commission_bps": total_bps / 3.0,
        "sell_tax_bps": total_bps / 3.0,
        "slippage_bps": total_bps / 3.0,
    }
    destination.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


def _run(root: Path, config_path: Path, snapshot_dir: Path):
    return SnapshotResearchRunner(
        snapshot_dir=snapshot_dir,
        config_path=config_path,
        artifact_root=root / "artifacts",
    ).run()


def _evaluate_feature_lag(case: ResearchEvalCase) -> ResearchEvalOutcome:
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
    mutated = original.copy()
    target_date = dates[-1].strftime("%Y-%m-%d")
    mutated.loc[mutated["trade_date"] == target_date, "close"] = 9999.0
    left = build_lagged_features(original)
    right = build_lagged_features(mutated)
    feature_columns = [
        "feature_return_1",
        "feature_return_5",
        "feature_volatility_5",
        "feature_volume_ratio_5",
        "score",
    ]
    left_row = left.loc[left["trade_date"] == pd.Timestamp(target_date), feature_columns]
    right_row = right.loc[right["trade_date"] == pd.Timestamp(target_date), feature_columns]
    passed = left_row.reset_index(drop=True).equals(right_row.reset_index(drop=True))
    return ResearchEvalOutcome(
        case_id=case.id,
        passed=passed,
        action=case.action,
        details=None if passed else "same-day close changed same-day features",
    )


def _evaluate_case(case: ResearchEvalCase, base_config: Path) -> ResearchEvalOutcome:
    if case.action == "feature_lag":
        return _evaluate_feature_lag(case)

    try:
        with tempfile.TemporaryDirectory(prefix="quant-agent-research-eval-") as temporary:
            root = Path(temporary)
            snapshot_dir = _build_snapshot(root)
            first = _run(root, base_config, snapshot_dir)

            if case.action == "deterministic_run":
                second = _run(root, base_config, snapshot_dir)
                passed = first.run_id == second.run_id and second.reused
                details = None if passed else "identical run was not deterministically reused"
            elif case.action == "cost_monotonicity":
                zero_config = root / "zero-cost.yaml"
                high_config = root / "high-cost.yaml"
                _write_cost_config(base_config, zero_config, 0.0)
                _write_cost_config(base_config, high_config, 90.0)
                zero = _run(root, zero_config, snapshot_dir)
                high = _run(root, high_config, snapshot_dir)
                zero_metrics = json.loads(zero.metrics_path.read_text(encoding="utf-8"))
                high_metrics = json.loads(high.metrics_path.read_text(encoding="utf-8"))
                zero_return = float(zero_metrics["metrics"]["net_cumulative_return"])
                high_return = float(high_metrics["metrics"]["net_cumulative_return"])
                passed = high_return < zero_return
                details = None if passed else f"high_cost={high_return}, zero_cost={zero_return}"
            elif case.action == "target_constraints":
                payload = json.loads(first.target_portfolio_path.read_text(encoding="utf-8"))
                instruments = [item["instrument"] for item in payload["positions"]]
                ranks = [item["rank"] for item in payload["positions"]]
                total = sum(float(item["target_weight"]) for item in payload["positions"])
                passed = (
                    len(instruments) == len(set(instruments))
                    and len(ranks) == len(set(ranks))
                    and total <= 1.0
                )
                details = None if passed else f"instruments={instruments}, ranks={ranks}, total={total}"
            elif case.action == "snapshot_tamper":
                normalized = snapshot_dir / "normalized" / "daily_bar.csv"
                normalized.write_text("tampered\n", encoding="utf-8")
                try:
                    _run(root / "tampered", base_config, snapshot_dir)
                except ValueError as exc:
                    passed = "integrity check" in str(exc)
                    details = None if passed else str(exc)
                else:
                    passed = False
                    details = "tampered snapshot was accepted"
            else:
                raise AssertionError(f"unsupported research eval action: {case.action}")
    except (AssertionError, ValueError) as exc:
        return ResearchEvalOutcome(
            case_id=case.id,
            passed=False,
            action=case.action,
            details=str(exc),
        )
    return ResearchEvalOutcome(
        case_id=case.id,
        passed=passed,
        action=case.action,
        details=details,
    )


def run_research_evals(
    suite_path: str | Path,
    *,
    config_path: str | Path = "configs/research/snapshot_baseline.yaml",
) -> ResearchEvalReport:
    suite_version, cases = load_research_cases(suite_path)
    base_config = Path(config_path)
    outcomes = [_evaluate_case(case, base_config) for case in cases]
    passed = sum(outcome.passed for outcome in outcomes)
    return ResearchEvalReport(
        suite_version=suite_version,
        total=len(outcomes),
        passed=passed,
        failed=len(outcomes) - passed,
        outcomes=outcomes,
    )


def render_research_eval_report(report: ResearchEvalReport) -> str:
    lines = [
        f"suite_version: {report.suite_version}",
        f"result: {report.passed}/{report.total} passed",
    ]
    for outcome in report.outcomes:
        status = "PASS" if outcome.passed else "FAIL"
        lines.append(f"[{status}] {outcome.case_id} ({outcome.action})")
        if outcome.details and not outcome.passed:
            lines.append(f"  details: {outcome.details}")
    return "\n".join(lines)
