import json
from pathlib import Path

import pandas as pd

from quant_agent.execution.bridge import ExecutionBridge
from quant_agent.execution.mock_gateway import MockExecutionAdapter
from quant_agent.research.report_writer import ReportWriter
from quant_agent.schemas.risk import ApprovedPosition, RiskDecision


def write_raw_daily_bar(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "trade_date": "2026-05-22",
                "symbol": "600519.SH",
                "open": 100.0,
                "high": 110.0,
                "low": 99.0,
                "close": 105.0,
                "volume": 1000,
                "amount": 105000.0,
            }
        ]
    ).to_csv(raw_dir / "daily_bar.csv", index=False)


def make_risk_decision() -> RiskDecision:
    return RiskDecision(
        run_id="demo-run",
        strategy_id="demo_strategy",
        approved=True,
        decision="APPROVE",
        positions=[
            ApprovedPosition(
                symbol="600519.SH",
                target_weight=0.10,
                adjusted=False,
                reason=None,
            )
        ],
        violations=[],
    )


def test_execution_bridge_and_mock_gateway_create_orders_and_trades(tmp_path):
    raw_dir = tmp_path / "artifacts" / "data" / "raw"
    write_raw_daily_bar(raw_dir)
    decision = make_risk_decision()

    orders = ExecutionBridge(raw_data_dir=raw_dir, account_value=1_000_000).build_orders(decision)
    trades = MockExecutionAdapter().execute(orders)

    assert orders.orders[0].symbol == "600519.SH"
    assert orders.orders[0].volume == 900
    assert trades.trades[0].volume == 900
    assert trades.trades[0].price == 105.0


def test_report_writer_generates_markdown_report(tmp_path):
    artifact_root = tmp_path / "artifacts"
    report_path = ReportWriter(artifact_root=artifact_root).write_report(
        run_id="demo-run",
        strategy_id="demo_strategy",
        metrics={"annual_return": 0.1},
        risk_decision=make_risk_decision(),
        orders_payload=None,
        trades_payload=None,
    )

    assert report_path.is_file()
    report_text = report_path.read_text()
    assert "demo-run" in report_text
    assert "Risk Decision" in report_text


def test_risk_decision_round_trips_json():
    decision = make_risk_decision()
    payload = decision.model_dump(mode="json")

    loaded = RiskDecision.model_validate(json.loads(json.dumps(payload)))

    assert loaded == decision
