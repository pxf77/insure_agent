## ADDED Requirements

### Requirement: Idempotent daily orchestration
The system SHALL provide a daily command that runs synchronization, validation, research,
planning, risk, and pre-execution reporting once per coherent run.

#### Scenario: Daily command is repeated
- **WHEN** the same trade date and resolved configuration are invoked again
- **THEN** the operator can resume or inspect the existing run without duplicating completed work

#### Scenario: Approval is required
- **WHEN** the workflow reaches a risk-approved order plan without a valid approval
- **THEN** it stops in an awaiting-approval state and reports the approval command

### Requirement: Run inspection and recovery
The system SHALL let operators show a run and resume the first incomplete or failed stage
by explicit run ID.

#### Scenario: Operator inspects a failed run
- **WHEN** `run show` is invoked
- **THEN** stage status, attempts, error, provenance, and registered artifacts are displayed

#### Scenario: Operator resumes a run
- **WHEN** `run resume` is invoked for an eligible run
- **THEN** the lifecycle records a new attempt and continues from the failed or incomplete stage

### Requirement: Decision-oriented report
The system SHALL report data health, research signal, current and target holdings, proposed
deltas, estimated costs, risk results, approval status, fills or unfilled reasons, NAV,
drawdown, and benchmark comparison when available.

#### Scenario: Run report is generated before approval
- **WHEN** a run stops awaiting approval
- **THEN** the report includes the exact plan checksum and unresolved approval status

#### Scenario: Completed report is generated
- **WHEN** paper execution and NAV accounting complete
- **THEN** the report includes execution outcomes and coherent provenance for the same run

### Requirement: Compatibility and live safety
The system SHALL keep existing local MVP commands and version 1.0 inputs readable and MUST
keep live order submission disabled.

#### Scenario: Legacy pipeline runs
- **WHEN** the existing paper pipeline command is invoked
- **THEN** its sample workflow remains operational without requiring a strict approval record

#### Scenario: Unsupported live mode is requested
- **WHEN** any command requests live order submission
- **THEN** the system rejects it regardless of research or approval state
