from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok_status() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.0.1"}
