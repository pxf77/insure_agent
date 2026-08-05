# insure_agent

A-share quantitative research, risk-control, and execution agent scaffold.

The project is being implemented from
[`technical_design_codex_enriched.md`](technical_design_codex_enriched.md). The
current codebase provides a local MVP: deterministic sample data generation,
Qlib-style conversion, research target generation, risk validation, mock paper
execution, Markdown reporting, and a `latest.json` artifact index.

The trustworthy daily workflow adds immutable canonical data snapshots,
reproducible research, deterministic pre-trade risk checks, checksum-bound
manual approval, and auditable paper execution:

```bash
quant-agent run daily --trade-date 2026-07-29 --provider sample
quant-agent approval grant --run-id <run_id> --approver <name>
quant-agent paper run --run-id <run_id>
quant-agent run show --run-id <run_id>
```

See [the migration guide](docs/migration_trustworthy_daily.md) and
[the runbook](docs/runbook.md) for configuration, recovery, and audit details.

The phased delivery plan is maintained in
[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md). Repository
integration decisions are recorded under [`docs/adr`](docs/adr).

## Architecture

The target system is intentionally split into independent layers:

```text
Market data
  -> Local raw data / provider adapters
  -> Qlib data conversion
  -> Research outputs
  -> Risk review
  -> Simulated execution
  -> Reports and audit logs
```

Implemented modules:

- `src/quant_agent/common`: configuration loading, path handling, run ID
  utilities, including the latest-run artifact index and environment doctor.
- `src/quant_agent/data`: A-share symbol normalization, daily bar validation,
  local CSV/Parquet adapter, and local Qlib layout conversion.
- `src/quant_agent/research`: deterministic local research baseline that writes
  `metrics.json`, `target_positions.json`, and a research report.
- `src/quant_agent/risk`: deterministic position-limit and kill-switch rules
  that write `approved_positions.json`.
- `src/quant_agent/execution`: mock paper execution bridge that converts
  approved positions into local orders and trades.
- `src/quant_agent/schemas`: backward-compatible v1 contracts and versioned v2
  domain contracts for research, risk, events, and order intents.
- `src/quant_agent/evals`: deterministic evaluation runners.
- `src/quant_agent/cli.py`: `quant-agent` commands for the local MVP workflow.
- `configs/env/dev.yaml`: default local development configuration.
- `configs/research`, `configs/risk`, and `configs/execution`: local MVP
  strategy, risk, and mock execution settings.
- `evals/contracts`: reviewable positive and adversarial contract cases.
- `scripts/`: thin script wrappers for Makefile and direct command usage.
- `tests/unit` and `tests/integration`: behavior coverage for contracts,
  pipeline steps, and the end-to-end local MVP flow.

Runtime outputs are written under `artifacts/` and are ignored by Git.

## Requirements

- Python `>=3.10,<3.14`
- Recommended local runner: `uv`

Install development dependencies:

```bash
python -m pip install -e .[dev]
```

Or run commands through `uv` without manually managing a virtual environment:

```bash
uv run --python 3.13 --extra dev quant-agent status
```

## Environment Doctor

Run the doctor before the first pipeline execution:

```bash
uv run --python 3.13 --extra dev quant-agent doctor --profile mvp
```

The command validates Python/platform support, configuration, timezone,
artifact-directory writability, live-trading safety defaults, command-line
tools, and optional Qlib/RD-Agent/vn.py dependencies. Missing optional modules
are warnings in the `mvp` profile.

Use stricter profiles when preparing research or paper/gateway-development
environments:

```bash
quant-agent doctor --profile research
quant-agent doctor --profile execution
quant-agent doctor --profile mvp --json
```

A failed safety or required-dependency check exits non-zero. The doctor does not
certify a machine for real-money trading. Any configuration with live trading
enabled fails until the M9 live-readiness controls are implemented.

## Versioned Contracts And Evaluation

The existing local pipeline continues to read and write its v1 payloads. New
cross-service development should target the contracts under
`src/quant_agent/schemas/v2`.

Export deterministic JSON Schemas and their SHA-256 manifest:

```bash
quant-agent contracts export --output artifacts/contracts
```

Run the public contract suites:

```bash
quant-agent eval contracts --suite evals/contracts/v0.1.yaml
quant-agent eval contracts --suite evals/contracts/v0.1-hardening.yaml
```

The suites cover symbol normalization, aware timestamps, research split
isolation, portfolio uniqueness and weight constraints, deterministic risk
decisions, idempotency keys, immutable buy-lot size, and order price semantics.
A failed case exits non-zero and blocks CI.

## Quick Start

Run the full local paper-mode MVP:

```bash
uv run --python 3.13 --extra dev quant-agent run pipeline --mode paper
```

