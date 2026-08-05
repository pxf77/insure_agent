## ADDED Requirements

### Requirement: Persistent transactional portfolio ledger
The system SHALL persist paper cash, position lots, holdings, orders, trades, fees, and NAV
in a transactional local SQLite ledger.

#### Scenario: Execution succeeds
- **WHEN** a paper order fills
- **THEN** cash, lots, holdings, trade, fees, and order state are committed atomically

#### Scenario: Execution fails
- **WHEN** any ledger mutation fails
- **THEN** the transaction rolls back without partial account changes

### Requirement: Target-delta order planning
The system SHALL generate orders from target holdings minus current holdings while applying
cash, board-lot, T+1, suspension, and price-limit constraints.

#### Scenario: Existing position exceeds target
- **WHEN** sellable holdings are greater than the target quantity
- **THEN** a sell order capped by T+1 available shares is planned

#### Scenario: Cash cannot fund target
- **WHEN** available cash is insufficient for a planned buy and estimated costs
- **THEN** the buy is reduced to an affordable board-lot quantity or omitted with a reason

### Requirement: Idempotent daily-bar paper execution
The system SHALL assign deterministic unique client order IDs and represent a daily-bar
paper order as fully filled or explicitly unfilled.

#### Scenario: Execution is retried
- **WHEN** the same order plan is executed more than once
- **THEN** no duplicate order, trade, fee, or position mutation is created

#### Scenario: Symbol is not tradable
- **WHEN** a symbol is suspended or blocked by its daily price limit
- **THEN** the order is recorded as unfilled with a deterministic reason

### Requirement: Daily NAV accounting
The system SHALL calculate end-of-day cash, market value, total equity, daily return, and
drawdown from the ledger and bound market snapshot.

#### Scenario: Paper day closes
- **WHEN** execution processing finishes for a trade date
- **THEN** one idempotent NAV record is stored and exposed in the execution result
