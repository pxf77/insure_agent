## ADDED Requirements

### Requirement: Explicit research engine
The system SHALL run the research engine selected by configuration and MUST NOT silently
fall back to a different engine.

#### Scenario: Qlib engine is selected
- **WHEN** Qlib or its configured provider data is unavailable
- **THEN** the run fails with an actionable research dependency error

#### Scenario: Deterministic engine is selected
- **WHEN** the deterministic momentum engine is configured
- **THEN** the system produces repeatable predictions, targets, and metrics from the bound snapshot

### Requirement: Temporal evaluation without look-ahead
The system MUST use ordered train, validation, and test periods and record label horizon,
feature cutoff, and execution lag.

#### Scenario: Invalid temporal split is configured
- **WHEN** train, validation, and test ranges overlap or are not chronological
- **THEN** research validation fails before training

#### Scenario: Predictions are generated
- **WHEN** a model evaluates a trade date
- **THEN** every prediction is based only on inputs available at or before its feature cutoff

### Requirement: Reproducible research artifacts
The system SHALL emit prediction scores, target positions, temporal metadata, cost-aware
metrics, baseline comparison, and complete provenance.

#### Scenario: Identical research is replayed
- **WHEN** data version, configuration hash, and code version are identical
- **THEN** deterministic artifacts have identical semantic contents

#### Scenario: Promotion evidence is generated
- **WHEN** a research run completes
- **THEN** its report includes sample-out performance, turnover, costs, drawdown, and baseline comparison without auto-promoting the strategy
