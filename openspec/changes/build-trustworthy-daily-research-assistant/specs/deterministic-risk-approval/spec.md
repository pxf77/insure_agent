## ADDED Requirements

### Requirement: Structured deterministic risk evaluation
The system SHALL evaluate data validity and freshness, tradability, cash, gross exposure,
single-position exposure, turnover, order value, drawdown, and the kill switch and SHALL
emit structured results for each applied rule.

#### Scenario: Hard risk rule fails
- **WHEN** a critical risk rule reports an error
- **THEN** the plan is rejected and cannot be approved or executed

#### Scenario: Adjustable limit is exceeded
- **WHEN** a configurable position or order limit can be safely reduced
- **THEN** the result records the adjustment and its originating rule

### Requirement: Kill switch at every execution boundary
The system MUST check the kill switch during risk evaluation, order planning, and
immediately before ledger or gateway execution.

#### Scenario: Kill switch activates after risk approval
- **WHEN** the kill switch becomes active before paper execution
- **THEN** execution is rejected without ledger mutation

### Requirement: Approval bound to exact order plan
The system SHALL require an unexpired approval record containing the exact order-plan
checksum, approver, grant time, and expiry for the strict daily paper workflow.

#### Scenario: Approved plan is unchanged
- **WHEN** the approval is unexpired and its checksum matches the plan
- **THEN** paper execution may proceed after final safety checks

#### Scenario: Plan changes after approval
- **WHEN** any order-plan semantic content changes
- **THEN** the approval is invalid and execution is rejected
