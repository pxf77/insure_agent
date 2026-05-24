# Contributing

## Git Commit Convention

This project uses Conventional Commits for Git commit messages.

Format:

```text
<type>(<scope>): <subject>
```

The `scope` is optional when a change clearly affects the whole repository:

```text
<type>: <subject>
```

## Allowed Types

Use one of these commit types:

| Type | Use when |
| --- | --- |
| `feat` | Adding a user-facing feature or new capability. |
| `fix` | Fixing a bug or incorrect behavior. |
| `docs` | Updating documentation only. |
| `style` | Formatting or style-only changes with no behavior change. |
| `refactor` | Restructuring code without changing behavior. |
| `test` | Adding or updating tests. |
| `chore` | Maintenance work that does not affect runtime behavior. |
| `build` | Changing packaging, dependencies, or build tooling. |
| `ci` | Changing CI, release, or automation workflows. |
| `perf` | Improving performance without changing behavior. |
| `revert` | Reverting a previous commit. |

## Recommended Scopes

Use short lowercase scopes that identify the affected area. Prefer existing
module or directory names once implementation files exist.

Recommended scopes for this repository:

- `docs`: documentation and runbooks.
- `config`: environment, data, research, risk, or execution configuration.
- `data`: market data adapters, validation, symbol handling, or Qlib conversion.
- `research`: Qlib, RD-Agent, portfolio construction, or reports.
- `risk`: risk engine, rules, approvals, and kill-switch behavior.
- `execution`: order generation, mock execution, vn.py adapters, or reconciliation.
- `cli`: command-line interface behavior.
- `tests`: test fixtures, test helpers, and test-only changes.
- `deps`: dependency updates.
- `repo`: repository-level metadata or workflow files.

Examples:

```text
docs(repo): add coding agent instructions
docs(repo): add git commit convention
feat(risk): add single-position limit rule
fix(data): normalize SH-prefixed symbols
test(risk): cover kill-switch rejection
chore(repo): ignore generated artifacts
```

## Subject Rules

- Use imperative mood: `add`, `fix`, `update`, `remove`.
- Start with a lowercase verb unless the first word is a proper noun.
- Keep the subject concise and specific.
- Do not end the subject with a period.
- Avoid vague subjects such as `update`, `fix bug`, `changes`, or `misc`.

Good:

```text
docs(repo): add git commit convention
fix(data): reject duplicate daily bars
feat(cli): add status command
```

Bad:

```text
update
fix bug
changes
docs: stuff
```

## Body And Footer

Use a commit body when the reason or tradeoff is not obvious from the subject.
Wrap prose at a readable width.

Use footers for issue references and breaking changes:

```text
feat(api): add approved positions endpoint

Expose approved risk decisions for downstream execution services.

Refs: #123
```

For breaking changes, use `BREAKING CHANGE:` in the footer:

```text
feat(contract): require schema version in target positions

BREAKING CHANGE: target_positions.json must include schema_version.
```

## Reverts

Use `revert` commits when undoing a previous commit:

```text
revert: docs(repo): add git commit convention
```

In the body, identify the commit being reverted and explain why.

## Agent Commit Rules

AI coding agents working in this repository must follow this convention when
creating commits.

Before committing, agents should:

- Check `git status -sb`.
- Stage only files that belong to the requested task.
- Run the relevant checks listed in `AGENTS.md`.
- Mention any skipped checks and why they were skipped.

Agents must not commit:

- Secrets, tokens, private keys, broker credentials, or `.env` files.
- Generated runtime outputs such as `artifacts/`.
- Unrelated local files such as `.DS_Store`.

## Automated Enforcement

This repository does not currently include commitlint or Git hook tooling.
If Node-based tooling is introduced later, prefer Conventional Commit
validation with `@commitlint/cli`, `@commitlint/config-conventional`, and Husky
or an equivalent CI-side check.
