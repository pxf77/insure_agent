from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

import pandas as pd

from quant_agent.data.symbol import normalize_symbol
from quant_agent.research.config import StrictResearchConfig
from quant_agent.schemas.research import PredictionScore


class ResearchDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResearchEngineOutput:
    engine: str
    predictions: list[PredictionScore]
    metrics: dict[str, Any]


class ResearchEngine(ABC):
    @abstractmethod
    def run(
        self,
        *,
        config: StrictResearchConfig,
        daily_bar: pd.DataFrame,
        provider_uri: Path | None,
    ) -> ResearchEngineOutput:
        raise NotImplementedError


class DeterministicMomentumEngine(ResearchEngine):
    def run(
        self,
        *,
        config: StrictResearchConfig,
        daily_bar: pd.DataFrame,
        provider_uri: Path | None,
    ) -> ResearchEngineOutput:
        del provider_uri
        frame = daily_bar.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        frame = frame.sort_values(["symbol", "trade_date"], kind="stable")
        grouped_close = frame.groupby("symbol", sort=False)["close"]
        frame["score"] = (
            frame["close"] / grouped_close.shift(config.portfolio.lookback_days)
        ) - 1
        entry_close = grouped_close.shift(-config.research.execution_lag_days)
        exit_close = grouped_close.shift(
            -(
                config.research.execution_lag_days
                + config.research.label_horizon_days
            )
        )
        frame["forward_return"] = (exit_close / entry_close) - 1
        test_start = pd.Timestamp(config.temporal.test_start)
        test_end = pd.Timestamp(config.temporal.test_end)
        evaluation = frame[
            (frame["trade_date"] >= test_start)
            & (frame["trade_date"] <= test_end)
            & frame["score"].notna()
        ].copy()
        evaluation["rank"] = (
            evaluation.groupby("trade_date")["score"]
            .rank(method="first", ascending=False)
            .astype(int)
        )
        predictions = [
            PredictionScore(
                trade_date=row.trade_date.strftime("%Y-%m-%d"),
                symbol=str(row.symbol),
                score=float(row.score),
                rank=int(row.rank),
                feature_cutoff=row.trade_date.strftime("%Y-%m-%d"),
            )
            for row in evaluation.itertuples(index=False)
        ]
        metrics = self._metrics(evaluation, config)
        return ResearchEngineOutput(
            engine="deterministic_momentum",
            predictions=predictions,
            metrics=metrics,
        )

    @staticmethod
    def _metrics(
        evaluation: pd.DataFrame,
        config: StrictResearchConfig,
    ) -> dict[str, Any]:
        forward = evaluation[evaluation["forward_return"].notna()].copy()
        if forward.empty:
            return {
                "annual_return": 0.0,
                "annual_volatility": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "turnover": 0.0,
                "estimated_cost": 0.0,
                "ic": 0.0,
                "rank_ic": 0.0,
                "baseline_annual_return": 0.0,
                "excess_annual_return_after_cost": 0.0,
                "observations": 0,
            }

        selected = forward[forward["rank"] <= config.portfolio.topk]
        gross = selected.groupby("trade_date")["forward_return"].mean().sort_index()
        baseline = forward.groupby("trade_date")["forward_return"].mean().sort_index()
        selected_sets = [
            set(group["symbol"].astype(str))
            for _, group in selected.groupby("trade_date", sort=True)
        ]
        turnovers: list[float] = []
        previous: set[str] = set()
        for current in selected_sets:
            if not previous:
                turnovers.append(1.0)
            else:
                denominator = max(len(current), 1)
                turnovers.append(1 - (len(current & previous) / denominator))
            previous = current
        turnover_series = pd.Series(turnovers, index=gross.index, dtype=float)
        cost_rate = config.costs.conservative_round_trip_rate
        net = gross - (turnover_series * cost_rate)
        periods_per_year = 252 / config.research.label_horizon_days
        annual_return = float(net.mean() * periods_per_year)
        annual_volatility = float(net.std(ddof=0) * (periods_per_year**0.5))
        sharpe = 0.0 if annual_volatility == 0 else annual_return / annual_volatility
        equity = (1 + net).cumprod()
        drawdown = (equity / equity.cummax()) - 1
        ic_values: list[float] = []
        rank_ic_values: list[float] = []
        for _, group in forward.groupby("trade_date", sort=True):
            if len(group) < 2:
                continue
            ic = group["score"].corr(group["forward_return"], method="pearson")
            rank_ic = group["score"].rank().corr(group["forward_return"].rank())
            if pd.notna(ic):
                ic_values.append(float(ic))
            if pd.notna(rank_ic):
                rank_ic_values.append(float(rank_ic))
        baseline_annual = float(baseline.mean() * periods_per_year)
        estimated_cost = float((turnover_series * cost_rate).sum())
        return {
            "annual_return": round(annual_return, 8),
            "annual_volatility": round(annual_volatility, 8),
            "sharpe": round(sharpe, 8),
            "max_drawdown": round(float(drawdown.min()), 8),
            "turnover": round(float(turnover_series.mean()), 8),
            "estimated_cost": round(estimated_cost, 8),
            "ic": round(sum(ic_values) / len(ic_values), 8) if ic_values else 0.0,
            "rank_ic": (
                round(sum(rank_ic_values) / len(rank_ic_values), 8)
                if rank_ic_values
                else 0.0
            ),
            "baseline_annual_return": round(baseline_annual, 8),
            "excess_annual_return_after_cost": round(
                annual_return - baseline_annual,
                8,
            ),
            "observations": int(len(gross)),
        }


