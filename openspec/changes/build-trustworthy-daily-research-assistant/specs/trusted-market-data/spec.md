## ADDED Requirements

### Requirement: Provider-neutral canonical datasets
The system SHALL normalize selected provider data into versioned canonical datasets for
daily bars, adjustment factors, trading calendars, instrument status, price limits,
listings, and point-in-time universe membership.

#### Scenario: Provider output is normalized
- **WHEN** a configured provider returns data for a requested trade date
- **THEN** the system emits canonical datasets with normalized A-share symbols and schemas

#### Scenario: Optional provider is unavailable
- **WHEN** a user selects an optional provider whose package or credentials are unavailable
- **THEN** synchronization fails with an actionable error and does not substitute another provider

### Requirement: Immutable versioned snapshots
The system SHALL write synchronized canonical data to an immutable snapshot and calculate
a stable data version from the canonical contents.

#### Scenario: Synchronization is repeated
- **WHEN** the same provider payload is synchronized for the same trade date
- **THEN** the system returns the existing snapshot and data version without rewriting it

#### Scenario: Provider data changes
- **WHEN** canonical content differs for the same requested trade date
- **THEN** the system creates a distinct immutable snapshot with a new data version

### Requirement: Data manifests and fail-closed validation
The system MUST record provider, retrieval time, requested cutoff, schema versions, row
counts, checksums, and validation results, and MUST reject critical quality failures.

#### Scenario: Critical dataset is invalid
- **WHEN** required fields, dates, symbols, price relationships, freshness, or coverage fail validation
- **THEN** the snapshot is marked invalid and downstream research is blocked

#### Scenario: Snapshot is valid
- **WHEN** all critical checks pass
- **THEN** the manifest is marked valid and may be bound to a run
