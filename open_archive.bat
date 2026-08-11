@echo off
chcp 65001 >nul
title 查看历史归档报告
color 0B

echo ╔════════════════════════════════════════╗
echo ║     颜佳AI · 历史归档报告查看器        ║
echo ╚════════════════════════════════════════╝
echo.
call .venv\Scripts\python.exe utils\serve_archive.py

pause
