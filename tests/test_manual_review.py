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
