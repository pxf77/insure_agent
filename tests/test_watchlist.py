from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_app_can_start_without_touching_default_sqlite_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "hermes.db"
    monkeypatch.chdir(tmp_path)

    with TestClient(create_app(create_tables_on_startup=False)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert not database_path.exists()


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
    assert patch_response.json()["updated_at"] != created["updated_at"]

    delete_response = client.delete(f"/api/watchlist/{created['id']}")
    assert delete_response.status_code == 204
    assert client.get("/api/watchlist").json() == []


def test_watchlist_status_filter_returns_only_matching_entries(client: TestClient) -> None:
    client.post("/api/watchlist", json={"symbol": "SH600000", "status": "active"})
    client.post("/api/watchlist", json={"symbol": "SH600001", "status": "blocked"})

    response = client.get("/api/watchlist?status_filter=blocked")

    assert response.status_code == 200
    assert [item["symbol"] for item in response.json()] == ["SH600001"]


def test_watchlist_missing_id_returns_404(client: TestClient) -> None:
    response = client.patch("/api/watchlist/999", json={"status": "blocked"})

    assert response.status_code == 404
    assert response.json()["detail"] == "watchlist entry not found"


def test_watchlist_delete_missing_id_returns_404(client: TestClient) -> None:
    response = client.delete("/api/watchlist/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "watchlist entry not found"
