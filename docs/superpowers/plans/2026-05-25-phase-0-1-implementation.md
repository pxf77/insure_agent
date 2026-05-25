# Phase 0 And Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build the first runnable implementation slice from the technical design: project scaffold, CLI, configuration, run IDs, local data adapter, symbol normalization, daily bar validation, and a Qlib conversion entry point.

**Architecture:** Implement a small Python package under `src/quant_agent` with focused `common` and `data` modules. Keep all generated data under `artifacts/` and expose user workflows through `quant-agent` plus script wrappers used by the Makefile.

**Tech Stack:** Python 3.10+, Typer, Pydantic, PyYAML, pandas, pytest, ruff, mypy.

---

### Task 1: Project Scaffold And Configuration

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `pyproject.toml`
- Create: `Makefile`
- Create: `configs/env/dev.yaml`
- Create: `src/quant_agent/__init__.py`
- Create: `src/quant_agent/common/config.py`
- Create: `src/quant_agent/common/paths.py`
- Create: `src/quant_agent/common/ids.py`
- Create: `tests/unit/test_config.py`

- [x] Write tests for loading `configs/env/dev.yaml`, creating artifact paths, and generating run IDs.
- [x] Run `uv run --python 3.13 pytest tests/unit/test_config.py -q` and confirm it fails because modules are missing.
- [x] Implement the scaffold and common modules.
- [x] Run `uv run --python 3.13 pytest tests/unit/test_config.py -q` and confirm it passes.

### Task 2: Symbol Normalization And Daily Bar Validation

**Files:**
- Create: `src/quant_agent/data/symbol.py`
- Create: `src/quant_agent/data/validators.py`
- Create: `tests/unit/test_symbol.py`
- Create: `tests/unit/test_validators.py`

- [x] Write tests for SH/SZ normalization, bad symbols, required columns, duplicate bars, and invalid prices.
- [x] Run `uv run --python 3.13 pytest tests/unit/test_symbol.py tests/unit/test_validators.py -q` and confirm it fails because modules are missing.
- [x] Implement `normalize_symbol()` and `validate_daily_bar()`.
- [x] Run the same tests and confirm they pass.

### Task 3: Local Data Adapter

**Files:**
- Create: `src/quant_agent/data/adapters/base.py`
- Create: `src/quant_agent/data/adapters/local_csv_adapter.py`
- Create: `tests/unit/test_local_csv_adapter.py`

- [x] Write tests for loading CSV data, filtering by date range, filtering by symbol, and missing files.
- [x] Run `uv run --python 3.13 pytest tests/unit/test_local_csv_adapter.py -q` and confirm it fails because the adapter is missing.
- [x] Implement the abstract adapter and local CSV/Parquet adapter.
- [x] Run the same tests and confirm they pass.

### Task 4: Qlib Converter, Scripts, And CLI

**Files:**
- Create: `src/quant_agent/data/qlib_converter.py`
- Create: `src/quant_agent/cli.py`
- Create: `scripts/init_project.py`
- Create: `scripts/pull_data.py`
- Create: `scripts/convert_to_qlib.py`
- Create: `tests/unit/test_qlib_converter.py`
- Create: `tests/unit/test_cli.py`

- [x] Write tests for sample data generation, conversion output, and CLI `status`, `init`, `data pull`, and `data convert`.
- [x] Run `uv run --python 3.13 pytest tests/unit/test_qlib_converter.py tests/unit/test_cli.py -q` and confirm it fails because implementation is missing.
- [x] Implement converter, script wrappers, and Typer CLI.
- [x] Run the same tests and confirm they pass.

### Task 5: Full Verification And Publish

**Files:**
- Modify only files created by Tasks 1-4 plus this plan.

- [x] Run `uv run --python 3.13 pytest -q`.
- [x] Run `uv run --python 3.13 ruff check src tests scripts`.
- [x] Run `uv run --python 3.13 mypy src`.
- [x] Run `uv run --python 3.13 quant-agent status`.
- [x] Run `uv run --python 3.13 quant-agent init`.
- [x] Run `uv run --python 3.13 quant-agent data pull --sample`.
- [x] Run `uv run --python 3.13 quant-agent data convert`.
- [x] Check `git status -sb` and stage only task-related files.
- [ ] Commit with `feat(data): add phase 0 and 1 scaffold`.
- [ ] Push the current branch to `origin/main`.
