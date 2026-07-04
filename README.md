# Expense Tracker

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite)

Import CSV bank exports, auto-categorize transactions, spot anomalies, and export monthly spending summaries. No AI — just deterministic rules and category matching that you can inspect and adjust.

## Features

- CSV import from bank or credit card exports
- Rule-based auto-categorization (groceries, dining, utilities, transportation, entertainment, health, shopping, income, and custom labels)
- Monthly budget summary dashboard
- Anomaly detection flagged on unusual amounts or frequency
- CSV export of categorized data for bookkeeping

## Tech Stack

- Python 3.11+ / FastAPI / SQLite
- Vanilla HTML/CSS/JS frontend served by the API
- Pytest

## Quick Start

```bash
uv sync
uv run uvicorn src.main:app --reload --port 8106
```

Open: http://localhost:8106

Windows: double-click `run.bat`

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Browser demo UI |
| GET | `/api/health` | Health check |
| GET | `/docs` | Interactive API docs |

## Tests

```bash
uv run pytest -q
```
