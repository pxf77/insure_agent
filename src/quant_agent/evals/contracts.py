from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from quant_agent.schemas.exporter import CONTRACT_MODELS


class ContractEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=100)
    payload: Any
    expect_valid: bool
    expected_output: Any | None = None
    error_contains: str | None = None
    tags: list[str] = Field(default_factory=list)
    severity: str = "normal"


class ContractEvalOutcome(BaseModel):
    case_id: str
    passed: bool
    model: str
    expected: str
    actual: str
    details: str | None = None


class ContractEvalReport(BaseModel):
    suite_version: str
    generated_at: datetime
    total: int
    passed: int
    failed: int
    outcomes: list[ContractEvalOutcome]

    @property
    def success(self) -> bool:
        return self.failed == 0


def load_contract_cases(suite_path: str | Path) -> tuple[str, list[ContractEvalCase]]:
    path = Path(suite_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    suite_version = str(payload.get("suite_version", "unknown"))
    cases = [ContractEvalCase.model_validate(item) for item in payload.get("cases", [])]
    if not cases:
        raise ValueError(f"contract evaluation suite contains no cases: {path}")
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("contract evaluation case IDs must be unique")
    return suite_version, cases


def _evaluate_case(case: ContractEvalCase) -> ContractEvalOutcome:
    model = CONTRACT_MODELS.get(case.model)
    if model is None:
        return ContractEvalOutcome(
            case_id=case.id,
            passed=False,
            model=case.model,
            expected="known contract model",
            actual="unknown contract model",
        )

    try:
        instance = model.model_validate(case.payload)
    except ValidationError as exc:
        if case.expect_valid:
            return ContractEvalOutcome(
                case_id=case.id,
                passed=False,
                model=case.model,
                expected="valid",
                actual="invalid",
                details=str(exc),
            )
        error_text = str(exc)
        matches_error = (
            case.error_contains is None
            or case.error_contains.lower() in error_text.lower()
        )
        return ContractEvalOutcome(
            case_id=case.id,
            passed=matches_error,
            model=case.model,
            expected="invalid",
            actual="invalid",
            details=None if matches_error else error_text,
        )

    if not case.expect_valid:
        return ContractEvalOutcome(
            case_id=case.id,
            passed=False,
            model=case.model,
            expected="invalid",
            actual="valid",
            details=str(instance.model_dump(mode="json")),
        )

    output = instance.model_dump(mode="json")
    output_matches = case.expected_output is None or output == case.expected_output
    return ContractEvalOutcome(
        case_id=case.id,
        passed=output_matches,
        model=case.model,
        expected="valid",
        actual="valid",
        details=None if output_matches else f"output={output!r}",
    )


def run_contract_evals(suite_path: str | Path) -> ContractEvalReport:
    suite_version, cases = load_contract_cases(suite_path)
    outcomes = [_evaluate_case(case) for case in cases]
    passed = sum(outcome.passed for outcome in outcomes)
    return ContractEvalReport(
        suite_version=suite_version,
        generated_at=datetime.now(timezone.utc),
        total=len(outcomes),
        passed=passed,
        failed=len(outcomes) - passed,
        outcomes=outcomes,
    )


def render_contract_eval_report(report: ContractEvalReport) -> str:
    lines = [
        f"suite_version: {report.suite_version}",
        f"result: {report.passed}/{report.total} passed",
    ]
    for outcome in report.outcomes:
        status = "PASS" if outcome.passed else "FAIL"
        lines.append(
            f"[{status}] {outcome.case_id}: expected {outcome.expected}, "
            f"got {outcome.actual}"
        )
        if outcome.details and not outcome.passed:
            lines.append(f"  details: {outcome.details}")
    return "\n".join(lines)
