@echo off
echo ===============================================
echo     防火墙配置 - 职称评审系统局域网访问
echo ===============================================
echo.

echo 正在配置Windows防火墙以允许局域网访问...
echo.

REM 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ 需要管理员权限！
    echo.
    echo 请以管理员身份运行此脚本：
    echo 1. 右键点击此批处理文件
    echo 2. 选择"以管理员身份运行"
    echo.
    pause
    exit /b 1
)

echo ✅ 管理员权限确认

echo.
echo 正在添加防火墙规则...

REM 删除可能存在的旧规则
netsh advfirewall firewall delete rule name="职称评审系统-TCP-5000" >nul 2>&1
netsh advfirewall firewall delete rule name="Python Flask App - Port 5000" >nul 2>&1

REM 添加新的防火墙规则
netsh advfirewall firewall add rule name="职称评审系统-TCP-5000" dir=in action=allow protocol=TCP localport=5000 profile=private,public
if %errorLevel% equ 0 (
    echo ✅ 防火墙规则添加成功
) else (
    echo ❌ 防火墙规则添加失败
    goto :error
)

echo.
echo 正在添加Python应用程序例外...

REM 查找Python可执行文件路径
for /f "tokens=*" %%i in ('where python 2^>nul') do set PYTHON_PATH=%%i

if defined PYTHON_PATH (
    echo 找到Python路径: %PYTHON_PATH%
    
    REM 删除可能存在的旧规则
    netsh advfirewall firewall delete rule name="Python-职称评审系统" >nul 2>&1
    
    REM 添加Python程序例外
    netsh advfirewall firewall add rule name="Python-职称评审系统" dir=in action=allow program="%PYTHON_PATH%" profile=private,public
    if %errorLevel% equ 0 (
        echo ✅ Python应用程序例外添加成功
    ) else (
        echo ⚠️ Python应用程序例外添加失败，但端口规则已生效
    )
) else (
    echo ⚠️ 未找到Python安装路径，仅配置端口规则
)

echo.
echo 正在验证配置...

REM 显示相关防火墙规则
echo 当前防火墙规则:
netsh advfirewall firewall show rule name="职称评审系统-TCP-5000"

echo.
echo ===============================================
echo              配置完成
echo ===============================================
echo ✅ 防火墙已配置完成
echo ✅ 端口5000已开放用于局域网访问
echo ✅ Python应用程序已添加到例外列表
echo.
echo 🌐 现在您可以：
echo    1. 启动职称评审系统: python app.py
echo    2. 从局域网其他设备访问系统
echo    3. 使用显示的局域网IP地址访问
echo.
echo 📱 移动设备访问步骤：
echo    1. 连接到同一WiFi网络
echo    2. 打开浏览器
echo    3. 输入: http://[显示的IP地址]:5000
echo.
echo 🔧 如需撤销配置，可以运行:
echo    netsh advfirewall firewall delete rule name="职称评审系统-TCP-5000"
echo.
goto :end

:error
echo.
echo ===============================================
echo              配置失败
echo ===============================================
echo ❌ 防火墙配置失败！
echo.
echo 可能的解决方案：
echo 1. 确保以管理员身份运行此脚本
echo 2. 检查Windows防火墙服务是否正在运行
echo 3. 手动在控制面板中配置防火墙例外
echo.
echo 手动配置步骤：
echo 1. 打开控制面板 → 系统和安全 → Windows Defender防火墙
echo 2. 点击"允许应用或功能通过Windows Defender防火墙"
echo 3. 点击"更改设置" → "允许其他应用"
echo 4. 浏览并选择Python.exe
echo 5. 确保"专用"和"公用"都勾选
echo.

:end
echo 按任意键退出...
pause >nul