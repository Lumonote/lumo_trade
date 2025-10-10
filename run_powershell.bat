@echo off
REM Kronos PowerShell执行脚本
REM 确保正确的编码设置

chcp 65001 >nul
setlocal EnableDelayedExpansion

REM 获取脚本所在目录
set "SCRIPT_DIR=%~dp0"

REM 检查PowerShell文件是否存在
if exist "%SCRIPT_DIR%quick_start.ps1" (
    echo 执行PowerShell脚本...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%quick_start.ps1" %*
) else if exist "%SCRIPT_DIR%quick_start.bat" (
    echo 执行批处理脚本...
    call "%SCRIPT_DIR%quick_start.bat" %*
) else (
    echo 错误: 未找到启动脚本
    pause
    exit /b 1
)

pause
