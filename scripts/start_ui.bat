@echo off
rem Starts the Streamlit UI. The API must already be running (scripts\start_api_local.bat).

cd /d "%~dp0\.."

where uv >nul 2>nul
if errorlevel 1 (
    echo uv was not found on PATH. See README "Getting started" or use: py -m uv
    pause
    exit /b 1
)

if "%PODC_API_URL%"=="" set PODC_API_URL=http://localhost:8000

echo Starting the UI at http://localhost:8501  (API: %PODC_API_URL%)
echo Close this window to stop it.
uv run --group ui streamlit run ui/streamlit_app.py --server.port 8501
pause
