# MemTrace API

Day 1 backend runtime skeleton. This step intentionally exposes only health and
readiness endpoints; task orchestration, tools, providers, and SSE are added in
the next implementation step.

## Local setup (PowerShell)

Run from `apps/api` with Python 3.11:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m uvicorn memtrace_api.main:app --app-dir src --reload
```

The service reads configuration from the repository-root `.env`, independent
of the shell's current directory. Copy `.env.example` to `.env` and keep real
secrets only in `.env`; Git ignores that file.

## Verification

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m pytest
```