List supported market-data providers:

```bash
uv run --python 3.13 --extra dev quant-agent data providers
```

Official Eastmoney Choice and Tonghuashun iFinD daily-bar adapters are available for
immutable point-in-time snapshots. They load credentials only from the official Choice SDK
activation or the `IFIND_ACCESS_TOKEN` process environment. See
[`docs/vendor_integrations.md`](docs/vendor_integrations.md) for setup and safety details.
Stable Ubuntu Choice hosts should also follow
[`docs/choice_ubuntu_deployment.md`](docs/choice_ubuntu_deployment.md).

Read-only broker snapshots can be imported in `live_shadow` mode:

```bash
uv run --python 3.13 --extra dev quant-agent execution shadow \
  --snapshot configs/execution/shadow_snapshot.example.json \
  --config configs/env/live_shadow.yaml
```

This mode cannot submit or cancel orders and does not enable live trading.

The command runs:

```text
init -> data pull -> data convert -> research qlib -> risk validate
     -> paper run -> report generate -> latest
```

To run each step manually, initialize local output directories:

```bash
uv run --python 3.13 --extra dev quant-agent init
```

Generate deterministic sample A-share daily bars:

```bash
uv run --python 3.13 --extra dev quant-agent data pull --sample
```

Convert raw sample data into the local Qlib-style layout:

```bash
uv run --python 3.13 --extra dev quant-agent data convert
```

Run research, risk validation, mock paper execution, and report generation:

```bash
uv run --python 3.13 --extra dev quant-agent research qlib
uv run --python 3.13 --extra dev quant-agent risk validate
uv run --python 3.13 --extra dev quant-agent paper run
uv run --python 3.13 --extra dev quant-agent report generate
uv run --python 3.13 --extra dev quant-agent latest
```

Expected generated files:

```text
artifacts/data/raw/daily_bar.csv
artifacts/data/qlib/cn_data/features/*.csv
artifacts/data/qlib/cn_data/instruments/all_a.txt
artifacts/data/qlib/cn_data/metadata.json
artifacts/contracts/*.schema.json
artifacts/contracts/index.json
artifacts/research_runs/<run_id>/target_positions.json
artifacts/research_runs/<run_id>/metrics.json
artifacts/risk_runs/<run_id>/approved_positions.json
artifacts/execution_runs/<run_id>/orders.json
artifacts/execution_runs/<run_id>/trades.json
artifacts/reports/<run_id>_report.md
artifacts/latest.json
```

## CLI Commands

```bash
quant-agent status
quant-agent doctor --profile mvp
quant-agent contracts export
quant-agent eval contracts --suite evals/contracts/v0.1.yaml
quant-agent init
quant-agent data pull --sample
quant-agent data convert
quant-agent research qlib
quant-agent risk validate
quant-agent paper run
quant-agent report generate
quant-agent report latest
quant-agent latest
quant-agent run pipeline --mode paper
```

Equivalent Makefile entry points:

```bash
make doctor
make contracts-export
make eval-contracts
make init
make data-pull
make data-convert
make research
make risk
make paper
make report
```

If using `uv`, make sure the generated virtual environment is on `PATH` before
running Makefile commands directly:

```bash
PATH="$PWD/.venv/bin:$PATH" make test
PATH="$PWD/.venv/bin:$PATH" make lint
```

## Development Checks

Run the full current verification set:

```bash
uv run --python 3.13 --extra dev pytest -q
uv run --python 3.13 --extra dev quant-agent eval contracts --suite evals/contracts/v0.1.yaml
uv run --python 3.13 --extra dev quant-agent eval contracts --suite evals/contracts/v0.1-hardening.yaml
uv run --python 3.13 --extra dev ruff check src tests scripts
uv run --python 3.13 --extra dev mypy src
```

## Safety Boundaries

This repository must not enable real trading in the current phase.

- Real broker integration is not implemented.
- Every live-enabled configuration fails the environment doctor until M9.
- Creating `artifacts/KILL_SWITCH` causes `quant-agent risk validate` to reject
  targets and exit with a non-zero status.
- Do not commit secrets, API keys, broker credentials, `.env` files, or runtime
  outputs.
- LLM-assisted logic must not bypass deterministic risk rules.

## Documentation

- [`AGENTS.md`](AGENTS.md): coding-agent operating rules.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): Git commit convention and contribution
  rules.
- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md): phased GitHub and
  Codex delivery plan.
- [`docs/runbook.md`](docs/runbook.md): local MVP runbook.
- [`docs/live_trading_checklist.md`](docs/live_trading_checklist.md): future
  live-trading guardrails.
- [`technical_design_codex_enriched.md`](technical_design_codex_enriched.md):
  detailed architecture and phased implementation plan.
