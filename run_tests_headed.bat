@echo off
title YanJiaAI Test Runner - Headed Mode
color 0A

echo ================================================
echo      YanJiaAI Web - Headed Mode Test
echo        Browser will be visible
echo ================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating venv...
    python -m venv .venv
)

echo Checking pinned dependencies...
call .venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt -q
if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
)

echo Checking Playwright Chromium...
call .venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 (
    echo Chromium installation failed. Run install_playwright.bat for mirror options.
    pause
    exit /b 1
)

if not exist ".env" (
    echo .env not found, copying from template...
    copy .env.example .env >nul
)

if not exist "reports" mkdir reports >nul 2>&1
if not exist "screenshots" mkdir screenshots >nul 2>&1

echo Running offline framework checks...
call .venv\Scripts\python.exe -m pytest unit_tests -q -o "addopts="
if errorlevel 1 (
    echo Framework checks failed; E2E tests were not started.
    pause
    exit /b 1
)

echo Running tests (headed mode)...
echo.

call .venv\Scripts\pytest.exe tests/test_core_cases.py ^
    --headed ^
    --alluredir=reports/allure-results ^
    -v --tb=short --color=yes

set EXIT_CODE=%errorlevel%

echo.
if %EXIT_CODE% equ 0 (
    echo All tests passed!
) else (
    echo %EXIT_CODE% test(s) failed, check details above.
)

echo.
echo Generating Allure report...
allure generate reports/allure-results -o reports/allure-report --clean >nul 2>&1
if %errorlevel% equ 0 (
    echo Allure report generated: reports/allure-report
    start http://localhost:8899
    start /b .venv\Scripts\python.exe -m http.server 8899 -d reports\allure-report
    echo Report server started: http://localhost:8899
) else (
    echo Allure CLI not found, install with: npm install -g allure-commandline
)

echo.
pause
exit /b %EXIT_CODE%
