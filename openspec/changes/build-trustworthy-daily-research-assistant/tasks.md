## 1. Contracts And Run Lifecycle

- [x] 1.1 Add versioned manifests, portfolio, order-plan, approval, execution-result, and provenance schemas while keeping legacy payloads readable.
- [x] 1.2 Add atomic JSON/checksum utilities and an immutable run-manifest store with ordered stages, attempts, failure records, and resume semantics.
- [x] 1.3 Make completed-run publication atomic and test that partial or mixed runs never replace the latest completed run.

## 2. Trusted Market Data

- [x] 2.1 Add canonical dataset schemas and provider-neutral sample and optional AkShare provider implementations.
- [x] 2.2 Implement immutable gzip snapshot storage, stable data versions, manifests, idempotent reuse, and critical quality validation.
- [x] 2.3 Add `data sync` behavior and tests for canonicalization, changed payloads, invalid data, missing optional packages, and repeated synchronization.

## 3. Reproducible Research

- [x] 3.1 Extend research configuration and outputs with explicit engine, temporal split, label horizon, execution lag, predictions, costs, baseline comparison, and provenance.
- [x] 3.2 Make the deterministic momentum engine consume a bound valid snapshot and produce reproducible multi-period research artifacts.
- [x] 3.3 Add a lazy real-Qlib engine that initializes Qlib, runs the configured workflow, normalizes recorder outputs, and fails without fallback when unavailable.
- [x] 3.4 Add temporal validation, look-ahead regression tests, deterministic replay tests, and optional Qlib integration coverage.

## 4. Portfolio Ledger And Paper Execution

- [x] 4.1 Implement the transactional standard-library SQLite ledger for accounts, lots, orders, trades, fees, and daily NAV.
- [x] 4.2 Implement target-delta order planning with cash, board-lot, T+1, suspension, price-limit, and configurable cost constraints.
- [x] 4.3 Implement deterministic order IDs, transactional full-fill/unfilled paper execution, retry idempotency, and end-of-day NAV accounting.
- [x] 4.4 Add tests for buy/sell deltas, cash reduction, T+1, untradable symbols, rollback, repeated execution, fees, and NAV.

## 5. Risk And Approval Safety

- [x] 5.1 Extend deterministic risk evaluation to data health, freshness, tradability, cash, exposure, turnover, order value, and drawdown with structured rule results.
- [x] 5.2 Implement expiring approval records bound to canonical order-plan checksums and invalidate approvals after semantic plan changes.
- [x] 5.3 Enforce the kill switch during risk, planning, and immediately before execution with fail-closed error handling.
- [x] 5.4 Add tests for hard rejection, safe adjustment, approval expiry/mismatch, and kill-switch activation after risk approval.

## 6. Daily Operator Workflow

- [x] 6.1 Implement idempotent daily orchestration, explicit run inspection, awaiting-approval stops, and resume from the first incomplete stage.
- [x] 6.2 Add canonical daily, resume, show, approval, and run-addressed paper CLI commands while preserving legacy commands and payloads.
- [x] 6.3 Enrich reports with coherent data health, research, holdings, deltas, estimated costs, risk, approval, execution, NAV, drawdown, benchmark, and provenance sections.
- [x] 6.4 Add end-to-end multi-day and recovery tests covering approval, execution, golden replay, coherent run IDs, and disabled live behavior.

## 7. Configuration, Documentation, And Verification

- [x] 7.1 Add environment, data, research, risk, execution, and fee configuration defaults plus operator runbook and migration documentation.
- [x] 7.2 Run the full pytest, Ruff, and Mypy suites and document optional-provider/Qlib checks and known limitations.
