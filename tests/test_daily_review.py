from fastapi.testclient import TestClient


def scan_symbol(client: TestClient, symbol: str) -> tuple[int, int]:
    watchlist_response = client.post("/api/watchlist", json={"symbol": symbol})
    response = client.post("/api/signals/scan", json={"account": {}})
    return int(watchlist_response.json()["id"]), int(response.json()["results"][0]["signal_id"])


def test_daily_review_summarizes_signals_and_decisions(client: TestClient) -> None:
    passed_watchlist_id, passed_signal_id = scan_symbol(client, "SH600000")
    client.patch(f"/api/watchlist/{passed_watchlist_id}", json={"status": "blocked"})
    scan_symbol(client, "LOW001")
    client.post(
        f"/api/signals/{passed_signal_id}/manual-review",
        json={"decision": "accepted"},
    )

    assert len(client.get("/api/signals").json()) == 2

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


def test_daily_review_counts_all_persisted_signal_rows(client: TestClient) -> None:
    scan_symbol(client, "SH600000")
    scan_symbol(client, "LOW001")

    assert len(client.get("/api/signals").json()) == 3

    response = client.get("/api/reviews/daily")

    assert response.status_code == 200
    body = response.json()
    assert body["total_signals"] == 3
    assert "3 signals" in body["summary"]
