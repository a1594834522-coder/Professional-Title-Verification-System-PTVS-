#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统初始化脚本
帮助用户快速设置数据库、缓存和其他配置
"""

import os
import sys
from pathlib import Path

def setup_environment():
    """设置环境和依赖"""
    print("🔧 正在检查系统环境...")
    
    # 检查Python版本
    if sys.version_info < (3, 10):
        print("⚠️ 建议使用Python 3.10或更高版本")
    else:
        print(f"✅ Python版本: {sys.version}")
    
    # 检查必要的模块
    required_modules = [
        'flask', 'pypdf', 'pandas', 'openpyxl', 
        'python-dotenv', 'markdown', 'markupsafe'
    ]
    
    missing_modules = []
    for module in required_modules:
        try:
            __import__(module.replace('-', '_'))
            print(f"✅ {module}")
        except ImportError:
            missing_modules.append(module)
            print(f"❌ {module} - 缺失")
    
    if missing_modules:
        print(f"\n📦 请安装缺失的模块:")
        print(f"pip install {' '.join(missing_modules)}")
        return False
    
    return True

def setup_database():
    """初始化数据库"""
    print("\n📊 正在初始化数据库...")
    
    try:
        from database_manager import DatabaseManager
        
        # 初始化数据库
        db_manager = DatabaseManager(
            progress_callback=lambda msg: print(f"[DB] {msg}")
        )
        
        print("✅ 数据库初始化完成")
        return True
        
    except Exception as e:
        print(f"❌ 数据库初始化失败: {e}")
        return False

def setup_cache():
    """设置缓存系统"""
    print("\n💾 正在设置缓存系统...")
    
    try:
        from cache_manager import SmartCacheManager
        
        # 初始化缓存管理器
        cache_manager = SmartCacheManager(
            progress_callback=lambda msg: print(f"[Cache] {msg}")
        )
        
        print("✅ 缓存系统设置完成")
        return True
        
    except Exception as e:
        print(f"❌ 缓存系统设置失败: {e}")
        return False

def check_api_keys():
    """检查API密钥配置"""
    print("\n🔑 正在检查API密钥配置...")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    # 检查各种API密钥配置方式
    api_keys_found = []
    
    # 检查批量配置
    batch_keys = os.environ.get('GOOGLE_API_KEYS')
    if batch_keys:
        keys_count = len([k for k in batch_keys.replace('\n', ',').split(',') if k.strip()])
        api_keys_found.append(f"GOOGLE_API_KEYS: {keys_count} 个密钥")
    
    # 检查单个配置
    single_key = os.environ.get('GOOGLE_API_KEY')
    if single_key:
        if ',' in single_key:
            keys_count = len([k for k in single_key.split(',') if k.strip()])
            api_keys_found.append(f"GOOGLE_API_KEY: {keys_count} 个密钥（逗号分隔）")
        else:
            api_keys_found.append("GOOGLE_API_KEY: 1 个密钥")
    
    # 检查分别配置
    i = 2
    individual_keys = 0
    while os.environ.get(f'GOOGLE_API_KEY_{i}'):
        individual_keys += 1
        i += 1
    
    if individual_keys > 0:
        api_keys_found.append(f"GOOGLE_API_KEY_2~{i-1}: {individual_keys} 个密钥")
    
    if api_keys_found:
        print("✅ 发现API密钥配置:")
        for config in api_keys_found:
            print(f"   {config}")
        return True
    else:
        print("❌ 未找到API密钥配置")
        print("💡 请在.env文件中配置API密钥:")
        print("   GOOGLE_API_KEY=your_api_key_here")
        print("   或者")
        print("   GOOGLE_API_KEYS=key1,key2,key3")
        return False

def check_optional_features():
    """检查可选功能"""
    print("\n🔍 正在检查可选功能...")
    
    # 检查Redis
    try:
        import redis
        redis_url = os.environ.get('REDIS_URL')
        if redis_url:
            print("✅ Redis缓存: 已配置")
        else:
            print("ℹ️ Redis缓存: 未配置（可选）")
    except ImportError:
        print("ℹ️ Redis缓存: 未安装（可选）")
    
    # 检查缓存目录
    cache_dir = os.environ.get('CACHE_DIR', './cache')
    if Path(cache_dir).exists():
        print(f"✅ 缓存目录: {cache_dir}")
    else:
        print(f"ℹ️ 缓存目录: 将自动创建 {cache_dir}")

def create_sample_env():
    """创建示例.env文件"""
    env_file = Path('.env')
    
    if env_file.exists():
        print("\n📝 .env文件已存在")
        return
    
    print("\n📝 正在创建示例.env文件...")
    
    sample_content = """# Google API配置（必需）
