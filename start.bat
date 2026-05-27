@echo off
chcp 65001 >nul 2>&1
title AI 改卷系统
cd /d "%~dp0"

:: 检查 Python 是否可用
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查依赖是否已安装，未安装则自动安装
python -c "import flask, openai, selenium" >nul 2>&1
if errorlevel 1 (
    echo 首次运行，正在安装依赖...
    pip install flask openai selenium Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
    echo 依赖安装完成！
    echo.
)

:: 启动服务
python app.py
pause
