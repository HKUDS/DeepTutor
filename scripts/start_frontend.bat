@echo off
REM Starts the frontend Vite development server
REM Prerequisites: Node.js 20+ installed, `cd frontend && npm install`

echo Starting DeepTutor Frontend...
echo Frontend will be available at: http://localhost:3782
echo.

cd /d "%~dp0..\frontend"
npm run dev -- --host 0.0.0.0 --port 3782
