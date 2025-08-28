# -*- coding: utf-8 -*-
"""
负载均衡器 - 智能任务分发和资源管理
"""

import logging
import time
import psutil
import os
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, deque
from threading import Lock
import redis
try:
    from .celery_app import celery_app
except ImportError:
    from celery_app import celery_app

logger = logging.getLogger(__name__)

class LoadBalancer:
    """智能负载均衡器"""
    
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        self.redis_client = None
        self._worker_stats = defaultdict(dict)
        self._queue_stats = defaultdict(dict)
        self._task_history = defaultdict(deque)  # 任务执行历史
        self._stats_lock = Lock()
        
        # 负载均衡配置
        self.max_queue_length = 100
        self.max_cpu_usage = 80.0
        self.max_memory_usage = 85.0
        self.min_available_memory = 500  # MB
        
        # 任务权重配置
        self.task_weights = {
            'pdf_extraction': 3.0,    # PDF提取任务权重高
            'file_processing': 2.0,   # 文件处理中等权重
            'cross_validation': 1.5,  # 交叉验证较低权重
            'generic': 1.0           # 通用任务基础权重
        }
        
        self._init_redis_connection()
    
    def _init_redis_connection(self):
        """初始化Redis连接"""
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            self.redis_client.ping()
            logger.info("Redis连接初始化成功")
        except Exception as e:
            logger.warning(f"Redis连接失败: {e}")
            self.redis_client = None
    
    def select_optimal_queue(self, task_type: str, task_size: int = 1) -> Tuple[str, int]:
        """
        选择最优队列和优先级
        
        Args:
            task_type: 任务类型
            task_size: 任务大小估算
        
        Returns:
            Tuple[队列名, 优先级]
        """
        # 获取系统资源状态
        system_load = self._get_system_load()
        
        # 获取队列状态
        queue_loads = self._get_queue_loads()
        
        # 根据任务类型确定候选队列
        candidate_queues = self._get_candidate_queues(task_type)
        
        # 选择最优队列
        optimal_queue = self._select_best_queue(
            candidate_queues, queue_loads, system_load, task_type
        )
        
        # 计算动态优先级
        priority = self._calculate_dynamic_priority(
            task_type, system_load, queue_loads.get(optimal_queue, 0)
        )
        
        logger.debug(f"为任务类型 {task_type} 选择队列 {optimal_queue}，优先级 {priority}")
        return optimal_queue, priority
    
    def _get_system_load(self) -> Dict[str, float]:
        """获取系统负载信息"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # 获取进程信息
            current_process = psutil.Process()
            process_memory = current_process.memory_info().rss / 1024 / 1024  # MB
            
            load_info = {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_available_mb': memory.available / 1024 / 1024,
                'disk_percent': disk.percent,
                'process_memory_mb': process_memory,
                'load_average': os.getloadavg()[0] if hasattr(os, 'getloadavg') else 0.0
            }
            
            return load_info
            
        except Exception as e:
            logger.warning(f"获取系统负载失败: {e}")
            return {
                'cpu_percent': 50.0,
                'memory_percent': 50.0,
                'memory_available_mb': 1000.0,
                'disk_percent': 50.0,
                'process_memory_mb': 100.0,
                'load_average': 1.0
            }
    
    def _get_queue_loads(self) -> Dict[str, int]:
        """获取各队列当前负载"""
        queue_loads = {}
        
        try:
            if self.redis_client:
                # 从Redis获取队列长度
                queues = ['pdf_extraction', 'file_processing', 'validation']
                for queue in queues:
                    length = self.redis_client.llen(f'celery_queue_{queue}')
                    queue_loads[queue] = length
            else:
                # 使用Celery inspect获取队列信息
                inspect = celery_app.control.inspect()
                active_tasks = inspect.active()
                scheduled_tasks = inspect.scheduled()
                
                if active_tasks and scheduled_tasks:
                    for worker, tasks in active_tasks.items():
                        for task in tasks:
                            queue = task.get('delivery_info', {}).get('routing_key', 'default')
                            queue_loads[queue] = queue_loads.get(queue, 0) + 1
        
        except Exception as e:
            logger.warning(f"获取队列负载失败: {e}")
        
        return queue_loads
    
    def _get_candidate_queues(self, task_type: str) -> List[str]:
        """根据任务类型获取候选队列"""
        queue_mapping = {
            'pdf_extraction': ['pdf_extraction', 'file_processing'],
            'file_processing': ['file_processing', 'pdf_extraction'],
            'cross_validation': ['validation', 'file_processing'],
            'generic': ['file_processing', 'validation']
        }
        
        return queue_mapping.get(task_type, ['file_processing'])
    
    def _select_best_queue(self, candidate_queues: List[str], 
                          queue_loads: Dict[str, int],
                          system_load: Dict[str, float],
                          task_type: str) -> str:
        """选择最佳队列"""
        if not candidate_queues:
            return 'file_processing'  # 默认队列
        
        # 计算每个队列的负载分数
        queue_scores = {}
        
        for queue in candidate_queues:
            score = 0.0
            
            # 队列长度因子（越短越好）
            queue_length = queue_loads.get(queue, 0)
            length_score = max(0, 100 - queue_length * 2)
            
            # 系统资源因子
            cpu_score = max(0, 100 - system_load['cpu_percent'])
            memory_score = max(0, 100 - system_load['memory_percent'])
            
            # 任务类型适配度
            type_bonus = 0
            if (task_type == 'pdf_extraction' and queue == 'pdf_extraction') or \
               (task_type == 'cross_validation' and queue == 'validation'):
                type_bonus = 20
            
            # 综合评分
            score = (length_score * 0.4 + 
                    cpu_score * 0.3 + 
                    memory_score * 0.2 + 
                    type_bonus * 0.1)
            
            queue_scores[queue] = score
        
        # 选择分数最高的队列
        best_queue = max(queue_scores.items(), key=lambda x: x[1])[0]
        
        # 检查资源限制
        if self._is_system_overloaded(system_load):
            # 系统负载过高，选择最轻量的队列
            return min(candidate_queues, key=lambda q: queue_loads.get(q, 0))
        
        return best_queue
    
    def _calculate_dynamic_priority(self, task_type: str, 
                                  system_load: Dict[str, float],
                                  queue_length: int) -> int:
        """计算动态优先级"""
        # 基础优先级
        base_priority = {
            'pdf_extraction': 7,
            'file_processing': 5,
            'cross_validation': 3,
            'generic': 4
        }.get(task_type, 4)
        
        # 根据系统负载调整
        cpu_load = system_load.get('cpu_percent', 50)
        memory_load = system_load.get('memory_percent', 50)
        
        # 高负载时降低优先级
        if cpu_load > self.max_cpu_usage or memory_load > self.max_memory_usage:
            base_priority = max(1, base_priority - 2)
        
        # 根据队列长度调整
        if queue_length > 50:
            base_priority = max(1, base_priority - 1)
        elif queue_length < 10:
            base_priority = min(10, base_priority + 1)
        
        return base_priority
    
    def _is_system_overloaded(self, system_load: Dict[str, float]) -> bool:
        """检查系统是否过载"""
        return (system_load.get('cpu_percent', 0) > self.max_cpu_usage or
                system_load.get('memory_percent', 0) > self.max_memory_usage or
                system_load.get('memory_available_mb', 1000) < self.min_available_memory)
    
    def should_throttle_tasks(self) -> bool:
        """判断是否应该限制任务提交"""
        system_load = self._get_system_load()
        return self._is_system_overloaded(system_load)
    
    def get_recommended_batch_size(self, task_type: str) -> int:
        """获取推荐的批处理大小"""
        system_load = self._get_system_load()
        
        # 基础批大小
        base_batch_sizes = {
            'pdf_extraction': 3,
            'file_processing': 5,
            'cross_validation': 2,
            'generic': 4
        }
        
        base_size = base_batch_sizes.get(task_type, 4)
        
        # 根据系统负载调整
        cpu_load = system_load.get('cpu_percent', 50)
        memory_load = system_load.get('memory_percent', 50)
        
        if cpu_load > 70 or memory_load > 75:
            # 高负载时减小批大小
            return max(1, base_size // 2)
        elif cpu_load < 30 and memory_load < 40:
            # 低负载时增大批大小
            return min(10, base_size * 2)
        
        return base_size
    
    def record_task_completion(self, task_type: str, queue: str, 
                             execution_time: float, success: bool):
        """记录任务完成情况"""
        with self._stats_lock:
            timestamp = time.time()
            
            # 更新队列统计
            if queue not in self._queue_stats:
                self._queue_stats[queue] = {
                    'total_tasks': 0,
                    'success_count': 0,
                    'total_time': 0.0,
                    'avg_time': 0.0
                }
            
            stats = self._queue_stats[queue]
            stats['total_tasks'] += 1
            if success:
                stats['success_count'] += 1
            stats['total_time'] += execution_time
            stats['avg_time'] = stats['total_time'] / stats['total_tasks']
            
            # 记录历史
            self._task_history[queue].append({
                'timestamp': timestamp,
                'task_type': task_type,
                'execution_time': execution_time,
                'success': success
            })
            
            # 限制历史记录长度
            if len(self._task_history[queue]) > 1000:
                self._task_history[queue].popleft()
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计信息"""
        with self._stats_lock:
            system_load = self._get_system_load()
            queue_loads = self._get_queue_loads()
            
            return {
                'system_load': system_load,
                'queue_loads': queue_loads,
                'queue_stats': dict(self._queue_stats),
                'task_history_count': {
                    queue: len(history) 
                    for queue, history in self._task_history.items()
                },
                'recommendations': {
                    'throttle_tasks': self.should_throttle_tasks(),
                    'batch_sizes': {
                        task_type: self.get_recommended_batch_size(task_type)
                        for task_type in self.task_weights.keys()
                    }
                }
            }
    
    def cleanup_old_stats(self, max_age: int = 3600):
        """清理旧的统计数据"""
        current_time = time.time()
        
        with self._stats_lock:
            for queue in list(self._task_history.keys()):
                history = self._task_history[queue]
                
                # 移除过期记录
                while history and (current_time - history[0]['timestamp']) > max_age:
                    history.popleft()
                
                # 如果队列为空，删除队列记录
                if not history:
                    del self._task_history[queue]

# 全局负载均衡器实例
load_balancer = LoadBalancer()