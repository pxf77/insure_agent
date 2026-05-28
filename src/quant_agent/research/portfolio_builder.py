from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from quant_agent.schemas.research import TargetPosition, TargetPositionRequest


class PortfolioBuilder:
    def build_targets(
        self,
        daily_bar: pd.DataFrame,
        *,
        run_id: str,
        strategy_id: str,
        universe: str,
        benchmark: str | None,
        topk: int,
        generated_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> TargetPositionRequest:
        if daily_bar.empty:
            raise ValueError("daily_bar is empty")

        latest_trade_date = str(daily_bar["trade_date"].max())
        latest = (
            daily_bar.sort_values("trade_date")
            .groupby("symbol", as_index=False)
            .tail(1)
            .copy()
        )
        latest["score"] = (latest["close"] - latest["open"]) / latest["open"]
        selected = latest.sort_values(["score", "symbol"], ascending=[False, True]).head(topk)
        if selected.empty:
            raise ValueError("no symbols selected for target positions")

        weight = 1 / len(selected)
        positions = [
            TargetPosition(
                symbol=str(row.symbol),
                target_weight=weight,
                score=float(row.score),
                rank=index + 1,
                reason="deterministic momentum score from sample daily bars",
            )
            for index, row in enumerate(selected.itertuples(index=False))
        ]
        return TargetPositionRequest(
            run_id=run_id,
            strategy_id=strategy_id,
            trade_date=latest_trade_date,
            generated_at=generated_at.isoformat(),
            universe=universe,
            benchmark=benchmark,
            positions=positions,
            metadata=metadata or {},
        )
