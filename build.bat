@echo off
chcp 65001 >nul 2>&1
echo ================================================
echo   BabelDOC AI 翻译工具 - 一键打包
echo ================================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python
    pause
    exit /b 1
)

REM 检查 PyInstaller
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [安装] 正在安装 PyInstaller...
    pip install pyinstaller
)

echo.
echo 选择打包模式:
echo   1. 单文件模式 (推荐，分发方便)
echo   2. 单目录模式 (启动更快)
echo   3. 使用 .spec 文件打包
echo   4. 清理并重新打包
echo.

set /p choice="请输入选项 (1/2/3/4): "

if "%choice%"=="1" (
    python build.py
) else if "%choice%"=="2" (
    python build.py --dir
) else if "%choice%"=="3" (
    python build.py --spec
) else if "%choice%"=="4" (
    python build.py --clean
) else (
    echo 无效选项，默认使用单文件模式
    python build.py
)

echo.
pause