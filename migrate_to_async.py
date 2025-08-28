# -*- coding: utf-8 -*-
"""
迁移脚本 - 将现有ThreadPoolExecutor替换为异步队列
此脚本用于自动更新cross_validator.py中的线程池调用
"""

import re
import os
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

class AsyncMigrator:
    """异步队列迁移器"""
    
    def __init__(self):
        self.backup_suffix = '.backup'
    
    def migrate_cross_validator(self, file_path: str = 'cross_validator.py') -> bool:
        """
        迁移cross_validator.py文件
        
        Args:
            file_path: 文件路径
        
        Returns:
            bool: 迁移是否成功
        """
        try:
            # 读取原文件
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 创建备份
            backup_path = file_path + self.backup_suffix
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"已创建备份文件: {backup_path}")
            
            # 执行迁移
            migrated_content = self._perform_migration(content)
            
            # 写入迁移后的内容
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(migrated_content)
            
            logger.info(f"迁移完成: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"迁移失败: {e}")
            return False
    
    def _perform_migration(self, content: str) -> str:
        """执行具体的迁移操作"""
        
        # 1. 添加必要的导入
        content = self._add_imports(content)
        
        # 2. 替换ThreadPoolExecutor导入
        content = self._replace_imports(content)
        
        # 3. 替换ThreadPoolExecutor使用
        content = self._replace_thread_pool_usage(content)
        
        # 4. 添加异步队列配置检查
        content = self._add_queue_checks(content)
        
        return content
    
    def _add_imports(self, content: str) -> str:
        """添加异步队列相关导入"""
        
        # 查找import区域
        import_pattern = r'(import\s+.*?\n)+'
        
        # 要添加的导入
        new_imports = """
# 异步队列系统导入
try:
    from .async_adapter import AsyncThreadPoolExecutor, async_as_completed
    from .queue_manager import queue_manager
    from .load_balancer import load_balancer
    ASYNC_QUEUE_AVAILABLE = True
except ImportError:
    # 回退到原始ThreadPoolExecutor
    from concurrent.futures import ThreadPoolExecutor as AsyncThreadPoolExecutor
    from concurrent.futures import as_completed as async_as_completed
    ASYNC_QUEUE_AVAILABLE = False
    logger.warning("异步队列系统不可用，使用传统ThreadPoolExecutor")

"""
        
        # 在导入区域后添加新导入
        def add_after_imports(match):
            return match.group(0) + new_imports
        
        # 如果找到导入区域，在其后添加
        if re.search(import_pattern, content):
            content = re.sub(import_pattern, add_after_imports, content, count=1)
        else:
            # 如果没有找到导入区域，在文件开头添加
            content = new_imports + content
        
        return content
    
    def _replace_imports(self, content: str) -> str:
        """替换ThreadPoolExecutor导入"""
        
        # 替换concurrent.futures导入
        patterns = [
            (r'from concurrent\.futures import ThreadPoolExecutor', 
             '# from concurrent.futures import ThreadPoolExecutor  # 已替换为异步队列'),
            (r'from concurrent\.futures import ThreadPoolExecutor, as_completed',
             '# from concurrent.futures import ThreadPoolExecutor, as_completed  # 已替换为异步队列'),
            (r'import concurrent\.futures',
             'import concurrent.futures  # 保留用于类型标注')
        ]
        
        for pattern, replacement in patterns:
            content = re.sub(pattern, replacement, content)
        
        return content
    
    def _replace_thread_pool_usage(self, content: str) -> str:
        """替换ThreadPoolExecutor的使用"""
        
        # 模式1: with ThreadPoolExecutor(max_workers=N) as executor:
        pattern1 = r'with concurrent\.futures\.ThreadPoolExecutor\(max_workers=(\d+)\) as executor:'
        replacement1 = r'with AsyncThreadPoolExecutor(max_workers=\1) as executor:'
        content = re.sub(pattern1, replacement1, content)
        
        # 模式2: concurrent.futures.as_completed
        pattern2 = r'concurrent\.futures\.as_completed'
        replacement2 = 'async_as_completed'
        content = re.sub(pattern2, replacement2, content)
        
        # 模式3: 添加负载均衡检查
        pattern3 = r'(with AsyncThreadPoolExecutor\(max_workers=(\d+)\) as executor:)'
        def add_load_balancing(match):
            max_workers = match.group(2)
            return f"""# 检查系统负载并调整工作线程数
        if ASYNC_QUEUE_AVAILABLE and load_balancer.should_throttle_tasks():
            max_workers = max(1, {max_workers} // 2)
            self._log("系统负载较高，减少并发线程数")
        else:
            max_workers = {max_workers}
        
        {match.group(1).replace(max_workers, 'max_workers')}"""
        
        content = re.sub(pattern3, add_load_balancing, content)
        
        return content
    
    def _add_queue_checks(self, content: str) -> str:
        """添加队列系统检查"""
        
        # 在类初始化方法中添加队列检查
        init_pattern = r'(def __init__\(self.*?\):.*?\n)'
        
        def add_queue_init(match):
            return match.group(1) + """
        # 初始化异步队列系统
        self._queue_available = ASYNC_QUEUE_AVAILABLE
        if self._queue_available:
            self._log("异步队列系统已启用")
        else:
            self._log("使用传统线程池")
"""
        
        content = re.sub(init_pattern, add_queue_init, content, flags=re.DOTALL)
        
        return content
    
    def rollback_migration(self, file_path: str = 'cross_validator.py') -> bool:
        """回滚迁移"""
        backup_path = file_path + self.backup_suffix
        
        if not os.path.exists(backup_path):
            logger.error(f"备份文件不存在: {backup_path}")
            return False
        
        try:
            # 从备份恢复
            with open(backup_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"已从备份恢复: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"回滚失败: {e}")
            return False
    
    def validate_migration(self, file_path: str = 'cross_validator.py') -> List[str]:
        """验证迁移结果"""
        issues = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 检查必要的导入
            if 'AsyncThreadPoolExecutor' not in content:
                issues.append("缺少AsyncThreadPoolExecutor导入")
            
            if 'async_as_completed' not in content:
                issues.append("缺少async_as_completed导入")
            
            # 检查是否还有旧的ThreadPoolExecutor使用
            if re.search(r'concurrent\.futures\.ThreadPoolExecutor\(', content):
                issues.append("仍存在旧的ThreadPoolExecutor使用")
            
            # 检查语法
            try:
                compile(content, file_path, 'exec')
            except SyntaxError as e:
                issues.append(f"语法错误: {e}")
            
        except Exception as e:
            issues.append(f"验证过程出错: {e}")
        
        return issues

def main():
    """主函数 - 执行迁移"""
    logging.basicConfig(level=logging.INFO)
    
    migrator = AsyncMigrator()
    
    print("开始迁移到异步队列系统...")
    
    # 执行迁移
    success = migrator.migrate_cross_validator()
    
    if success:
        print("迁移完成！")
        
        # 验证迁移
        issues = migrator.validate_migration()
        if issues:
            print("验证发现问题:")
            for issue in issues:
                print(f"  - {issue}")
            
            # 询问是否回滚
            response = input("是否回滚迁移? (y/N): ")
            if response.lower() == 'y':
                migrator.rollback_migration()
                print("已回滚迁移")
        else:
            print("迁移验证通过！")
    else:
        print("迁移失败！")

if __name__ == '__main__':
    main()