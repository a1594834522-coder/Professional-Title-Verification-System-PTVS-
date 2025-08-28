# -*- coding: utf-8 -*-
"""
队列管理器 - 封装Celery任务调度和监控
提供统一的队列管理接口，支持任务优先级和负载均衡
"""

import logging
import time
from typing import Dict, List, Any, Optional, Callable
from celery import group, chain, chord
from celery.result import AsyncResult, GroupResult
try:
    from .celery_app import celery_app
except ImportError:
    from celery_app import celery_app
try:
    from .tasks import (
        extract_pdf_content_task,
        process_single_file_task,
        cross_validate_materials_task,
        batch_process_files_task,
        get_task_progress,
        cleanup_old_task_status
    )
except ImportError:
    from tasks import (
        extract_pdf_content_task,
        process_single_file_task,
        cross_validate_materials_task,
        batch_process_files_task,
        get_task_progress,
        cleanup_old_task_status
    )

logger = logging.getLogger(__name__)

class QueueManager:
    """异步队列管理器"""
    
    def __init__(self):
        self.app = celery_app
        self._active_tasks = {}
        
    def submit_pdf_extraction_batch(self, 
                                  file_materials: Dict[str, List[str]], 
                                  priority: int = 7,
                                  progress_callback: Optional[Callable] = None) -> str:
        """
        提交批量PDF提取任务
        
        Args:
            file_materials: {材料ID: [文件路径列表]}
            priority: 任务优先级 (1-10, 10最高)
            progress_callback: 进度回调函数
        
        Returns:
            str: 批任务ID
        """
        tasks = []
        
        for material_id, file_paths in file_materials.items():
            for file_path in file_paths:
                task = extract_pdf_content_task.apply_async(
                    args=[file_path, material_id],
                    kwargs={'priority': priority},
                    priority=priority,
                    queue='pdf_extraction'
                )
                tasks.append(task)
        
        # 创建组任务
        job = group(tasks)
        result = job.apply_async()
        
        # 记录任务组
        group_id = result.id
        self._active_tasks[group_id] = {
            'type': 'pdf_extraction_batch',
            'tasks': tasks,
            'result': result,
            'start_time': time.time(),
            'progress_callback': progress_callback,
            'total_tasks': len(tasks)
        }
        
        logger.info(f"提交PDF提取批任务 {group_id}，包含 {len(tasks)} 个任务")
        return group_id
    
    def submit_file_processing_batch(self, 
                                   file_paths: List[str],
                                   batch_size: int = 5,
                                   priority: int = 5,
                                   progress_callback: Optional[Callable] = None) -> str:
        """
        提交批量文件处理任务
        
        Args:
            file_paths: 文件路径列表
            batch_size: 批次大小
            priority: 任务优先级
            progress_callback: 进度回调函数
        
        Returns:
            str: 批任务ID
        """
        # 智能优先级分配
        prioritized_files = self._assign_file_priorities(file_paths, priority)
        
        # 创建批处理任务
        task = batch_process_files_task.apply_async(
            args=[file_paths],
            kwargs={'batch_size': batch_size, 'priority': priority},
            priority=priority,
            queue='file_processing'
        )
        
        # 记录任务
        task_id = task.id
        self._active_tasks[task_id] = {
            'type': 'file_processing_batch',
            'task': task,
            'start_time': time.time(),
            'progress_callback': progress_callback,
            'total_files': len(file_paths)
        }
        
        logger.info(f"提交文件处理批任务 {task_id}，包含 {len(file_paths)} 个文件")
        return task_id
    
    def submit_cross_validation(self, 
                              materials_data: Dict,
                              rules_data: Dict,
                              priority: int = 3,
                              progress_callback: Optional[Callable] = None) -> str:
        """
        提交交叉验证任务
        
        Args:
            materials_data: 材料数据
            rules_data: 规则数据
            priority: 任务优先级
            progress_callback: 进度回调函数
        
        Returns:
            str: 任务ID
        """
        task = cross_validate_materials_task.apply_async(
            args=[materials_data, rules_data],
            kwargs={'priority': priority},
            priority=priority,
            queue='validation'
        )
        
        # 记录任务
        task_id = task.id
        self._active_tasks[task_id] = {
            'type': 'cross_validation',
            'task': task,
            'start_time': time.time(),
            'progress_callback': progress_callback
        }
        
        logger.info(f"提交交叉验证任务 {task_id}")
        return task_id
    
    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
        
        Returns:
            Dict: 任务状态信息
        """
        if task_id not in self._active_tasks:
            return {'status': 'NOT_FOUND', 'message': '任务不存在'}
        
        task_info = self._active_tasks[task_id]
        task_type = task_info['type']
        
        try:
            if task_type.endswith('_batch') and 'result' in task_info:
                # 组任务状态
                result = task_info['result']
                if hasattr(result, 'ready'):
                    if result.ready():
                        status = 'SUCCESS' if result.successful() else 'FAILURE'
                        progress = 100
                    else:
                        # 计算进度
                        completed = sum(1 for t in task_info['tasks'] if t.ready())
                        total = task_info['total_tasks']
                        progress = int((completed / total) * 100) if total > 0 else 0
                        status = 'PROGRESS'
                else:
                    status = 'PENDING'
                    progress = 0
            else:
                # 单任务状态
                task = task_info.get('task')
                if task:
                    result = AsyncResult(task.id, app=self.app)
                    status = result.status
                    
                    # 获取详细进度
                    task_progress = get_task_progress(task.id)
                    if task_progress:
                        progress = task_progress.get('progress', 0)
                        message = task_progress.get('message', '')
                    else:
                        progress = 100 if status in ['SUCCESS', 'FAILURE'] else 0
                        message = f"任务状态: {status}"
                else:
                    status = 'UNKNOWN'
                    progress = 0
                    message = '无法获取任务信息'
            
            return {
                'task_id': task_id,
                'status': status,
                'progress': progress,
                'message': message,
                'type': task_type,
                'start_time': task_info['start_time'],
                'elapsed_time': time.time() - task_info['start_time']
            }
            
        except Exception as e:
            logger.error(f"获取任务状态失败 {task_id}: {e}")
            return {
                'task_id': task_id,
                'status': 'ERROR',
                'progress': 0,
                'message': f'状态查询失败: {str(e)}',
                'type': task_type
            }
    
    def get_task_result(self, task_id: str, timeout: int = 30):
        """
        获取任务结果
        
        Args:
            task_id: 任务ID
            timeout: 超时时间(秒)
        
        Returns:
            任务结果
        """
        if task_id not in self._active_tasks:
            raise ValueError(f"任务 {task_id} 不存在")
        
        task_info = self._active_tasks[task_id]
        
        try:
            if 'result' in task_info:  # 组任务
                result = task_info['result']
                return result.get(timeout=timeout)
            else:  # 单任务
                task = task_info['task']
                return task.get(timeout=timeout)
        except Exception as e:
            logger.error(f"获取任务结果失败 {task_id}: {e}")
            raise
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
        
        Returns:
            bool: 是否成功取消
        """
        if task_id not in self._active_tasks:
            return False
        
        task_info = self._active_tasks[task_id]
        
        try:
            if 'result' in task_info:  # 组任务
                result = task_info['result']
                result.revoke(terminate=True)
                for task in task_info['tasks']:
                    task.revoke(terminate=True)
            else:  # 单任务
                task = task_info['task']
                task.revoke(terminate=True)
            
            # 从活动任务中移除
            del self._active_tasks[task_id]
            logger.info(f"任务 {task_id} 已取消")
            return True
            
        except Exception as e:
            logger.error(f"取消任务失败 {task_id}: {e}")
            return False
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """获取队列统计信息"""
        try:
            # 获取Celery统计信息
            stats = self.app.control.inspect().stats()
            active = self.app.control.inspect().active()
            scheduled = self.app.control.inspect().scheduled()
            
            return {
                'active_tasks': len(self._active_tasks),
                'celery_stats': stats,
                'active_workers': active,
                'scheduled_tasks': scheduled,
                'queue_lengths': self._get_queue_lengths()
            }
        except Exception as e:
            logger.error(f"获取队列统计失败: {e}")
            return {'error': str(e)}
    
    def cleanup_completed_tasks(self, max_age: int = 3600):
        """清理已完成的任务记录"""
        current_time = time.time()
        completed_tasks = []
        
        for task_id, task_info in self._active_tasks.items():
            # 检查任务是否完成
            try:
                if 'result' in task_info:  # 组任务
                    if task_info['result'].ready():
                        completed_tasks.append(task_id)
                else:  # 单任务
                    task = task_info['task']
                    if task.ready():
                        completed_tasks.append(task_id)
                        
                # 检查任务年龄
                if current_time - task_info['start_time'] > max_age:
                    completed_tasks.append(task_id)
                    
            except Exception as e:
                logger.warning(f"检查任务状态失败 {task_id}: {e}")
                completed_tasks.append(task_id)
        
        # 移除已完成的任务
        for task_id in completed_tasks:
            if task_id in self._active_tasks:
                del self._active_tasks[task_id]
        
        # 清理任务状态缓存
        cleanup_old_task_status(max_age)
        
        logger.info(f"清理了 {len(completed_tasks)} 个已完成的任务")
    
    def _assign_file_priorities(self, file_paths: List[str], base_priority: int) -> List[tuple]:
        """根据文件特征分配优先级"""
        prioritized_files = []
        
        for file_path in file_paths:
            priority = base_priority
            
            try:
                # 根据文件大小调整优先级
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    
                    # 小文件提高优先级
                    if file_size < 1024 * 1024:  # 1MB
                        priority += 2
                    # 大文件降低优先级
                    elif file_size > 10 * 1024 * 1024:  # 10MB
                        priority -= 2
                
                # 根据文件类型调整优先级
                if file_path.endswith('.pdf'):
                    priority += 1  # PDF文件稍微提高优先级
                
                # 确保优先级在合理范围内
                priority = max(1, min(10, priority))
                
            except Exception as e:
                logger.warning(f"分配文件优先级失败 {file_path}: {e}")
            
            prioritized_files.append((file_path, priority))
        
        return prioritized_files
    
    def _get_queue_lengths(self) -> Dict[str, int]:
        """获取各队列长度"""
        try:
            # 这需要Redis连接来查询队列长度
            # 简化实现，返回占位数据
            return {
                'pdf_extraction': 0,
                'file_processing': 0,
                'validation': 0
            }
        except Exception as e:
            logger.warning(f"获取队列长度失败: {e}")
            return {}

# 全局队列管理器实例
queue_manager = QueueManager()