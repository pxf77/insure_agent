from datetime import date
from pathlib import Path

import pytest

from quant_agent.data.providers.base import CanonicalDataBundle
from quant_agent.data.providers.sample_provider import SampleDataProvider
from quant_agent.data.snapshots import DataSnapshotStore
from quant_agent.execution.config import PaperAccountSettings
from quant_agent.execution.ledger import PortfolioLedger
from quant_agent.execution.paper import LedgerPaperExecutor
from quant_agent.execution.planning import PortfolioOrderPlanner
from quant_agent.schemas.portfolio import PlannedOrder
from quant_agent.schemas.research import TargetPosition, TargetPositionRequest

TRADE_DATE = date(2026, 7, 29)


def snapshot(tmp_path: Path, provider=None):
    return DataSnapshotStore(tmp_path).synchronize(
        provider or SampleDataProvider(),
        TRADE_DATE,
    )


def targets(positions: list[tuple[str, float]]) -> TargetPositionRequest:
    return TargetPositionRequest(
        run_id="daily-run-1",
        strategy_id="daily-momentum",
        trade_date=TRADE_DATE.isoformat(),
        generated_at="2026-07-29T16:00:00+08:00",
        universe="CSI300",
        positions=[
            TargetPosition(
                symbol=symbol,
                target_weight=weight,
                score=1.0 - index,
                rank=index + 1,
            )
            for index, (symbol, weight) in enumerate(positions)
        ],
        data_version=None,
        config_hash="config-hash",
        code_version="code-hash",
    )


def planner_and_ledger(
    tmp_path: Path,
    *,
    initial_cash: float = 1_000_000,
):
    settings = PaperAccountSettings(initial_cash=initial_cash)
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    planner = PortfolioOrderPlanner(
        ledger=ledger,
        settings=settings,
        artifact_root=tmp_path,
    )
    return planner, ledger, settings


def test_planner_and_executor_create_idempotent_buys_fees_and_nav(tmp_path: Path):
    market = snapshot(tmp_path)
    planner, ledger, settings = planner_and_ledger(tmp_path)
    request = targets([("600519.SH", 0.2), ("000001.SZ", 0.2)])
    request.data_version = market.manifest.data_version

    plan = planner.build(targets=request, manifest=market.manifest)
    first = LedgerPaperExecutor(
        ledger=ledger,
        settings=settings,
        artifact_root=tmp_path,
    ).execute(plan=plan, manifest=market.manifest, require_approval=False)
    second = LedgerPaperExecutor(
        ledger=ledger,
        settings=settings,
        artifact_root=tmp_path,
    ).execute(plan=plan, manifest=market.manifest, require_approval=False)

    assert plan.orders
    assert all(order.side == "BUY" for order in plan.orders)
    assert all(order.volume % 100 == 0 for order in plan.orders)
    assert first.nav.total_equity < settings.initial_cash
    assert first.nav.drawdown == 0
    assert ledger.order_count() == len(plan.orders)
    assert ledger.trade_count() == len(plan.orders)
    assert all(outcome.status == "DUPLICATE" for outcome in second.outcomes)
    same_day = ledger.portfolio_snapshot(
        account_id=settings.account_id,
        trade_date=TRADE_DATE.isoformat(),
        prices={
            outcome.symbol: outcome.price
            for outcome in first.outcomes
            if outcome.status == "FILLED"
        },
    )
    assert all(position.available_volume == 0 for position in same_day.positions)


def test_planner_generates_sell_delta_from_available_lot(tmp_path: Path):
    market = snapshot(tmp_path)
    planner, ledger, settings = planner_and_ledger(tmp_path, initial_cash=100_000)
    ledger.ensure_account(settings.account_id, settings.initial_cash)
    ledger.seed_lot(
        account_id=settings.account_id,
        symbol="600519.SH",
        acquired_date="2026-07-28",
        volume=1_000,
        unit_cost=100,
    )
    request = targets([])
    request.data_version = market.manifest.data_version

    plan = planner.build(targets=request, manifest=market.manifest)

    assert len(plan.orders) == 1
    assert plan.orders[0].side == "SELL"
    assert plan.orders[0].volume == 1_000


def test_t1_locked_position_is_not_sold(tmp_path: Path):
    market = snapshot(tmp_path)
    planner, ledger, settings = planner_and_ledger(tmp_path)
    ledger.ensure_account(settings.account_id, settings.initial_cash)
    ledger.seed_lot(
        account_id=settings.account_id,
        symbol="600519.SH",
        acquired_date=TRADE_DATE.isoformat(),
        volume=1_000,
        unit_cost=100,
    )
    request = targets([])
    request.data_version = market.manifest.data_version

    plan = planner.build(targets=request, manifest=market.manifest)

    assert plan.orders == []
    assert plan.skipped[0].reason == "T1_LOCKED"
    assert plan.skipped[0].requested_volume == 1_000


