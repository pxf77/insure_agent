from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pandas as pd
import yaml

from quant_agent.data.snapshot import DataSnapshotManifest, SnapshotBuilder
from quant_agent.schemas.v2 import (
    DateRange,
    ResearchSpec,
    TargetPortfolio,
    TargetPositionV2,
)

_ENGINE_VERSION = "snapshot-baseline-v1"


@dataclass(frozen=True)
class SnapshotResearchResult:
    run_id: str
    artifact_dir: Path
    spec_path: Path
    metrics_path: Path
    predictions_path: Path
    daily_returns_path: Path
    target_portfolio_path: Path
    report_path: Path
    result_manifest_path: Path
    reused: bool


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _decimal(value: float, places: int = 10) -> Decimal:
    return Decimal(str(round(float(value), places)))


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return cast(dict[str, Any], payload)


def _build_spec(config: dict[str, Any], snapshot_id: str, as_of: object) -> ResearchSpec:
    research = cast(dict[str, Any], config["research"])
    costs = cast(dict[str, Any], config.get("costs", {}))
    train = cast(dict[str, Any], research["train"])
    validation = cast(dict[str, Any], research["validation"])
    test = cast(dict[str, Any], research["test"])
    commission = Decimal(str(costs.get("commission_bps", 0)))
    sell_tax = Decimal(str(costs.get("sell_tax_bps", 0)))
    slippage = Decimal(str(costs.get("slippage_bps", 0)))
    return ResearchSpec(
        strategy_id=str(research["strategy_id"]),
        data_snapshot_id=snapshot_id,
        universe=str(research["universe"]),
        benchmark=str(research["benchmark"]) if research.get("benchmark") else None,
        feature_set=str(research["feature_set"]),
        model_name=str(research["model_name"]),
        train=DateRange(start=date.fromisoformat(str(train["start"])), end=date.fromisoformat(str(train["end"]))),
        validation=DateRange(
            start=date.fromisoformat(str(validation["start"])),
            end=date.fromisoformat(str(validation["end"])),
        ),
        test=DateRange(start=date.fromisoformat(str(test["start"])), end=date.fromisoformat(str(test["end"]))),
        random_seed=int(research["random_seed"]),
        transaction_cost_bps=commission + sell_tax + slippage,
        created_at=as_of,
    )


