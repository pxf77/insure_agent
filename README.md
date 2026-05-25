# insure_agent

A-share quantitative research, risk-control, and execution agent scaffold.

The project is being implemented from
[`technical_design_codex_enriched.md`](technical_design_codex_enriched.md). The
current codebase covers Phase 0 and Phase 1: project scaffold, configuration,
CLI, local sample data generation, data validation, symbol normalization, and a
lightweight local Qlib-style conversion flow.

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

Current implementation:

- `src/quant_agent/common`: configuration loading, path handling, and run ID
  utilities.
- `src/quant_agent/data`: A-share symbol normalization, daily bar validation,
  local CSV/Parquet adapter, and local Qlib layout conversion.
- `src/quant_agent/cli.py`: `quant-agent` commands for status, initialization,
  sample data generation, and data conversion.
- `configs/env/dev.yaml`: default local development configuration.
- `scripts/`: thin script wrappers for Makefile and direct command usage.
- `tests/unit`: unit tests for the current scaffold and data layer.

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

## Quick Start

Initialize local output directories:

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

Expected generated files:

```text
artifacts/data/raw/daily_bar.csv
artifacts/data/qlib/cn_data/features/*.csv
artifacts/data/qlib/cn_data/instruments/all_a.txt
artifacts/data/qlib/cn_data/metadata.json
```

## CLI Commands

```bash
quant-agent status
quant-agent init
quant-agent data pull --sample
quant-agent data convert
```

Equivalent Makefile entry points:

```bash
make init
make data-pull
make data-convert
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
uv run --python 3.13 --extra dev ruff check src tests scripts
uv run --python 3.13 --extra dev mypy src
```

## Safety Boundaries

This repository must not enable real trading by default.

- Real broker integration is not implemented in the current phase.
- `live` trading must remain disabled unless explicitly configured and reviewed.
- Do not commit secrets, API keys, broker credentials, `.env` files, or runtime
  outputs.
- LLM-assisted logic must not bypass deterministic risk rules.

## Documentation

- [`AGENTS.md`](AGENTS.md): coding-agent operating rules.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): Git commit convention and contribution
  rules.
- [`technical_design_codex_enriched.md`](technical_design_codex_enriched.md):
  detailed architecture and phased implementation plan.
