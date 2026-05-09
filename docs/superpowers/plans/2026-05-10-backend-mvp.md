# Backend MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend-only Hermes trading-assistant MVP described in `docs/superpowers/specs/2026-05-09-backend-mvp-design.md`.

**Architecture:** Create a small layered FastAPI application under `backend/app`. API routers validate requests and call services; SQLModel models own persistence; service classes own mock market data, mock LLM analysis, risk checks, signal orchestration, notifications, and daily reviews.

**Tech Stack:** Python 3.11+, FastAPI, SQLModel, SQLite by default through `DATABASE_URL`, pytest, httpx TestClient, ruff, mypy.

---

## File Structure

- `pyproject.toml`: project metadata, runtime dependencies, dev tooling, pytest path config, ruff config, mypy config.
- `.env.example`: default local environment values.
- `README.md`: setup, run, test, API summary, and safety boundaries.
- `backend/__init__.py`: package marker.
- `backend/app/__init__.py`: application package marker.
- `backend/app/config.py`: environment-backed settings.
- `backend/app/database.py`: SQLModel engine/session helpers and table initialization.
- `backend/app/main.py`: app factory, startup table creation, router registration.
- `backend/app/models.py`: SQLModel tables for watchlist entries, signals, risk checks, and manual reviews.
- `backend/app/schemas.py`: request/response schemas and pure data contracts used by services.
- `backend/app/api/__init__.py`: API package marker.
- `backend/app/api/deps.py`: request-scoped database dependency.
- `backend/app/api/routes/__init__.py`: router package marker.
- `backend/app/api/routes/health.py`: health endpoint.
- `backend/app/api/routes/watchlist.py`: watchlist CRUD endpoints.
- `backend/app/api/routes/signals.py`: signal scan, signal listing, and manual review endpoints.
- `backend/app/api/routes/reviews.py`: daily review endpoint.
- `backend/app/services/__init__.py`: services package marker.
- `backend/app/services/market_data.py`: deterministic mock market provider.
- `backend/app/services/llm_analyzer.py`: deterministic mock analyzer returning `SignalCandidate`.
- `backend/app/services/risk.py`: pure hard-rule risk engine.
- `backend/app/services/notifications.py`: console notification provider with safety disclaimers.
- `backend/app/services/signal_engine.py`: scan orchestration and persistence.
- `backend/app/services/review_engine.py`: daily statistics and text summary.
- `tests/conftest.py`: isolated SQLite test database and FastAPI TestClient fixtures.
- `tests/test_health.py`: health endpoint coverage.
- `tests/test_schemas.py`: schema validation coverage.
- `tests/test_watchlist.py`: watchlist CRUD coverage.
- `tests/test_risk_engine.py`: every hard risk rule.
- `tests/test_notifications.py`: notification disclaimer coverage.
- `tests/test_signal_scan.py`: happy-path and risk-blocked scan coverage.
- `tests/test_manual_review.py`: manual review status transition coverage.
- `tests/test_daily_review.py`: daily review statistics coverage.

---

### Task 1: Project Tooling And Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `README.md`
- Create: `backend/__init__.py`
- Create: `backend/app/__init__.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/routes/__init__.py`
- Create: `backend/app/services/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create project metadata and tooling config**

Write `pyproject.toml`:

```toml
[project]
name = "hermes-trading-assistant"
version = "0.1.0"
description = "Backend-only trading-assistant MVP with mock signal scanning and hard risk gates."
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115,<1.0",
    "sqlmodel>=0.0.22,<0.1",
    "uvicorn[standard]>=0.30,<1.0",
]

[project.optional-dependencies]
dev = [
    "httpx>=0.27,<1.0",
    "mypy>=1.13,<2.0",
    "pytest>=8.3,<9.0",
    "ruff>=0.8,<1.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.11"
disallow_untyped_defs = true
check_untyped_defs = true
no_implicit_optional = true
warn_return_any = true
warn_unused_configs = true
plugins = []
```

- [ ] **Step 2: Create local environment example**

Write `.env.example`:

```dotenv
DATABASE_URL=sqlite:///./hermes.db
```

- [ ] **Step 3: Create initial README**

Write `README.md`:

````markdown
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
````

- [ ] **Step 4: Create package markers**

Create each marker file as empty UTF-8 text:

```text
backend/__init__.py
backend/app/__init__.py
backend/app/api/__init__.py
backend/app/api/routes/__init__.py
backend/app/services/__init__.py
tests/__init__.py
```

- [ ] **Step 5: Install dependencies**

Run from the repository root:

```powershell
python -m pip install -e ".[dev]"
```

Expected: package installs without dependency resolution errors.

- [ ] **Step 6: Run baseline quality commands**

Run:

```powershell
pytest
ruff check .
mypy backend/app
```

Expected: `pytest` reports no tests collected, `ruff` passes, and `mypy` passes or reports that `backend/app` has no source files.

- [ ] **Step 7: Commit**

Run:

```powershell
git add pyproject.toml .env.example README.md backend tests
git status --short
git commit -m "chore: scaffold backend project"
```

Expected: only the files listed in this task are committed.

---

### Task 2: Health Endpoint And App Factory

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/app/database.py`
- Create: `backend/app/main.py`
- Create: `backend/app/api/deps.py`
- Create: `backend/app/api/routes/health.py`
- Create: `tests/test_health.py`

- [ ] **Step 1: Write the failing health endpoint test**

Write `tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_health_endpoint_returns_service_status() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "hermes-trading-assistant",
    }
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
pytest tests/test_health.py -v
```

Expected: FAIL because `backend.app.main` does not exist.

- [ ] **Step 3: Add settings and database helpers**

Write `backend/app/config.py`:

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./hermes.db")
    service_name: str = "hermes-trading-assistant"


def get_settings() -> Settings:
    return Settings()
```

Write `backend/app/database.py`:

```python
from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from backend.app.config import get_settings


def _connect_args(database_url: str) -> dict[str, bool]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args=_connect_args(settings.database_url),
)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
```

Write `backend/app/api/deps.py`:

```python
from collections.abc import Generator

