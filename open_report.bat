@echo off
chcp 65001 >nul
title 颜佳AI 测试报告查看器
color 0B

echo ╔════════════════════════════════════════════╗
echo ║     颜佳AI Web端 · 自动化测试报告          ║
echo ║       一键查看上次测试结果                  ║
echo ╚════════════════════════════════════════════╝
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ❌ 未找到虚拟环境，请先运行 run_tests.bat 安装依赖
    pause
    exit /b 1
)

if not exist "reports\allure-results" (
    echo ❌ 未找到测试结果，请先运行 run_tests.bat 执行测试
    pause
    exit /b 1
)

echo ⏳ 正在启动报告服务器...
start http://localhost:8899
call .venv\Scripts\python.exe utils\serve_report.py

pause
