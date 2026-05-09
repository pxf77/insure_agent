# Backend MVP Design

Date: 2026-05-09

## Goal

Build a backend-only Hermes trading-assistant MVP that runs the full safe decision-support loop:

Add watchlist symbol -> run mock market and mock LLM scan -> apply hard risk rules -> persist signal and risk result -> emit console notification -> record manual review -> generate daily review.

The MVP must not automate trading, control Eastmoney, capture app traffic, store brokerage credentials, bypass verification, or place orders.

## Scope

In scope:

- FastAPI backend with health, watchlist, signal scan, signal listing, manual review, and daily review endpoints.
- SQLModel persistence with a local SQLite default via `DATABASE_URL`.
- Pydantic/SQLModel schemas for watchlist entries, market snapshots, signals, risk checks, and manual reviews.
- Mock market data provider for deterministic test and local behavior.
- Mock LLM analyzer that returns structured `SignalCandidate` objects.
- Risk engine with hard-coded safety rules independent of the LLM.
- Signal engine that orchestrates watchlist symbols, market data, mock LLM, risk checks, persistence, and notifications.
- Console notification provider that clearly states signals are not automatic order instructions.
- Review engine that summarizes counts for signals, risk pass/block, and manual user decisions.
- pytest, ruff, and mypy setup.
- README and environment example.

Out of scope for this first MVP:

- React/Vite dashboard.
- Real Anthropic API integration.
- Real market data integration.
- PostgreSQL/Redis runtime dependency for local tests.
- Scheduler runtime loops.
- Webhook, Telegram, email, Bark, or ServerChan notifications.
- Any Eastmoney APP automation, reverse engineering, packet capture, credential storage, or auto-trading logic.

## Architecture

The backend is a small layered FastAPI application. API routers validate requests and delegate to focused services. SQLModel models define persistence. Service classes hold business behavior and are easy to test directly.

Default local development uses SQLite to keep the MVP runnable without external infrastructure. The database URL remains configurable so PostgreSQL can replace SQLite later without changing API or service boundaries.

The signal generation path is deliberately mock-first. `MockMarketDataProvider` and `MockLLMAnalyzer` provide stable inputs, while `RiskEngine` enforces hard safety rules before anything is presented as a candidate. `SignalEngine` is the only orchestration layer.

## Components

### API

- `GET /health`: returns service status.
- `POST /api/watchlist`: creates a watchlist entry.
- `GET /api/watchlist`: lists watchlist entries, defaulting to all entries.
- `PATCH /api/watchlist/{id}`: updates status, note, sector, or name.
- `DELETE /api/watchlist/{id}`: deletes a watchlist entry.
- `POST /api/signals/scan`: scans active watchlist entries using mock providers.
- `GET /api/signals`: lists generated signals, optionally filtered by status.
- `POST /api/signals/{signal_id}/manual-review`: records `accepted`, `rejected`, or `ignored` manual user decisions.
- `GET /api/reviews/daily`: returns daily review statistics and a text summary.

### Data Models

- `Watchlist`: user-tracked symbols with `active` or `blocked` status.
- `Signal`: structured trading candidate generated from mock analysis and accepted by persistence even when risk-blocked, with a status showing review/risk state.
- `RiskCheck`: risk engine output tied to a signal.
- `ManualReview`: user decision record tied to a signal.

### Schemas

- `SignalCandidate`: LLM output contract with action, score, confidence, risk level, price range, stop loss, take profit, reasons, risks, and manual checklist.
- `AccountState`: current account-level risk context.
- `MarketState`: market-level risk context for the symbol.
- `RiskConfig`: configurable thresholds.
- `RiskCheckResult`: risk result returned by the engine.

### Services

- `MockMarketDataProvider`: returns deterministic snapshot and market state data.
- `MockLLMAnalyzer`: returns deterministic candidate recommendations for tests and local scans.
- `RiskEngine`: pure business service that blocks unsafe candidates.
- `SignalEngine`: orchestrates active watchlist scanning, persistence, risk checks, and notifications.
- `ConsoleNotificationProvider`: formats signal alerts with manual-confirmation disclaimers.
- `ReviewEngine`: computes daily counts and summary text.

## Risk Rules

The first MVP must block signals when any of these conditions are true:

- `score < min_signal_score`, default `70`.
- Missing stop loss.
- `max_position_pct > max_single_position_pct`, default `5`.
- `account.total_position_pct >= max_total_position_pct`, default `50`.
- `account.daily_loss_pct <= -max_daily_loss_pct`, default `2`.
- Reward/risk ratio is below `min_reward_risk_ratio`, default `1.5`.
- Market state identifies ST/risk-warning stock and ST blocking is enabled.
- Turnover is below `min_turnover_cny`, default `100_000_000`.
- Suggested price range is missing.
- Take profit is missing.
- Stop loss is invalid relative to entry price.
- Limit-up buy blocking is enabled and market state says the symbol is limit-up.

Each blocked result must include a clear `blocked_reason`.

## Data Flow

1. User creates active watchlist entries.
2. User calls `POST /api/signals/scan`.
3. `SignalEngine` reads active watchlist rows.
4. `MockMarketDataProvider` returns deterministic market state for each symbol.
5. `MockLLMAnalyzer` returns a `SignalCandidate`.
6. `RiskEngine` evaluates the candidate against account state, market state, and config.
7. The app saves a `Signal` and a `RiskCheck`.
8. If risk passes, notification text is emitted through `ConsoleNotificationProvider`.
9. User records manual review through the API.
10. `ReviewEngine` summarizes daily outcomes.

## Error Handling

- API endpoints return `404` for missing watchlist or signal IDs.
- Manual review rejects actions outside `accepted`, `rejected`, and `ignored` through schema validation.
- Risk failures are normal business outcomes, not exceptions.
- Signal scan returns per-symbol results rather than aborting the whole scan when one symbol fails.
- Database sessions are request-scoped.

## Testing

Tests are required for:

- Health endpoint.
- Watchlist CRUD.
- Signal schema validation.
- Every hard risk rule.
- Signal scan happy path with mock providers.
- Signal scan risk-blocked path.
- Manual review status transitions.
- Daily review statistics.
- Console notification content includes manual confirmation and non-auto-trading disclaimers.

## Acceptance Criteria

- `pytest` passes.
- `ruff check .` passes.
- `mypy backend/app` passes or has narrowly documented config for framework limitations.
- `/health` returns `{"status":"ok","service":"hermes-trading-assistant"}`.
- Active watchlist symbols can be scanned into persisted signals.
- Risk-blocked signals persist blocked reasons.
- Manual review records `accepted`, `rejected`, and `ignored` decisions.
- No code path performs automatic trading or Eastmoney APP automation.
