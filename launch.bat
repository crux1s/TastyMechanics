@echo off
REM ──────────────────────────────────────────────────────────────────────────
REM  TastyMechanics — Windows 11 launcher
REM  Double-click this file to start the Streamlit dashboard in your browser.
REM
REM  Requirements:
REM    - Python 3.10+ installed and on your PATH  (https://python.org)
REM    - Dependencies installed:  pip install -r requirements.txt
REM
REM  Optional: place a virtual environment named ".venv" or "venv" in the
REM  same folder as this file and it will be activated automatically.
REM ──────────────────────────────────────────────────────────────────────────

REM Change to the directory that contains this batch file
cd /d "%~dp0"

REM ── Virtual environment detection ────────────────────────────────────────
if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment: .venv
    call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment: venv
    call "venv\Scripts\activate.bat"
) else (
    echo No virtual environment found — using system Python.
)

REM ── Launch ────────────────────────────────────────────────────────────────
echo.
echo Starting TastyMechanics...  ^(press Ctrl+C in this window to stop^)
echo.
python -m streamlit run "tastymechanics.py"

REM ── Error handling ────────────────────────────────────────────────────────
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: TastyMechanics exited with code %ERRORLEVEL%.
    echo See the output above for details.
    echo.
    pause
)
