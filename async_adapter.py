# -*- coding: utf-8 -*-
"""
异步队列适配器 - 替代ThreadPoolExecutor
提供向后兼容的接口，将现有代码平滑迁移到Celery队列系统
"""

import logging
import time
from typing import Dict, List, Any, Optional, Callable, Union
from concurrent.futures import Future, as_completed

try:
    from .queue_manager import queue_manager
except ImportError:
    from queue_manager import queue_manager

try:
    from .tasks import get_task_progress
except ImportError:
    from tasks import get_task_progress

logger = logging.getLogger(__name__)

class AsyncTaskFuture:
    """模拟concurrent.futures.Future的接口"""
    
    def __init__(self, task_id: str, queue_mgr, task_type: str = 'unknown'):
        self.task_id = task_id
        self.queue_mgr = queue_mgr
        self.task_type = task_type
        self._result = None
        self._exception = None
        self._done = False
    
    def result(self, timeout: Optional[float] = None) -> Any:
        """获取任务结果"""
        if self._done:
            if self._exception:
                raise self._exception
            return self._result
        
        try:
            self._result = self.queue_mgr.get_task_result(self.task_id, timeout or 30)
            self._done = True
            return self._result
        except Exception as e:
            self._exception = e
            self._done = True
            raise
    
    def done(self) -> bool:
        """检查任务是否完成"""
        if self._done:
            return True
        
        try:
            status = self.queue_mgr.get_task_status(self.task_id)
            self._done = status['status'] in ['SUCCESS', 'FAILURE', 'REVOKED']
            return self._done
        except Exception:
            return False
    
    def cancel(self) -> bool:
        """取消任务"""
        if self._done:
            return False
        return self.queue_mgr.cancel_task(self.task_id)
    
    def cancelled(self) -> bool:
        """检查任务是否被取消"""
        try:
            status = self.queue_mgr.get_task_status(self.task_id)
            return status['status'] == 'REVOKED'
        except Exception:
            return False

