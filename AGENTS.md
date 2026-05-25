# AGENTS.md

## Scope

These instructions apply to the entire repository unless a more specific
`AGENTS.md` exists in a subdirectory.

This repository is for an A-share quantitative research, risk, and execution
agent. Treat the technical design document as the product and architecture
source of truth, but keep this file focused on operational rules for coding
agents.

## Project Structure

The repository is currently documentation-first. Expected implementation areas
from the design are:

- `configs/`: environment, data, research, risk, and execution configuration.
- `src/quant_agent/`: application code.
- `scripts/`: CLI entry scripts and maintenance automation.
- `tests/`: unit, contract, and integration tests.
- `docs/`: durable project documentation and runbooks.
- `artifacts/`: local run outputs, data caches, reports, audit logs, and other
  generated runtime files.

Do not commit generated runtime outputs from `artifacts/` unless explicitly
requested. Do not edit generated files directly; add or update the generator
instead.

## Setup

- Use Python `>=3.10,<3.14`.
- Install development dependencies: `python -m pip install -e .[dev]`.
- With `uv`, run checks without manually activating a virtual environment:
  `uv run --python 3.13 --extra dev <command>`.
- Initialize local artifact directories: `quant-agent init`.
- Generate sample raw data: `quant-agent data pull --sample`.
- Convert sample data to the local Qlib layout: `quant-agent data convert`.

## Checks

Before completing a code change, run the most specific available checks. If the
corresponding commands do not exist yet, say that explicitly in the final
summary.

Expected checks after the project scaffold exists:

- `uv run --python 3.13 --extra dev pytest -q`
- `uv run --python 3.13 --extra dev ruff check src tests scripts`
- `uv run --python 3.13 --extra dev mypy src`
- `make test`
- `make lint`

For documentation-only changes, verify the changed Markdown files are present
and reviewable; do not invent test results.

## Code Style

- Use Python type hints for new application code.
- Use Pydantic schemas for external or cross-module data contracts.
- Keep strategy, risk, data, and execution modules separated.
- Prefer configuration files under `configs/` over hard-coded runtime values.
- Keep changes minimal and localized to the requested task.
- Reuse existing utilities and project patterns before adding abstractions.

## Testing Policy

- Add or update tests for changed behavior.
- For bug fixes, add a regression test when practical.
- Cover data validation, symbol normalization, target position contracts, risk
  rules, order generation, idempotency, and kill-switch behavior.
- Do not skip, weaken, or delete tests to make a change pass.

## Dependencies

- Do not add production dependencies without explicit approval.
- Prefer dependencies already named in the design before introducing new ones.
- Do not introduce real broker, trading gateway, or live-trading dependencies in
  the first implementation phase unless explicitly requested.

## Security And Trading Safety

- Never commit secrets, tokens, private keys, broker credentials, or `.env`
  files.
- Do not log credentials, access tokens, account identifiers, or sensitive
  trading/account data.
- LLMs may assist with explanations, diagnostics, and reports, but must not
  bypass deterministic risk rules.
- `live` trading must remain disabled by default.
- Do not implement unattended live order submission unless explicitly requested
  and protected by configuration, manual approval, audit logging, and a kill
  switch.
- Do not weaken authentication, authorization, validation, risk checks, approval
  checks, or kill-switch behavior to make tests pass.

## Data And Contracts

- Use normalized symbols such as `600519.SH` and `000001.SZ` at system
  boundaries.
- Every research, risk, and execution run must have a `run_id`.
- Persist inputs, outputs, config snapshots, code/data versions, decisions, and
  orders so runs are auditable and reproducible.
- Keep public JSON contract changes backward compatible unless the task
  explicitly requests a breaking change.

## Git Commit Rules

- Follow Conventional Commits.
- Use this format: `<type>(<scope>): <subject>`.
- Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`,
  `build`, `ci`, `perf`, `revert`.
- Keep the subject concise, specific, and in imperative mood.
- Do not use vague messages such as `update`, `fix bug`, `changes`, or `misc`.
- Before committing, check `git status -sb`, stage only task-related files, and
  run the relevant checks listed above.
- See `CONTRIBUTING.md#git-commit-convention` for the full policy.

## Pull Request Expectations

When summarizing a change, include:

- What changed.
- Why it changed.
- Checks or verification run.
- Any known limitations or skipped checks.
