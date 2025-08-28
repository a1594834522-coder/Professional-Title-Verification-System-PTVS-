@echo off
chcp 65001 >nul
title 职称评审材料交叉检验系统

echo.
echo ==========================================
echo    职称评审材料交叉检验系统启动器
echo ==========================================
echo.

:: 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误：未找到Python，请先安装Python 3.10+
    echo 💡 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 显示Python版本
echo 🐍 Python版本：
python --version

:: 检查虚拟环境
if exist "venv\Scripts\activate.bat" (
    echo 📦 激活虚拟环境...
    call venv\Scripts\activate.bat
)

:: 检查依赖
echo 🔍 检查依赖文件...
if not exist "requirements.txt" (
    echo ❌ 缺少 requirements.txt 文件
    pause
    exit /b 1
)

if not exist "app.py" (
    echo ❌ 缺少 app.py 文件
    pause
    exit /b 1
)

:: 安装依赖（如果需要）
echo 📥 检查并安装依赖...
pip install -r requirements.txt >nul 2>&1

:: 检查环境变量文件
if not exist ".env" (
    echo ⚠️  警告：未找到 .env 文件
    echo 💡 请创建 .env 文件并添加 GOOGLE_API_KEY
    echo.
)

:: 系统选择菜单
echo.
echo 🚀 请选择操作：
echo 1. 首次设置（初始化系统）
echo 2. 标准启动（推荐）
echo 3. 增强启动脚本
echo 4. 直接启动app.py
echo 5. 数据库管理
echo 6. 查看系统状态
echo.
set /p choice="请选择 (1-6): "

if "%choice%"=="1" (
    echo 🔧 正在进行首次设置...
    python setup.py
    echo.
    echo 💡 设置完成后，请重新运行此脚本选择启动选项
    pause
) else if "%choice%"=="2" (
    echo 🌐 正在启动增强版服务器...
    python start_server.py
) else if "%choice%"=="3" (
    echo 🌐 正在启动增强版服务器...
    python start_server.py
) else if "%choice%"=="4" (
    echo 🌐 正在直接启动应用...
    python app.py
) else if "%choice%"=="5" (
    echo 📊 数据库管理工具
    echo 1. 查看统计信息
    echo 2. 备份数据库
    echo 3. 清理旧任务
    echo 4. 列出最近任务
    echo 5. 返回主菜单
    set /p db_choice="请选择数据库操作 (1-5): "
    
    if "!db_choice!"=="1" (
        python manage_database.py stats
    ) else if "!db_choice!"=="2" (
        python manage_database.py backup
    ) else if "!db_choice!"=="3" (
        python manage_database.py cleanup
    ) else if "!db_choice!"=="4" (
        python manage_database.py list
    ) else (
        echo 返回主菜单...
    )
    pause
    goto :eof
) else if "%choice%"=="6" (
    echo 🔍 系统状态检查...
    python setup.py
    pause
) else (
    echo 🌐 默认使用增强启动...
    python start_server.py
)

echo.
echo 👋 服务器已停止
pause