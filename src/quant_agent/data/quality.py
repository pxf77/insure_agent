from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import Enum
from typing import Any, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from quant_agent.data.symbol import normalize_symbol

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
