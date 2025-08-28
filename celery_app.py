# -*- coding: utf-8 -*-
"""
Celery异步任务队列配置
用于替代现有的ThreadPoolExecutor，提供更强大的任务管理能力
"""

from celery import Celery
from kombu import Queue
import os
from datetime import timedelta

# Redis连接配置
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# 创建Celery应用
celery_app = Celery('pdf_processor')

# Celery配置
celery_app.conf.update(
    # Redis作为消息代理和结果后端
    broker_url=REDIS_URL,
    result_backend=REDIS_URL,
    
    # 任务序列化
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    
    # 时区设置
    timezone='Asia/Shanghai',
    enable_utc=True,
    
    # 任务结果过期时间
    result_expires=timedelta(hours=1),
    
    # 工作进程配置
    worker_prefetch_multiplier=1,  # 每个工作进程一次只处理一个任务
    task_acks_late=True,  # 任务完成后才确认
    worker_disable_rate_limits=False,
    
    # 队列配置 - 支持优先级
    task_routes={
        'pdf_processor.tasks.extract_pdf_content': {'queue': 'pdf_extraction'},
        'pdf_processor.tasks.cross_validate_materials': {'queue': 'validation'},
        'pdf_processor.tasks.process_single_file': {'queue': 'file_processing'},
    },
    
    # 定义队列和优先级
    task_queues=(
        # 高优先级队列 - PDF提取任务
        Queue('pdf_extraction', priority=9),
        # 中优先级队列 - 文件处理任务  
        Queue('file_processing', priority=5),
        # 低优先级队列 - 交叉验证任务
        Queue('validation', priority=1),
    ),
    
    # 任务优先级设置
    task_default_priority=5,
    worker_direct=True,
    
    # 重试配置
    task_default_retry_delay=60,  # 重试延迟60秒
    task_max_retries=3,
    
    # 任务超时配置
    task_soft_time_limit=300,  # 5分钟软超时
    task_time_limit=600,       # 10分钟硬超时
    
    # 监控配置
    worker_send_task_events=True,
    task_send_sent_event=True,
    
    # 内存管理
    worker_max_tasks_per_child=50,  # 每个工作进程最多处理50个任务后重启
    worker_max_memory_per_child=200000,  # 200MB内存限制
)

# 任务导入将在tasks.py中处理