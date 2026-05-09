# Hermes Trading Assistant Backend MVP

Backend-only MVP for safe, manual trading decision support.

## Safety Boundaries

This service does not automate trading, place orders, control Eastmoney, capture app traffic, store brokerage credentials, bypass verification, or provide automatic order instructions.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

## Run

```powershell
.\.venv\Scripts\uvicorn backend.app.main:app --reload
```

## Verify

```powershell
.\.venv\Scripts\pytest
.\.venv\Scripts\ruff check .
.\.venv\Scripts\mypy backend/app
```