from sqlmodel import Session

from backend.app.database import get_session


def get_db_session() -> Generator[Session, None, None]:
    yield from get_session()
```

- [ ] **Step 4: Add app factory and health router**

Write `backend/app/api/routes/health.py`:

```python
from fastapi import APIRouter

from backend.app.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "service": settings.service_name}
```

Write `backend/app/main.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.routes import health
from backend.app.database import create_db_and_tables


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Hermes Trading Assistant", lifespan=lifespan)
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 5: Run the health test and quality checks**

Run:

```powershell
pytest tests/test_health.py -v
ruff check backend tests
mypy backend/app
```

Expected: all commands pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add backend/app/config.py backend/app/database.py backend/app/main.py backend/app/api/deps.py backend/app/api/routes/health.py tests/test_health.py
git status --short
git commit -m "feat: add health endpoint"
```

Expected: only the files listed in this task are committed.

---

### Task 3: Schemas And Persistence Models

**Files:**
- Create: `backend/app/models.py`
- Create: `backend/app/schemas.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write failing schema validation tests**

Write `tests/test_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from backend.app.schemas import ManualReviewCreate, SignalCandidate, WatchlistCreate


def test_watchlist_create_uppercases_symbol() -> None:
    payload = WatchlistCreate(symbol="  sh600000  ", name="PF Bank")

    assert payload.symbol == "SH600000"


def test_signal_candidate_rejects_bad_score() -> None:
    with pytest.raises(ValidationError):
        SignalCandidate(
            symbol="SH600000",
            action="buy",
            score=101,
            confidence=0.8,
            risk_level="medium",
            price_range=(10.0, 10.5),
            stop_loss=9.5,
            take_profit=12.0,
            max_position_pct=3.0,
            reasons=["trend"],
            risks=["volatility"],
            manual_checklist=["confirm manually"],
        )


def test_manual_review_rejects_unknown_decision() -> None:
    with pytest.raises(ValidationError):
        ManualReviewCreate(decision="approve")
```

- [ ] **Step 2: Run the schema tests and verify they fail**

Run:

```powershell
pytest tests/test_schemas.py -v
```

Expected: FAIL because `backend.app.schemas` does not exist.

- [ ] **Step 3: Add SQLModel tables**

Write `backend/app/models.py`:

```python
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class Watchlist(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    name: str | None = None
    sector: str | None = None
    note: str | None = None
    status: str = Field(default="active", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Signal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    action: str
    score: int
    confidence: float
    risk_level: str
    price_low: float | None = None
    price_high: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    max_position_pct: float
    status: str = Field(default="pending_review", index=True)
    reasons_text: str
    risks_text: str
    manual_checklist_text: str
    generated_at: datetime = Field(default_factory=utc_now, index=True)


class RiskCheck(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    signal_id: int = Field(foreign_key="signal.id", index=True)
    passed: bool = Field(index=True)
    blocked_reason: str | None = None
    checked_at: datetime = Field(default_factory=utc_now, index=True)


class ManualReview(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    signal_id: int = Field(foreign_key="signal.id", index=True)
    decision: str = Field(index=True)
    note: str | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)
```

- [ ] **Step 4: Add request, response, and service schemas**

Write `backend/app/schemas.py`:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

WatchlistStatus = Literal["active", "blocked"]
SignalStatus = Literal["risk_passed", "risk_blocked", "accepted", "rejected", "ignored"]
ManualDecision = Literal["accepted", "rejected", "ignored"]


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not symbol:
        msg = "symbol must not be empty"
        raise ValueError(msg)
    return symbol


