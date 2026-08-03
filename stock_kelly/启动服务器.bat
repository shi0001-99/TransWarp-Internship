@echo off
chcp 65001 >nul
title 股票凯利分析器 - 启动

cd /d "%~dp0"
python start_server.py
pause
