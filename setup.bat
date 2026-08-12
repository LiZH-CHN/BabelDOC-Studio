@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   BabelDOC Studio - 一键环境配置
echo ============================================
echo.

REM 检查 Python 是否安装
echo [1/5] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未检测到 Python，请先安装 Python 3.12
    echo    下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
echo.

REM 检查 Python 版本是否为 3.12
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set pyver=%%i
echo 当前 Python 版本: !pyver!
echo.

REM 检查并安装 uv
echo [2/5] 检查 uv 工具...
uv --version >nul 2>&1
if errorlevel 1 (
    echo 📦 正在安装 uv...
    powershell -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 (
        echo ❌ uv 安装失败，请手动安装: https://github.com/astral-sh/uv#installation
        pause
        exit /b 1
    )
    echo ✅ uv 安装完成
) else (
    echo ✅ uv 已安装
)
uv --version
echo.

REM 创建虚拟环境并安装依赖
echo [3/5] 创建虚拟环境并安装依赖...
if exist ".venv" (
    echo ⚠️ 检测到已存在 .venv 虚拟环境
    choice /C YN /M "是否删除并重新创建"
    if errorlevel 2 (
        echo 跳过虚拟环境重建
        goto :skip_venv
    )
    rmdir /s /q .venv
)
uv venv --python 3.12
if errorlevel 1 (
    echo ❌ 虚拟环境创建失败
    pause
    exit /b 1
)
echo ✅ 虚拟环境创建完成
:skip_venv

echo [4/5] 同步依赖...
uv sync
if errorlevel 1 (
    echo ❌ 依赖安装失败
    pause
    exit /b 1
)
echo ✅ 依赖安装完成
echo.

REM 验证安装
echo [5/5] 验证安装...
.venv\Scripts\python -c "import babeldoc; print('✅ BabelDOC 导入成功')" 2>nul
if errorlevel 1 (
    echo ⚠️ BabelDOC 导入验证失败，请检查安装
) else (
    echo ✅ 所有组件验证通过
)
echo.

echo ============================================
echo 🎉 环境配置完成！
echo.
echo 启动方式:
echo   1. 开发模式:   .venv\Scripts\python main.py
echo   2. 运行 GUI:   .venv\Scripts\python -m BabelDOC_Studio
echo   3. 命令行:     .venv\Scripts\babeldoc --help
echo ============================================
pause