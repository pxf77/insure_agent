from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from quant_agent.execution.v2_models import (
    CurrentHolding,
    OrderAggregate,
    OrderSide,
    ReconciliationDiscrepancy,
    ReconciliationReport,
    ReconciliationSeverity,
)


def expected_positions(
    *,
    holdings: list[CurrentHolding],
    orders: list[OrderAggregate],
) -> dict[str, int]:
    positions = defaultdict(int)
    for holding in holdings:
        positions[str(holding.instrument)] += holding.quantity
    for aggregate in orders:
        signed = 1 if aggregate.intent.side == OrderSide.BUY else -1
        positions[str(aggregate.intent.instrument)] += signed * aggregate.filled_quantity
    return dict(sorted(positions.items()))


def reconcile_positions(
    *,
    run_id: str,
    checked_at: datetime,
    holdings: list[CurrentHolding],
    orders: list[OrderAggregate],
    gateway_positions: dict[str, int],
) -> ReconciliationReport:
    expected = expected_positions(holdings=holdings, orders=orders)
    discrepancies: list[ReconciliationDiscrepancy] = []
    for instrument in sorted(set(expected) | set(gateway_positions)):
        expected_quantity = expected.get(instrument, 0)
        actual_quantity = gateway_positions.get(instrument, 0)
        if expected_quantity < 0:
            discrepancies.append(
                ReconciliationDiscrepancy(
                    instrument=instrument,
                    severity=ReconciliationSeverity.CRITICAL,
                    reason_code="NEGATIVE_EXPECTED_POSITION",
                    expected=str(expected_quantity),
                    actual=str(actual_quantity),
                    message="fills produced a negative internal position",
                )
            )
        if expected_quantity != actual_quantity:
            discrepancies.append(
                ReconciliationDiscrepancy(
                    instrument=instrument,
                    severity=ReconciliationSeverity.CRITICAL,
                    reason_code="POSITION_MISMATCH",
                    expected=str(expected_quantity),
                    actual=str(actual_quantity),
                    message="internal and gateway position quantities differ",
                )
            )
    return ReconciliationReport(
        run_id=run_id,
        checked_at=checked_at,
        discrepancies=discrepancies,
    )
