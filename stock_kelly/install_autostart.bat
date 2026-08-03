@echo off
chcp 65001 >nul
title 股票凯利分析器 - 安装开机自启动

echo ============================================
echo   股票凯利分析器 - 安装开机自启动
echo ============================================
echo.

REM 获取当前脚本所在目录
set "SCRIPT_DIR=%~dp0"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo [信息] 项目目录: %SCRIPT_DIR%
echo [信息] 启动目录: %STARTUP_DIR%
echo.

REM 检查启动目录是否存在
if not exist "%STARTUP_DIR%" (
    echo [错误] 启动目录不存在
    pause
    exit /b 1
)

REM 创建启动脚本（使用vbs隐藏窗口）
echo [创建] 正在创建开机自启动脚本...

(
echo Set WshShell = CreateObject("WScript.Shell"^)
echo WshShell.CurrentDirectory = "%SCRIPT_DIR%"
echo WshShell.Run "python app.py", 0, False
) > "%STARTUP_DIR%\StockAnalyzer.vbs"

REM 创建一个bat版本作为备选
(
echo @echo off
echo cd /d "%SCRIPT_DIR%"
echo start /min python app.py
) > "%STARTUP_DIR%\StockAnalyzer.bat"

echo.
echo [成功] 开机自启动脚本已创建！
echo.
echo [位置] %STARTUP_DIR%\StockAnalyzer.vbs
echo.
echo [说明] 电脑重启后，股票分析服务器会自动启动
echo [说明] 无需手动运行任何脚本
echo.

REM 验证文件是否创建成功
if exist "%STARTUP_DIR%\StockAnalyzer.vbs" (
    echo [验证] ✓ VBS启动脚本已创建
) else (
    echo [验证] ✗ VBS启动脚本创建失败
)

if exist "%STARTUP_DIR%\StockAnalyzer.bat" (
    echo [验证] ✓ BAT启动脚本已创建
) else (
    echo [验证] ✗ BAT启动脚本创建失败
)

echo.
echo [提示] 如需取消开机自启动，请删除以下文件：
echo        %STARTUP_DIR%\StockAnalyzer.vbs
echo        %STARTUP_DIR%\StockAnalyzer.bat
echo.

pause