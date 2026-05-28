from __future__ import annotations

import json
from pathlib import Path

from quant_agent.common.run_index import RunIndex
from quant_agent.execution.bridge import ExecutionBridge
from quant_agent.execution.mock_gateway import MockExecutionAdapter
from quant_agent.schemas.risk import RiskDecision


class PaperTradingRunner:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        raw_data_dir: str | Path,
        account_value: float = 1_000_000,
    ):
        self.artifact_root = Path(artifact_root)
        self.raw_data_dir = Path(raw_data_dir)
        self.account_value = account_value

    def run(self, approved_positions_path: str | Path) -> tuple[Path, Path]:
        decision = RiskDecision.model_validate_json(
            Path(approved_positions_path).read_text(encoding="utf-8")
        )
        orders = ExecutionBridge(self.raw_data_dir, self.account_value).build_orders(decision)
        trades = MockExecutionAdapter().execute(orders)
        output_dir = self.artifact_root / "execution_runs" / decision.run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        orders_path = output_dir / "orders.json"
        trades_path = output_dir / "trades.json"
        orders_path.write_text(
            json.dumps(orders.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        trades_path.write_text(
            json.dumps(trades.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        RunIndex(self.artifact_root).update(
            execution_run=decision.run_id,
            orders=str(orders_path),
            trades=str(trades_path),
        )
        return orders_path, trades_path