class QlibWorkflowEngine(ResearchEngine):
    def run(
        self,
        *,
        config: StrictResearchConfig,
        daily_bar: pd.DataFrame,
        provider_uri: Path | None,
    ) -> ResearchEngineOutput:
        del daily_bar
        if provider_uri is None or not provider_uri.exists():
            raise ResearchDependencyError(
                f"Qlib provider data is unavailable: {provider_uri}"
            )
        try:
            qlib_module: Any = import_module("qlib")
            utils_module: Any = import_module("qlib.utils")
            workflow_module: Any = import_module("qlib.workflow")
            records_module: Any = import_module("qlib.workflow.record_temp")
        except ImportError as exc:
            raise ResearchDependencyError(
                "Qlib is not installed; install the research extra before selecting "
                "the qlib engine"
            ) from exc
        task = config.qlib.task
        if "model" not in task or "dataset" not in task:
            raise ValueError("Qlib task requires model and dataset configuration")

        qlib_module.init(provider_uri=str(provider_uri), region=config.qlib.region)
        model = utils_module.init_instance_by_config(task["model"])
        dataset = utils_module.init_instance_by_config(task["dataset"])
        recorder: Any
        with workflow_module.R.start(experiment_name=config.qlib.experiment_name):
            model.fit(dataset)
            recorder = workflow_module.R.get_recorder()
            records_module.SignalRecord(model, dataset, recorder).generate()
            records_module.SigAnaRecord(recorder).generate()
            if config.qlib.port_analysis_config:
                records_module.PortAnaRecord(
                    recorder,
                    config.qlib.port_analysis_config,
                    "day",
                ).generate()
            raw_metrics = dict(recorder.list_metrics())
            prediction_object = recorder.load_object("pred.pkl")
        predictions = self._normalize_predictions(prediction_object)
        return ResearchEngineOutput(
            engine="qlib",
            predictions=predictions,
            metrics={"qlib": raw_metrics, "observations": len(predictions)},
        )

    @staticmethod
    def _normalize_predictions(value: Any) -> list[PredictionScore]:
        if isinstance(value, pd.Series):
            frame = value.rename("score").reset_index()
        elif isinstance(value, pd.DataFrame):
            frame = value.reset_index()
        else:
            raise TypeError(f"unsupported Qlib prediction type: {type(value).__name__}")
        date_column = next(
            (name for name in ("datetime", "date", "trade_date") if name in frame),
            None,
        )
        symbol_column = next(
            (name for name in ("instrument", "symbol") if name in frame),
            None,
        )
        score_column = "score" if "score" in frame else None
        if score_column is None:
            numeric = [
                name
                for name in frame.columns
                if name not in {date_column, symbol_column}
                and pd.api.types.is_numeric_dtype(frame[name])
            ]
            score_column = numeric[0] if numeric else None
        if date_column is None or symbol_column is None or score_column is None:
            raise ValueError(f"cannot normalize Qlib prediction columns: {list(frame.columns)}")
        normalized = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(frame[date_column]),
                "symbol": frame[symbol_column].map(lambda value: normalize_symbol(str(value))),
                "score": pd.to_numeric(frame[score_column]),
            }
        )
        normalized["rank"] = (
            normalized.groupby("trade_date")["score"]
            .rank(method="first", ascending=False)
            .astype(int)
        )
        return [
            PredictionScore(
                trade_date=row.trade_date.strftime("%Y-%m-%d"),
                symbol=str(row.symbol),
                score=float(row.score),
                rank=int(row.rank),
                feature_cutoff=row.trade_date.strftime("%Y-%m-%d"),
            )
            for row in normalized.itertuples(index=False)
        ]
