from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from backend.app.models import RiskCheck, Signal, Watchlist
from backend.app.schemas import AccountState, SignalCandidate
from backend.app.services.signal_engine import SignalEngine


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as db_session:
        yield db_session


class FailingNotifier:
    def notify(self, candidate: SignalCandidate, signal_id: int) -> None:
        raise RuntimeError("notification unavailable")


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


def test_signal_scan_rolls_back_persisted_rows_when_notification_fails(
    session: Session,
) -> None:
    session.add(Watchlist(symbol="SH600000", status="active"))
    session.commit()

    results = SignalEngine(notifier=FailingNotifier()).scan_active_watchlist(
        session,
        AccountState(),
    )

    assert len(results) == 1
    assert results[0].symbol == "SH600000"
    assert results[0].error == "notification unavailable"
    assert results[0].signal_id is None
    assert session.exec(select(Signal).where(Signal.symbol == "SH600000")).all() == []
    assert session.exec(select(RiskCheck)).all() == []
