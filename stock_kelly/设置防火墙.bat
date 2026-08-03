@echo off
chcp 65001 >nul
title 配置股票分析服务器防火墙

echo ================================================
echo   股票凯利分析器 - 防火墙配置
echo ================================================
echo.

rem 请求管理员权限
net session >nul 2>&1
if %time% neq 0 (
    echo [提示] 需要管理员权限，正在请求提权...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo [操作] 正在添加防火墙规则...

rem 删除旧规则（如果存在）
netsh advfirewall firewall delete rule name="股票分析服务器" dir=in 2>nul

rem 添加新规则
netsh advfirewall firewall add rule name="股票分析服务器" dir=in action=allow protocol=tcp localport=5000

if %errorlevel% equ 0 (
    echo [成功] 防火墙规则已添加！
    echo.
    echo [信息] 现在局域网内其他设备可以通过以下地址访问：
    echo         http://172.22.205.154:5000
) else (
    echo [失败] 防火墙规则添加失败，请手动添加
)

echo.
pause