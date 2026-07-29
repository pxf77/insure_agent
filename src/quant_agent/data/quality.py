from __future__ import annotations

from datetime import date

import pandas as pd

from quant_agent.data.providers.base import CANONICAL_COLUMNS, CANONICAL_DATASETS
from quant_agent.data.validators import validate_daily_bar
from quant_agent.schemas.data import DataValidationResult


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
