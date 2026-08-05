## Context

The repository is a local, file-based MVP with stable module boundaries and tests, but
its research, risk, and execution behavior is intentionally simplified. The change is
for a single local operator running an after-close A-share workflow. Existing commands
and version 1.0 JSON payloads are already useful as fixtures and must remain readable.
Live order submission remains disabled.

## Goals / Non-Goals

**Goals:**

- Make daily data inputs versioned, quality checked, immutable, and provider neutral.
- Use one auditable run identity across data, research, risk, approval, execution, and
  reporting, with safe retries and atomic latest-run publication.
- Support an explicit deterministic baseline and a real optional Qlib workflow without
  silently substituting one for the other.
- Persist realistic paper account state and generate idempotent target-delta orders.
- Enforce deterministic risk and approval checks at every execution boundary.
- Provide an operator-friendly daily, inspect, resume, approve, and paper workflow.

**Non-Goals:**

- Minute/tick research, distributed services, multi-user access, or remote APIs.
- PostgreSQL, Redis, Kafka, gRPC, vn.py, broker connectivity, or unattended live trading.
- LLM/RD-Agent control of strategy configuration, risk decisions, approvals, or orders.
- Guaranteeing investment performance or automatically promoting a strategy by return.

## Decisions

### Data snapshots and providers

Provider adapters return canonical pandas frames for `daily_bar`, `adjust_factor`,
`trading_calendar`, `instrument_status`, `limit_price`, `listing`, and
`universe_membership`. The sample provider remains deterministic; AkShare is an optional
runtime adapter loaded only when selected. Canonical snapshots are written as immutable,
gzip-compressed CSV partitions so the core dependency set does not need a Parquet engine.
A manifest records per-dataset checksums, row counts, schema version, provider, requested
trade date, and retrieval time.

Alternative considered: writing directly into Qlib or SQLite. Rejected because provider
responses and normalized source data must remain independently replayable and auditable.

### Run lifecycle and atomic publication

Each orchestration creates or resumes `artifacts/runs/<run_id>/manifest.json`. A run has
ordered stages, a current status, immutable provenance, and numbered attempts. Stages
write to their existing domain directories but register input/output checksums in the run
manifest. JSON files use temporary-file-plus-replace writes. `latest.json` is published
only when a run reaches `COMPLETED`; legacy individual commands may update compatibility
keys but cannot mark an incomplete daily run as latest-complete.

Alternative considered: a workflow server. Rejected because a local single-user process
does not justify another service.

### Research engines

Research configuration selects `deterministic_momentum` or `qlib`; the choice is explicit.
The deterministic engine remains the default for sample fixtures. The Qlib engine imports
Qlib lazily, initializes the configured provider URI, runs the configured task, and
normalizes recorder outputs into the repository's prediction, metric, and target
contracts. Missing Qlib or missing Qlib data is an error, never a fallback.

Temporal split metadata, label horizon, execution lag, costs, and provenance are required
for new research runs. The first live-data strategy uses a five-trading-day label and
weekly rebalance schedule, while the engine remains configuration driven.

### Stateful paper ledger

Python `sqlite3` stores accounts, positions, position lots, orders, trades, fees, and NAV.
All writes run in transactions; deterministic client order IDs have a unique constraint.
Order planning compares target quantities with current quantities and cash. Buy quantities
round down to board lots; sells are capped by available T+1 quantities. Daily-bar
simulation produces either a full fill or a documented unfilled result.

Alternative considered: SQLAlchemy. Rejected for this increment to avoid a new production
dependency.

### Risk, approval, and execution boundaries

Risk evaluates data freshness, tradability, total and single-position exposure, turnover,
cash sufficiency, order value, drawdown, and the kill switch. Each rule emits a structured
result. An approval record contains the order-plan SHA-256, approver, grant time, and
expiry. Paper execution rechecks both approval validity and the kill switch immediately
before ledger mutation. Any missing or inconsistent safety input fails closed.

### CLI and compatibility

New commands operate on explicit trade dates and run IDs. `run daily` orchestrates
idempotent stages and `run resume` continues the first incomplete or failed stage.
Existing sample, research, risk, paper, report, and pipeline commands remain supported and
continue accepting version 1.0 payloads. Compatibility behavior is isolated from the new
strict daily workflow.

## Risks / Trade-offs

- [Free provider instability] → Preserve immutable raw/canonical snapshots, fail quality
  checks explicitly, and make provider selection replaceable.
- [Qlib installation and platform variance] → Keep Qlib optional, lazy-load it, and run
  Qlib integration tests only when the research extra and fixture data are available.
- [Daily bars cannot model intraday fills] → Model full fill or unfilled only, label the
  simulation assumptions, and never infer partial fills.
- [SQLite is single-host storage] → Use transactions and WAL; migrate only after there is
  a demonstrated concurrent-writer requirement.
- [Backward-compatible payloads can weaken strictness] → Validate new daily runs strictly
  while keeping legacy parsing at command boundaries.
- [Large scope] → Deliver in dependency-ordered vertical slices and keep future live and
  agentic capabilities excluded.

## Migration Plan

1. Add new schemas and lifecycle/storage services without changing legacy commands.
2. Add snapshot validation and deterministic daily fixtures.
3. Add research engine selection and normalized outputs.
4. Add ledger-backed planning, risk, approval, and paper execution.
5. Add daily orchestration, inspection, resume, and enriched reporting.
6. Retain legacy commands as compatibility aliases and document the new canonical flow.
7. Rollback consists of invoking the legacy commands; new state is isolated under
   `artifacts/runs`, `artifacts/data/snapshots`, and `artifacts/portfolio.db`.

## Open Questions

None for this increment. Broker-specific fees, a paid provider, and shadow/live modes
require separate future changes.
