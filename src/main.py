from __future__ import annotations
import csv, io, json, sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
APP_NAME='Expense Tracker'
DB_FILE=Path(__file__).resolve().parent.parent/'data'/'app.sqlite'
DB_FILE.parent.mkdir(exist_ok=True)
app=FastAPI(title=APP_NAME, version='0.1.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

def db() -> sqlite3.Connection:
    conn=sqlite3.connect(DB_FILE); conn.row_factory=sqlite3.Row; conn.execute('pragma journal_mode=wal'); return conn
def init_db() -> None:
    with db() as conn: conn.execute('create table if not exists records (id integer primary key autoincrement, kind text not null, title text not null, payload text not null, created_at text not null)')
init_db()
def save_record(kind: str, title: str, payload: str) -> int:
    with db() as conn:
        cur=conn.execute('insert into records(kind,title,payload,created_at) values (?,?,?,?)',(kind,title,payload,datetime.now(timezone.utc).isoformat())); return int(cur.lastrowid)
def rows(kind: str | None = None) -> list[dict[str, Any]]:
    with db() as conn:
        data=conn.execute('select * from records where kind=? order by id desc',(kind,)).fetchall() if kind else conn.execute('select * from records order by id desc').fetchall()
    return [dict(r) for r in data]
@app.get('/api/health')
def health(): return {'ok': True, 'app': APP_NAME, 'records': len(rows())}
@app.get('/', response_class=HTMLResponse)
def home(): return INDEX_HTML

class ExpenseRequest(BaseModel):
    description: str
    amount: float
    date: str = Field(default_factory=lambda: date.today().isoformat())
def category(desc: str) -> str:
    d=desc.lower()
    if any(w in d for w in ['vercel','github','domain','hosting','aws','railway']): return 'Developer Tools'
    if any(w in d for w in ['uber','gas','flight','hotel']): return 'Travel'
    if any(w in d for w in ['restaurant','coffee','food']): return 'Meals'
    if any(w in d for w in ['course','book','school','training']): return 'Education'
    return 'General'
@app.post('/api/expenses')
def add_expense(req: ExpenseRequest):
    payload=req.model_dump(); payload['category']=category(req.description); payload['anomaly']=abs(req.amount) > 500
    expense_id=save_record('expense', req.description, json.dumps(payload)); return {'id': expense_id, **payload}
@app.post('/api/import.csv')
async def import_csv(file: UploadFile = File(...)):
    text=(await file.read()).decode('utf-8', errors='ignore'); reader=csv.DictReader(io.StringIO(text)); imported=[]; skipped=0
    for row in reader:
        desc=row.get('description') or row.get('Description') or row.get('memo') or 'Expense'
        try: amt=float(str(row.get('amount') or row.get('Amount') or 0).replace('$','').replace(',','').strip() or 0)
        except ValueError: skipped += 1; continue
        imported.append(add_expense(ExpenseRequest(description=desc, amount=amt, date=row.get('date') or row.get('Date') or date.today().isoformat())))
    return {'imported': len(imported), 'skipped': skipped, 'expenses': imported}
@app.get('/api/summary')
def summary():
    items=[json.loads(r['payload']) for r in rows('expense')]; by_cat=defaultdict(float); total=0.0; anomalies=[]
    for item in items:
        total += item['amount']; by_cat[item['category']] += item['amount']
        if item.get('anomaly'): anomalies.append(item)
    return {'total': round(total,2), 'by_category': {k: round(v,2) for k,v in by_cat.items()}, 'anomalies': anomalies, 'count': len(items)}

INDEX_HTML='<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Expense Tracker</title><style>body{font-family:Inter,Arial,sans-serif;background:#0f172a;color:#e5e7eb;margin:0}main{max-width:980px;margin:auto;padding:32px}.card{background:#111827;border:1px solid #334155;border-radius:18px;padding:24px;margin:18px 0}h1{font-size:42px}textarea,input{width:100%;box-sizing:border-box;border-radius:12px;border:1px solid #475569;background:#020617;color:#e5e7eb;padding:14px;margin:8px 0}button{background:#22c55e;color:#04130a;border:0;border-radius:12px;padding:12px 18px;font-weight:700}pre{white-space:pre-wrap;background:#020617;border-radius:12px;padding:16px}.pill{background:#1e293b;border:1px solid #475569;border-radius:999px;padding:6px 10px}</style></head><body><main><div class="card"><span class="pill">finance automation</span><h1>Expense Tracker</h1><p>Import CSV expenses, auto-categorize spending, detect anomalies, and export monthly insights.</p><ul><li>CSV expense import</li><li>Auto categorization</li><li>Budget summary dashboard</li><li>Anomaly detection</li><li>Monthly spending summary</li></ul></div><div class="card"><h2>Live API Demo</h2><textarea id="input" rows="7">GitHub Pro subscription</textarea><input id="input2" type="number" value="4" /><button onclick="runDemo()">Run Demo</button><pre id="out">Click Run Demo to call the FastAPI backend.</pre></div><div class="card"><h2>API</h2><p>Health: <code>/api/health</code> · Docs: <code>/docs</code></p></div><script>async function runDemo(){const res = await (fetch(\'/api/expenses\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({description:document.getElementById(\'input\').value,amount:Number(document.getElementById(\'input2\').value||42)})})); const data = await res.json(); document.getElementById(\'out\').textContent = JSON.stringify(data,null,2);}</script></main></body></html>'
