# MemTrace G0 API

Day 1 backend for the process-local G0 Agent loop. It exposes health/readiness,
task creation and snapshots, ordered SSE events, deterministic Mock streaming,
the DeepSeek adapter, and the non-executing `python_ast_check` tool. Day 1 has
no database or long-term memory; restarting the process clears every task.

## Local setup (PowerShell)

Run from `apps/api` with Python 3.11:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m uvicorn memtrace_api.main:app --app-dir src --reload
```

The service reads configuration from the repository-root `.env`, independent
of the shell's current directory. Copy `.env.example` to `.env` and keep real
secrets only in `.env`; Git ignores that file.

## Verification

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m pytest -W error
```

From the repository root, validate every normative schema and fixture:

```powershell
.\apps\api\.venv\Scripts\python.exe scripts\day1\validate_fixtures.py
```

Export the deterministic OpenAPI document from `apps/api` with:

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py
```

The AST tool only calls `ast.parse`; it never executes code, starts a shell,
writes user files, or accesses the network.