def test_buy_is_reduced_when_cash_cannot_fund_one_lot(tmp_path: Path):
    market = snapshot(tmp_path)
    daily = DataSnapshotStore.load_dataset(market.manifest, "daily_bar")
    latest_price = float(
        daily[
            (daily["trade_date"] == TRADE_DATE.isoformat())
            & (daily["symbol"] == "600519.SH")
        ]["close"].iloc[0]
    )
    planner, _, _ = planner_and_ledger(
        tmp_path,
        initial_cash=(latest_price * 100) + 1,
    )
    request = targets([("600519.SH", 1.0)])
    request.data_version = market.manifest.data_version

    plan = planner.build(targets=request, manifest=market.manifest)

    assert plan.orders == []
    assert plan.skipped[0].reason == "CASH_REDUCED"


def test_estimated_buy_value_and_cash_constraint_include_slippage(tmp_path: Path):
    market = snapshot(tmp_path)
    daily = DataSnapshotStore.load_dataset(market.manifest, "daily_bar")
    latest_price = float(
        daily[
            (daily["trade_date"] == TRADE_DATE.isoformat())
            & (daily["symbol"] == "600519.SH")
        ]["close"].iloc[0]
    )
    planner, _, settings = planner_and_ledger(
        tmp_path,
        initial_cash=(latest_price * 100) + settings_minimum_commission(),
    )
    request = targets([("600519.SH", 1.0)])
    request.data_version = market.manifest.data_version

    plan = planner.build(targets=request, manifest=market.manifest)

    assert plan.orders == []
    expected_price = settings.fees.execution_price("BUY", latest_price)
    assert expected_price > latest_price


def settings_minimum_commission() -> float:
    return PaperAccountSettings().fees.minimum_commission


class SuspendedSampleProvider(SampleDataProvider):
    def fetch(self, trade_date: date) -> CanonicalDataBundle:
        original = super().fetch(trade_date)
        datasets = {name: frame.copy() for name, frame in original.datasets.items()}
        latest = datasets["instrument_status"]["trade_date"] == trade_date.isoformat()
        symbol = datasets["instrument_status"]["symbol"] == "600519.SH"
        datasets["instrument_status"].loc[latest & symbol, "suspended"] = True
        datasets["instrument_status"].loc[latest & symbol, "status"] = "SUSPENDED"
        return CanonicalDataBundle(
            provider=original.provider,
            trade_date=original.trade_date,
            datasets=datasets,
            metadata=original.metadata,
        )


def test_suspended_symbol_is_skipped(tmp_path: Path):
    market = snapshot(tmp_path, SuspendedSampleProvider())
    planner, _, _ = planner_and_ledger(tmp_path)
    request = targets([("600519.SH", 0.2)])
    request.data_version = market.manifest.data_version

    plan = planner.build(targets=request, manifest=market.manifest)

    assert plan.orders == []
    assert plan.skipped[0].reason == "SUSPENDED"


def test_mid_transaction_failure_rolls_back_cash_and_order(
    tmp_path: Path,
    monkeypatch,
):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.ensure_account("paper-main", 100_000)
    order = PlannedOrder(
        client_order_id="order-1",
        symbol="600519.SH",
        side="BUY",
        price=100,
        volume=100,
        estimated_value=10_000,
        estimated_fee=5,
    )

    def fail():
        raise RuntimeError("injected failure")

    monkeypatch.setattr(ledger, "_after_cash_mutation", fail)

    with pytest.raises(RuntimeError, match="injected failure"):
        ledger.execute_order(
            account_id="paper-main",
            run_id="run-1",
            plan_checksum="checksum",
            trade_date=TRADE_DATE.isoformat(),
            order=order,
            execution_price=100,
            fee_schedule=PaperAccountSettings().fees,
        )

    assert ledger.cash("paper-main") == 100_000
    assert ledger.order_count() == 0
    assert ledger.trade_count() == 0


def test_account_allows_only_one_execution_run_per_trade_date(tmp_path: Path):
    ledger = PortfolioLedger(tmp_path / "portfolio.db")
    ledger.ensure_account("paper-main", 100_000)
    ledger.begin_execution_session(
        account_id="paper-main",
        trade_date=TRADE_DATE.isoformat(),
        run_id="run-1",
        plan_checksum="plan-1",
    )

    with pytest.raises(ValueError, match="different execution session"):
        ledger.begin_execution_session(
            account_id="paper-main",
            trade_date=TRADE_DATE.isoformat(),
            run_id="run-2",
            plan_checksum="plan-2",
        )
