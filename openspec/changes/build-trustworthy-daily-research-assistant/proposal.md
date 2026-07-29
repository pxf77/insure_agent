## Why

The current repository demonstrates the intended research-to-execution shape, but its
sample-only data, simplified research calculations, stateless all-buy execution, and
partial safety checks cannot support repeatable daily investment decisions. The next
increment must make correctness, reproducibility, portfolio state, and fail-closed
operation the primary product capabilities while retaining the existing local workflow.

## What Changes

- Add replaceable A-share data providers, immutable daily data snapshots, manifests, and
  validation for prices, adjustments, calendars, trading status, price limits, listings,
  and point-in-time universes.
- Introduce a single-run lifecycle with immutable manifests, attempts, checksums, resumable
  stages, and atomic publication of the latest completed run.
- Replace the Qlib-named placeholder with a real optional Qlib workflow and retain a
  deterministic momentum baseline for fixtures, diagnostics, and comparison.
- Add reproducible time-series evaluation, prediction artifacts, cost-aware metrics, and
  promotion evidence without making returns an automatic deployment criterion.
- Add a standard-library SQLite portfolio ledger for cash, positions, orders, trades,
  fees, and daily NAV; generate delta orders rather than unconditional buys.
- Extend deterministic risk controls, enforce the kill switch at every execution boundary,
  and require expiring approval records bound to the exact order plan.
- Add idempotent daily, resume, show, approval, and run-addressed paper commands while
  preserving the existing CLI and JSON inputs as compatibility paths.
- Expand reports, tests, and runbooks around data health, holdings, planned changes,
  execution results, NAV, failures, and operational recovery.
- Keep live brokerage, unattended trading, RD-Agent/LLM control, distributed messaging,
  and multi-user infrastructure out of this change.

## Capabilities

### New Capabilities

- `trusted-market-data`: Provider-neutral daily A-share datasets, immutable snapshots,
  manifests, and fail-closed quality validation.
- `auditable-run-lifecycle`: One run identity across stages, state transitions, attempts,
  checksums, resume support, and atomic latest-run publication.
- `reproducible-research`: Deterministic and Qlib-backed research workflows with temporal
  evaluation, predictions, targets, metrics, and provenance.
- `portfolio-paper-execution`: Persistent paper account state, target-delta order planning,
  A-share trading constraints, idempotent execution, and NAV accounting.
- `deterministic-risk-approval`: Layered risk decisions, multi-boundary kill-switch checks,
  and expiring approvals bound to immutable order plans.
- `daily-operator-workflow`: Daily CLI orchestration, run inspection and recovery,
  compatibility commands, and decision-oriented reports.

### Modified Capabilities

None. This repository has no existing OpenSpec capability specifications.

## Impact

- Affects the data, research, risk, execution, reporting, shared schema, configuration, CLI,
  test, and documentation areas.
- Keeps the existing core production dependency set; AkShare, Tushare, Qlib, and LightGBM
  remain optional research/data extras.
- Adds a local SQLite file under `artifacts/` using Python's standard library.
- Extends existing JSON contracts compatibly through optional provenance fields and new
  versioned payloads.
- Does not enable or add a path to unattended live trading.
