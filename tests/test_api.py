from fastapi.testclient import TestClient
from src.main import app


def _clean_db():
    """Each test starts from an empty records table."""
    from src.main import _connect

    with _connect() as conn:
        conn.execute("delete from records")


def test_health():
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True


def test_expense_summary():
    _clean_db()
    with TestClient(app) as client:
        client.post("/api/expenses", json={"description": "GitHub Pro", "amount": 4})
        data = client.get("/api/summary").json()
        assert data["count"] >= 1
        assert "Developer Tools" in data["by_category"]


def test_no_wildcard_cors():
    """No CORS middleware: responses must not carry permissive CORS headers."""
    with TestClient(app) as client:
        r = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in r.headers


def test_nan_amount_rejected():
    _clean_db()
    with TestClient(app) as client:
        r = client.post("/api/expenses", json={"description": "weird", "amount": "NaN"})
        assert r.status_code == 422
        r = client.post(
            "/api/expenses", json={"description": "weird", "amount": "Infinity"}
        )
        assert r.status_code == 422


def test_oversized_amount_rejected():
    with TestClient(app) as client:
        r = client.post("/api/expenses", json={"description": "huge", "amount": 10**9})
        assert r.status_code == 422


def test_bad_csv_row_reports_error_not_500():
    """A malformed amount/date row must be reported, not crash the import."""
    _clean_db()
    csv_body = (
        "description,amount,date\n"
        "Valid Coffee,4.50,2026-01-15\n"
        "Bad Amount,not-a-number,2026-01-16\n"
        "Bad Date,5.00,not-a-date\n"
    )
    with TestClient(app) as client:
        r = client.post(
            "/api/import.csv",
            files={"file": ("expenses.csv", csv_body, "text/csv")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["imported"] == 1
        assert len(data["errors"]) == 2
        assert data["errors"][0]["row"] == 3  # second data row


def test_csv_amount_variants_parse():
    """$ and comma variants and empty amounts should import cleanly."""
    _clean_db()
    csv_body = (
        "description,amount,date\n"
        "Coffee,$4.50,2026-01-15\n"
        'Big Item,"1,234.56",2026-01-15\n'
        "Free Thing,,2026-01-15\n"
    )
    with TestClient(app) as client:
        r = client.post(
            "/api/import.csv",
            files={"file": ("expenses.csv", csv_body, "text/csv")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["imported"] == 3
        amounts = {e["description"]: e["amount"] for e in data["expenses"]}
        assert amounts["Coffee"] == 4.50
        assert amounts["Big Item"] == 1234.56
        assert amounts["Free Thing"] == 0.0


def test_csv_us_date_format_accepted():
    _clean_db()
    csv_body = "description,amount,date\nCoffee,4.50,01/15/2026\n"
    with TestClient(app) as client:
        r = client.post(
            "/api/import.csv",
            files={"file": ("expenses.csv", csv_body, "text/csv")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["imported"] == 1
        assert data["expenses"][0]["date"] == "2026-01-15"