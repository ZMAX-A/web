@echo off
title YanJiaAI - Playwright Browser Installer
color 0E

echo ================================================
echo    YanJiaAI - Playwright Manual Install Tool
echo ================================================
echo.
echo This tool helps you install Chromium browser for Playwright
echo Download ~150MB, keep network connected
echo.

if not exist ".venv\Scripts\python.exe" (
    echo venv not found! Run run_tests.bat first
    pause
    exit /b 1
)

:retry
echo Installing Chromium browser...
echo.

echo [Method 1] python -m playwright install chromium
call .venv\Scripts\python.exe -m playwright install chromium
if %errorlevel% equ 0 goto :success

echo.
echo [Method 2] Try mirror...
set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
call .venv\Scripts\python.exe -m playwright install chromium
if %errorlevel% equ 0 goto :success

echo.
echo [Method 3] Try Azure mirror...
set PLAYWRIGHT_DOWNLOAD_HOST=https://playwright.azureedge.net
call .venv\Scripts\python.exe -m playwright install chromium
if %errorlevel% equ 0 goto :success

echo.
echo All methods failed.
echo.
echo Possible solutions:
echo   1. Use VPN/proxy then retry
echo   2. Try mobile hotspot
echo   3. Set proxy manually:
echo      set HTTPS_PROXY=http://127.0.0.1:your-proxy-port
echo      .venv\Scripts\python.exe -m playwright install chromium
echo.
echo Press R to retry, any other key to exit.
echo.
choice /c RrN /n /m "Press R to retry: " >nul
if errorlevel 1 goto :retry

pause
exit /b 1

:success
echo.
echo ================================================
echo      Chromium installed successfully!
echo ================================================
echo.
echo Now run run_tests.bat to start testing
echo.
pause
