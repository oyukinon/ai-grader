@echo off
chcp 65001 >nul 2>&1
title AI Grader
cd /d "%~dp0"

:: ========== Find Python ==========
set "PYTHON_CMD="

:: Check known Python 3.14 path first (this machine)
if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
    goto :found
)
if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Python\bin\python.exe"
    goto :found
)

:: Check PATH
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto :found
)

:: Check other common paths
for %%V in (314 313 312 311 310 39) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        goto :found
    )
    if exist "C:\Python%%V\python.exe" (
        set "PYTHON_CMD=C:\Python%%V\python.exe"
        goto :found
    )
    if exist "C:\Program Files\Python%%V\python.exe" (
        set "PYTHON_CMD=C:\Program Files\Python%%V\python.exe"
        goto :found
    )
)

:: Not found
echo.
echo ========================================
echo   Python not found
echo ========================================
echo.
echo   Install Python 3.10+ from:
echo   https://www.python.org/downloads/
echo.
echo   Check "Add Python to PATH" during install
echo.
pause
exit /b 1

:found
echo [OK] Python found:
"%PYTHON_CMD%" --version
echo.

:: ========== Install deps ==
"%PYTHON_CMD%" -c "import flask, openai, selenium" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    "%PYTHON_CMD%" -m pip install flask openai selenium Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo.
        echo [Error] Failed to install dependencies
        pause
        exit /b 1
    )
    echo.
    echo Dependencies installed!
    echo.
)

:: ========== Start ==
echo Starting AI Grader...
"%PYTHON_CMD%" app.py
pause