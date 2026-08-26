from fastapi.testclient import TestClient
from src.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True


def test_expense_summary():
    with TestClient(app) as client:
        client.post("/api/expenses", json={"description": "GitHub Pro", "amount": 4})
        data = client.get("/api/summary").json()
        assert data["count"] >= 1
        assert "Developer Tools" in data["by_category"]
