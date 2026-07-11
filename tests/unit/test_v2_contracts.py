from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from quant_agent.schemas.research import TargetPosition, TargetPositionRequest
from quant_agent.schemas.v2 import (
    EventEnvelope,
    InstrumentId,
    OrderIntent,
    ResearchSpec,
    RiskDecisionV2,
    TargetPortfolio,
)

CORRELATION_ID = "11111111-1111-4111-8111-111111111111"


def test_instrument_id_normalizes_and_serializes_as_string() -> None:
    instrument = InstrumentId.model_validate("sh600519")

    assert instrument.root == "600519.SH"
    assert instrument.model_dump(mode="json") == "600519.SH"


def test_instrument_id_rejects_numeric_input_to_preserve_leading_zeroes() -> None:
    with pytest.raises(ValidationError, match="must be a string"):
        InstrumentId.model_validate(1)


def test_event_envelope_normalizes_aware_timestamp_to_utc() -> None:
    envelope = EventEnvelope.model_validate(
        {
            "event_type": "risk.completed",
            "occurred_at": "2026-07-11T09:00:00+08:00",
            "correlation_id": CORRELATION_ID,
            "producer": "risk-service",
            "payload": {},
        }
    )

    assert envelope.occurred_at == datetime(2026, 7, 11, 1, 0, tzinfo=timezone.utc)


def test_event_envelope_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        EventEnvelope.model_validate(
            {
                "event_type": "risk.completed",
                "occurred_at": "2026-07-11T09:00:00",
                "correlation_id": CORRELATION_ID,
                "producer": "risk-service",
                "payload": {},
            }
        )


def test_event_envelope_requires_correlation_id() -> None:
    with pytest.raises(ValidationError, match="correlation_id"):
        EventEnvelope.model_validate(
            {
                "event_type": "risk.completed",
                "occurred_at": "2026-07-11T01:00:00Z",
                "producer": "risk-service",
                "payload": {},
            }
        )


def _research_spec_payload() -> dict[str, object]:
    return {
        "strategy_id": "lgb-alpha158-v2",
        "data_snapshot_id": "snapshot-1",
        "universe": "CSI300",
        "feature_set": "Alpha158",
        "model_name": "LightGBM",
        "train": {"start": "2018-01-01", "end": "2022-12-31"},
        "validation": {"start": "2023-01-01", "end": "2023-12-31"},
        "test": {"start": "2024-01-01", "end": "2025-12-31"},
        "random_seed": 42,
        "transaction_cost_bps": "12.5",
        "created_at": "2026-07-11T01:00:00Z",
    }


def test_research_spec_uses_decimal_and_non_overlapping_splits() -> None:
    spec = ResearchSpec.model_validate(_research_spec_payload())

    assert spec.transaction_cost_bps == Decimal("12.5")
    assert spec.model_dump(mode="json")["transaction_cost_bps"] == "12.5"


def test_research_spec_rejects_overlapping_splits() -> None:
    payload = _research_spec_payload()
    payload["validation"] = {"start": "2022-12-01", "end": "2023-12-31"}

    with pytest.raises(ValidationError, match="train range"):
        ResearchSpec.model_validate(payload)


def _target_portfolio_payload() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "strategy_id": "strategy-1",
        "trade_date": "2026-07-10",
        "generated_at": "2026-07-10T07:00:00Z",
        "universe": "CSI300",
        "positions": [
            {
                "instrument": "600519",
                "target_weight": "0.2",
                "score": "1",
                "rank": 1,
            },
            {
                "instrument": "000001.SZ",
                "target_weight": "0.1",
                "score": "0.5",
                "rank": 2,
            },
        ],
    }


def test_target_portfolio_rejects_normalized_duplicate_instruments() -> None:
    payload = _target_portfolio_payload()
    payload["positions"] = [
        {"instrument": "600519", "target_weight": "0.2", "score": "1", "rank": 1},
        {"instrument": "SH600519", "target_weight": "0.1", "score": "0.5", "rank": 2},
    ]

    with pytest.raises(ValidationError, match="duplicate instruments"):
        TargetPortfolio.model_validate(payload)


def test_target_portfolio_rejects_duplicate_ranks() -> None:
    payload = _target_portfolio_payload()
    positions = payload["positions"]
    assert isinstance(positions, list)
    positions[1]["rank"] = 1

    with pytest.raises(ValidationError, match="duplicate ranks"):
        TargetPortfolio.model_validate(payload)


def test_risk_decision_rejects_inconsistent_rejection() -> None:
    with pytest.raises(ValidationError, match="rejected decision"):
        RiskDecisionV2.model_validate(
            {
                "run_id": "run-1",
                "strategy_id": "strategy-1",
                "policy_version": "paper-v1",
                "decision": "REJECT",
                "approved": True,
                "decided_at": "2026-07-10T07:00:00Z",
                "positions": [],
                "rule_results": [],
            }
        )


def test_risk_rejection_requires_deterministic_reason() -> None:
    with pytest.raises(ValidationError, match="requires at least one REJECT"):
        RiskDecisionV2.model_validate(
            {
                "run_id": "run-1",
                "strategy_id": "strategy-1",
                "policy_version": "paper-v1",
                "decision": "REJECT",
                "approved": False,
                "decided_at": "2026-07-10T07:00:00Z",
                "positions": [],
                "rule_results": [],
            }
        )


def test_risk_rejection_with_reason_is_valid() -> None:
    decision = RiskDecisionV2.model_validate(
        {
            "run_id": "run-1",
            "strategy_id": "strategy-1",
            "policy_version": "paper-v1",
            "decision": "REJECT",
            "approved": False,
            "decided_at": "2026-07-10T07:00:00Z",
            "positions": [],
            "rule_results": [
                {
                    "rule_id": "kill-switch",
                    "rule_version": "1",
                    "outcome": "REJECT",
                    "reason_code": "KILL_SWITCH_ACTIVE",
                    "message": "global kill switch is active",
                }
            ],
        }
    )

    assert not decision.approved


def _order_payload() -> dict[str, object]:
    return {
        "idempotency_key": "run-1:600519:buy",
        "run_id": "run-1",
        "strategy_id": "strategy-1",
        "account_id": "paper-account",
        "instrument": "600519.SH",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": 100,
        "limit_price": "1500.50",
        "created_at": "2026-07-10T07:00:00Z",
    }


def test_order_intent_enforces_buy_lot_and_decimal_price() -> None:
    order = OrderIntent.model_validate(_order_payload())

    assert order.limit_price == Decimal("1500.50")
    assert order.model_dump(mode="json")["limit_price"] == "1500.50"

    invalid = _order_payload()
    invalid["quantity"] = 50
    with pytest.raises(ValidationError, match="multiple of lot_size"):
        OrderIntent.model_validate(invalid)


def test_order_intent_rejects_client_lot_size_override() -> None:
    payload = _order_payload()
    payload["quantity"] = 50
    payload["lot_size"] = 1

    with pytest.raises(ValidationError, match="Input should be 100"):
        OrderIntent.model_validate(payload)


def test_existing_v1_contract_remains_numeric_and_readable() -> None:
    request = TargetPositionRequest(
        run_id="run-1",
        strategy_id="strategy-1",
        trade_date="2026-07-10",
        generated_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        universe="CSI300",
        positions=[
            TargetPosition(symbol="600519.SH", target_weight=0.2, score=1.0, rank=1)
        ],
    )

    payload = request.model_dump(mode="json")
    assert payload["schema_version"] == "1.0"
    assert payload["positions"][0]["target_weight"] == 0.2
