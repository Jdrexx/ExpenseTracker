"""AI Expense Tracker — import CSV expenses, auto-categorize, detect anomalies.

Local-first single-file FastAPI app. Data stays in a local SQLite file.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

APP_NAME = "AI Expense Tracker"
DB_FILE = Path(__file__).resolve().parent.parent / "data" / "app.sqlite"
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB per import file

DB_FILE.parent.mkdir(exist_ok=True)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=wal")
    # A concurrent writer surfaces "database is locked" instantly without this;
    # WAL readers keep working, but writers should wait their turn.
    conn.execute("pragma busy_timeout=5000")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            "create table if not exists records (id integer primary key autoincrement, kind text not null, title text not null, payload text not null, created_at text not null)"
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=APP_NAME, version="0.1.0", lifespan=lifespan)


def save_record(kind: str, title: str, payload: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "insert into records(kind,title,payload,created_at) values (?,?,?,?)",
            (kind, title, payload, datetime.now(timezone.utc).isoformat()),
        )
        return int(cur.lastrowid)


def rows(kind: str | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        data = (
            conn.execute(
                "select * from records where kind=? order by id desc", (kind,)
            ).fetchall()
            if kind
            else conn.execute("select * from records order by id desc").fetchall()
        )
    return [dict(r) for r in data]


@app.get("/api/health")
def health():
    return {"ok": True, "app": APP_NAME, "records": len(rows())}


@app.get("/", response_class=HTMLResponse)
def home():
    return INDEX_HTML


class ExpenseRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, populate_by_name=True)

    description: str = Field(..., min_length=1, max_length=500)
    amount: float = Field(..., ge=-1_000_000, le=1_000_000)
    # Field is named expense_date to avoid the `date: date` pydantic clash;
    # the API wire format stays "date" via the alias.
    expense_date: date = Field(default_factory=lambda: date.today(), alias="date")


def category(desc: str) -> str:
    d = desc.lower()
    if any(w in d for w in ["vercel", "github", "domain", "hosting", "aws", "railway"]):
        return "Developer Tools"
    if any(w in d for w in ["uber", "gas", "flight", "hotel"]):
        return "Travel"
    if any(w in d for w in ["restaurant", "coffee", "food"]):
        return "Meals"
    if any(w in d for w in ["course", "book", "school", "training"]):
        return "Education"
    return "General"


def _clean_amount(raw: object) -> float:
    """Parse a CSV amount cell: strips $ , and spaces; '' -> 0.0.

    Raises ValueError for values that cannot be a number, so a malformed row is
    reported instead of crashing the whole import with a 500.
    """
    if raw is None:
        return 0.0
    text = str(raw).strip().replace(",", "").replace("$", "").replace(" ", "")
    if not text:
        return 0.0
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        raise ValueError(f"amount is not a finite number: {raw!r}")
    return value


def _clean_date(raw: object) -> date:
    """Accept ISO (YYYY-MM-DD) and US-style MM/DD/YYYY or MM-DD-YYYY cells."""
    if raw is None:
        return date.today()
    text = str(raw).strip()
    if not text:
        return date.today()
    if text.isdigit() and len(text) == 8:  # 20260115
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date: {raw!r} (use YYYY-MM-DD or MM/DD/YYYY)")


@app.post("/api/expenses")
def add_expense(req: ExpenseRequest):
    payload = req.model_dump(mode="json", by_alias=True)  # date -> ISO string
    payload["category"] = category(req.description)
    payload["anomaly"] = abs(req.amount) > 500
    expense_id = save_record("expense", req.description, json.dumps(payload))
    return {"id": expense_id, **payload}


@app.post("/api/import.csv")
async def import_csv(file: UploadFile = File(...)):
    # Content-Length is advisory (absent/spoofable under chunked encoding), so
    # the bounded read below is the real cap; both checks stay.
    content_length = int(file.headers.get("content-length", 0))
    if content_length > MAX_UPLOAD_SIZE:
        raise HTTPException(413, detail=f"File too large. Maximum 10MB allowed.")
    raw = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(raw) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, detail=f"File too large. Maximum 10MB allowed.")
    text = raw.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    imported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(reader, start=2):  # row 1 is the header
        try:
            desc = (
                row.get("description")
                or row.get("Description")
                or row.get("memo")
                or "Expense"
            )
            amount = _clean_amount(row.get("amount") or row.get("Amount"))
            expense_date = _clean_date(row.get("date") or row.get("Date"))
            imported.append(
                add_expense(
                    ExpenseRequest(
                        description=desc,
                        amount=amount,
                        date=expense_date,
                    )
                )
            )
        except (ValueError, ValidationError) as exc:
            # One bad row must not 500 the whole import: report it and continue.
            errors.append({"row": index, "error": str(exc)})
    return {"imported": len(imported), "errors": errors, "expenses": imported}


@app.get("/api/summary")
def summary():
    items = [json.loads(r["payload"]) for r in rows("expense")]
    by_cat = defaultdict(float)
    total = 0.0
    anomalies = []
    for item in items:
        total += item["amount"]
        by_cat[item["category"]] += item["amount"]
        if item.get("anomaly"):
            anomalies.append(item)
    return {
        "total": round(total, 2),
        "by_category": {k: round(v, 2) for k, v in by_cat.items()},
        "anomalies": anomalies,
        "count": len(items),
    }


INDEX_HTML = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Expense Tracker</title><style>body{font-family:Inter,Arial,sans-serif;background:#0f172a;color:#e5e7eb;margin:0}main{max-width:980px;margin:auto;padding:32px}.card{background:#111827;border:1px solid #334155;border-radius:18px;padding:24px;margin:18px 0}h1{font-size:42px}textarea,input{width:100%;box-sizing:border-box;border-radius:12px;border:1px solid #475569;background:#020617;color:#e5e7eb;padding:14px;margin:8px 0}button{background:#22c55e;color:#04130a;border:0;border-radius:12px;padding:12px 18px;font-weight:700}pre{white-space:pre-wrap;background:#020617;border-radius:12px;padding:16px}.pill{background:#1e293b;border:1px solid #475569;border-radius:999px;padding:6px 10px}</style></head><body><main><div class="card"><span class="pill">finance automation</span><h1>AI Expense Tracker</h1><p>Import CSV expenses, auto-categorize spending, detect anomalies, and export monthly insights.</p><ul><li>CSV expense import</li><li>Auto categorization</li><li>Budget summary dashboard</li><li>Anomaly detection</li></ul></div><div class="card"><h2>Live API Demo</h2><textarea id="input" rows="7">GitHub Pro subscription</textarea><input id="input2" type="number" value="4" /><button onclick="runDemo()">Run Demo</button><pre id="out">Click Run Demo to call the FastAPI backend.</pre></div><div class="card"><h2>API</h2><p>Health: <code>/api/health</code> · Docs: <code>/docs</code></p></div><script>async function runDemo(){const res = await (fetch(\'/api/expenses\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({description:document.getElementById(\'input\').value,amount:Number(document.getElementById(\'input2\').value||42)})})); const data = await res.json(); document.getElementById(\'out\').textContent = JSON.stringify(data,null,2);}</script></main></body></html>'