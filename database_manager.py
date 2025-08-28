#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库管理模块
实现SQLite数据库集成，支持任务状态存储、历史记录查看和断点续传
"""

import os
import sqlite3
import json
import time
import threading
from typing import Dict, List, Optional, Any, Tuple, Callable
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from contextlib import contextmanager

@dataclass
class TaskInfo:
    """任务信息数据结构"""
    task_id: str
    status: str  # pending, processing, complete, error, cancelled
    created_at: float
    updated_at: float
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    zip_file_path: Optional[str] = None
    excel_file_path: Optional[str] = None
    zip_file_name: Optional[str] = None
    excel_file_name: Optional[str] = None
    progress_percent: float = 0.0
    current_step: Optional[str] = None
    total_materials: int = 0
    processed_materials: int = 0
    report_content: Optional[str] = None
    formatted_report: Optional[str] = None
    error_message: Optional[str] = None
    file_size_mb: float = 0.0
    processing_time_seconds: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskInfo':
        """从字典创建实例"""
        return cls(**data)

@dataclass
class TaskLog:
    """任务日志数据结构"""
    log_id: Optional[int]
    task_id: str
    timestamp: float
    level: str  # INFO, WARN, ERROR, DEBUG
    message: str
    step: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)

class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, db_path: Optional[str] = None, progress_callback: Optional[Callable[[str], None]] = None):
        """
        初始化数据库管理器
        
        Args:
            db_path: 数据库文件路径，默认为当前目录下的database.db
            progress_callback: 进度回调函数
        """
        self.progress_callback = progress_callback or (lambda msg: None)
        
        # 设置数据库路径
        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = Path(__file__).parent / "database.db"
        
        # 确保数据库目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 线程锁，确保数据库操作的线程安全
        self.lock = threading.RLock()
        
        # 初始化数据库
        self._init_database()
        
        self._log(f"📊 数据库管理器初始化完成")
        self._log(f"   📁 数据库路径: {self.db_path}")
        
    def _log(self, message: str):
        """记录日志"""
        if self.progress_callback:
            self.progress_callback(message)
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器"""
        with self.lock:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row  # 使结果可以通过列名访问
            try:
                yield conn
            finally:
                conn.close()
    
    def _init_database(self):
        """初始化数据库表结构"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 创建任务表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    start_time REAL,
                    end_time REAL,
                    zip_file_path TEXT,
                    excel_file_path TEXT,
                    zip_file_name TEXT,
                    excel_file_name TEXT,
                    progress_percent REAL DEFAULT 0.0,
                    current_step TEXT,
                    total_materials INTEGER DEFAULT 0,
                    processed_materials INTEGER DEFAULT 0,
                    report_content TEXT,
                    formatted_report TEXT,
                    error_message TEXT,
                    file_size_mb REAL DEFAULT 0.0,
                    processing_time_seconds REAL DEFAULT 0.0,
                    cache_hits INTEGER DEFAULT 0,
                    cache_misses INTEGER DEFAULT 0
                )
            """)
            
            # 创建任务日志表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    step TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks (task_id)
                )
            """)
            
            # 创建索引以提高查询性能
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks (created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_logs_task_id ON task_logs (task_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_logs_timestamp ON task_logs (timestamp)
            """)
            
            conn.commit()
            
            # 检查是否需要数据库升级
            self._upgrade_database(cursor)
            conn.commit()
    
    def _upgrade_database(self, cursor):
        """数据库升级逻辑"""
        try:
            # 检查是否存在新字段，如果不存在则添加
            cursor.execute("PRAGMA table_info(tasks)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # 添加新字段（如果不存在）
            new_columns = [
                ('progress_percent', 'REAL DEFAULT 0.0'),
                ('current_step', 'TEXT'),
                ('total_materials', 'INTEGER DEFAULT 0'),
                ('processed_materials', 'INTEGER DEFAULT 0'),
                ('file_size_mb', 'REAL DEFAULT 0.0'),
                ('processing_time_seconds', 'REAL DEFAULT 0.0'),
                ('cache_hits', 'INTEGER DEFAULT 0'),
                ('cache_misses', 'INTEGER DEFAULT 0'),
            ]
            
            for column_name, column_def in new_columns:
                if column_name not in columns:
                    cursor.execute(f"ALTER TABLE tasks ADD COLUMN {column_name} {column_def}")
                    self._log(f"   🔧 数据库升级: 添加字段 {column_name}")
                    
        except Exception as e:
            self._log(f"⚠️ 数据库升级警告: {e}")
    
    def create_task(self, task_info: TaskInfo) -> bool:
        """
        创建新任务
        
        Args:
            task_info: 任务信息
            
        Returns:
            是否创建成功
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 插入任务记录
                cursor.execute("""
                    INSERT INTO tasks (
                        task_id, status, created_at, updated_at, start_time, end_time,
                        zip_file_path, excel_file_path, zip_file_name, excel_file_name,
                        progress_percent, current_step, total_materials, processed_materials,
                        report_content, formatted_report, error_message,
                        file_size_mb, processing_time_seconds, cache_hits, cache_misses
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_info.task_id, task_info.status, task_info.created_at, task_info.updated_at,
                    task_info.start_time, task_info.end_time, task_info.zip_file_path, task_info.excel_file_path,
                    task_info.zip_file_name, task_info.excel_file_name, task_info.progress_percent,
                    task_info.current_step, task_info.total_materials, task_info.processed_materials,
                    task_info.report_content, task_info.formatted_report, task_info.error_message,
                    task_info.file_size_mb, task_info.processing_time_seconds, task_info.cache_hits, task_info.cache_misses
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            self._log(f"❌ 创建任务失败: {e}")
            return False
    
    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新任务信息
        
        Args:
            task_id: 任务ID
            updates: 要更新的字段字典
            
        Returns:
            是否更新成功
        """
        try:
            if not updates:
                return True
                
            # 自动添加更新时间
            updates['updated_at'] = time.time()
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 构建UPDATE语句
                set_clauses = []
                values = []
                for key, value in updates.items():
                    set_clauses.append(f"{key} = ?")
                    values.append(value)
                
                values.append(task_id)
                
                sql = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE task_id = ?"
                cursor.execute(sql, values)
                
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            self._log(f"❌ 更新任务失败: {e}")
            return False
    
    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """
        获取任务信息
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务信息或None
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
                row = cursor.fetchone()
                
                if row:
                    return TaskInfo(**dict(row))
                return None
                
        except Exception as e:
            self._log(f"❌ 获取任务失败: {e}")
            return None
    
    def get_tasks_by_status(self, status: str, limit: int = 100) -> List[TaskInfo]:
        """
        根据状态获取任务列表
        
        Args:
            status: 任务状态
            limit: 返回数量限制
            
        Returns:
            任务信息列表
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM tasks 
                    WHERE status = ? 
                    ORDER BY created_at DESC 
                    LIMIT ?
                """, (status, limit))
                
                rows = cursor.fetchall()
                return [TaskInfo(**dict(row)) for row in rows]
                
        except Exception as e:
            self._log(f"❌ 获取任务列表失败: {e}")
            return []
    
    def get_recent_tasks(self, limit: int = 20) -> List[TaskInfo]:
        """
        获取最近的任务列表
        
        Args:
            limit: 返回数量限制
            
        Returns:
            任务信息列表
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM tasks 
                    ORDER BY created_at DESC 
                    LIMIT ?
                """, (limit,))
                
                rows = cursor.fetchall()
                return [TaskInfo(**dict(row)) for row in rows]
                
        except Exception as e:
            self._log(f"❌ 获取最近任务失败: {e}")
            return []
    
    def add_task_log(self, task_log: TaskLog) -> bool:
        """
        添加任务日志
        
        Args:
            task_log: 任务日志
            
        Returns:
            是否添加成功
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO task_logs (task_id, timestamp, level, message, step)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    task_log.task_id, task_log.timestamp, task_log.level,
                    task_log.message, task_log.step
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            self._log(f"❌ 添加任务日志失败: {e}")
            return False
    
    def get_task_logs(self, task_id: str, limit: int = 1000) -> List[TaskLog]:
        """
        获取任务日志
        
        Args:
            task_id: 任务ID
            limit: 返回数量限制
            
        Returns:
            任务日志列表
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM task_logs 
                    WHERE task_id = ? 
                    ORDER BY timestamp ASC 
                    LIMIT ?
                """, (task_id, limit))
                
                rows = cursor.fetchall()
                return [TaskLog(**dict(row)) for row in rows]
                
        except Exception as e:
            self._log(f"❌ 获取任务日志失败: {e}")
            return []
    
    def delete_task(self, task_id: str) -> bool:
        """
        删除任务（包括相关日志）
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否删除成功
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 删除任务日志
                cursor.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
                
                # 删除任务
                cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
                
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            self._log(f"❌ 删除任务失败: {e}")
            return False
    
    def cleanup_old_tasks(self, days_old: int = 30) -> int:
        """
        清理旧任务
        
        Args:
            days_old: 删除多少天前的任务
            
        Returns:
            删除的任务数量
        """
        try:
            cutoff_time = time.time() - (days_old * 24 * 3600)
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 获取要删除的任务
                cursor.execute("""
                    SELECT task_id FROM tasks 
                    WHERE created_at < ? AND status IN ('complete', 'error', 'cancelled')
                """, (cutoff_time,))
                
                old_task_ids = [row[0] for row in cursor.fetchall()]
                
                if old_task_ids:
                    # 删除任务日志
                    placeholders = ','.join(['?'] * len(old_task_ids))
                    cursor.execute(f"DELETE FROM task_logs WHERE task_id IN ({placeholders})", old_task_ids)
                    
                    # 删除任务
                    cursor.execute(f"DELETE FROM tasks WHERE task_id IN ({placeholders})", old_task_ids)
                    
                    conn.commit()
                    
                    self._log(f"🧹 清理了 {len(old_task_ids)} 个旧任务")
                    return len(old_task_ids)
                
                return 0
                
        except Exception as e:
            self._log(f"❌ 清理旧任务失败: {e}")
            return 0
    
    def get_task_statistics(self) -> Dict[str, Any]:
        """
        获取任务统计信息
        
        Returns:
            统计信息字典
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 基本统计
                cursor.execute("SELECT COUNT(*) FROM tasks")
                total_tasks = cursor.fetchone()[0]
                
                cursor.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")
                status_counts = dict(cursor.fetchall())
                
                # 最近7天的任务
                week_ago = time.time() - (7 * 24 * 3600)
                cursor.execute("SELECT COUNT(*) FROM tasks WHERE created_at > ?", (week_ago,))
                recent_tasks = cursor.fetchone()[0]
                
                # 平均处理时间
                cursor.execute("""
                    SELECT AVG(processing_time_seconds) 
                    FROM tasks 
                    WHERE status = 'complete' AND processing_time_seconds > 0
                """)
                avg_processing_time = cursor.fetchone()[0] or 0
                
                # 成功率
                success_count = status_counts.get('complete', 0)
                error_count = status_counts.get('error', 0)
                success_rate = (success_count / (success_count + error_count) * 100) if (success_count + error_count) > 0 else 0
                
                return {
                    'total_tasks': total_tasks,
                    'status_counts': status_counts,
                    'recent_tasks_7days': recent_tasks,
                    'average_processing_time_seconds': round(avg_processing_time, 2),
                    'success_rate_percent': round(success_rate, 2),
                    'database_size_mb': round(os.path.getsize(self.db_path) / 1024 / 1024, 2) if self.db_path.exists() else 0
                }
                
        except Exception as e:
            self._log(f"❌ 获取统计信息失败: {e}")
            return {}
    
    def export_task_data(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        导出任务数据（用于备份或分析）
        
        Args:
            task_id: 任务ID
            
        Returns:
            包含任务信息和日志的完整数据
        """
        try:
            task_info = self.get_task(task_id)
            if not task_info:
                return None
            
            task_logs = self.get_task_logs(task_id)
            
            return {
                'task_info': task_info.to_dict(),
                'logs': [log.to_dict() for log in task_logs],
                'export_time': time.time()
            }
            
        except Exception as e:
            self._log(f"❌ 导出任务数据失败: {e}")
            return None
    
    def get_resumable_tasks(self) -> List[TaskInfo]:
        """
        获取可恢复的任务（状态为processing但长时间未更新）
        
        Returns:
            可恢复的任务列表
        """
        try:
            # 超过1小时未更新的processing任务认为可能需要恢复
            stale_time = time.time() - 3600
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM tasks 
                    WHERE status = 'processing' AND updated_at < ?
                    ORDER BY updated_at ASC
                """, (stale_time,))
                
                rows = cursor.fetchall()
                return [TaskInfo(**dict(row)) for row in rows]
                
        except Exception as e:
            self._log(f"❌ 获取可恢复任务失败: {e}")
            return []
    
    def backup_database(self, backup_path: str) -> bool:
        """
        备份数据库
        
        Args:
            backup_path: 备份文件路径
            
        Returns:
            是否备份成功
        """
        try:
            import shutil
            shutil.copy2(str(self.db_path), backup_path)
            self._log(f"💾 数据库备份成功: {backup_path}")
            return True
            
        except Exception as e:
            self._log(f"❌ 数据库备份失败: {e}")
            return False
    
    def optimize_database(self) -> bool:
        """
        优化数据库（重建索引、清理空间）
        
        Returns:
            是否优化成功
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 重建索引
                cursor.execute("REINDEX")
                
                # 清理数据库
                cursor.execute("VACUUM")
                
                conn.commit()
                
            self._log("🔧 数据库优化完成")
            return True
            
        except Exception as e:
            self._log(f"❌ 数据库优化失败: {e}")
            return False