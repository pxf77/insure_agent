from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from quant_agent.data.quality import evaluate_daily_bar_quality
from quant_agent.data.snapshot import SnapshotBuilder


class DataEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    action: Literal["quality", "snapshot"]
    rows: list[dict[str, Any]]
    as_of: str | None = None
    expect_success: bool
    expected_checks: list[str] = Field(default_factory=list)
    expected_visible_rows: int | None = Field(default=None, ge=0)
    expected_symbols: list[str] | None = None
    repeat: bool = False
    tamper: bool = False
    error_contains: str | None = None
    tags: list[str] = Field(default_factory=list)
    severity: str = "normal"


class DataEvalOutcome(BaseModel):
    case_id: str
    passed: bool
    action: str
    details: str | None = None


class DataEvalReport(BaseModel):
    suite_version: str
    total: int
    passed: int
    failed: int
    outcomes: list[DataEvalOutcome]

    @property
    def success(self) -> bool:
        return self.failed == 0


class _RowsProvider:
    provider_id = "eval-rows"
    provider_version = "1"

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def fetch_daily_bars(self, *, as_of: datetime) -> pd.DataFrame:
        del as_of
        return pd.DataFrame(self.rows)


def load_data_cases(suite_path: str | Path) -> tuple[str, list[DataEvalCase]]:
    path = Path(suite_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    suite_version = str(payload.get("suite_version", "unknown"))
    cases = [DataEvalCase.model_validate(item) for item in payload.get("cases", [])]
    if not cases:
        raise ValueError(f"data evaluation suite contains no cases: {path}")
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("data evaluation case IDs must be unique")
    return suite_version, cases


def _evaluate_quality(case: DataEvalCase) -> DataEvalOutcome:
    report = evaluate_daily_bar_quality(pd.DataFrame(case.rows))
    check_ids = {issue.check_id for issue in report.issues}
    expected_checks = set(case.expected_checks)
    success_matches = (not report.blocked) == case.expect_success
    checks_match = expected_checks.issubset(check_ids)
    passed = success_matches and checks_match
    details = None
    if not passed:
        details = (
            f"blocked={report.blocked}, checks={sorted(check_ids)}, "
            f"expected_success={case.expect_success}, "
            f"expected_checks={sorted(expected_checks)}"
        )
    return DataEvalOutcome(
        case_id=case.id,
        passed=passed,
        action=case.action,
        details=details,
    )


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        raise ValueError("snapshot evaluation case requires as_of")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _evaluate_snapshot(case: DataEvalCase) -> DataEvalOutcome:
    try:
        with tempfile.TemporaryDirectory(prefix="quant-agent-data-eval-") as temporary:
            builder = SnapshotBuilder(snapshot_root=Path(temporary) / "snapshots")
            provider = _RowsProvider(case.rows)
            result = builder.build_daily_bars(provider, as_of=_parse_as_of(case.as_of))
            if case.tamper:
                result.normalized_path.write_text("tampered\n", encoding="utf-8")
                builder.build_daily_bars(provider, as_of=_parse_as_of(case.as_of))
            if case.repeat:
                repeated = builder.build_daily_bars(provider, as_of=_parse_as_of(case.as_of))
                if repeated.manifest.snapshot_id != result.manifest.snapshot_id or not repeated.reused:
                    raise AssertionError("repeated snapshot was not deterministically reused")
            if case.expected_visible_rows is not None:
                if result.manifest.visible_rows != case.expected_visible_rows:
                    raise AssertionError(
                        f"visible_rows={result.manifest.visible_rows}, "
                        f"expected={case.expected_visible_rows}"
                    )
            if case.expected_symbols is not None:
                if result.manifest.symbols != sorted(case.expected_symbols):
                    raise AssertionError(
                        f"symbols={result.manifest.symbols}, expected={sorted(case.expected_symbols)}"
                    )
    except (AssertionError, ValueError) as exc:
        if case.expect_success:
            return DataEvalOutcome(
                case_id=case.id,
                passed=False,
                action=case.action,
                details=str(exc),
            )
        matches_error = case.error_contains is None or case.error_contains.lower() in str(exc).lower()
        return DataEvalOutcome(
            case_id=case.id,
            passed=matches_error,
            action=case.action,
            details=None if matches_error else str(exc),
        )

    if not case.expect_success:
        return DataEvalOutcome(
            case_id=case.id,
            passed=False,
            action=case.action,
            details="snapshot unexpectedly succeeded",
        )
    return DataEvalOutcome(case_id=case.id, passed=True, action=case.action)


def run_data_evals(suite_path: str | Path) -> DataEvalReport:
    suite_version, cases = load_data_cases(suite_path)
    outcomes = [
        _evaluate_quality(case) if case.action == "quality" else _evaluate_snapshot(case)
        for case in cases
    ]
    passed = sum(outcome.passed for outcome in outcomes)
    return DataEvalReport(
        suite_version=suite_version,
        total=len(outcomes),
        passed=passed,
        failed=len(outcomes) - passed,
        outcomes=outcomes,
    )


def render_data_eval_report(report: DataEvalReport) -> str:
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
