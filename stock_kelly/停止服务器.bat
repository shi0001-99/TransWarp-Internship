@echo off
chcp 65001 >nul
title 股票凯利分析器 - 停止

cd /d "%~dp0"
python stop_server.py
pause
