@echo off
setlocal enabledelayedexpansion
title IMS Agent — Starting Up
cd /d "%~dp0"

echo.
echo ============================================================
echo   IMS Agent Startup
echo ============================================================
echo.

REM ── 1. Python / venv ─────────────────────────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found at .venv\
    echo         Run:  python -m venv .venv
    echo               .venv\Scripts\activate.bat
    echo               pip install -r requirements.txt
    pause & exit /b 1
)
call .venv\Scripts\activate.bat
echo [OK]  Virtual environment active

REM ── 2. .env present ──────────────────────────────────────────
if not exist ".env" (
    echo [ERROR] .env file not found.
    echo         Copy .env.example to .env and fill in ANTHROPIC_API_KEY at minimum.
    pause & exit /b 1
)
echo [OK]  .env present

REM ── 3. IMS master file ───────────────────────────────────────
set MASTER_COUNT=0
for /f %%f in ('dir /b "data\ims_master\*.mpp" "data\ims_master\*.xml" 2^>nul') do set /a MASTER_COUNT+=1
if !MASTER_COUNT! EQU 0 (
    echo [INFO] data\ims_master\ is empty — seeding from sample_ims.xml ...
    python main.py --init-mpp
    if errorlevel 1 (
        echo [WARN] --init-mpp failed. The cycle will still run using data\sample_ims.xml directly.
        echo        Check that MS Project or the MPXJ/JVM backend is available.
    ) else (
        echo [OK]  Master IMS seeded.
    )
) else (
    echo [OK]  Master IMS present (!MASTER_COUNT! file^(s^))
)

REM ── 4. Open browser after server warms up ─────────────────────
echo.
echo [INFO] Starting scheduler + dashboard ...
echo [INFO] Dashboard will be at http://localhost:9000
echo [INFO] Press Ctrl+C to stop.
echo.

REM Open browser 8 seconds after server starts (background)
start /b cmd /c "timeout /t 8 >nul && start http://localhost:9000"

REM ── 5. Start scheduler + dashboard (foreground) ───────────────
python main.py --schedule

REM If we get here, the server stopped cleanly (Ctrl+C)
echo.
echo [INFO] IMS Agent stopped.
pause
