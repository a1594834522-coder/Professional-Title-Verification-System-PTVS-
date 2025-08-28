@echo off
REM Celery启动脚本 - Windows版本

echo 启动异步队列系统...

REM 检查Redis是否运行
echo 检查Redis服务状态...
redis-cli ping >nul 2>&1
if %errorlevel% neq 0 (
    echo 警告: Redis服务未运行，请先启动Redis服务
    echo 可以使用以下命令启动Redis:
    echo   redis-server
    echo.
    pause
    exit /b 1
)

REM 设置环境变量
set PYTHONPATH=%~dp0

REM 启动Celery Worker
echo 启动Celery Worker...
python start_worker.py

pause