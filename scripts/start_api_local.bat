@echo off
rem Starts the API for local work: SQLite instead of Postgres, uploads read inline (no Redis).
rem Run from anywhere; it always works from the repository root.

cd /d "%~dp0\.."

set PODC_DATABASE_URL=sqlite:///local.db
set PODC_INGEST_INLINE=true

where uv >nul 2>nul
if errorlevel 1 (
    echo uv was not found on PATH. See README "Getting started" or use: py -m uv
    pause
    exit /b 1
)

echo Preparing the local database (local.db)...
uv run alembic upgrade head
if errorlevel 1 (
    echo Database setup failed. Read the message above.
    pause
    exit /b 1
)

echo Starting the API at http://localhost:8000  (API docs: http://localhost:8000/docs)
echo Close this window to stop it.
uv run uvicorn app.main:app --reload --port 8000
pause