def build_lagged_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Build deterministic features using only information available before each open."""
    data = frame.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values(["symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    grouped = data.groupby("symbol", sort=False, group_keys=False)
    close_return = grouped["close"].pct_change()
    data["feature_return_1"] = close_return.groupby(data["symbol"]).shift(1)
    data["feature_return_5"] = grouped["close"].pct_change(5).groupby(data["symbol"]).shift(1)
    data["feature_volatility_5"] = (
        close_return.groupby(data["symbol"])
        .rolling(5)
        .std(ddof=0)
        .reset_index(level=0, drop=True)
        .groupby(data["symbol"])
        .shift(1)
    )
    lagged_volume = grouped["volume"].shift(1)
    rolling_volume = (
        grouped["volume"]
        .rolling(5)
        .mean()
        .reset_index(level=0, drop=True)
        .groupby(data["symbol"])
        .shift(1)
    )
    data["feature_volume_ratio_5"] = lagged_volume / rolling_volume
    feature_columns = [
        "feature_return_1",
        "feature_return_5",
        "feature_volatility_5",
        "feature_volume_ratio_5",
    ]
    data = data.dropna(subset=feature_columns).copy()
    cross_section = data.groupby("trade_date", sort=True)
    data["rank_return_1"] = cross_section["feature_return_1"].rank(
        pct=True,
        method="first",
    )
    data["rank_return_5"] = cross_section["feature_return_5"].rank(
        pct=True,
        method="first",
    )
    data["rank_volatility_5"] = cross_section["feature_volatility_5"].rank(
        pct=True,
        method="first",
    )
    data["rank_volume_ratio_5"] = cross_section["feature_volume_ratio_5"].rank(
        pct=True,
        method="first",
    )
    data["score"] = (
        data["rank_return_5"]
        + 0.4 * data["rank_return_1"]
        - 0.4 * data["rank_volatility_5"]
        + 0.2 * data["rank_volume_ratio_5"]
    )
    data["intraday_return"] = data["close"] / data["open"] - 1.0
    return data.sort_values(["trade_date", "score", "symbol"], kind="mergesort")


def _metrics(daily: pd.DataFrame) -> dict[str, Any]:
    returns = daily["net_return"].astype(float)
    gross_returns = daily["gross_return"].astype(float)
    observations = len(returns)
    if observations == 0:
        raise ValueError("test period contains no backtest observations")
    net_curve = (1.0 + returns).cumprod()
    gross_curve = (1.0 + gross_returns).cumprod()
    annual_return = float(net_curve.iloc[-1] ** (252.0 / observations) - 1.0)
    annual_volatility = float(returns.std(ddof=0) * (252.0**0.5))
    sharpe = 0.0
    if returns.std(ddof=0) > 0:
        sharpe = float(returns.mean() / returns.std(ddof=0) * (252.0**0.5))
    drawdown = net_curve / net_curve.cummax() - 1.0
    return {
        "observations": observations,
        "gross_cumulative_return": round(float(gross_curve.iloc[-1] - 1.0), 10),
        "net_cumulative_return": round(float(net_curve.iloc[-1] - 1.0), 10),
        "annual_return": round(annual_return, 10),
        "annual_volatility": round(annual_volatility, 10),
        "sharpe": round(sharpe, 10),
        "max_drawdown": round(float(drawdown.min()), 10),
        "average_turnover": round(float(daily["turnover"].mean()), 10),
        "total_cost": round(float(daily["cost"].sum()), 10),
    }


class SnapshotResearchRunner:
    def __init__(
        self,
        *,
        snapshot_dir: str | Path,
        config_path: str | Path,
        artifact_root: str | Path,
    ):
        self.snapshot_dir = Path(snapshot_dir)
        self.config_path = Path(config_path)
        self.artifact_root = Path(artifact_root)

    def run(self) -> SnapshotResearchResult:
        manifest = SnapshotBuilder(snapshot_root=self.snapshot_dir.parent)._verify_existing(
            self.snapshot_dir
        )
        config = _load_yaml(self.config_path)
        spec = _build_spec(config, manifest.snapshot_id, manifest.as_of)
        normalized_path = self.snapshot_dir / "normalized" / "daily_bar.csv"
        bars = pd.read_csv(normalized_path)
        features = build_lagged_features(bars)
        test_frame = features.loc[
            (features["trade_date"].dt.date >= spec.test.start)
            & (features["trade_date"].dt.date <= spec.test.end)
        ].copy()
        if test_frame.empty:
            raise ValueError("snapshot contains no usable rows in the configured test period")

        portfolio = cast(dict[str, Any], config.get("portfolio", {}))
        costs = cast(dict[str, Any], config.get("costs", {}))
        topk = int(portfolio.get("topk", 3))
        account_value = float(portfolio.get("account_value", 1_000_000))
        lot_size = int(portfolio.get("lot_size", 100))
        if topk <= 0 or account_value <= 0 or lot_size != 100:
            raise ValueError("portfolio requires topk>0, account_value>0, and lot_size=100")
        commission_bps = float(costs.get("commission_bps", 0))
        sell_tax_bps = float(costs.get("sell_tax_bps", 0))
        slippage_bps = float(costs.get("slippage_bps", 0))
        if min(commission_bps, sell_tax_bps, slippage_bps) < 0:
            raise ValueError("transaction costs must be non-negative")

        predictions: list[dict[str, Any]] = []
        daily_rows: list[dict[str, Any]] = []
        previous_weights: dict[str, float] = {}
        last_selected = pd.DataFrame()
        last_weights: dict[str, float] = {}
        for trade_date, day_frame in test_frame.groupby("trade_date", sort=True):
            ranked = day_frame.sort_values(
                ["score", "symbol"],
                ascending=[False, True],
                kind="mergesort",
            ).copy()
            ranked["rank"] = range(1, len(ranked) + 1)
            selected = ranked.head(topk).copy()
            weights: dict[str, float] = {}
            target_value = account_value / topk
            for row in selected.itertuples(index=False):
                shares = int(target_value / float(row.open) / lot_size) * lot_size
                weights[str(row.symbol)] = shares * float(row.open) / account_value
            gross_return = sum(
                weights.get(str(row.symbol), 0.0) * float(row.intraday_return)
                for row in selected.itertuples(index=False)
            )
            symbols = set(previous_weights) | set(weights)
            deltas = {
                symbol: weights.get(symbol, 0.0) - previous_weights.get(symbol, 0.0)
                for symbol in symbols
            }
            buy_turnover = sum(max(delta, 0.0) for delta in deltas.values())
            sell_turnover = sum(max(-delta, 0.0) for delta in deltas.values())
            turnover = buy_turnover + sell_turnover
            cost = (
                turnover * (commission_bps + slippage_bps) / 10_000.0
                + sell_turnover * sell_tax_bps / 10_000.0
            )
            net_return = gross_return - cost
            daily_rows.append(
                {
                    "trade_date": pd.Timestamp(trade_date).strftime("%Y-%m-%d"),
                    "gross_return": gross_return,
                    "net_return": net_return,
                    "turnover": turnover,
                    "buy_turnover": buy_turnover,
                    "sell_turnover": sell_turnover,
                    "cost": cost,
                }
            )
            selected_symbols = set(selected["symbol"].astype(str))
            for row in ranked.itertuples(index=False):
                predictions.append(
                    {
                        "trade_date": pd.Timestamp(trade_date).strftime("%Y-%m-%d"),
                        "symbol": str(row.symbol),
                        "score": float(row.score),
                        "rank": int(row.rank),
                        "selected": str(row.symbol) in selected_symbols,
                        "feature_as_of": (
                            pd.Timestamp(trade_date) - pd.tseries.offsets.BDay(1)
                        ).strftime("%Y-%m-%d"),
                    }
                )
            previous_weights = weights
            last_selected = selected
            last_weights = weights

        daily = pd.DataFrame(daily_rows)
        predictions_frame = pd.DataFrame(predictions).sort_values(
            ["trade_date", "rank", "symbol"],
            kind="mergesort",
        )
        metrics = {
            "engine_version": _ENGINE_VERSION,
            "strategy_id": spec.strategy_id,
            "snapshot_id": manifest.snapshot_id,
            "test_period": {
                "start": spec.test.start.isoformat(),
                "end": spec.test.end.isoformat(),
            },
            "costs_bps": {
                "commission": commission_bps,
                "sell_tax": sell_tax_bps,
                "slippage": slippage_bps,
            },
            "metrics": _metrics(daily),
        }
        target_positions: list[TargetPositionV2] = []
        final_ranked = last_selected.sort_values(
            ["score", "symbol"],
            ascending=[False, True],
            kind="mergesort",
        )
        for rank, row in enumerate(final_ranked.itertuples(index=False), start=1):
            target_positions.append(
                TargetPositionV2(
                    instrument=str(row.symbol),
                    target_weight=_decimal(last_weights[str(row.symbol)]),
                    score=_decimal(float(row.score), places=12),
                    rank=rank,
                    reason="deterministic lagged alpha-local score",
                )
            )
        target = TargetPortfolio(
            run_id="pending",
            strategy_id=spec.strategy_id,
            trade_date=pd.Timestamp(last_selected["trade_date"].iloc[0]).date(),
            generated_at=manifest.as_of,
            universe=spec.universe,
            benchmark=spec.benchmark,
            positions=target_positions,
        )

        identity = {
            "engine_version": _ENGINE_VERSION,
            "snapshot_id": manifest.snapshot_id,
            "config_sha256": _file_sha256(self.config_path),
            "spec": spec.model_dump(mode="json"),
            "predictions_sha256": _sha256(
                predictions_frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
            ),
            "daily_returns_sha256": _sha256(
                daily.to_csv(index=False, lineterminator="\n").encode("utf-8")
            ),
            "metrics": metrics,
        }
        run_id = f"research-{_sha256(_canonical_json(identity).encode())[:20]}"
        target.run_id = run_id
        return self._write_artifacts(
            run_id=run_id,
            spec=spec,
            manifest=manifest,
            config=self.config_path.read_text(encoding="utf-8"),
            predictions=predictions_frame,
            daily=daily,
            metrics=metrics,
            target=target,
        )

    def _write_artifacts(
        self,
        *,
        run_id: str,
        spec: ResearchSpec,
        manifest: DataSnapshotManifest,
        config: str,
        predictions: pd.DataFrame,
        daily: pd.DataFrame,
        metrics: dict[str, Any],
        target: TargetPortfolio,
    ) -> SnapshotResearchResult:
        artifact_dir = self.artifact_root / "research_v2" / run_id
        result_manifest_path = artifact_dir / "result_manifest.json"
        if artifact_dir.exists():
            self._verify_existing(artifact_dir, run_id)
            return self._result(artifact_dir, run_id, reused=True)

        temporary = artifact_dir.parent / f".{run_id}.{uuid4().hex}.tmp"
        try:
            temporary.mkdir(parents=True, exist_ok=False)
            files: dict[str, bytes] = {
                "research_spec.json": _canonical_json(spec.model_dump(mode="json")).encode(),
                "data_manifest.json": _canonical_json(manifest.model_dump(mode="json")).encode(),
                "config_snapshot.yaml": config.encode("utf-8"),
                "predictions.csv": predictions.to_csv(index=False, lineterminator="\n").encode(),
                "daily_returns.csv": daily.to_csv(index=False, lineterminator="\n").encode(),
                "metrics.json": _canonical_json(metrics).encode(),
                "target_portfolio.json": _canonical_json(target.model_dump(mode="json")).encode(),
                "report.md": self._report(run_id, metrics, target).encode("utf-8"),
            }
            for relative_path, content in files.items():
                (temporary / relative_path).write_bytes(content)
            result_manifest = {
                "schema_version": "1.0",
                "run_id": run_id,
                "engine_version": _ENGINE_VERSION,
                "files": {
                    name: _sha256(content)
                    for name, content in sorted(files.items())
                },
            }
            (temporary / "result_manifest.json").write_text(
                _canonical_json(result_manifest),
                encoding="utf-8",
            )
            artifact_dir.parent.mkdir(parents=True, exist_ok=True)
            os.rename(temporary, artifact_dir)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        return self._result(artifact_dir, run_id, reused=False)

    @staticmethod
    def _verify_existing(artifact_dir: Path, run_id: str) -> None:
        manifest_path = artifact_dir / "result_manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("research artifact directory is incomplete or unsafe")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("run_id") != run_id:
            raise ValueError("research result manifest run_id mismatch")
        expected_files = cast(dict[str, str], payload.get("files", {}))
        for name, expected_hash in expected_files.items():
            path = artifact_dir / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"research artifact is missing or unsafe: {name}")
            if _file_sha256(path) != expected_hash:
                raise ValueError(f"research artifact failed integrity check: {name}")

    @staticmethod
    def _report(run_id: str, metrics: dict[str, Any], target: TargetPortfolio) -> str:
        result_metrics = cast(dict[str, Any], metrics["metrics"])
        return (
            "# Snapshot Research Report\n\n"
            f"- run_id: `{run_id}`\n"
            f"- strategy_id: `{metrics['strategy_id']}`\n"
            f"- snapshot_id: `{metrics['snapshot_id']}`\n"
            f"- observations: `{result_metrics['observations']}`\n"
            f"- annual_return: `{result_metrics['annual_return']}`\n"
            f"- sharpe: `{result_metrics['sharpe']}`\n"
            f"- max_drawdown: `{result_metrics['max_drawdown']}`\n"
            f"- total_cost: `{result_metrics['total_cost']}`\n"
            f"- final_positions: `{len(target.positions)}`\n"
        )

    @staticmethod
    def _result(artifact_dir: Path, run_id: str, *, reused: bool) -> SnapshotResearchResult:
        return SnapshotResearchResult(
            run_id=run_id,
            artifact_dir=artifact_dir,
            spec_path=artifact_dir / "research_spec.json",
            metrics_path=artifact_dir / "metrics.json",
            predictions_path=artifact_dir / "predictions.csv",
            daily_returns_path=artifact_dir / "daily_returns.csv",
            target_portfolio_path=artifact_dir / "target_portfolio.json",
            report_path=artifact_dir / "report.md",
            result_manifest_path=artifact_dir / "result_manifest.json",
            reused=reused,
        )