# 单个API密钥
GOOGLE_API_KEY=your_api_key_here

# 或者批量配置多个API密钥（用逗号分隔）
# GOOGLE_API_KEYS=key1,key2,key3

# 或者分别配置多个API密钥
# GOOGLE_API_KEY_2=your_second_api_key
# GOOGLE_API_KEY_3=your_third_api_key

# 数据库配置（可选）
# DATABASE_PATH=./database.db

# 缓存配置（可选）
# CACHE_DIR=./cache
# CACHE_MAX_AGE_HOURS=24
# CACHE_MAX_MEMORY_ITEMS=100
# CACHE_MAX_DISK_SIZE_MB=1000

# Redis缓存配置（可选）
# REDIS_URL=redis://localhost:6379/0

# Flask配置（可选）
# SECRET_KEY=your_secret_key_here
# FLASK_ENV=production
"""
    
    with open(env_file, 'w', encoding='utf-8') as f:
        f.write(sample_content)
    
    print(f"✅ 示例.env文件已创建: {env_file.absolute()}")
    print("💡 请编辑.env文件并添加您的API密钥")

def run_quick_test():
    """运行快速测试"""
    print("\n🧪 正在运行快速测试...")
    
    try:
        # 测试导入
        from cross_validator import CrossValidator
        from database_manager import DatabaseManager
        from cache_manager import SmartCacheManager
        
        print("✅ 所有模块导入成功")
        
        # 测试数据库连接
        db_manager = DatabaseManager()
        stats = db_manager.get_task_statistics()
        print(f"✅ 数据库连接正常，当前有 {stats.get('total_tasks', 0)} 个任务")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

def main():
    """主函数"""
    print("🚀 职称评审材料交叉检验系统 - 初始化向导")
    print("=" * 60)
    
    success_count = 0
    total_checks = 6
    
    # 1. 环境检查
    if setup_environment():
        success_count += 1
    
    # 2. 创建示例.env文件
    create_sample_env()
    
    # 3. 数据库初始化
    if setup_database():
        success_count += 1
    
    # 4. 缓存系统设置
    if setup_cache():
        success_count += 1
    
    # 5. API密钥检查
    if check_api_keys():
        success_count += 1
    
    # 6. 可选功能检查
    check_optional_features()
    success_count += 1  # 这个总是成功
    
    # 7. 快速测试
    if run_quick_test():
        success_count += 1
    
    print("\n" + "=" * 60)
    print(f"🎉 初始化完成! ({success_count}/{total_checks} 项成功)")
    
    if success_count == total_checks:
        print("✅ 系统已就绪，可以启动服务器了")
        print("💡 运行命令: python app.py 或 python start_server.py")
    else:
        print("⚠️ 部分配置需要完善，请检查上面的错误信息")
        print("💡 重要: 确保在.env文件中配置了有效的Google API密钥")
    
    print("\n📚 相关文档:")
    print("   - 缓存配置: CACHE_CONFIG.md")
    print("   - 数据库配置: DATABASE_GUIDE.md")
    print("   - 系统说明: README.md")

if __name__ == '__main__':
    main()