# -*- coding: utf-8 -*-
"""
Celery异步任务定义
包含PDF处理、内容提取、交叉验证等任务
"""

from celery import current_task
from celery.exceptions import Retry
try:
    from .celery_app import celery_app
except ImportError:
    # 直接导入，用于独立运行
    from celery_app import celery_app
import logging
import time
import os
from typing import Dict, List, Any, Optional, Tuple
import threading

# 设置日志
logger = logging.getLogger(__name__)

# 全局状态管理
task_status = {}
status_lock = threading.Lock()

def update_task_progress(task_id: str, progress: int, message: str = ""):
    """更新任务进度"""
    with status_lock:
        task_status[task_id] = {
            'progress': progress,
            'message': message,
            'timestamp': time.time()
        }
    
    # 更新Celery任务状态
    if current_task:
        current_task.update_state(
            state='PROGRESS',
            meta={'progress': progress, 'message': message}
        )

@celery_app.task(bind=True, name='pdf_processor.tasks.extract_pdf_content')
def extract_pdf_content_task(self, file_path: str, material_id: str, priority: int = 5):
    """
    异步PDF内容提取任务
    
    Args:
        file_path: PDF文件路径
        material_id: 材料ID
        priority: 任务优先级
    
    Returns:
        Dict: 提取结果
    """
    task_id = self.request.id
    
    try:
        update_task_progress(task_id, 0, f"开始处理PDF文件: {os.path.basename(file_path)}")
        
        # 导入cross_validator来使用现有的PDF处理逻辑
        from .cross_validator import CrossValidator
        
        # 创建一个临时的CrossValidator实例
        validator = CrossValidator()
        
        update_task_progress(task_id, 20, "初始化PDF处理器")
        
        # 使用现有的PDF提取方法
        content = validator._extract_pdf_content_enhanced(file_path)
        
        update_task_progress(task_id, 80, "PDF内容提取完成")
        
        result = {
            'material_id': material_id,
            'file_path': file_path,
            'content': content,
            'success': True,
            'error': None
        }
        
        update_task_progress(task_id, 100, "任务完成")
        return result
        
    except Exception as e:
        error_msg = f"PDF提取失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        result = {
            'material_id': material_id,
            'file_path': file_path,
            'content': None,
            'success': False,
            'error': error_msg
        }
        
        update_task_progress(task_id, 100, f"任务失败: {error_msg}")
        return result

@celery_app.task(bind=True, name='pdf_processor.tasks.process_single_file')
def process_single_file_task(self, file_path: str, file_index: int, priority: int = 5):
    """
    异步单文件处理任务
    
    Args:
        file_path: 文件路径
        file_index: 文件索引
        priority: 任务优先级
    
    Returns:
        Dict: 处理结果
    """
    task_id = self.request.id
    
    try:
        update_task_progress(task_id, 0, f"开始处理文件: {os.path.basename(file_path)}")
        
        from .cross_validator import CrossValidator
        validator = CrossValidator()
        
        update_task_progress(task_id, 20, "分析文件类型")
        
        # 使用现有的文件处理逻辑
        result = validator._process_single_file_enhanced(file_path, file_index)
        
        update_task_progress(task_id, 100, "文件处理完成")
        return result
        
    except Exception as e:
        error_msg = f"文件处理失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        result = {
            'file_path': file_path,
            'success': False,
            'error': error_msg
        }
        
        update_task_progress(task_id, 100, f"任务失败: {error_msg}")
        return result

@celery_app.task(bind=True, name='pdf_processor.tasks.cross_validate_materials')
def cross_validate_materials_task(self, materials_data: Dict, rules_data: Dict, priority: int = 3):
    """
    异步交叉验证任务
    
    Args:
        materials_data: 材料数据
        rules_data: 规则数据
        priority: 任务优先级
    
    Returns:
        Dict: 验证结果
    """
    task_id = self.request.id
    
    try:
        update_task_progress(task_id, 0, "开始交叉验证分析")
        
        from .cross_validator import CrossValidator
        validator = CrossValidator()
        
        update_task_progress(task_id, 20, "加载验证规则")
        
        # 执行交叉验证逻辑
        validation_results = validator._perform_cross_validation(materials_data, rules_data)
        
        update_task_progress(task_id, 80, "生成验证报告")
        
        # 生成最终报告
        report = validator._generate_validation_report(validation_results)
        
        result = {
            'validation_results': validation_results,
            'report': report,
            'success': True,
            'error': None
        }
        
        update_task_progress(task_id, 100, "交叉验证完成")
        return result
        
    except Exception as e:
        error_msg = f"交叉验证失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        result = {
            'validation_results': None,
            'report': None,
            'success': False,
            'error': error_msg
        }
        
        update_task_progress(task_id, 100, f"任务失败: {error_msg}")
        return result

@celery_app.task(bind=True, name='pdf_processor.tasks.batch_process_files')
def batch_process_files_task(self, file_list: List[str], batch_size: int = 5, priority: int = 5):
    """
    批量文件处理任务 - 支持更好的负载均衡
    
    Args:
        file_list: 文件列表
        batch_size: 批次大小
        priority: 任务优先级
    
    Returns:
        List: 处理结果列表
    """
    task_id = self.request.id
    
    try:
        total_files = len(file_list)
        update_task_progress(task_id, 0, f"开始批量处理 {total_files} 个文件")
        
        results = []
        
        # 分批处理文件
        for i in range(0, total_files, batch_size):
            batch = file_list[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_files + batch_size - 1) // batch_size
            
            update_task_progress(
                task_id, 
                int((i / total_files) * 100), 
                f"处理批次 {batch_num}/{total_batches} ({len(batch)} 个文件)"
            )
            
            # 为当前批次创建子任务
            batch_tasks = []
            for j, file_path in enumerate(batch):
                # 根据文件大小和类型调整优先级
                file_priority = priority
                if file_path.endswith('.pdf'):
                    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                    # 大文件降低优先级
                    if file_size > 10 * 1024 * 1024:  # 10MB
                        file_priority = max(1, priority - 2)
                
                task = process_single_file_task.apply_async(
                    args=[file_path, i + j + 1],
                    kwargs={'priority': file_priority},
                    priority=file_priority
                )
                batch_tasks.append(task)
            
            # 等待当前批次完成
            batch_results = []
            for task in batch_tasks:
                try:
                    result = task.get(timeout=300)  # 5分钟超时
                    batch_results.append(result)
                except Exception as e:
                    batch_results.append({
                        'success': False,
                        'error': f"子任务执行失败: {str(e)}"
                    })
            
            results.extend(batch_results)
        
        update_task_progress(task_id, 100, f"批量处理完成，共处理 {len(results)} 个文件")
        return results
        
    except Exception as e:
        error_msg = f"批量处理失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        update_task_progress(task_id, 100, f"任务失败: {error_msg}")
        raise

def get_task_progress(task_id: str) -> Optional[Dict]:
    """获取任务进度"""
    with status_lock:
        return task_status.get(task_id)

def cleanup_old_task_status(max_age: int = 3600):
    """清理旧的任务状态记录"""
    current_time = time.time()
    with status_lock:
        expired_tasks = [
            task_id for task_id, status in task_status.items()
            if current_time - status.get('timestamp', 0) > max_age
        ]
        for task_id in expired_tasks:
            del task_status[task_id]