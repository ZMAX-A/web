@echo off
chcp 65001 >nul
title 生成颜佳AI Allure测试报告

if not exist "reports\allure-results" (
    echo 未找到 reports\allure-results，请先执行测试。
    pause
    exit /b 1
)

where allure >nul 2>&1
if errorlevel 1 (
    echo 未找到 Allure CLI，请先安装 Allure。
    pause
    exit /b 1
)

allure generate reports\allure-results -o reports\allure-report --clean
if errorlevel 1 (
    echo 报告生成失败。
    pause
    exit /b 1
)

echo 报告已生成：reports\allure-report

echo.
echo 归档本次报告到 reports\history\...
call .venv\Scripts\python.exe utils\archive_report.py

call .venv\Scripts\python.exe utils\serve_report.py