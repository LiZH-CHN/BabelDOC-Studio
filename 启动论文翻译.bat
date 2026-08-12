@echo off
chcp 65001 >nul 2>&1
title BabelDOC AI 论文翻译工具

cd /d "E:\pdfTrans\BabelDOC"

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请安装 Python 3.10+
    pause
    exit /b 1
)

REM 启动 GUI
echo 正在启动 BabelDOC AI 论文翻译工具...
python main.py

if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出
    pause
)