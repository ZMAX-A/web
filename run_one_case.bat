@echo off
title YanJiaAI - Run Single Test Case
color 0E

echo ================================================
echo      Run a Single Test Case (Headed Mode)
echo ================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run run_tests.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\python.exe -m pytest unit_tests -q -o "addopts="
if errorlevel 1 (
    echo Framework checks failed; the case was not started.
    pause
    exit /b 1
)
set /p CASE_ID="Enter Case ID (e.g. TC-DETAIL-004): "

if "%CASE_ID%"=="" (
    echo No input. Exiting.
    pause
    exit /b 1
)

echo.
echo ================================================
echo  Running: %CASE_ID%
echo ================================================
echo.

call .venv\Scripts\pytest.exe tests/test_core_cases.py -k "%CASE_ID%" --alluredir=reports/allure-results -v --tb=short --headed --slowmo 500
set EXIT_CODE=%errorlevel%

echo.
pause
exit /b %EXIT_CODE%
