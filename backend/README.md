# CLEARGATE Backend

FastAPI backend for the CLEARGATE anonymization gateway.

## Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
```

## Run

```powershell
uvicorn app.main:app --reload --port 8000
```

Health check: `http://localhost:8000/health`

## Test

```powershell
pytest -v
```
