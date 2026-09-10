@echo off
setlocal EnableExtensions

REM Double-click launcher for DeepTutor on Windows.
REM Keep this window open while DeepTutor is running so Ctrl+C stops the app.

cd /d "%~dp0" || (
    echo ERROR: Failed to switch to the DeepTutor project directory.
    pause
    exit /b 1
)

set "PROJECT_DIR=%CD%"
set "PYTHON="
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo Starting DeepTutor...
echo Workspace: "%PROJECT_DIR%"

REM Prefer the project virtual environment when it is available.
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)

REM Run the source checkout with its own Python installation when possible.
if defined PYTHON (
    "%PYTHON%" -c "import deeptutor_cli.main" >nul 2>&1
    if not errorlevel 1 goto :start_with_python
)

REM Fall back to an installed `deeptutor` command on PATH.
where deeptutor >nul 2>&1
if not errorlevel 1 goto :start_with_command

echo.
echo ERROR: DeepTutor was not found or its Python dependencies are not installed.
echo Install the dependencies first, for example:
echo   py -3.11 -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -e .
echo   cd web ^&^& npm ci --legacy-peer-deps
set "EXIT_CODE=1"
goto :done

:start_with_python
"%PYTHON%" -m deeptutor_cli.main start --home "%PROJECT_DIR%" %*
set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:start_with_command
call deeptutor start --home "%PROJECT_DIR%" %*
set "EXIT_CODE=%ERRORLEVEL%"

:done
echo.
if not "%EXIT_CODE%"=="0" echo DeepTutor exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
