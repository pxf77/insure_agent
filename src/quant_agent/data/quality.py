from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from enum import Enum
from typing import Any, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from quant_agent.data.providers.base import CANONICAL_COLUMNS, CANONICAL_DATASETS
from quant_agent.data.symbol import normalize_symbol
from quant_agent.data.validators import validate_daily_bar
from quant_agent.schemas.data import DataValidationResult

DAILY_BAR_SNAPSHOT_COLUMNS = (
    "trade_date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "available_at",
)


class DataQualitySeverity(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class DataQualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    severity: DataQualitySeverity
    message: str
    row_count: int = Field(ge=0)
    samples: list[dict[str, Any]] = Field(default_factory=list)


class DataQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = "daily_bar"
    input_rows: int = Field(ge=0)
    issues: list[DataQualityIssue] = Field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(issue.severity == DataQualitySeverity.CRITICAL for issue in self.issues)

    @property
    def summary(self) -> dict[str, int]:
        counts = Counter(issue.severity.value for issue in self.issues)
        return {
            "critical": counts[DataQualitySeverity.CRITICAL.value],
            "warning": counts[DataQualitySeverity.WARNING.value],
        }


def has_explicit_timezone(value: object) -> bool:
    if isinstance(value, datetime):
        return value.tzinfo is not None and value.utcoffset() is not None
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _samples(frame: pd.DataFrame, mask: pd.Series, limit: int = 3) -> list[dict[str, Any]]:
    sample = frame.loc[mask].head(limit).copy()
    records = sample.astype(object).where(pd.notna(sample), None).to_dict(orient="records")
    return cast(list[dict[str, Any]], records)


def evaluate_daily_bar_quality(frame: pd.DataFrame) -> DataQualityReport:
    report = DataQualityReport(input_rows=len(frame))
    missing = [column for column in DAILY_BAR_SNAPSHOT_COLUMNS if column not in frame.columns]
    if missing:
        report.issues.append(
            DataQualityIssue(
                check_id="REQUIRED_COLUMNS",
                severity=DataQualitySeverity.CRITICAL,
                message=f"missing required columns: {missing}",
                row_count=len(frame),
            )
        )
        return report

    required = frame[list(DAILY_BAR_SNAPSHOT_COLUMNS)]
    null_mask = required.isna().any(axis=1)
    if null_mask.any():
        report.issues.append(
            DataQualityIssue(
                check_id="NULL_REQUIRED_FIELD",
                severity=DataQualitySeverity.CRITICAL,
                message="rows contain null required fields",
                row_count=int(null_mask.sum()),
                samples=_samples(frame, null_mask),
            )
        )

    normalized_symbols: list[str | None] = []
    invalid_symbol_mask: list[bool] = []
    for raw_symbol in frame["symbol"]:
        try:
            normalized_symbols.append(normalize_symbol(str(raw_symbol)))
            invalid_symbol_mask.append(False)
        except ValueError:
            normalized_symbols.append(None)
            invalid_symbol_mask.append(True)
    invalid_symbols = pd.Series(invalid_symbol_mask, index=frame.index)
    if invalid_symbols.any():
        report.issues.append(
            DataQualityIssue(
                check_id="INVALID_SYMBOL",
                severity=DataQualitySeverity.CRITICAL,
                message="rows contain invalid A-share symbols",
                row_count=int(invalid_symbols.sum()),
                samples=_samples(frame, invalid_symbols),
            )
        )

    trade_dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    invalid_dates = trade_dates.isna()
    if invalid_dates.any():
        report.issues.append(
            DataQualityIssue(
                check_id="INVALID_TRADE_DATE",
                severity=DataQualitySeverity.CRITICAL,
                message="rows contain invalid trade dates",
                row_count=int(invalid_dates.sum()),
                samples=_samples(frame, invalid_dates),
            )
        )

    explicit_timezone = frame["available_at"].map(has_explicit_timezone)
    naive_available_at = ~explicit_timezone & frame["available_at"].notna()
    if naive_available_at.any():
        report.issues.append(
            DataQualityIssue(
                check_id="NAIVE_AVAILABLE_AT",
                severity=DataQualitySeverity.CRITICAL,
                message="available_at must include an explicit timezone offset or Z",
                row_count=int(naive_available_at.sum()),
                samples=_samples(frame, naive_available_at),
            )
        )

    available_at = pd.to_datetime(frame["available_at"], errors="coerce", utc=True)
    invalid_available_at = available_at.isna()
    if invalid_available_at.any():
        report.issues.append(
            DataQualityIssue(
                check_id="INVALID_AVAILABLE_AT",
                severity=DataQualitySeverity.CRITICAL,
                message="rows contain invalid or unparseable available_at timestamps",
                row_count=int(invalid_available_at.sum()),
                samples=_samples(frame, invalid_available_at),
            )
        )

    numeric_columns = ["open", "high", "low", "close", "volume", "amount"]
    numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    invalid_numeric = numeric.isna().any(axis=1)
    if invalid_numeric.any():
        report.issues.append(
            DataQualityIssue(
                check_id="INVALID_NUMERIC_VALUE",
                severity=DataQualitySeverity.CRITICAL,
                message="rows contain non-numeric market values",
                row_count=int(invalid_numeric.sum()),
                samples=_samples(frame, invalid_numeric),
            )
        )

    price_valid = ~invalid_numeric
    invalid_price = price_valid & (
        (numeric["open"] <= 0)
        | (numeric["high"] <= 0)
        | (numeric["low"] <= 0)
        | (numeric["close"] <= 0)
        | (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1))
        | (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))
    )
    if invalid_price.any():
        report.issues.append(
            DataQualityIssue(
                check_id="INVALID_OHLC",
                severity=DataQualitySeverity.CRITICAL,
                message="rows violate positive-price or OHLC envelope rules",
                row_count=int(invalid_price.sum()),
                samples=_samples(frame, invalid_price),
            )
        )

    invalid_activity = price_valid & ((numeric["volume"] < 0) | (numeric["amount"] < 0))
    if invalid_activity.any():
        report.issues.append(
            DataQualityIssue(
                check_id="NEGATIVE_ACTIVITY",
                severity=DataQualitySeverity.CRITICAL,
                message="rows contain negative volume or amount",
                row_count=int(invalid_activity.sum()),
                samples=_samples(frame, invalid_activity),
            )
        )

    duplicate_frame = pd.DataFrame(
        {
            "trade_date": trade_dates.dt.strftime("%Y-%m-%d"),
            "symbol": normalized_symbols,
        },
        index=frame.index,
    )
    duplicate_mask = duplicate_frame.duplicated(["trade_date", "symbol"], keep=False)
    duplicate_mask &= duplicate_frame["symbol"].notna() & duplicate_frame["trade_date"].notna()
    if duplicate_mask.any():
        report.issues.append(
            DataQualityIssue(
                check_id="DUPLICATE_PRIMARY_KEY",
                severity=DataQualitySeverity.CRITICAL,
                message="rows contain duplicate trade_date/symbol keys after normalization",
                row_count=int(duplicate_mask.sum()),
                samples=_samples(frame, duplicate_mask),
            )
        )

    return report

