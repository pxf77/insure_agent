## ADDED Requirements

### Requirement: Single run identity and provenance
The system SHALL use one run ID across all stages of a daily workflow and record its trade
date, data version, resolved configuration, configuration hash, code version, and inputs.

#### Scenario: Daily workflow starts
- **WHEN** an operator starts a workflow for a trade date and configuration
- **THEN** one run manifest is created and every downstream artifact references that run ID

### Requirement: Ordered state transitions and attempts
The system SHALL record stage status, timestamps, attempts, errors, input checksums, and
output checksums, and SHALL reject invalid state transitions.

#### Scenario: A stage fails
- **WHEN** a stage raises an error
- **THEN** the attempt and error are recorded and later stages do not run

#### Scenario: A run resumes
- **WHEN** an operator resumes a failed or incomplete run
- **THEN** a new attempt starts at the first non-completed stage without overwriting prior attempts

### Requirement: Atomic completed-run publication
The system SHALL publish the latest completed run atomically and MUST NOT expose a partial
daily run as the latest completed run.

#### Scenario: Daily workflow completes
- **WHEN** every required stage completes
- **THEN** `latest.json` atomically points to the coherent run and its registered artifacts

#### Scenario: Daily workflow is partial
- **WHEN** one or more required stages are incomplete or failed
- **THEN** the previously completed latest run remains published