class AsyncThreadPoolExecutor:
    """替代ThreadPoolExecutor的异步队列执行器"""
    
    def __init__(self, max_workers: Optional[int] = None, thread_name_prefix: str = ''):
        self.max_workers = max_workers or 4
        self.thread_name_prefix = thread_name_prefix
        self.queue_mgr = queue_manager
        self._futures = {}
        self._task_counter = 0
        
        logger.info(f"初始化AsyncThreadPoolExecutor，最大工作数: {self.max_workers}")
    
    def submit(self, fn: Callable, *args, **kwargs) -> AsyncTaskFuture:
        """提交任务到异步队列"""
        self._task_counter += 1
        
        # 根据函数名决定任务类型和优先级
        task_type, priority = self._determine_task_type(fn, args)
        
        try:
            if task_type == 'pdf_extraction':
                # PDF提取任务
                file_path = args[1] if len(args) > 1 else ''
                material_id = args[0] if len(args) > 0 else f'material_{self._task_counter}'
                
                task_id = self.queue_mgr.submit_pdf_extraction_batch(
                    {material_id: [file_path]}, 
                    priority=priority
                )
                
            elif task_type == 'file_processing':
                # 文件处理任务
                file_path = args[0] if len(args) > 0 else ''
                file_index = args[1] if len(args) > 1 else self._task_counter
                
                try:
                    from .tasks import process_single_file_task
                    # 修复: 使用类型检查确保process_single_file_task有apply_async方法
                    if hasattr(process_single_file_task, 'apply_async') and callable(getattr(process_single_file_task, 'apply_async', None)):
                        task = process_single_file_task.apply_async(  # type: ignore
                            args=[file_path, file_index],
                            kwargs={'priority': priority},
                            priority=priority,
                            queue='file_processing'
                        )
                        task_id = task.id
                    else:
                        # 如果没有apply_async方法，使用队列管理器的方法
                        logger.warning("process_single_file_task缺少apply_async方法，使用队列管理器")
                        # 修复: 使用正确的QueueManager方法
                        task_id = self.queue_mgr.submit_file_processing_batch(
                            [file_path], 
                            priority=priority
                        )
                except (ImportError, AttributeError) as e:
                    # 如果导入失败，使用队列管理器的方法
                    logger.warning(f"直接导入任务失败，使用队列管理器: {e}")
                    # 修复: 使用正确的QueueManager方法
                    task_id = self.queue_mgr.submit_file_processing_batch(
                        [file_path], 
                        priority=priority
                    )
                
            elif task_type == 'cross_validation':
                # 交叉验证任务
                materials_data = args[0] if len(args) > 0 else {}
                rules_data = args[1] if len(args) > 1 else {}
                
                task_id = self.queue_mgr.submit_cross_validation(
                    materials_data, 
                    rules_data, 
                    priority=priority
                )
                
            else:
                # 通用任务处理
                task_id = self._submit_generic_task(fn, args, kwargs, priority)
            
            # 创建Future对象
            future = AsyncTaskFuture(task_id, self.queue_mgr, task_type)
            self._futures[task_id] = future
            
            logger.debug(f"提交任务 {task_id}，类型: {task_type}，优先级: {priority}")
            return future
            
        except Exception as e:
            logger.error(f"提交任务失败: {e}")
            # 创建一个失败的Future
            future = AsyncTaskFuture(f"failed_{self._task_counter}", self.queue_mgr, 'failed')
            future._exception = e
            future._done = True
            return future
    
    def map(self, fn: Callable, *iterables, timeout: Optional[float] = None, chunksize: int = 1):
        """批量执行任务"""
        futures = []
        
        # 提交所有任务
        for args in zip(*iterables):
            future = self.submit(fn, *args)
            futures.append(future)
        
        # 等待结果
        results = []
        for future in futures:
            try:
                result = future.result(timeout)
                results.append(result)
            except Exception as e:
                logger.error(f"批量任务执行失败: {e}")
                results.append(None)
        
        return results
    
    def shutdown(self, wait: bool = True):
        """关闭执行器"""
        if wait:
            # 等待所有任务完成
            for future in self._futures.values():
                try:
                    if not future.done():
                        future.result(timeout=30)
                except Exception as e:
                    logger.warning(f"等待任务完成时出错: {e}")
        
        # 清理资源
        self._futures.clear()
        logger.info("AsyncThreadPoolExecutor已关闭")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)
    
    def _determine_task_type(self, fn: Callable, args: tuple) -> tuple:
        """根据函数和参数确定任务类型和优先级"""
        fn_name = getattr(fn, '__name__', str(fn))
        
        # PDF提取相关
        if 'extract' in fn_name.lower() and 'pdf' in fn_name.lower():
            return 'pdf_extraction', 8
        
        # 文件处理相关
        if 'process' in fn_name.lower() and 'file' in fn_name.lower():
            return 'file_processing', 6
        
        # 交叉验证相关
        if 'validate' in fn_name.lower() or 'cross' in fn_name.lower():
            return 'cross_validation', 4
        
        # 检查参数中的文件路径
        for arg in args:
            if isinstance(arg, str):
                if arg.endswith('.pdf'):
                    return 'pdf_extraction', 7
                elif any(arg.endswith(ext) for ext in ['.doc', '.docx', '.txt']):
                    return 'file_processing', 5
        
        # 默认任务
        return 'generic', 5
    
    def _submit_generic_task(self, fn: Callable, args: tuple, kwargs: dict, priority: int) -> str:
        """提交通用任务"""
        try:
            from .tasks import celery_app
            
            # 创建一个包装任务
            @celery_app.task(bind=True, name='pdf_processor.tasks.generic_task')
            def generic_task_wrapper(self, fn_name: str, args: tuple, kwargs: dict):
                """通用任务包装器"""
                try:
                    # 这里需要根据fn_name重新构造函数调用
                    # 简化实现：直接调用原函数（需要函数可序列化）
                    result = fn(*args, **kwargs)
                    return result
                except Exception as e:
                    logger.error(f"通用任务执行失败: {e}")
                    raise
            
            # 修复: 使用类型检查确保generic_task_wrapper有apply_async方法
            if hasattr(generic_task_wrapper, 'apply_async') and callable(getattr(generic_task_wrapper, 'apply_async', None)):
                # 提交任务
                task = generic_task_wrapper.apply_async(  # type: ignore
                    args=[getattr(fn, '__name__', str(fn)), args, kwargs],
                    priority=priority,
                    queue='file_processing'
                )
                
                return task.id
            else:
                logger.error("generic_task_wrapper缺少apply_async方法")
                # 返回一个错误任务ID
                return f"failed_generic_{self._task_counter}"
            
        except Exception as e:
            logger.error(f"提交通用任务失败: {e}")
            # 返回一个错误任务ID
            return f"failed_generic_{self._task_counter}"

def async_as_completed(futures: List[AsyncTaskFuture], timeout: Optional[float] = None):
    """异步版本的as_completed"""
    completed = []
    start_time = time.time()
    
    while len(completed) < len(futures):
        if timeout and (time.time() - start_time) > timeout:
            break
        
        for future in futures:
            if future not in completed and future.done():
                completed.append(future)
                yield future
        
        # 短暂休眠避免忙等待
        time.sleep(0.1)

# 兼容性导入
ThreadPoolExecutor = AsyncThreadPoolExecutor
as_completed = async_as_completed