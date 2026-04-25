from __future__ import annotations


def test_alarm_status_with_school_prefix_returns_200(client) -> None:
    response = client.get(
        "/default/alarm/status",
        headers={"X-API-Key": "test-api-key"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "is_active" in payload
    assert "is_training" in payload


def test_alarm_status_without_school_prefix_returns_404(client) -> None:
    response = client.get(
        "/alarm/status",
        headers={"X-API-Key": "test-api-key"},
    )
    assert response.status_code == 404
