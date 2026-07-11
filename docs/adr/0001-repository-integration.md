# ADR-0001: Keep the A-share system at the repository root

- **Status:** Accepted
- **Date:** 2026-07-11
- **Decision owners:** Repository maintainer and implementation agents

## Context

The detailed implementation plan required a read-only repository assessment before choosing between a root monorepo and an isolated `projects/a_share_trading_agent/` subtree.

The assessment found that this repository is already dedicated to the A-share quantitative agent. The root contains:

- a Python package under `src/quant_agent`;
- environment, research, risk, and execution configuration under `configs/`;
- deterministic local data, research, risk, and paper-execution modules;
- unit and integration tests;
- a root `AGENTS.md`, `Makefile`, `pyproject.toml`, and project documentation.

Creating a second nested project would duplicate package metadata, configuration, tests, artifacts, and developer commands without protecting any unrelated production application.

## Decision

Continue implementation at the repository root.

The root layout remains the stable integration boundary:

```text
configs/
src/quant_agent/
scripts/
tests/
docs/
artifacts/       # generated and ignored
```

Future web, API, evaluation, and infrastructure components may introduce `apps/`, `services/`, `evals/`, or `docker/` directories when their milestones begin. They must reuse the root configuration, contracts, safety rules, and development commands rather than creating a second standalone project.

## Protected boundaries

- Do not commit runtime files under `artifacts/`.
- Do not commit credentials, `.env` files, API keys, broker secrets, or account identifiers.
- Do not enable live trading by default.
- Do not let LLM-assisted code bypass deterministic risk checks.
- Keep data, research, risk, and execution modules separated.
- Public JSON contract changes must remain backward compatible unless a reviewed migration explicitly allows a breaking change.

## Consequences

### Positive

- Existing local MVP behavior remains intact.
- Codex tasks can implement milestones incrementally without a repository migration.
- One package, one test suite, and one configuration hierarchy remain the source of truth.
- Documentation and operational commands are easier for a new developer to discover.

### Trade-offs

- As the project grows, ownership boundaries must be enforced through subdirectory `AGENTS.md` files and CODEOWNERS rather than a nested project boundary.
- Frontend and service workspaces will require explicit naming and dependency rules when introduced.
- The repository name remains historical and does not exactly describe the A-share system.

## Follow-up decisions

- Define contract and database ownership before M1 persistence work.
- Define frontend workspace tooling before M7.
- Define paper/live physical separation before M9.
