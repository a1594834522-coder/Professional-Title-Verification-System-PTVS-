#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
改进的缓存管理器
支持持久化缓存、过期机制和基于MD5哈希的智能缓存键
"""

import os
import json
import hashlib
import time
import pickle
import tempfile
import threading
from typing import Dict, Optional, Any, Union, Callable
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

@dataclass
class CacheEntry:
    """缓存条目数据结构"""
    content: str
    file_hash: str
    file_size: int
    file_mtime: float
    cache_time: float
    access_count: int = 0
    last_access: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheEntry':
        """从字典创建实例"""
        return cls(**data)
    
    def is_expired(self, max_age_hours: int = 24) -> bool:
        """检查是否已过期"""
        return time.time() - self.cache_time > max_age_hours * 3600
    
    def is_file_changed(self, file_path: str) -> bool:
        """检查文件是否已更改"""
        try:
            stat = os.stat(file_path)
            return (stat.st_size != self.file_size or 
                   stat.st_mtime != self.file_mtime)
        except (OSError, FileNotFoundError):
            return True

class SmartCacheManager:
    """智能缓存管理器"""
    
    def __init__(self, 
                 cache_dir: Optional[str] = None,
                 max_age_hours: int = 24,
                 max_memory_items: int = 100,
                 max_disk_size_mb: int = 1000,
                 enable_redis: bool = False,
                 redis_url: Optional[str] = None,
                 progress_callback: Optional[Callable] = None):
        """
        初始化缓存管理器
        
        Args:
            cache_dir: 缓存目录路径，默认为系统临时目录
            max_age_hours: 缓存最大生存时间（小时）
            max_memory_items: 内存缓存最大条目数
            max_disk_size_mb: 磁盘缓存最大大小（MB）
            enable_redis: 是否启用Redis缓存
            redis_url: Redis连接URL
            progress_callback: 进度回调函数
        """
        self.max_age_hours = max_age_hours
        self.max_memory_items = max_memory_items
        self.max_disk_size_mb = max_disk_size_mb
        self.enable_redis = enable_redis
        self.progress_callback = progress_callback or (lambda msg: None)
        self.lock = threading.RLock()
        
        # 内存缓存
        self.memory_cache: Dict[str, CacheEntry] = {}
        
        # 设置缓存目录
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path(tempfile.gettempdir()) / "pdf_content_cache"
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 缓存统计
        self.stats = {
            'hits': 0,
            'misses': 0,
            'disk_hits': 0,
            'memory_hits': 0,
            'redis_hits': 0,
            'files_cached': 0,
            'cache_size_mb': 0.0
        }
        
        # Redis配置
        self.redis_client = None
        if enable_redis:
            self._init_redis(redis_url)
        
        # 启动时清理过期缓存
        self._cleanup_expired_cache()
        
        self._log("💾 智能缓存管理器初始化完成")
        self._log(f"   📁 缓存目录: {self.cache_dir}")
        self._log(f"   ⏰ 缓存有效期: {max_age_hours} 小时")
        self._log(f"   🧠 内存缓存限制: {max_memory_items} 个条目")
        self._log(f"   💽 磁盘缓存限制: {max_disk_size_mb} MB")
        if self.redis_client:
            self._log(f"   🔴 Redis缓存: 已启用")
    
    def _log(self, message: str):
        """记录日志"""
        if self.progress_callback:
            self.progress_callback(message)
    
    def _init_redis(self, redis_url: Optional[str]):
        """初始化Redis连接"""
        try:
            try:
                import redis
            except ImportError:
                self._log("⚠️ Redis包未安装，将使用文件缓存")
                self.redis_client = None
                self.enable_redis = False
                return
                
            if redis_url:
                self.redis_client = redis.from_url(redis_url)
            else:
                # 尝试连接默认的本地Redis
                self.redis_client = redis.Redis(
                    host='localhost', 
                    port=6379, 
                    db=0,
                    decode_responses=False,  # 保持二进制模式用于pickle
                    socket_timeout=2
                )
            
            # 测试连接
            self.redis_client.ping()
            self._log("🔴 Redis缓存连接成功")
            
        except Exception as e:
            self._log(f"⚠️ Redis连接失败，将使用文件缓存: {e}")
            self.redis_client = None
            self.enable_redis = False
    
    def _get_file_hash(self, file_path: str) -> str:
        """计算文件的MD5哈希值"""
        hash_md5 = hashlib.md5()
        
        try:
            # 获取文件基本信息
            stat = os.stat(file_path)
            file_info = f"{file_path}_{stat.st_size}_{stat.st_mtime}"
            
            # 如果文件很大，只计算前1MB和后1MB的哈希
            if stat.st_size > 10 * 1024 * 1024:  # 10MB
                with open(file_path, 'rb') as f:
                    # 读取前1MB
                    chunk = f.read(1024 * 1024)
                    hash_md5.update(chunk)
                    
                    # 如果文件大于2MB，跳到末尾读取最后1MB
                    if stat.st_size > 2 * 1024 * 1024:
                        f.seek(-1024 * 1024, 2)
                        chunk = f.read(1024 * 1024)
                        hash_md5.update(chunk)
                        
                    # 添加文件信息
                    hash_md5.update(file_info.encode())
            else:
                # 小文件直接计算完整哈希
                with open(file_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        hash_md5.update(chunk)
                        
            return hash_md5.hexdigest()
            
        except Exception as e:
            # 如果文件读取失败，使用文件信息作为哈希
            self._log(f"⚠️ 无法计算文件哈希，使用文件信息: {e}")
            try:
                stat = os.stat(file_path)
                file_info = f"{file_path}_{stat.st_size}_{stat.st_mtime}"
                hash_md5.update(file_info.encode())
                return hash_md5.hexdigest()
            except Exception:
                # 如果连文件信息都获取不到，使用文件路径
                hash_md5.update(file_path.encode())
                return hash_md5.hexdigest()
    
    def _get_cache_key(self, file_path: str, file_hash: str, prefix: str = "") -> str:
        """生成缓存键"""
        if prefix:
            return f"{prefix}_{file_hash}"
        return file_hash
    
    def _get_cache_file_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        # 使用前两个字符作为子目录，避免单个目录文件过多
        subdir = cache_key[:2]
        cache_subdir = self.cache_dir / subdir
        cache_subdir.mkdir(exist_ok=True)
        return cache_subdir / f"{cache_key}.cache"
    
    def get(self, file_path: str, prefix: str = "") -> Optional[str]:
        """
        获取缓存内容
        
        Args:
            file_path: 文件路径
            prefix: 缓存键前缀（用于区分不同类型的缓存）
            
        Returns:
            缓存的内容，如果不存在或过期则返回None
        """
        with self.lock:
            try:
                # 计算文件哈希
                file_hash = self._get_file_hash(file_path)
                cache_key = self._get_cache_key(file_path, file_hash, prefix)
                
                # 1. 检查内存缓存
                if cache_key in self.memory_cache:
                    entry = self.memory_cache[cache_key]
                    
                    # 检查是否过期或文件已更改
                    if entry.is_expired(self.max_age_hours) or entry.is_file_changed(file_path):
                        del self.memory_cache[cache_key]
                    else:
                        entry.access_count += 1
                        entry.last_access = time.time()
                        self.stats['hits'] += 1
                        self.stats['memory_hits'] += 1
                        return entry.content
                
                # 2. 检查Redis缓存
                if self.redis_client:
                    try:
                        cached_data = self.redis_client.get(f"pdf_cache:{cache_key}")
                        if cached_data:
                            # 确保数据是bytes类型
                            if isinstance(cached_data, str):
                                cached_data = cached_data.encode('utf-8')
                            
                            if isinstance(cached_data, bytes):
                                entry_dict = pickle.loads(cached_data)
                                entry = CacheEntry.from_dict(entry_dict)
                                
                                if not entry.is_expired(self.max_age_hours) and not entry.is_file_changed(file_path):
                                    # 将热点数据加载到内存
                                    if len(self.memory_cache) < self.max_memory_items:
                                        self.memory_cache[cache_key] = entry
                                    
                                    entry.access_count += 1
                                    entry.last_access = time.time()
                                    self.stats['hits'] += 1
                                    self.stats['redis_hits'] += 1
                                    return entry.content
                                else:
                                    # 删除过期的Redis缓存
                                    self.redis_client.delete(f"pdf_cache:{cache_key}")
                    except Exception as e:
                        self._log(f"⚠️ Redis缓存读取失败: {e}")
                
                # 3. 检查文件缓存
                cache_file = self._get_cache_file_path(cache_key)
                if cache_file.exists():
                    try:
                        with open(cache_file, 'rb') as f:
                            entry_dict = pickle.load(f)
                            entry = CacheEntry.from_dict(entry_dict)
                            
                        if not entry.is_expired(self.max_age_hours) and not entry.is_file_changed(file_path):
                            # 将数据加载到内存
                            if len(self.memory_cache) < self.max_memory_items:
                                self.memory_cache[cache_key] = entry
                            
                            # 如果启用Redis，也存储到Redis
                            if self.redis_client:
                                try:
                                    self.redis_client.setex(
                                        f"pdf_cache:{cache_key}",
                                        self.max_age_hours * 3600,
                                        pickle.dumps(entry_dict)
                                    )
                                except Exception as e:
                                    self._log(f"⚠️ Redis缓存写入失败: {e}")
                            
                            entry.access_count += 1
                            entry.last_access = time.time()
                            self.stats['hits'] += 1
                            self.stats['disk_hits'] += 1
                            return entry.content
                        else:
                            # 删除过期的文件缓存
                            cache_file.unlink(missing_ok=True)
                    except Exception as e:
                        self._log(f"⚠️ 文件缓存读取失败: {e}")
                        cache_file.unlink(missing_ok=True)
                
                # 缓存未命中
                self.stats['misses'] += 1
                return None
                
            except Exception as e:
                self._log(f"❌ 缓存获取失败: {e}")
                self.stats['misses'] += 1
                return None
    
    def set(self, file_path: str, content: str, prefix: str = "") -> bool:
        """
        设置缓存内容
        
        Args:
            file_path: 文件路径
            content: 要缓存的内容
            prefix: 缓存键前缀
            
        Returns:
            是否成功设置缓存
        """
        with self.lock:
            try:
                # 计算文件哈希和基本信息
                file_hash = self._get_file_hash(file_path)
                cache_key = self._get_cache_key(file_path, file_hash, prefix)
                
                stat = os.stat(file_path)
                current_time = time.time()
                
                # 创建缓存条目
                entry = CacheEntry(
                    content=content,
                    file_hash=file_hash,
                    file_size=stat.st_size,
                    file_mtime=stat.st_mtime,
                    cache_time=current_time,
                    access_count=1,
                    last_access=current_time
                )
                
                # 1. 存储到内存缓存
                if len(self.memory_cache) >= self.max_memory_items:
                    self._evict_memory_cache()
                
                self.memory_cache[cache_key] = entry
                
                # 2. 存储到Redis缓存
                if self.redis_client:
                    try:
                        self.redis_client.setex(
                            f"pdf_cache:{cache_key}",
                            self.max_age_hours * 3600,
                            pickle.dumps(entry.to_dict())
                        )
                    except Exception as e:
                        self._log(f"⚠️ Redis缓存存储失败: {e}")
                
                # 3. 存储到文件缓存
                try:
                    cache_file = self._get_cache_file_path(cache_key)
                    with open(cache_file, 'wb') as f:
                        pickle.dump(entry.to_dict(), f)
                except Exception as e:
                    self._log(f"⚠️ 文件缓存存储失败: {e}")
                
                self.stats['files_cached'] += 1
                self._update_cache_size()
                
                return True
                
            except Exception as e:
                self._log(f"❌ 缓存设置失败: {e}")
                return False
    
    def _evict_memory_cache(self):
        """内存缓存淘汰策略：LRU"""
        if not self.memory_cache:
            return
            
        # 按最后访问时间排序，删除最久未使用的条目
        sorted_items = sorted(
            self.memory_cache.items(),
            key=lambda x: x[1].last_access
        )
        
        # 删除最老的25%条目
        remove_count = max(1, len(sorted_items) // 4)
        for i in range(remove_count):
            cache_key, _ = sorted_items[i]
            del self.memory_cache[cache_key]
    
    def _cleanup_expired_cache(self):
        """清理过期缓存"""
        cleaned_files = 0
        cleaned_size = 0
        
        try:
            # 清理文件缓存
            for cache_file in self.cache_dir.rglob("*.cache"):
                try:
                    with open(cache_file, 'rb') as f:
                        entry_dict = pickle.load(f)
                        entry = CacheEntry.from_dict(entry_dict)
                    
                    if entry.is_expired(self.max_age_hours):
                        file_size = cache_file.stat().st_size
                        cache_file.unlink()
                        cleaned_files += 1
                        cleaned_size += file_size
                        
                except Exception:
                    # 损坏的缓存文件，直接删除
                    try:
                        file_size = cache_file.stat().st_size
                        cache_file.unlink()
                        cleaned_files += 1
                        cleaned_size += file_size
                    except Exception:
                        pass
            
            if cleaned_files > 0:
                self._log(f"🧹 清理了 {cleaned_files} 个过期缓存文件，释放 {cleaned_size/1024/1024:.1f} MB空间")
                
        except Exception as e:
            self._log(f"⚠️ 缓存清理失败: {e}")
    
    def _update_cache_size(self):
        """更新缓存大小统计"""
        try:
            total_size = 0
            for cache_file in self.cache_dir.rglob("*.cache"):
                try:
                    total_size += cache_file.stat().st_size
                except Exception:
                    pass
            
            self.stats['cache_size_mb'] = total_size / 1024 / 1024
            
            # 如果缓存大小超过限制，清理旧文件
            if self.stats['cache_size_mb'] > self.max_disk_size_mb:
                self._cleanup_large_cache()
                
        except Exception as e:
            self._log(f"⚠️ 缓存大小统计失败: {e}")
    
    def _cleanup_large_cache(self):
        """清理过大的缓存"""
        try:
            # 收集所有缓存文件信息
            cache_files = []
            for cache_file in self.cache_dir.rglob("*.cache"):
                try:
                    stat = cache_file.stat()
                    cache_files.append((cache_file, stat.st_mtime, stat.st_size))
                except Exception:
                    pass
            
            # 按修改时间排序，删除最老的文件
            cache_files.sort(key=lambda x: x[1])
            
            cleaned_size = 0
            cleaned_files = 0
            target_size = self.max_disk_size_mb * 1024 * 1024 * 0.8  # 清理到80%
            
            for cache_file, mtime, size in cache_files:
                if cleaned_size >= (self.stats['cache_size_mb'] * 1024 * 1024 - target_size):
                    break
                    
                try:
                    cache_file.unlink()
                    cleaned_size += size
                    cleaned_files += 1
                except Exception:
                    pass
            
            if cleaned_files > 0:
                self._log(f"🧹 缓存空间清理: 删除了 {cleaned_files} 个文件，释放 {cleaned_size/1024/1024:.1f} MB")
                self._update_cache_size()
                
        except Exception as e:
            self._log(f"⚠️ 缓存空间清理失败: {e}")
    
    def clear(self):
        """清空所有缓存"""
        with self.lock:
            # 清空内存缓存
            self.memory_cache.clear()
            
            # 清空Redis缓存
            if self.redis_client:
                try:
                    # 使用scan_iter更安全地遍历和删除键
                    keys_to_delete = []
                    for key in self.redis_client.scan_iter(match="pdf_cache:*"):
                        keys_to_delete.append(key)
                    
                    if keys_to_delete:
                        # 分批删除，避免一次性删除太多键
                        batch_size = 1000
                        for i in range(0, len(keys_to_delete), batch_size):
                            batch = keys_to_delete[i:i+batch_size]
                            self.redis_client.delete(*batch)
                except Exception as e:
                    self._log(f"⚠️ Redis缓存清空失败: {e}")
            
            # 清空文件缓存
            try:
                import shutil
                if self.cache_dir.exists():
                    shutil.rmtree(self.cache_dir)
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self._log(f"⚠️ 文件缓存清空失败: {e}")
            
            # 重置统计
            self.stats = {
                'hits': 0,
                'misses': 0,
                'disk_hits': 0,
                'memory_hits': 0,
                'redis_hits': 0,
                'files_cached': 0,
                'cache_size_mb': 0.0
            }
            
            self._log("🧹 所有缓存已清空")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self.lock:
            total_requests = self.stats['hits'] + self.stats['misses']
            hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0
            
            return {
                **self.stats,
                'memory_items': len(self.memory_cache),
                'hit_rate_percent': round(hit_rate, 2),
                'total_requests': total_requests
            }
    
    def print_stats(self):
        """打印缓存统计信息"""
        stats = self.get_stats()
        
        self._log("📊 缓存统计信息:")
        self._log(f"   🎯 命中率: {stats['hit_rate_percent']:.1f}% ({stats['hits']}/{stats['total_requests']})")
        self._log(f"   🧠 内存命中: {stats['memory_hits']}")
        self._log(f"   💽 磁盘命中: {stats['disk_hits']}")
        if self.enable_redis:
            self._log(f"   🔴 Redis命中: {stats['redis_hits']}")
        self._log(f"   📁 缓存文件数: {stats['files_cached']}")
        self._log(f"   💾 内存缓存条目: {stats['memory_items']}")
        self._log(f"   📏 磁盘缓存大小: {stats['cache_size_mb']:.1f} MB")