class WatchlistCreate(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None
    note: str | None = None
    status: WatchlistStatus = "active"

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return normalize_symbol(value)


class WatchlistUpdate(BaseModel):
    name: str | None = None
    sector: str | None = None
    note: str | None = None
    status: WatchlistStatus | None = None


class WatchlistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str | None
    sector: str | None
    note: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class SignalCandidate(BaseModel):
    symbol: str
    action: Literal["buy", "sell", "hold"]
    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    risk_level: Literal["low", "medium", "high"]
    price_range: tuple[float, float] | None
    stop_loss: float | None
    take_profit: float | None
    max_position_pct: float = Field(gt=0)
    reasons: list[str]
    risks: list[str]
    manual_checklist: list[str]

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return normalize_symbol(value)


class AccountState(BaseModel):
    total_position_pct: float = 0.0
    daily_loss_pct: float = 0.0


class MarketState(BaseModel):
    symbol: str
    last_price: float
    turnover_cny: float
    is_st: bool = False
    is_limit_up: bool = False


class RiskConfig(BaseModel):
    min_signal_score: int = 70
    max_single_position_pct: float = 5.0
    max_total_position_pct: float = 50.0
    max_daily_loss_pct: float = 2.0
    min_reward_risk_ratio: float = 1.5
    block_st: bool = True
    min_turnover_cny: float = 100_000_000
    block_limit_up_buy: bool = True


class RiskCheckResult(BaseModel):
    passed: bool
    blocked_reason: str | None = None


class SignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    action: str
    score: int
    confidence: float
    risk_level: str
    price_low: float | None
    price_high: float | None
    stop_loss: float | None
    take_profit: float | None
    max_position_pct: float
    status: str
    reasons_text: str
    risks_text: str
    manual_checklist_text: str
    generated_at: datetime


class ScanRequest(BaseModel):
    account: AccountState = Field(default_factory=AccountState)


class SignalScanResult(BaseModel):
    symbol: str
    signal_id: int | None = None
    risk_passed: bool = False
    blocked_reason: str | None = None
    error: str | None = None


class ScanResponse(BaseModel):
    results: list[SignalScanResult]


class ManualReviewCreate(BaseModel):
    decision: ManualDecision
    note: str | None = None


class ManualReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_id: int
    decision: str
    note: str | None
    created_at: datetime


class DailyReviewResponse(BaseModel):
    date: str
    total_signals: int
    risk_passed: int
    risk_blocked: int
    accepted: int
    rejected: int
    ignored: int
    summary: str
```

- [ ] **Step 5: Run schema tests and quality checks**

Run:

```powershell
pytest tests/test_schemas.py -v
ruff check backend tests
mypy backend/app
```

Expected: all commands pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add backend/app/models.py backend/app/schemas.py tests/test_schemas.py
git status --short
git commit -m "feat: add backend schemas and models"
```

Expected: only the files listed in this task are committed.

---

### Task 4: Watchlist CRUD API

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/app/api/routes/watchlist.py`
- Create: `tests/conftest.py`
- Create: `tests/test_watchlist.py`

- [ ] **Step 1: Write isolated database fixtures**

Write `tests/conftest.py`:

```python
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from backend.app.api.deps import get_db_session
from backend.app.main import create_app


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Write failing watchlist CRUD tests**

Write `tests/test_watchlist.py`:

```python
from fastapi.testclient import TestClient


def test_watchlist_crud(client: TestClient) -> None:
    create_response = client.post(
        "/api/watchlist",
        json={"symbol": "sh600000", "name": "PF Bank", "sector": "bank"},
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["id"] > 0
    assert created["symbol"] == "SH600000"
    assert created["status"] == "active"

    list_response = client.get("/api/watchlist")
    assert list_response.status_code == 200
    assert [item["symbol"] for item in list_response.json()] == ["SH600000"]

    patch_response = client.patch(
        f"/api/watchlist/{created['id']}",
        json={"status": "blocked", "note": "manual pause"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "blocked"
    assert patch_response.json()["note"] == "manual pause"

    delete_response = client.delete(f"/api/watchlist/{created['id']}")
    assert delete_response.status_code == 204
    assert client.get("/api/watchlist").json() == []


def test_watchlist_missing_id_returns_404(client: TestClient) -> None:
    response = client.patch("/api/watchlist/999", json={"status": "blocked"})

    assert response.status_code == 404
    assert response.json()["detail"] == "watchlist entry not found"
```

- [ ] **Step 3: Run the watchlist tests and verify they fail**

Run:

```powershell
pytest tests/test_watchlist.py -v
```

Expected: FAIL with `404 Not Found` for `/api/watchlist`.

- [ ] **Step 4: Add watchlist router**

Write `backend/app/api/routes/watchlist.py`:

```python
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, select

from backend.app.api.deps import get_db_session
from backend.app.models import Watchlist
from backend.app.schemas import WatchlistCreate, WatchlistRead, WatchlistUpdate

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])
SessionDep = Annotated[Session, Depends(get_db_session)]


@router.post("", response_model=WatchlistRead, status_code=status.HTTP_201_CREATED)
def create_watchlist_entry(payload: WatchlistCreate, session: SessionDep) -> Watchlist:
    entry = Watchlist(**payload.model_dump())
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.get("", response_model=list[WatchlistRead])
def list_watchlist_entries(session: SessionDep, status_filter: str | None = None) -> list[Watchlist]:
    statement = select(Watchlist)
    if status_filter is not None:
        statement = statement.where(Watchlist.status == status_filter)
    return list(session.exec(statement).all())


@router.patch("/{entry_id}", response_model=WatchlistRead)
def update_watchlist_entry(
    entry_id: int,
    payload: WatchlistUpdate,
    session: SessionDep,
) -> Watchlist:
    entry = session.get(Watchlist, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="watchlist entry not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    entry.updated_at = datetime.now(UTC)

    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist_entry(entry_id: int, session: SessionDep) -> Response:
    entry = session.get(Watchlist, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="watchlist entry not found")

    session.delete(entry)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 5: Register the router**

Update `backend/app/main.py` imports and router registration:

```python
from backend.app.api.routes import health, watchlist


def create_app() -> FastAPI:
    app = FastAPI(title="Hermes Trading Assistant", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(watchlist.router)
    return app
```

- [ ] **Step 6: Run watchlist and health tests**

Run:

```powershell
pytest tests/test_health.py tests/test_watchlist.py -v
ruff check backend tests
mypy backend/app
```

Expected: all commands pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add backend/app/main.py backend/app/api/routes/watchlist.py tests/conftest.py tests/test_watchlist.py
git status --short
git commit -m "feat: add watchlist api"
```

Expected: only the files listed in this task are committed.

---

### Task 5: Risk Engine

**Files:**
- Create: `backend/app/services/risk.py`
- Create: `tests/test_risk_engine.py`

- [ ] **Step 1: Write failing tests for every hard risk rule**

Write `tests/test_risk_engine.py`:

```python
import pytest

from backend.app.schemas import AccountState, MarketState, SignalCandidate
from backend.app.services.risk import RiskEngine


def candidate(**overrides: object) -> SignalCandidate:
    data: dict[str, object] = {
        "symbol": "SH600000",
        "action": "buy",
        "score": 82,
        "confidence": 0.78,
        "risk_level": "medium",
        "price_range": (10.0, 10.5),
        "stop_loss": 9.2,
        "take_profit": 12.4,
        "max_position_pct": 3.0,
        "reasons": ["trend confirmation"],
        "risks": ["market volatility"],
        "manual_checklist": ["confirm account state"],
    }
    data.update(overrides)
    return SignalCandidate(**data)


def market(**overrides: object) -> MarketState:
    data: dict[str, object] = {
        "symbol": "SH600000",
        "last_price": 10.2,
        "turnover_cny": 150_000_000,
        "is_st": False,
        "is_limit_up": False,
    }
    data.update(overrides)
    return MarketState(**data)


@pytest.mark.parametrize(
    ("bad_candidate", "expected_reason"),
    [
        (candidate(score=69), "score below minimum"),
        (candidate(stop_loss=None), "missing stop loss"),
        (candidate(max_position_pct=5.1), "single position too large"),
        (candidate(take_profit=11.0), "reward/risk ratio below minimum"),
        (candidate(price_range=None), "missing price range"),
        (candidate(take_profit=None), "missing take profit"),
        (candidate(stop_loss=10.3), "invalid stop loss"),
    ],
)
def test_candidate_risk_rules_block(
    bad_candidate: SignalCandidate,
    expected_reason: str,
) -> None:
    result = RiskEngine().evaluate(bad_candidate, AccountState(), market())

    assert result.passed is False
    assert result.blocked_reason == expected_reason


def test_total_position_rule_blocks() -> None:
    result = RiskEngine().evaluate(
        candidate(),
        AccountState(total_position_pct=50),
        market(),
    )

    assert result.passed is False
    assert result.blocked_reason == "total position limit reached"


def test_daily_loss_rule_blocks() -> None:
    result = RiskEngine().evaluate(
        candidate(),
        AccountState(daily_loss_pct=-2),
        market(),
    )

    assert result.passed is False
    assert result.blocked_reason == "daily loss limit reached"


def test_st_rule_blocks() -> None:
    result = RiskEngine().evaluate(candidate(), AccountState(), market(is_st=True))

    assert result.passed is False
    assert result.blocked_reason == "st or risk-warning stock blocked"


def test_turnover_rule_blocks() -> None:
    result = RiskEngine().evaluate(
        candidate(),
        AccountState(),
        market(turnover_cny=99_000_000),
    )

    assert result.passed is False
    assert result.blocked_reason == "turnover below minimum"


def test_limit_up_buy_rule_blocks() -> None:
    result = RiskEngine().evaluate(candidate(), AccountState(), market(is_limit_up=True))

    assert result.passed is False
    assert result.blocked_reason == "limit-up buy blocked"


def test_valid_candidate_passes() -> None:
    result = RiskEngine().evaluate(candidate(), AccountState(), market())

    assert result.passed is True
    assert result.blocked_reason is None
```

- [ ] **Step 2: Run risk tests and verify they fail**

Run:

```powershell
pytest tests/test_risk_engine.py -v
```

Expected: FAIL because `backend.app.services.risk` does not exist.

- [ ] **Step 3: Implement hard risk rules**

Write `backend/app/services/risk.py`:

```python
from backend.app.schemas import AccountState, MarketState, RiskCheckResult, RiskConfig, SignalCandidate


class RiskEngine:
    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def evaluate(
        self,
        candidate: SignalCandidate,
        account: AccountState,
        market: MarketState,
    ) -> RiskCheckResult:
        config = self.config

        if candidate.score < config.min_signal_score:
            return self._blocked("score below minimum")
        if candidate.stop_loss is None:
            return self._blocked("missing stop loss")
        if candidate.max_position_pct > config.max_single_position_pct:
            return self._blocked("single position too large")
        if account.total_position_pct >= config.max_total_position_pct:
            return self._blocked("total position limit reached")
        if account.daily_loss_pct <= -config.max_daily_loss_pct:
            return self._blocked("daily loss limit reached")
        if config.block_st and market.is_st:
            return self._blocked("st or risk-warning stock blocked")
        if market.turnover_cny < config.min_turnover_cny:
            return self._blocked("turnover below minimum")
        if candidate.price_range is None:
            return self._blocked("missing price range")
        if candidate.take_profit is None:
            return self._blocked("missing take profit")

        entry_price = sum(candidate.price_range) / 2
        if candidate.action == "buy":
            if candidate.stop_loss >= entry_price:
                return self._blocked("invalid stop loss")
            if config.block_limit_up_buy and market.is_limit_up:
                return self._blocked("limit-up buy blocked")
            risk = entry_price - candidate.stop_loss
            reward = candidate.take_profit - entry_price
        else:
            risk = abs(entry_price - candidate.stop_loss)
            reward = abs(candidate.take_profit - entry_price)

        if risk <= 0:
            return self._blocked("invalid stop loss")
        if reward / risk < config.min_reward_risk_ratio:
            return self._blocked("reward/risk ratio below minimum")

        return RiskCheckResult(passed=True)

    @staticmethod
    def _blocked(reason: str) -> RiskCheckResult:
        return RiskCheckResult(passed=False, blocked_reason=reason)
```

- [ ] **Step 4: Run risk tests and quality checks**

Run:

```powershell
pytest tests/test_risk_engine.py -v
ruff check backend tests
mypy backend/app
```

Expected: all commands pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add backend/app/services/risk.py tests/test_risk_engine.py
git status --short
git commit -m "feat: add hard risk engine"
```

Expected: only the files listed in this task are committed.

---

### Task 6: Mock Providers And Console Notifications

**Files:**
- Create: `backend/app/services/market_data.py`
- Create: `backend/app/services/llm_analyzer.py`
- Create: `backend/app/services/notifications.py`
- Create: `tests/test_notifications.py`

- [ ] **Step 1: Write failing notification disclaimer test**

Write `tests/test_notifications.py`:

```python
from backend.app.schemas import SignalCandidate
from backend.app.services.notifications import ConsoleNotificationProvider


def test_console_notification_contains_manual_confirmation_disclaimer(capsys) -> None:  # type: ignore[no-untyped-def]
    candidate = SignalCandidate(
        symbol="SH600000",
        action="buy",
        score=82,
        confidence=0.78,
        risk_level="medium",
        price_range=(10.0, 10.5),
        stop_loss=9.2,
        take_profit=12.4,
        max_position_pct=3.0,
        reasons=["trend confirmation"],
        risks=["market volatility"],
        manual_checklist=["confirm account state"],
    )

    ConsoleNotificationProvider().notify(candidate, signal_id=1)

    output = capsys.readouterr().out
    assert "manual confirmation required" in output
    assert "not an automatic order instruction" in output
    assert "SH600000" in output
```

- [ ] **Step 2: Run notification test and verify it fails**

Run:

```powershell
pytest tests/test_notifications.py -v
```

Expected: FAIL because `backend.app.services.notifications` does not exist.

- [ ] **Step 3: Add mock market provider**

Write `backend/app/services/market_data.py`:

```python
from backend.app.schemas import MarketState


class MockMarketDataProvider:
    def get_market_state(self, symbol: str) -> MarketState:
        normalized = symbol.strip().upper()
        return MarketState(
            symbol=normalized,
            last_price=10.2,
            turnover_cny=50_000_000 if normalized.startswith("LOWTURN") else 150_000_000,
            is_st=normalized.startswith("ST"),
            is_limit_up=normalized.startswith("LIMITUP"),
        )
```

- [ ] **Step 4: Add mock LLM analyzer**

Write `backend/app/services/llm_analyzer.py`:

```python
from backend.app.schemas import MarketState, SignalCandidate


class MockLLMAnalyzer:
    def analyze(self, symbol: str, market: MarketState) -> SignalCandidate:
        normalized = symbol.strip().upper()
        score = 60 if normalized.startswith("LOW") else 82
        return SignalCandidate(
            symbol=normalized,
            action="buy",
            score=score,
            confidence=0.78,
            risk_level="medium",
            price_range=(10.0, 10.5),
            stop_loss=9.2,
            take_profit=12.4,
            max_position_pct=3.0,
            reasons=[f"mock trend confirmation at {market.last_price:.2f}"],
            risks=["mock market volatility"],
            manual_checklist=[
                "confirm signal manually",
                "confirm account and position limits manually",
            ],
        )
```

- [ ] **Step 5: Add console notification provider**

Write `backend/app/services/notifications.py`:

```python
from backend.app.schemas import SignalCandidate


class ConsoleNotificationProvider:
    def notify(self, candidate: SignalCandidate, signal_id: int) -> None:
        price_range = candidate.price_range or (0.0, 0.0)
        print(
            "\n".join(
                [
                    f"Signal #{signal_id}: {candidate.symbol} {candidate.action.upper()}",
                    f"Score: {candidate.score}, confidence: {candidate.confidence:.2f}",
                    f"Suggested range: {price_range[0]:.2f}-{price_range[1]:.2f}",
                    f"Stop loss: {candidate.stop_loss}, take profit: {candidate.take_profit}",
                    "manual confirmation required",
                    "not an automatic order instruction",
                ],
            ),
        )
```

- [ ] **Step 6: Run notification test and quality checks**

Run:

```powershell
pytest tests/test_notifications.py -v
ruff check backend tests
mypy backend/app
```

Expected: all commands pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add backend/app/services/market_data.py backend/app/services/llm_analyzer.py backend/app/services/notifications.py tests/test_notifications.py
git status --short
git commit -m "feat: add mock providers and notifications"
```

Expected: only the files listed in this task are committed.

---

### Task 7: Signal Scan And Signal Listing

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/app/services/signal_engine.py`
- Create: `backend/app/api/routes/signals.py`
- Create: `tests/test_signal_scan.py`

- [ ] **Step 1: Write failing signal scan tests**

Write `tests/test_signal_scan.py`:

```python
from fastapi.testclient import TestClient


def add_symbol(client: TestClient, symbol: str) -> int:
    response = client.post("/api/watchlist", json={"symbol": symbol})
    assert response.status_code == 201
    return int(response.json()["id"])


def test_signal_scan_persists_risk_passed_signal(client: TestClient) -> None:
    add_symbol(client, "SH600000")

    scan_response = client.post("/api/signals/scan", json={"account": {}})

    assert scan_response.status_code == 200
    results = scan_response.json()["results"]
    assert len(results) == 1
    assert results[0]["symbol"] == "SH600000"
    assert results[0]["risk_passed"] is True
    assert results[0]["blocked_reason"] is None
    assert results[0]["signal_id"] is not None

    list_response = client.get("/api/signals")
    assert list_response.status_code == 200
    signals = list_response.json()
    assert len(signals) == 1
    assert signals[0]["symbol"] == "SH600000"
    assert signals[0]["status"] == "risk_passed"


def test_signal_scan_persists_risk_blocked_signal(client: TestClient) -> None:
    add_symbol(client, "LOW001")

    response = client.post("/api/signals/scan", json={"account": {}})

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["risk_passed"] is False
    assert result["blocked_reason"] == "score below minimum"
    assert result["signal_id"] is not None

    blocked = client.get("/api/signals", params={"status_filter": "risk_blocked"}).json()
    assert len(blocked) == 1
    assert blocked[0]["status"] == "risk_blocked"
```

- [ ] **Step 2: Run signal scan tests and verify they fail**

Run:

```powershell
pytest tests/test_signal_scan.py -v
```

Expected: FAIL with `404 Not Found` for `/api/signals/scan`.

- [ ] **Step 3: Add signal engine**

Write `backend/app/services/signal_engine.py`:

```python
from sqlmodel import Session, select

from backend.app.models import RiskCheck, Signal, Watchlist
from backend.app.schemas import AccountState, SignalCandidate, SignalScanResult
from backend.app.services.llm_analyzer import MockLLMAnalyzer
from backend.app.services.market_data import MockMarketDataProvider
from backend.app.services.notifications import ConsoleNotificationProvider
from backend.app.services.risk import RiskEngine


def _join_text(values: list[str]) -> str:
    return "\n".join(values)


def _to_signal(candidate: SignalCandidate, status: str) -> Signal:
    price_low: float | None = None
    price_high: float | None = None
    if candidate.price_range is not None:
        price_low, price_high = candidate.price_range
    return Signal(
        symbol=candidate.symbol,
        action=candidate.action,
        score=candidate.score,
        confidence=candidate.confidence,
        risk_level=candidate.risk_level,
        price_low=price_low,
        price_high=price_high,
        stop_loss=candidate.stop_loss,
        take_profit=candidate.take_profit,
        max_position_pct=candidate.max_position_pct,
        status=status,
        reasons_text=_join_text(candidate.reasons),
        risks_text=_join_text(candidate.risks),
        manual_checklist_text=_join_text(candidate.manual_checklist),
    )


class SignalEngine:
    def __init__(
        self,
        market_provider: MockMarketDataProvider | None = None,
        analyzer: MockLLMAnalyzer | None = None,
        risk_engine: RiskEngine | None = None,
        notifier: ConsoleNotificationProvider | None = None,
    ) -> None:
        self.market_provider = market_provider or MockMarketDataProvider()
        self.analyzer = analyzer or MockLLMAnalyzer()
        self.risk_engine = risk_engine or RiskEngine()
        self.notifier = notifier or ConsoleNotificationProvider()

    def scan_active_watchlist(
        self,
        session: Session,
        account: AccountState,
    ) -> list[SignalScanResult]:
        entries = session.exec(
            select(Watchlist).where(Watchlist.status == "active"),
        ).all()
        results: list[SignalScanResult] = []

        for entry in entries:
            try:
                market = self.market_provider.get_market_state(entry.symbol)
                candidate = self.analyzer.analyze(entry.symbol, market)
                risk_result = self.risk_engine.evaluate(candidate, account, market)
                signal_status = "risk_passed" if risk_result.passed else "risk_blocked"
                signal = _to_signal(candidate, signal_status)
                session.add(signal)
                session.commit()
                session.refresh(signal)

                risk_check = RiskCheck(
                    signal_id=int(signal.id),
                    passed=risk_result.passed,
                    blocked_reason=risk_result.blocked_reason,
                )
                session.add(risk_check)
                session.commit()

                if risk_result.passed:
                    self.notifier.notify(candidate, int(signal.id))

                results.append(
                    SignalScanResult(
                        symbol=entry.symbol,
                        signal_id=signal.id,
                        risk_passed=risk_result.passed,
                        blocked_reason=risk_result.blocked_reason,
                    ),
                )
            except Exception as exc:
                session.rollback()
                results.append(SignalScanResult(symbol=entry.symbol, error=str(exc)))

        return results
```

- [ ] **Step 4: Add signals router**

Write `backend/app/api/routes/signals.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.app.api.deps import get_db_session
from backend.app.models import Signal
from backend.app.schemas import ScanRequest, ScanResponse, SignalRead
from backend.app.services.signal_engine import SignalEngine

router = APIRouter(prefix="/api/signals", tags=["signals"])
SessionDep = Annotated[Session, Depends(get_db_session)]


@router.post("/scan", response_model=ScanResponse)
def scan_signals(payload: ScanRequest, session: SessionDep) -> ScanResponse:
    return ScanResponse(results=SignalEngine().scan_active_watchlist(session, payload.account))


@router.get("", response_model=list[SignalRead])
def list_signals(session: SessionDep, status_filter: str | None = None) -> list[Signal]:
    statement = select(Signal)
    if status_filter is not None:
        statement = statement.where(Signal.status == status_filter)
    return list(session.exec(statement).all())


def get_signal_or_404(session: Session, signal_id: int) -> Signal:
    signal = session.get(Signal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="signal not found")
    return signal
```

- [ ] **Step 5: Register signals router**

Update `backend/app/main.py` imports and router registration:

```python
from backend.app.api.routes import health, signals, watchlist


def create_app() -> FastAPI:
    app = FastAPI(title="Hermes Trading Assistant", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(watchlist.router)
    app.include_router(signals.router)
    return app
```

- [ ] **Step 6: Run signal scan tests and quality checks**

Run:

```powershell
pytest tests/test_signal_scan.py tests/test_watchlist.py -v
ruff check backend tests
mypy backend/app
```

Expected: all commands pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add backend/app/main.py backend/app/services/signal_engine.py backend/app/api/routes/signals.py tests/test_signal_scan.py
git status --short
git commit -m "feat: add signal scan api"
```

Expected: only the files listed in this task are committed.

---

### Task 8: Manual Review Endpoint

**Files:**
- Modify: `backend/app/api/routes/signals.py`
- Create: `tests/test_manual_review.py`

- [ ] **Step 1: Write failing manual review tests**

Write `tests/test_manual_review.py`:

```python
from fastapi.testclient import TestClient


def create_signal(client: TestClient) -> int:
    client.post("/api/watchlist", json={"symbol": "SH600000"})
    response = client.post("/api/signals/scan", json={"account": {}})
    return int(response.json()["results"][0]["signal_id"])


def test_manual_review_records_decision_and_updates_signal_status(client: TestClient) -> None:
    signal_id = create_signal(client)

    response = client.post(
        f"/api/signals/{signal_id}/manual-review",
        json={"decision": "accepted", "note": "reviewed manually"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["signal_id"] == signal_id
    assert body["decision"] == "accepted"

    signal = client.get("/api/signals").json()[0]
    assert signal["status"] == "accepted"


def test_manual_review_accepts_all_valid_decisions(client: TestClient) -> None:
    for decision in ["accepted", "rejected", "ignored"]:
        signal_id = create_signal(client)
        response = client.post(
            f"/api/signals/{signal_id}/manual-review",
            json={"decision": decision},
        )
        assert response.status_code == 201
        assert response.json()["decision"] == decision


def test_manual_review_missing_signal_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/signals/999/manual-review",
        json={"decision": "ignored"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "signal not found"
```

- [ ] **Step 2: Run manual review tests and verify they fail**

Run:

```powershell
pytest tests/test_manual_review.py -v
```

Expected: FAIL with `404 Not Found` for `/manual-review`.

- [ ] **Step 3: Add manual review endpoint**

Append this endpoint to `backend/app/api/routes/signals.py`:

```python
from fastapi import status

from backend.app.models import ManualReview
from backend.app.schemas import ManualReviewCreate, ManualReviewRead


@router.post(
    "/{signal_id}/manual-review",
    response_model=ManualReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def create_manual_review(
    signal_id: int,
    payload: ManualReviewCreate,
    session: SessionDep,
) -> ManualReview:
    signal = get_signal_or_404(session, signal_id)
    review = ManualReview(signal_id=signal_id, decision=payload.decision, note=payload.note)
    signal.status = payload.decision
    session.add(signal)
    session.add(review)
    session.commit()
    session.refresh(review)
    return review
```

Keep the import section sorted after adding these imports:

```python
from fastapi import APIRouter, Depends, HTTPException, status
```

- [ ] **Step 4: Run manual review tests and quality checks**

Run:

```powershell
pytest tests/test_manual_review.py tests/test_signal_scan.py -v
ruff check backend tests
mypy backend/app
```

Expected: all commands pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add backend/app/api/routes/signals.py tests/test_manual_review.py
git status --short
git commit -m "feat: add manual review endpoint"
```

Expected: only the files listed in this task are committed.

---

### Task 9: Daily Review Engine And Endpoint

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/app/services/review_engine.py`
- Create: `backend/app/api/routes/reviews.py`
- Create: `tests/test_daily_review.py`

- [ ] **Step 1: Write failing daily review tests**

Write `tests/test_daily_review.py`:

```python
from fastapi.testclient import TestClient


def scan_symbol(client: TestClient, symbol: str) -> int:
    client.post("/api/watchlist", json={"symbol": symbol})
    response = client.post("/api/signals/scan", json={"account": {}})
    return int(response.json()["results"][0]["signal_id"])


def test_daily_review_summarizes_signals_and_decisions(client: TestClient) -> None:
    passed_signal_id = scan_symbol(client, "SH600000")
    scan_symbol(client, "LOW001")
    client.post(
        f"/api/signals/{passed_signal_id}/manual-review",
        json={"decision": "accepted"},
    )

    response = client.get("/api/reviews/daily")

    assert response.status_code == 200
    body = response.json()
    assert body["total_signals"] == 2
    assert body["risk_passed"] == 1
    assert body["risk_blocked"] == 1
    assert body["accepted"] == 1
    assert body["rejected"] == 0
    assert body["ignored"] == 0
    assert "2 signals" in body["summary"]
    assert "1 risk-passed" in body["summary"]
    assert "1 risk-blocked" in body["summary"]
```

- [ ] **Step 2: Run daily review tests and verify they fail**

Run:

```powershell
pytest tests/test_daily_review.py -v
```

Expected: FAIL with `404 Not Found` for `/api/reviews/daily`.

- [ ] **Step 3: Add review engine**

Write `backend/app/services/review_engine.py`:

```python
from datetime import UTC, date, datetime, time, timedelta

from sqlmodel import Session, select

from backend.app.models import ManualReview, RiskCheck, Signal
from backend.app.schemas import DailyReviewResponse


class ReviewEngine:
    def daily_review(self, session: Session, review_date: date | None = None) -> DailyReviewResponse:
        selected_date = review_date or datetime.now(UTC).date()
        start = datetime.combine(selected_date, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)

        signals = list(
            session.exec(
                select(Signal).where(Signal.generated_at >= start, Signal.generated_at < end),
            ).all(),
        )
        signal_ids = [signal.id for signal in signals if signal.id is not None]
        risk_checks = []
        reviews = []
        if signal_ids:
            risk_checks = list(
                session.exec(select(RiskCheck).where(RiskCheck.signal_id.in_(signal_ids))).all(),
            )
            reviews = list(
                session.exec(select(ManualReview).where(ManualReview.signal_id.in_(signal_ids))).all(),
            )

        risk_passed = sum(1 for check in risk_checks if check.passed)
        risk_blocked = sum(1 for check in risk_checks if not check.passed)
        accepted = sum(1 for review in reviews if review.decision == "accepted")
        rejected = sum(1 for review in reviews if review.decision == "rejected")
        ignored = sum(1 for review in reviews if review.decision == "ignored")
        summary = (
            f"{len(signals)} signals, {risk_passed} risk-passed, "
            f"{risk_blocked} risk-blocked, {accepted} accepted, "
            f"{rejected} rejected, {ignored} ignored."
        )

        return DailyReviewResponse(
            date=selected_date.isoformat(),
            total_signals=len(signals),
            risk_passed=risk_passed,
            risk_blocked=risk_blocked,
            accepted=accepted,
            rejected=rejected,
            ignored=ignored,
            summary=summary,
        )
```

- [ ] **Step 4: Add reviews router**

Write `backend/app/api/routes/reviews.py`:

```python
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from backend.app.api.deps import get_db_session
from backend.app.schemas import DailyReviewResponse
from backend.app.services.review_engine import ReviewEngine

router = APIRouter(prefix="/api/reviews", tags=["reviews"])
SessionDep = Annotated[Session, Depends(get_db_session)]


@router.get("/daily", response_model=DailyReviewResponse)
def get_daily_review(session: SessionDep, review_date: date | None = None) -> DailyReviewResponse:
    return ReviewEngine().daily_review(session, review_date)
```

- [ ] **Step 5: Register reviews router**

Update `backend/app/main.py` imports and router registration:

```python
from backend.app.api.routes import health, reviews, signals, watchlist


def create_app() -> FastAPI:
    app = FastAPI(title="Hermes Trading Assistant", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(watchlist.router)
    app.include_router(signals.router)
    app.include_router(reviews.router)
    return app
```

- [ ] **Step 6: Run daily review tests and quality checks**

Run:

```powershell
pytest tests/test_daily_review.py tests/test_manual_review.py tests/test_signal_scan.py -v
ruff check backend tests
mypy backend/app
```

Expected: all commands pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add backend/app/main.py backend/app/services/review_engine.py backend/app/api/routes/reviews.py tests/test_daily_review.py
git status --short
git commit -m "feat: add daily review api"
```

Expected: only the files listed in this task are committed.

---

### Task 10: Final Verification And Documentation Polish

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Expand README with endpoint examples**

Replace `README.md` with:

````markdown
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
````

- [ ] **Step 2: Confirm environment example remains minimal**

Ensure `.env.example` contains exactly:

```dotenv
DATABASE_URL=sqlite:///./hermes.db
```

- [ ] **Step 3: Run the complete test suite**

Run:

```powershell
pytest
```

Expected: all tests pass, including health, watchlist CRUD, schema validation, all hard risk rules, signal scan, manual review, daily review, and notification disclaimer coverage.

- [ ] **Step 4: Run the complete lint check**

Run:

```powershell
ruff check .
```

Expected: no lint errors.

- [ ] **Step 5: Run the complete type check**

Run:

```powershell
mypy backend/app
```

Expected: no type errors. If SQLModel generic typing produces a framework limitation, narrow the ignore to the exact line and include a one-sentence comment explaining the limitation.

- [ ] **Step 6: Manually verify the safety boundary**

Run:

```powershell
rg -n "eastmoney|order|trade|broker|credential|traffic|packet|automation|auto" backend tests README.md
```

Expected: matches appear only in safety disclaimers, test names, or non-automation descriptions. No code path controls Eastmoney, captures app traffic, stores brokerage credentials, bypasses verification, or places orders.

- [ ] **Step 7: Commit**

Run:

```powershell
git add README.md .env.example
git status --short
git commit -m "docs: document backend mvp usage"
```

Expected: only the files listed in this task are committed.

---

## Spec Coverage Self-Review

- Health endpoint: Task 2.
- Watchlist create/list/update/delete: Task 4.
- SQLite `DATABASE_URL` persistence: Tasks 1, 2, and 4.
- SQLModel tables and Pydantic schemas: Task 3.
- Mock market data and mock LLM analyzer: Task 6.
- Hard risk rules independent of LLM output: Task 5.
- Signal orchestration, persistence, per-symbol results, and notifications: Task 7.
- Signal listing and status filtering: Task 7.
- Manual review decisions and status transitions: Task 8.
- Daily review statistics and summary text: Task 9.
- pytest, ruff, and mypy setup: Tasks 1 and 10.
- README and environment example: Tasks 1 and 10.
- Safety boundary against automatic trading and Eastmoney automation: README in Tasks 1 and 10; verification command in Task 10.
