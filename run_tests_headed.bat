@echo off
chcp 65001 >nul
title 颜佳AI 全量测试（有头模式）
color 0E

echo ================================================
echo    颜佳AI Web - 全量测试（有头模式）
echo    浏览器窗口可见，请勿操作浏览器
echo ================================================
echo.
echo  注意：全量启用用例预计耗时较长，
echo        日常全量请用 run_tests.bat（无头更快）
echo.

if not exist ".venv\Scripts\python.exe" (
    echo 创建虚拟环境...
    python -m venv .venv
)

echo 检查依赖...
call .venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt -q
if errorlevel 1 (
    echo 依赖安装失败。
    pause
    exit /b 1
)

echo 检查 Playwright Chromium...
if not exist "%LOCALAPPDATA%\ms-playwright\chromium-1223" (
    call .venv\Scripts\python.exe -m playwright install chromium
    if errorlevel 1 (
        echo Chromium 安装失败。
        pause
        exit /b 1
    )
) else (
    echo Chromium 已安装，跳过。
)

if not exist ".env" (
    echo .env 不存在，从模板复制...
    copy .env.example .env >nul
)

if not exist "reports" mkdir reports >nul 2>&1
if not exist "screenshots" mkdir screenshots >nul 2>&1

echo 运行离线框架检查...
call .venv\Scripts\python.exe -m pytest unit_tests -q -o "addopts="
if errorlevel 1 (
    echo 框架检查失败，未启动 E2E 测试。
    pause
    exit /b 1
)

echo 开始全量测试（有头模式）...
echo.

call .venv\Scripts\pytest.exe tests/test_core_cases.py ^
    --headed ^
    --alluredir=reports/allure-results ^
    -v --tb=short --color=yes

set EXIT_CODE=%errorlevel%

echo.
if %EXIT_CODE% equ 0 (
    echo 全部通过！
) else (
    echo 有失败用例，退出码：%EXIT_CODE%
)

echo.
echo 生成 Allure 报告...
allure generate reports/allure-results -o reports/allure-report --clean
if %errorlevel% equ 0 (
    echo 报告已生成：reports\allure-report
    echo 归档本次报告...
    call .venv\Scripts\python.exe utils\archive_report.py
    start http://localhost:8899
    start /b .venv\Scripts\python.exe -m http.server 8899 -d reports\allure-report
    echo 报告服务器已启动：http://localhost:8899
) else (
    echo Allure CLI 未找到，请安装：npm install -g allure-commandline
)

echo.
pause
exit /b %EXIT_CODE%
