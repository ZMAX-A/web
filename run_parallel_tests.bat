@echo off
setlocal
cd /d "%~dp0"

title YanJiaAI Parallel Test Runner
color 0B

echo ================================================
echo    YanJiaAI Web - Parallel Test Runner
echo    Worker A and Worker B will run concurrently
echo ================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python was not found. Install Python and add it to PATH.
        goto :error
    )
    python -m venv .venv
    if errorlevel 1 goto :error
)

echo Checking pinned dependencies...
call ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt -q
if errorlevel 1 goto :error

echo Checking Playwright Chromium...
if not exist "%LOCALAPPDATA%\ms-playwright\chromium-1223" (
    call ".venv\Scripts\python.exe" -m playwright install chromium
    if errorlevel 1 goto :error
) else (
    echo Chromium is already installed.
)

if not exist ".env" (
    echo .env was not found. Copying .env.example...
    copy ".env.example" ".env" >nul
    echo Configure account A and account B in .env, then run this file again.
    pause
    exit /b 2
)

echo.
call ".venv\Scripts\python.exe" "run_parallel_tests.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Parallel test run completed successfully.
) else (
    echo Test run finished with exit code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%

:error
echo Environment initialization failed. Review the error above.
pause
exit /b 1
