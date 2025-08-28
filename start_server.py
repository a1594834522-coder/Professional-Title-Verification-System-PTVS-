#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强的服务器启动脚本
解决网络选择器和线程问题
"""

import os
import sys
import time
import socket
import signal
import platform
import subprocess
from pathlib import Path

def check_port_available(host, port):
    """检查端口是否可用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex((host, port))
            return result != 0
    except Exception:
        return False

def find_available_port(start_port=5000, max_attempts=10):
    """查找可用端口"""
    for port in range(start_port, start_port + max_attempts):
        if check_port_available('127.0.0.1', port):
            return port
    return None

def setup_environment():
    """设置环境变量和编码"""
    # 设置控制台编码
    if platform.system() == 'Windows':
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        try:
            # Windows控制台UTF-8支持
            subprocess.run(['chcp', '65001'], capture_output=True)
        except:
            pass
    
    # 设置Flask环境
    os.environ.setdefault('FLASK_APP', 'app.py')
    os.environ.setdefault('FLASK_ENV', 'production')

def graceful_shutdown(signum, frame):
    """优雅关闭服务器"""
    print(f"\n🛑 接收到关闭信号 {signum}")
    print("🔄 正在优雅关闭服务器...")
    sys.exit(0)

def main():
    """主启动函数"""
    print("🚀 职称评审材料交叉检验系统启动脚本")
    print("=" * 50)
    
    # 设置信号处理
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    
    # 检查工作目录
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    print(f"📁 工作目录: {script_dir}")
    
    # 设置环境
    setup_environment()
    
    # 检查依赖文件
    required_files = ['app.py', 'cross_validator.py', 'requirements.txt']
    missing_files = [f for f in required_files if not Path(f).exists()]
    
    if missing_files:
        print(f"❌ 缺少必要文件: {', '.join(missing_files)}")
        return 1
    
    # 查找可用端口
    port = find_available_port()
    if not port:
        print("❌ 无法找到可用端口 (5000-5009)")
        return 1
    
    print(f"🌐 使用端口: {port}")
    
    # 导入并启动Flask应用
    try:
        # 动态导入以避免循环导入
        sys.path.insert(0, str(script_dir))
        
        print("📦 加载应用模块...")
        from app import app
        
        print("🔧 配置应用设置...")
        app.config.update({
            'TESTING': False,
            'DEBUG': False,
            'PROPAGATE_EXCEPTIONS': True,
            'TRAP_HTTP_EXCEPTIONS': False,
            'MAX_CONTENT_LENGTH': 200 * 1024 * 1024,  # 200MB
        })
        
        print("🌐 启动Web服务器...")
        print(f"   本地访问: http://127.0.0.1:{port}")
        print(f"   局域网访问: http://0.0.0.0:{port}")
        print("   按 Ctrl+C 停止服务器")
        print("=" * 50)
        
        # 启动服务器
        app.run(
            host='0.0.0.0',
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False,
            use_debugger=False,
            use_evalex=False,
            passthrough_errors=False
        )
        
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("💡 请确保安装了所有依赖: pip install -r requirements.txt")
        return 1
        
    except OSError as e:
        print(f"❌ 网络错误: {e}")
        print("💡 解决建议:")
        print("   1. 检查防火墙设置")
        print("   2. 尝试以管理员身份运行")
        print("   3. 检查是否有其他程序占用端口")
        return 1
        
    except KeyboardInterrupt:
        print(f"\n👋 用户中断，服务器已停止")
        return 0
        
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)