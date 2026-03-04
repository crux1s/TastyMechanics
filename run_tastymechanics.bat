@echo off
SETLOCAL EnableDelayedExpansion

echo Checking for Python...
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Python not found. Please install Python 3.9 or higher and add it to your PATH.
    pause
    exit /b 1
)

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Activating virtual environment...
call .venv\Scripts\activate

echo Checking/Installing dependencies...
pip install -r requirements.txt

echo Starting TastyMechanics...
streamlit run tastymechanics.py

pause
