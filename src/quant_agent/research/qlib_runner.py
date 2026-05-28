from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
import yaml

from quant_agent.common.ids import generate_run_id
from quant_agent.common.run_index import RunIndex
from quant_agent.data.adapters.local_csv_adapter import LocalCsvAdapter
from quant_agent.research.portfolio_builder import PortfolioBuilder


@dataclass(frozen=True)
class QlibRunResult:
    run_id: str
    artifact_dir: Path
    metrics_path: Path
    target_positions_path: Path
    report_path: Path


class QlibRunner:
    def __init__(
        self,
        config_path: str | Path,
        artifact_root: str | Path,
        raw_data_dir: str | Path,
    ):
        self.config_path = Path(config_path)
        self.artifact_root = Path(artifact_root)
        self.raw_data_dir = Path(raw_data_dir)

    def run_backtest(self) -> QlibRunResult:
        config = self._load_config()
        research = cast(dict[str, Any], config["research"])
        portfolio = cast(dict[str, Any], config.get("portfolio", {}))
        strategy_id = str(research["strategy_id"])
        generated_at = datetime.now()
        run_id = generate_run_id("research", strategy_id, now=generated_at)

        daily_bar = LocalCsvAdapter(self.raw_data_dir).fetch_daily_bar(
            start=date.fromisoformat(str(research["test_start"])),
            end=date.fromisoformat(str(research["test_end"])),
        )
        targets = PortfolioBuilder().build_targets(
            daily_bar,
            run_id=run_id,
            strategy_id=strategy_id,
            universe=str(research["universe"]),
            benchmark=str(research.get("benchmark")) if research.get("benchmark") else None,
            topk=int(portfolio.get("topk", 3)),
            generated_at=generated_at,
            metadata={"config_uri": str(self.config_path)},
        )

        artifact_dir = self.artifact_root / "research_runs" / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        metrics = self._build_metrics(daily_bar, run_id, research)
        metrics_path = artifact_dir / "metrics.json"
        target_positions_path = artifact_dir / "target_positions.json"
        report_path = artifact_dir / "report.md"
        (artifact_dir / "config_snapshot.yaml").write_text(
            self.config_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
        target_positions_path.write_text(
            json.dumps(targets.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        report_path.write_text(self._build_research_report(run_id, metrics), encoding="utf-8")
        RunIndex(self.artifact_root).update(
            research_run=run_id,
            target_positions=str(target_positions_path),
            metrics=str(metrics_path),
            research_report=str(report_path),
        )
        return QlibRunResult(
            run_id=run_id,
            artifact_dir=artifact_dir,
            metrics_path=metrics_path,
            target_positions_path=target_positions_path,
            report_path=report_path,
        )

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"research config not found: {self.config_path}")
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        return cast(dict[str, Any], data)

    @staticmethod
    def _build_metrics(
        daily_bar: pd.DataFrame,
        run_id: str,
        research: dict[str, Any],
    ) -> dict[str, Any]:
        returns = (daily_bar["close"] - daily_bar["open"]) / daily_bar["open"]
        volatility = returns.std(ddof=0)
        sharpe = 0.0 if volatility == 0 else round(float(returns.mean() / volatility), 6)
        return {
            "run_id": run_id,
            "strategy_id": research["strategy_id"],
            "universe": research["universe"],
            "benchmark": research.get("benchmark"),
            "period": {"start": str(research["test_start"]), "end": str(research["test_end"])},
            "metrics": {
                "annual_return": round(float(returns.mean() * 252), 6),
                "annual_volatility": round(float(volatility * (252**0.5)), 6),
                "sharpe": sharpe,
                "max_drawdown": 0.0,
                "turnover": 1.0,
            },
        }

    @staticmethod
    def _build_research_report(run_id: str, metrics: dict[str, Any]) -> str:
        return (
            f"# Research Report\n\n"
            f"- run_id: `{run_id}`\n"
            f"- strategy_id: `{metrics['strategy_id']}`\n"
            f"- universe: `{metrics['universe']}`\n"
        )