def validate_canonical_datasets(
    datasets: dict[str, pd.DataFrame],
    *,
    trade_date: date,
) -> list[DataValidationResult]:
    results: list[DataValidationResult] = []
    for name in CANONICAL_DATASETS:
        frame = datasets.get(name)
        missing_columns = (
            list(CANONICAL_COLUMNS[name])
            if frame is None
            else sorted(set(CANONICAL_COLUMNS[name]) - set(frame.columns))
        )
        results.append(
            DataValidationResult(
                rule_id="SCHEMA_COLUMNS",
                dataset=name,
                passed=not missing_columns,
                severity="ERROR",
                message=(
                    "canonical columns present"
                    if not missing_columns
                    else f"missing columns: {missing_columns}"
                ),
            )
        )

    daily = datasets.get("daily_bar", pd.DataFrame())
    try:
        validate_daily_bar(daily)
    except ValueError as exc:
        results.append(
            DataValidationResult(
                rule_id="DAILY_BAR_VALID",
                dataset="daily_bar",
                passed=False,
                severity="ERROR",
                message=str(exc),
            )
        )
    else:
        results.append(
            DataValidationResult(
                rule_id="DAILY_BAR_VALID",
                dataset="daily_bar",
                passed=True,
                severity="ERROR",
                message="daily bars pass structural validation",
            )
        )

    calendar = datasets.get("trading_calendar", pd.DataFrame())
    calendar_dates = (
        set(pd.to_datetime(calendar["trade_date"]).dt.date)
        if not calendar.empty and "trade_date" in calendar
        else set()
    )
    results.append(
        DataValidationResult(
            rule_id="TRADING_CALENDAR_PRESENT",
            dataset="trading_calendar",
            passed=bool(calendar_dates),
            severity="ERROR",
            message=(
                "trading calendar is present"
                if calendar_dates
                else "trading calendar is empty"
            ),
        )
    )
    open_calendar_dates = (
        set(
            pd.to_datetime(
                calendar.loc[calendar["is_open"].astype(bool), "trade_date"]
            ).dt.date
        )
        if not calendar.empty
        else set()
    )
    eligible_open_dates = {
        value for value in open_calendar_dates if value <= trade_date
    }
    expected_latest_date = (
        max(eligible_open_dates) if eligible_open_dates else None
    )
    latest_bar_date = (
        pd.to_datetime(daily["trade_date"]).dt.date.max() if not daily.empty else None
    )
    fresh = latest_bar_date == expected_latest_date
    results.append(
        DataValidationResult(
            rule_id="DATA_FRESHNESS",
            dataset="daily_bar",
            passed=fresh,
            severity="ERROR",
            message=(
                f"latest daily bar matches expected open date {expected_latest_date}"
                if fresh
                else (
                    f"expected latest open date {expected_latest_date}, "
                    f"latest bar is {latest_bar_date}"
                )
            ),
        )
    )
    observed_bar_dates = (
        set(pd.to_datetime(daily["trade_date"]).dt.date)
        if not daily.empty
        else set()
    )
    missing_open_dates = sorted(eligible_open_dates - observed_bar_dates)
    results.append(
        DataValidationResult(
            rule_id="MISSING_TRADING_DAYS",
            dataset="daily_bar",
            passed=not missing_open_dates,
            severity="ERROR",
            message=(
                "daily bars cover every open calendar date"
                if not missing_open_dates
                else f"missing {len(missing_open_dates)} open dates"
            ),
            details={
                "missing_dates": [
                    value.isoformat() for value in missing_open_dates[:20]
                ]
            },
        )
    )
    non_open_bar_dates = sorted(observed_bar_dates - open_calendar_dates)
    results.append(
        DataValidationResult(
            rule_id="BAR_DATES_IN_CALENDAR",
            dataset="daily_bar",
            passed=not non_open_bar_dates,
            severity="ERROR",
            message=(
                "every daily-bar date is an open calendar date"
                if not non_open_bar_dates
                else f"{len(non_open_bar_dates)} bar dates are not open dates"
            ),
            details={
                "unexpected_dates": [
                    value.isoformat() for value in non_open_bar_dates[:20]
                ]
            },
        )
    )

    factors = datasets.get("adjust_factor", pd.DataFrame())
    factor_duplicates = (
        bool(factors.duplicated(["trade_date", "symbol"]).any())
        if not factors.empty
        else False
    )
    factor_keys = (
        set(
            zip(
                factors["trade_date"].astype(str),
                factors["symbol"].astype(str),
                strict=True,
            )
        )
        if not factors.empty
        else set()
    )
    daily_keys = (
        set(
            zip(
                daily["trade_date"].astype(str),
                daily["symbol"].astype(str),
                strict=True,
            )
        )
        if not daily.empty
        else set()
    )
    factor_valid = bool(
        daily_keys
        and factor_keys == daily_keys
        and not factor_duplicates
        and (
            pd.to_numeric(factors["adjust_factor"], errors="coerce") > 0
        ).all()
    )
    results.append(
        DataValidationResult(
            rule_id="ADJUST_FACTOR_AVAILABLE",
            dataset="adjust_factor",
            passed=factor_valid,
            severity="ERROR",
            message=(
                "positive adjustment factors cover every daily bar"
                if factor_valid
                else "adjustment factors are unavailable, invalid, or incomplete"
            ),
            details={
                "daily_keys": len(daily_keys),
                "factor_keys": len(factor_keys),
                "duplicate_keys": factor_duplicates,
            },
        )
    )
    continuity_passed = False
    maximum_adjusted_jump: float | None = None
    if factor_valid:
        adjusted = daily[["trade_date", "symbol", "close"]].merge(
            factors[["trade_date", "symbol", "adjust_factor"]],
            on=["trade_date", "symbol"],
            validate="one_to_one",
        )
        adjusted["adjusted_close"] = (
            pd.to_numeric(adjusted["close"])
            * pd.to_numeric(adjusted["adjust_factor"])
        )
        adjusted = adjusted.sort_values(["symbol", "trade_date"], kind="stable")
        jumps = adjusted.groupby("symbol")["adjusted_close"].pct_change().abs()
        maximum_adjusted_jump = float(jumps.max()) if jumps.notna().any() else 0.0
        continuity_passed = maximum_adjusted_jump <= 0.35
    results.append(
        DataValidationResult(
            rule_id="ADJUSTED_PRICE_CONTINUITY",
            dataset="adjust_factor",
            passed=continuity_passed,
            severity="ERROR",
            message=(
                f"maximum adjusted close jump is {maximum_adjusted_jump:.2%}"
                if maximum_adjusted_jump is not None
                else "adjusted price continuity cannot be evaluated"
            ),
        )
    )

    membership = datasets.get("universe_membership", pd.DataFrame())
    active_symbols: set[str] = set()
    if not membership.empty:
        target_timestamp = pd.Timestamp(trade_date)
        start_values = pd.to_datetime(membership["effective_start"])
        end_values = pd.to_datetime(membership["effective_end"], errors="coerce")
        active = membership[
            (start_values <= target_timestamp)
            & (end_values.isna() | (end_values >= target_timestamp))
        ]
        active_symbols = set(active["symbol"].astype(str))
    latest_symbols = (
        set(
            daily.loc[
                pd.to_datetime(daily["trade_date"]).dt.date == trade_date,
                "symbol",
            ].astype(str)
        )
        if not daily.empty
        else set()
    )
    coverage = len(latest_symbols & active_symbols) / len(active_symbols) if active_symbols else 0.0
    results.append(
        DataValidationResult(
            rule_id="UNIVERSE_COVERAGE",
            dataset="universe_membership",
            passed=bool(active_symbols) and coverage >= 0.95,
            severity="ERROR",
            message=f"latest-bar universe coverage is {coverage:.2%}",
            details={"active_symbols": len(active_symbols), "latest_symbols": len(latest_symbols)},
        )
    )

    for name in ("instrument_status", "limit_price"):
        frame = datasets.get(name, pd.DataFrame())
        current_symbols = (
            set(
                frame.loc[
                    frame["trade_date"].astype(str) == trade_date.isoformat(),
                    "symbol",
                ].astype(str)
            )
            if not frame.empty
            else set()
        )
        coverage = (
            len(current_symbols & active_symbols) / len(active_symbols)
            if active_symbols
            else 0.0
        )
        available = bool(active_symbols) and coverage >= 0.95
        results.append(
            DataValidationResult(
                rule_id=f"{name.upper()}_AVAILABLE",
                dataset=name,
                passed=available,
                severity="ERROR",
                message=f"{name} current-universe coverage is {coverage:.2%}",
            )
        )
    return results


def has_critical_failures(results: list[DataValidationResult]) -> bool:
    return any(not result.passed and result.severity == "ERROR" for result in results)
