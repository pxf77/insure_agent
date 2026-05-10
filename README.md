# Hermes Trading Assistant Backend MVP

Backend-only MVP for safe, manual trading decision support.

## Safety Boundaries

This service does not automate trading, place orders, control Eastmoney, capture app traffic, store brokerage credentials, bypass verification, or provide automatic order instructions.

Signals are decision-support records only. A human must review every signal before taking any action outside this system.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Copy `.env.example` values into your shell or environment manager when overriding defaults.

## Run

```powershell
.\.venv\Scripts\uvicorn backend.app.main:app --reload
```

Default local persistence uses `sqlite:///./hermes.db`.

## API

- `GET /health`
- `POST /api/watchlist`
- `GET /api/watchlist`
- `PATCH /api/watchlist/{id}`
- `DELETE /api/watchlist/{id}`
- `POST /api/signals/scan`
- `GET /api/signals`
- `POST /api/signals/{signal_id}/manual-review`
- `GET /api/reviews/daily`

## Example Flow

```powershell
curl -X POST http://127.0.0.1:8000/api/watchlist -H "Content-Type: application/json" -d "{\"symbol\":\"SH600000\"}"
curl -X POST http://127.0.0.1:8000/api/signals/scan -H "Content-Type: application/json" -d "{\"account\":{}}"
curl http://127.0.0.1:8000/api/signals
curl -X POST http://127.0.0.1:8000/api/signals/1/manual-review -H "Content-Type: application/json" -d "{\"decision\":\"accepted\"}"
curl http://127.0.0.1:8000/api/reviews/daily
```

## Verify

```powershell
.\.venv\Scripts\pytest
.\.venv\Scripts\ruff check .
.\.venv\Scripts\mypy backend/app
```
