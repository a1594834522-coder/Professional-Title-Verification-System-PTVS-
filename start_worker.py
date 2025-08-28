#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Celery Worker启动脚本
用于启动异步任务处理器
"""

import os
import sys
import logging
# 【修改1】: 导入Celery的主命令入口，而不是worker子命令
from celery.bin.celery import celery as celery_main_command

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def start_worker():
    """启动Celery worker"""
    # 这一行保留，确保 celery_app 在Python路径中是可导入的
    from celery_app import celery_app
    
    # 【修改2】: 重新组织参数列表，模拟正确的命令行结构
    # 全局选项 (-A 或 --app) 必须在子命令 'worker' 之前
    # 使用 -A celery_app 更简洁，Celery会自动寻找app实例
    worker_args = [
        '-A', 'celery_app',
        'worker',
        '--loglevel=info',
        '--concurrency=4',
        '--queues=pdf_extraction,file_processing,validation',
        '--hostname=worker@%h',
        '--max-tasks-per-child=50',
        '--time-limit=600',
        '--soft-time-limit=300',
    ]
    
    # Windows下需要设置线程池
    if os.name == 'nt':
        worker_args.extend(['--pool=threads'])
    
    print("启动Celery Worker...")
    # 为了清晰，我们在打印的参数前加上 'celery'
    print(f"执行命令: celery {' '.join(worker_args)}")
    
    # 【修改3】: 调用Celery的主命令入口的 .main() 方法
    celery_main_command.main(worker_args)

if __name__ == '__main__':
    start_worker()