@echo off
REM DeepTutor Backend Startup Script
REM Activates virtual environment and starts the backend API server

REM Move to the project root (this script lives in scripts/)
cd /d "%~dp0.."

REM Set UTF-8 encoding for stdout to support emoji characters
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo Activating Python virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment. Make sure .venv exists.
    pause
    exit /b 1
)

echo Starting DeepTutor Backend Server...
echo Backend will be available at: http://localhost:8001
echo Press Ctrl+C to stop the server.
python -m deeptutor.api.run_server
pause
