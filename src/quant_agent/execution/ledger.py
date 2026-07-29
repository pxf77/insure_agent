from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from quant_agent.execution.config import FeeSchedule
from quant_agent.schemas.portfolio import (
    ExecutionOutcome,
    NavSnapshot,
    PlannedOrder,
    PortfolioPosition,
    PortfolioSnapshot,
)


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class PortfolioLedger:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    cash REAL NOT NULL CHECK (cash >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS position_lots (
                    lot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    acquired_date TEXT NOT NULL,
                    volume INTEGER NOT NULL CHECK (volume > 0),
                    remaining_volume INTEGER NOT NULL CHECK (remaining_volume >= 0),
                    unit_cost REAL NOT NULL CHECK (unit_cost >= 0),
                    source_trade_id TEXT,
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
                );
                CREATE INDEX IF NOT EXISTS idx_position_lots_account_symbol
                    ON position_lots(account_id, symbol, acquired_date, lot_id);
                CREATE TABLE IF NOT EXISTS orders (
                    client_order_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    plan_checksum TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    reference_price REAL NOT NULL,
                    execution_price REAL NOT NULL,
                    requested_volume INTEGER NOT NULL,
                    filled_volume INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    fee REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
                );
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    client_order_id TEXT UNIQUE NOT NULL,
                    account_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    value REAL NOT NULL,
                    fee REAL NOT NULL,
                    traded_at TEXT NOT NULL,
                    FOREIGN KEY (client_order_id) REFERENCES orders(client_order_id),
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
                );
                CREATE TABLE IF NOT EXISTS fees (
                    client_order_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    FOREIGN KEY (client_order_id) REFERENCES orders(client_order_id),
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
                );
                CREATE TABLE IF NOT EXISTS nav (
                    account_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    cash REAL NOT NULL,
                    market_value REAL NOT NULL,
                    total_equity REAL NOT NULL,
                    daily_return REAL NOT NULL,
                    drawdown REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, trade_date),
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
                );
                CREATE TABLE IF NOT EXISTS execution_sessions (
                    account_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    plan_checksum TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, trade_date),
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
                );
                """
            )
            connection.commit()

    def ensure_account(self, account_id: str, initial_cash: float) -> None:
        if initial_cash <= 0:
            raise ValueError("initial cash must be positive")
        timestamp = now_text()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO accounts(account_id, cash, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (account_id, initial_cash, timestamp, timestamp),
            )
            connection.commit()

    def cash(self, account_id: str) -> float:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT cash FROM accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"paper account not found: {account_id}")
        return float(row["cash"])

    def validate_trade_date_ordering(
        self,
        *,
        account_id: str,
        trade_date: str,
    ) -> None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT MAX(trade_date) AS latest_trade_date
                FROM execution_sessions
                WHERE account_id = ?
                """,
                (account_id,),
            ).fetchone()
        latest = (
            str(row["latest_trade_date"])
            if row and row["latest_trade_date"] is not None
            else None
        )
        if latest is not None and latest > trade_date:
            raise ValueError(
                f"cannot process {trade_date}; account already advanced to {latest}"
            )

    def begin_execution_session(
        self,
        *,
        account_id: str,
        trade_date: str,
        run_id: str,
        plan_checksum: str,
    ) -> None:
        self.validate_trade_date_ordering(
            account_id=account_id,
            trade_date=trade_date,
        )
        timestamp = now_text()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT run_id, plan_checksum
                FROM execution_sessions
                WHERE account_id = ? AND trade_date = ?
                """,
                (account_id, trade_date),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["run_id"]) != run_id
                    or str(existing["plan_checksum"]) != plan_checksum
                ):
                    connection.rollback()
                    raise ValueError(
                        f"account {account_id} already has a different execution "
                        f"session for {trade_date}"
                    )
                connection.rollback()
                return
            connection.execute(
                """
                INSERT INTO execution_sessions(
                    account_id, trade_date, run_id, plan_checksum,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'STARTED', ?, ?)
                """,
                (
                    account_id,
                    trade_date,
                    run_id,
                    plan_checksum,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()

    def complete_execution_session(
        self,
        *,
        account_id: str,
        trade_date: str,
        run_id: str,
        plan_checksum: str,
    ) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE execution_sessions
                SET status = 'COMPLETED', updated_at = ?
                WHERE account_id = ? AND trade_date = ?
                  AND run_id = ? AND plan_checksum = ?
                """,
                (
                    now_text(),
                    account_id,
                    trade_date,
                    run_id,
                    plan_checksum,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise ValueError("execution session identity is inconsistent")
            connection.commit()

    def seed_lot(
        self,
        *,
        account_id: str,
        symbol: str,
        acquired_date: str,
        volume: int,
        unit_cost: float,
    ) -> None:
        if volume <= 0 or unit_cost < 0:
            raise ValueError("seed lot requires positive volume and non-negative cost")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO position_lots(
                    account_id, symbol, acquired_date, volume, remaining_volume, unit_cost
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (account_id, symbol, acquired_date, volume, volume, unit_cost),
            )
            connection.commit()

    def portfolio_snapshot(
        self,
        *,
        account_id: str,
        trade_date: str,
        prices: dict[str, float],
    ) -> PortfolioSnapshot:
        cash = self.cash(account_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    symbol,
                    SUM(remaining_volume) AS total_volume,
                    SUM(
                        CASE WHEN acquired_date < ? THEN remaining_volume ELSE 0 END
                    ) AS available_volume,
                    SUM(remaining_volume * unit_cost) AS cost_value
                FROM position_lots
                WHERE account_id = ? AND remaining_volume > 0
                GROUP BY symbol
                ORDER BY symbol
                """,
                (trade_date, account_id),
            ).fetchall()
        positions: list[PortfolioPosition] = []
        for row in rows:
            symbol = str(row["symbol"])
            if symbol not in prices:
                raise KeyError(f"missing market price for held symbol: {symbol}")
            total_volume = int(row["total_volume"])
            market_price = float(prices[symbol])
            positions.append(
                PortfolioPosition(
                    symbol=symbol,
                    total_volume=total_volume,
                    available_volume=int(row["available_volume"]),
                    average_cost=(
                        float(row["cost_value"]) / total_volume if total_volume else 0.0
                    ),
                    market_price=market_price,
                    market_value=round(total_volume * market_price, 6),
                )
            )
        market_value = round(sum(position.market_value for position in positions), 6)
        return PortfolioSnapshot(
            account_id=account_id,
            trade_date=trade_date,
            cash=round(cash, 6),
            market_value=market_value,
            total_equity=round(cash + market_value, 6),
            positions=positions,
        )

    def execute_order(
        self,
        *,
        account_id: str,
        run_id: str,
        plan_checksum: str,
        trade_date: str,
        order: PlannedOrder,
        execution_price: float,
        fee_schedule: FeeSchedule,
        unfilled_reason: str | None = None,
    ) -> ExecutionOutcome:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM orders WHERE client_order_id = ?",
                (order.client_order_id,),
            ).fetchone()
            if existing is not None:
                connection.rollback()
                return self._duplicate_outcome(existing)
            if unfilled_reason:
                outcome = self._insert_unfilled(
                    connection,
                    account_id=account_id,
                    run_id=run_id,
                    plan_checksum=plan_checksum,
                    trade_date=trade_date,
                    order=order,
                    execution_price=execution_price,
                    reason=unfilled_reason,
                )
                connection.commit()
                return outcome

            trade_value = round(execution_price * order.volume, 6)
            fee = fee_schedule.estimate_fee(order.side, trade_value)
            trade_id = f"trade-{order.client_order_id}"
            timestamp = now_text()
            try:
                if order.side == "BUY":
                    cash_row = connection.execute(
                        "SELECT cash FROM accounts WHERE account_id = ?",
                        (account_id,),
                    ).fetchone()
                    if cash_row is None:
                        raise KeyError(f"paper account not found: {account_id}")
                    required = trade_value + fee
                    if float(cash_row["cash"]) + 1e-9 < required:
                        outcome = self._insert_unfilled(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            plan_checksum=plan_checksum,
                            trade_date=trade_date,
                            order=order,
                            execution_price=execution_price,
                            reason="INSUFFICIENT_CASH",
                        )
                        connection.commit()
                        return outcome
                    connection.execute(
                        """
                        UPDATE accounts
                        SET cash = cash - ?, updated_at = ?
                        WHERE account_id = ?
                        """,
                        (required, timestamp, account_id),
                    )
                    self._after_cash_mutation()
                    connection.execute(
                        """
                        INSERT INTO position_lots(
                            account_id, symbol, acquired_date, volume,
                            remaining_volume, unit_cost, source_trade_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            account_id,
                            order.symbol,
                            trade_date,
                            order.volume,
                            order.volume,
                            (trade_value + fee) / order.volume,
                            trade_id,
                        ),
                    )
                else:
                    available = self._available_lots(
                        connection,
                        account_id=account_id,
                        symbol=order.symbol,
                        trade_date=trade_date,
                    )
                    if sum(int(row["remaining_volume"]) for row in available) < order.volume:
                        outcome = self._insert_unfilled(
                            connection,
                            account_id=account_id,
                            run_id=run_id,
                            plan_checksum=plan_checksum,
                            trade_date=trade_date,
                            order=order,
                            execution_price=execution_price,
                            reason="T1_INSUFFICIENT_AVAILABLE",
                        )
                        connection.commit()
                        return outcome
                    remaining = order.volume
                    for lot in available:
                        consumed = min(remaining, int(lot["remaining_volume"]))
                        connection.execute(
                            """
                            UPDATE position_lots
                            SET remaining_volume = remaining_volume - ?
                            WHERE lot_id = ?
                            """,
                            (consumed, int(lot["lot_id"])),
                        )
                        remaining -= consumed
                        if remaining == 0:
                            break
                    proceeds = trade_value - fee
                    connection.execute(
                        """
                        UPDATE accounts
                        SET cash = cash + ?, updated_at = ?
                        WHERE account_id = ?
                        """,
                        (proceeds, timestamp, account_id),
                    )
                    self._after_cash_mutation()

                connection.execute(
                    """
                    INSERT INTO orders(
                        client_order_id, account_id, run_id, plan_checksum, trade_date,
                        symbol, side, reference_price, execution_price, requested_volume,
                        filled_volume, status, reason, fee, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FILLED', NULL, ?, ?, ?)
                    """,
                    (
                        order.client_order_id,
                        account_id,
                        run_id,
                        plan_checksum,
                        trade_date,
                        order.symbol,
                        order.side,
                        order.price,
                        execution_price,
                        order.volume,
                        order.volume,
                        fee,
                        timestamp,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO trades(
                        trade_id, client_order_id, account_id, trade_date, symbol,
                        side, price, volume, value, fee, traded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade_id,
                        order.client_order_id,
                        account_id,
                        trade_date,
                        order.symbol,
                        order.side,
                        execution_price,
                        order.volume,
                        trade_value,
                        fee,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO fees(client_order_id, account_id, trade_date, amount)
                    VALUES (?, ?, ?, ?)
                    """,
                    (order.client_order_id, account_id, trade_date, fee),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return ExecutionOutcome(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            requested_volume=order.volume,
            filled_volume=order.volume,
            price=execution_price,
            fee=fee,
            status="FILLED",
            trade_id=trade_id,
        )

    def record_nav(
        self,
        *,
        account_id: str,
        trade_date: str,
        prices: dict[str, float],
    ) -> NavSnapshot:
        snapshot = self.portfolio_snapshot(
            account_id=account_id,
            trade_date=trade_date,
            prices=prices,
        )
        with self._connection() as connection:
            previous = connection.execute(
                """
                SELECT total_equity FROM nav
                WHERE account_id = ? AND trade_date < ?
                ORDER BY trade_date DESC LIMIT 1
                """,
                (account_id, trade_date),
            ).fetchone()
            peak = connection.execute(
                "SELECT MAX(total_equity) AS peak FROM nav WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            previous_equity = float(previous["total_equity"]) if previous else None
            prior_peak = float(peak["peak"]) if peak and peak["peak"] is not None else 0.0
            daily_return = (
                0.0
                if not previous_equity
                else (snapshot.total_equity / previous_equity) - 1
            )
            current_peak = max(prior_peak, snapshot.total_equity)
            drawdown = (
                0.0
                if current_peak <= 0
                else (snapshot.total_equity / current_peak) - 1
            )
            nav = NavSnapshot(
                account_id=account_id,
                trade_date=trade_date,
                cash=snapshot.cash,
                market_value=snapshot.market_value,
                total_equity=snapshot.total_equity,
                daily_return=round(daily_return, 8),
                drawdown=round(min(drawdown, 0.0), 8),
            )
            existing = connection.execute(
                "SELECT * FROM nav WHERE account_id = ? AND trade_date = ?",
                (account_id, trade_date),
            ).fetchone()
            if existing is not None:
                persisted = NavSnapshot(
                    account_id=account_id,
                    trade_date=trade_date,
                    cash=float(existing["cash"]),
                    market_value=float(existing["market_value"]),
                    total_equity=float(existing["total_equity"]),
                    daily_return=float(existing["daily_return"]),
                    drawdown=float(existing["drawdown"]),
                )
                if persisted != nav:
                    raise ValueError(
                        f"NAV already exists with different values for {trade_date}"
                    )
                return persisted
            connection.execute(
                """
                INSERT INTO nav(
                    account_id, trade_date, cash, market_value, total_equity,
                    daily_return, drawdown, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    trade_date,
                    nav.cash,
                    nav.market_value,
                    nav.total_equity,
                    nav.daily_return,
                    nav.drawdown,
                    now_text(),
                ),
            )
            connection.commit()
        return nav

    def order_count(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM orders").fetchone()
        return int(row["count"]) if row else 0

    def trade_count(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM trades").fetchone()
        return int(row["count"]) if row else 0

    def latest_nav(
        self,
        account_id: str,
        *,
        before_trade_date: str | None = None,
    ) -> NavSnapshot | None:
        date_filter = "AND trade_date < ?" if before_trade_date else ""
        parameters: tuple[str, ...] = (
            (account_id, before_trade_date)
            if before_trade_date
            else (account_id,)
        )
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM nav
                WHERE account_id = ?
                {date_filter}
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                parameters,
            ).fetchone()
        if row is None:
            return None
        return NavSnapshot(
            account_id=account_id,
            trade_date=str(row["trade_date"]),
            cash=float(row["cash"]),
            market_value=float(row["market_value"]),
            total_equity=float(row["total_equity"]),
            daily_return=float(row["daily_return"]),
            drawdown=float(row["drawdown"]),
        )

    def _after_cash_mutation(self) -> None:
        """Test seam used to prove the transaction rolls back after a mid-write failure."""

    @staticmethod
    def _available_lots(
        connection: sqlite3.Connection,
        *,
        account_id: str,
        symbol: str,
        trade_date: str,
    ) -> list[sqlite3.Row]:
        return list(
            connection.execute(
                """
                SELECT lot_id, remaining_volume
                FROM position_lots
                WHERE account_id = ? AND symbol = ? AND acquired_date < ?
                  AND remaining_volume > 0
                ORDER BY acquired_date, lot_id
                """,
                (account_id, symbol, trade_date),
            ).fetchall()
        )

    @staticmethod
    def _insert_unfilled(
        connection: sqlite3.Connection,
        *,
        account_id: str,
        run_id: str,
        plan_checksum: str,
        trade_date: str,
        order: PlannedOrder,
        execution_price: float,
        reason: str,
    ) -> ExecutionOutcome:
        timestamp = now_text()
        connection.execute(
            """
            INSERT INTO orders(
                client_order_id, account_id, run_id, plan_checksum, trade_date,
                symbol, side, reference_price, execution_price, requested_volume,
                filled_volume, status, reason, fee, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'UNFILLED', ?, 0, ?, ?)
            """,
            (
                order.client_order_id,
                account_id,
                run_id,
                plan_checksum,
                trade_date,
                order.symbol,
                order.side,
                order.price,
                execution_price,
                order.volume,
                reason,
                timestamp,
                timestamp,
            ),
        )
        return ExecutionOutcome(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            requested_volume=order.volume,
            filled_volume=0,
            price=execution_price,
            fee=0,
            status="UNFILLED",
            reason=reason,
        )

    @staticmethod
    def _duplicate_outcome(row: sqlite3.Row) -> ExecutionOutcome:
        raw_side = str(row["side"])
        if raw_side not in {"BUY", "SELL"}:
            raise ValueError(f"invalid persisted order side: {raw_side}")
        side: Literal["BUY", "SELL"] = "BUY" if raw_side == "BUY" else "SELL"
        return ExecutionOutcome(
            client_order_id=str(row["client_order_id"]),
            symbol=str(row["symbol"]),
            side=side,
            requested_volume=int(row["requested_volume"]),
            filled_volume=int(row["filled_volume"]),
            price=float(row["execution_price"]),
            fee=float(row["fee"]),
            status="DUPLICATE",
            reason=str(row["reason"]) if row["reason"] is not None else None,
            trade_id=(
                f"trade-{row['client_order_id']}"
                if str(row["status"]) == "FILLED"
                else None
            ),
        )
