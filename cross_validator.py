#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
职称评审材料交叉检验系统 - 核心模块
"""

import os
import pandas as pd
import zipfile
import tempfile
import shutil
from typing import Dict, List, Tuple, Optional, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path
import re
from datetime import datetime
import json
import threading
import random
import queue
import hashlib

from google import genai
from google.genai import types
from pypdf import PdfReader
import concurrent.futures
from functools import partial
import time

# 导入改进的缓存管理器
from cache_manager import SmartCacheManager

class APIRotator:
    """
    API轮询管理器 - 管理多个API密钥的轮询使用
    """
    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys if api_keys else []
        self.current_index = 0
        self.clients = {}
        self.usage_count = {key: 0 for key in self.api_keys}
        self.last_use_time = {key: 0.0 for key in self.api_keys}
        self.error_count = {key: 0 for key in self.api_keys}
        # 🚀 新增：性能监控相关属性
        self.response_times = {key: [] for key in self.api_keys}  # 存储最近10次响应时间
        self.avg_response_time = {key: 0.0 for key in self.api_keys}  # 平均响应时间
        self.success_count = {key: 0 for key in self.api_keys}  # 成功调用次数
        self.blacklisted = set()
        self.lock = threading.Lock()
        
        # 初始化所有客户端
        for api_key in self.api_keys:
            try:
                self.clients[api_key] = genai.Client(api_key=api_key)
            except Exception as e:
                print(f"⚠️ API密钥初始化失败: {api_key[:10]}... - {e}")
                self.blacklisted.add(api_key)
    
    def get_next_client(self) -> Tuple[genai.Client, str]:
        """获取下一个可用的API客户端 - 优化版：使用轮询策略减少锁竞争"""
        with self.lock:
            if not self.api_keys:
                raise ValueError("未配置任何API密钥")
            
            # 过滤掉被黑名单的API
            available_keys = [key for key in self.api_keys if key not in self.blacklisted]
            
            if not available_keys:
                # 如果所有API都被黑名单了，重置黑名单（可能是临时问题）
                self.blacklisted.clear()
                self.error_count = {key: 0 for key in self.api_keys}
                available_keys = self.api_keys
            
            # 🚀 优化：使用轮询策略而非最少使用次数，从 O(n) 优化到 O(1)
            if len(available_keys) == 1:
                selected_key = available_keys[0]
            else:
                # 找到当前索引对应的可用密钥
                available_indices = [self.api_keys.index(key) for key in available_keys]
                
                # 从当前索引开始找下一个可用的
                next_index = self.current_index
                while next_index not in available_indices:
                    next_index = (next_index + 1) % len(self.api_keys)
                    if next_index == self.current_index:  # 防止无限循环
                        next_index = available_indices[0]
                        break
                
                selected_key = self.api_keys[next_index]
                # 更新下次的索引
                self.current_index = (next_index + 1) % len(self.api_keys)
            
            # 更新使用统计（保留统计功能）
            self.usage_count[selected_key] += 1
            self.last_use_time[selected_key] = time.time()
            
            return self.clients[selected_key], selected_key
    
    def report_error(self, api_key: str, error: Exception):
        """报告API调用错误"""
        with self.lock:
            self.error_count[api_key] += 1
            
            # 如果某个API连续错误超过3次，临时加入黑名单
            if self.error_count[api_key] >= 3:
                self.blacklisted.add(api_key)
                print(f"🚫 API密钥临时禁用: {api_key[:10]}... (连续错误{self.error_count[api_key]}次)")
    
    def report_success(self, api_key: str, response_time: float = 0.0):
        """报告API调用成功（优化：增加响应时间统计）"""
        with self.lock:
            # 成功调用后重置错误计数
            if self.error_count[api_key] > 0:
                self.error_count[api_key] = max(0, self.error_count[api_key] - 1)
            
            # 如果错误次数降到0，从黑名单移除
            if self.error_count[api_key] == 0 and api_key in self.blacklisted:
                self.blacklisted.remove(api_key)
            
            # 🚀 新增：记录成功统计和响应时间
            self.success_count[api_key] += 1
            
            if response_time > 0:
                # 记录响应时间（保留最近10次）
                if len(self.response_times[api_key]) >= 10:
                    self.response_times[api_key].pop(0)  # 移除最旧的记录
                self.response_times[api_key].append(response_time)
                
                # 更新平均响应时间
                if self.response_times[api_key]:
                    self.avg_response_time[api_key] = sum(self.response_times[api_key]) / len(self.response_times[api_key])
    
    def get_status(self) -> Dict[str, Any]:
        """获取API使用状态（优化：增加性能统计）"""
        with self.lock:
            return {
                "total_apis": len(self.api_keys),
                "available_apis": len(self.api_keys) - len(self.blacklisted),
                "blacklisted_apis": len(self.blacklisted),
                "usage_stats": dict(self.usage_count),
                "error_stats": dict(self.error_count),
                # 🚀 新增：性能监控统计
                "success_stats": dict(self.success_count),
                "avg_response_times": dict(self.avg_response_time),
                "performance_ranking": self._get_performance_ranking()
            }
    
    def _get_performance_ranking(self) -> List[str]:
        """根据性能排列API（响应时间优先，成功率次之）"""
        available_keys = [key for key in self.api_keys if key not in self.blacklisted]
        
        # 按平均响应时间排序（响应时间越短越好）
        def performance_score(api_key):
            avg_time = self.avg_response_time[api_key]
            success_rate = self.success_count[api_key] / max(1, self.usage_count[api_key])
            # 综合评分：响应时间越短、成功率越高越好
            if avg_time > 0:
                return success_rate / avg_time  # 成功率/响应时间
            else:
                return success_rate  # 没有响应时间数据时只看成功率
        
        return sorted(available_keys, key=performance_score, reverse=True)

@dataclass
class RuleItem:
    序号: int; 文件类型: str; 核心问题: str; 补充规则: str = ""; 规则内容: str = ""; 优先级: str = "中"; 备注: str = ""; 填写人: str = ""; source_file: str = ""

@dataclass
class MaterialInfo:
    id: int; name: str; file_path: Optional[str] = None; content: Optional[str] = None; is_empty: bool = True
    core_info: Dict[str, Any] = field(default_factory=dict); rule_violations: List[str] = field(default_factory=list)
    processing_method: str = "未处理"; applicable_rules: List[RuleItem] = field(default_factory=list)

class CrossValidator:
    MATERIAL_NAMES = {
        1: "教育经历", 2: "工作经历", 3: "继续教育(培训情况)", 4: "学术技术兼职情况",
        5: "获奖情况", 6: "获得荣誉称号情况", 7: "主持参与科研项目(基金)情况", 8: "主持参与工程技术项目情况",
        9: "论文", 10: "著(译)作(教材)", 11: "专利(著作权)情况", 12: "主持参与指定标准情况",
        13: "成果被批示、采纳、运用和推广情况", 14: "资质证书", 15: "奖惩情况", 16: "考核情况", 17: "申报材料附件信息"
    }
    
    def __init__(self, api_key: Optional[str] = None, api_keys: Optional[List[str]] = None, rules_dir: str = "rules", progress_callback: Optional[Callable[[str], None]] = None, cache_config: Optional[Dict[str, Any]] = None):
        # 首先设置回调函数
        self.progress_callback = progress_callback or (lambda msg: None)
        
        # API轮询配置
        if api_keys and len(api_keys) > 1:
            # 使用多个API密钥轮询
            self.api_rotator = APIRotator(api_keys)
            self.use_rotation = True
            self._log(f"🔄 启用API轮询模式: {len(api_keys)}个API密钥")
        elif api_key:
            # 使用单个API密钥
            self.api_rotator = APIRotator([api_key])
            self.use_rotation = False
            self._log(f"🔑 使用单个API密钥模式")
        else:
            raise ValueError("必须提供 api_key 或 api_keys 参数")
        
        self.rules_dir = Path(rules_dir)
        # 初始化第一个客户端作为默认客户端
        self.client, _ = self.api_rotator.get_next_client()
        self.materials: Dict[int, MaterialInfo] = {i: MaterialInfo(id=i, name=self.MATERIAL_NAMES[i]) for i in range(1, 18)}
        self.rules: List[RuleItem] = []
        self.high_priority_violations: List[str] = []
        self.validation_results = {"empty_materials": [], "final_report": ""}
        
        # 初始化改进的缓存管理器
        cache_config = cache_config or {}
        self.cache_manager = SmartCacheManager(
            cache_dir=cache_config.get('cache_dir'),
            max_age_hours=cache_config.get('max_age_hours', 24),
            max_memory_items=cache_config.get('max_memory_items', 100),
            max_disk_size_mb=cache_config.get('max_disk_size_mb', 1000),
            enable_redis=cache_config.get('enable_redis', False),
            redis_url=cache_config.get('redis_url'),
            progress_callback=self.progress_callback
        )
        
        # 保持兼容性，但使用新的缓存管理器
        # self.content_cache: Dict[str, str] = {}  # 已被 SmartCacheManager 替代
        
        # 添加速率限制相关属性
        self.last_api_call_time = 0
        self.min_call_interval = 0.1  # 最小调用间隔为0.1秒
        self.progress_callback("初始化交叉检验系统...")
        self.load_rules()

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return self.cache_manager.get_stats()
    
    def print_cache_stats(self):
        """打印缓存统计信息"""
        self.cache_manager.print_stats()
    
    def clear_cache(self):
        """清空所有缓存"""
        self.cache_manager.clear()
        self._log("🧤 所有缓存已清空")
    
    def _log(self, message: str):
        self.progress_callback(message)

    def _rotated_api_call(self, call_func: Callable, max_retries: int = 3) -> Any:
        """
        使用API轮询机制进行API调用（优化：增加响应时间监控）
        """
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                # 获取下一个可用的客户端
                client, api_key = self.api_rotator.get_next_client()
                
                # 速率限制
                current_time = time.time()
                if current_time - self.last_api_call_time < self.min_call_interval:
                    time.sleep(self.min_call_interval - (current_time - self.last_api_call_time))
                
                # 🚀 优化：记录响应时间
                call_start_time = time.time()
                
                # 执行API调用
                result = call_func(client)
                
                # 计算响应时间
                response_time = time.time() - call_start_time
                self.last_api_call_time = time.time()
                
                # 报告成功（包含响应时间）
                self.api_rotator.report_success(api_key, response_time)
                
                if self.use_rotation:
                    # 记录成功使用的API和性能信息
                    self._log(f"  🔄 API轮询: 使用 {api_key[:10]}... (响应 {response_time:.2f}s, 尝试 {attempt+1}/{max_retries})")
                
                return result
                
            except Exception as e:
                last_exception = e
                
                # 报告错误
                current_api_key = ""
                if hasattr(self, 'api_rotator'):
                    try:
                        client, current_api_key = self.api_rotator.get_next_client()  # 获取当前使用的key
                        self.api_rotator.report_error(current_api_key, e)
                    except Exception:
                        current_api_key = "unknown"
                
                # 判断是否为速率限制错误
                error_str = str(e).lower()
                if any(keyword in error_str for keyword in ['rate limit', 'quota', 'too many requests', '429']):
                    self._log(f"  ⚠️ API速率限制: {current_api_key[:10]}... 等待后重试 ({attempt+1}/{max_retries})")
                    # 速率限制时等待更长时间
                    wait_time = (2 ** attempt) * (1 + random.uniform(0, 0.5))  # 指数退避 + 随机抖动
                    time.sleep(min(wait_time, 60))  # 最多等待60秒
                elif 'invalid api key' in error_str or 'api_key_invalid' in error_str:
                    self._log(f"  ❌ API密钥无效: {current_api_key[:10]}... 尝试下一个")
                    # API密钥无效时不等待，直接尝试下一个
                    pass
                else:
                    self._log(f"  ⚠️ API调用失败: {str(e)[:50]}... 等待后重试 ({attempt+1}/{max_retries})")
                    time.sleep(2 ** attempt)  # 普通错误的指数退避
        
        # 所有重试都失败后，抛出最后一个异常
        raise last_exception or Exception(f"API调用失败，已重试{max_retries}次")

    def _smart_truncate_content(self, content: str, max_length: int = 200000, head_size: int = 5000, tail_size: int = 5000) -> str:
        """
        智能截取内容：当内容超过max_length时，保留头部head_size字符和尾部tail_size字符
        
        Args:
            content: 要截取的内容
            max_length: 最大长度阈值，默认200000字符
            head_size: 头部保留字符数，默认5000字符
            tail_size: 尾部保留字符数，默认5000字符
            
        Returns:
            截取后的内容
        """
        if not content or len(content) <= max_length:
            return content
            
        # 计算省略的字符数
        omitted_chars = len(content) - head_size - tail_size
        
        # 构建截取后的内容
        head_part = content[:head_size]
        tail_part = content[-tail_size:] if tail_size > 0 else ""
        
        truncated_content = (
            head_part + 
            f"\n\n[... 中间省略 {omitted_chars:,} 个字符 ...]\n\n" + 
            tail_part
        )
        
        return truncated_content

    def _safe_basename(self, file_path: str) -> str:
        """安全地获取文件名，确保中文文件名正确显示"""
        try:
            # 获取基本文件名
            basename = os.path.basename(file_path)
            
            # 处理字节数组格式
            if isinstance(basename, bytes):
                # 尝试用不同编码解码
                for encoding in ['utf-8', 'gbk', 'cp936', 'cp437']:
                    try:
                        return basename.decode(encoding)
                    except UnicodeDecodeError:
                        continue
                # 如果都失败了，使用错误处理
                return basename.decode('utf-8', errors='replace')
            
            # 处理字符串格式，清理可能存在的问题字符
            # 移除或替换不可读字符
            cleaned_name = ''.join(c if ord(c) < 65536 and c.isprintable() or c in '一-鿿' else '_' for c in basename)
            
            # 如果清理后的文件名为空或太短，返回默认值
            if not cleaned_name or len(cleaned_name) < 2:
                return "未知文件"
                
            return cleaned_name
            
        except Exception as e:
            # 如果所有尝试都失败，返回安全的默认值
            return f"文件处理错误_{str(e)[:10]}"

    def _detect_zip_encoding(self, zip_path: str) -> str:
        """检测ZIP文件的编码方式"""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # 检查文件名中是否包含中文或特殊字符
                has_chinese_files = False
                has_encoding_issues = False
                
                for file_info in zf.filelist:
                    filename = file_info.filename
                    
                    # 检测是否包含中文字符
                    if any('一' <= c <= '鿿' for c in filename):
                        has_chinese_files = True
                    
                    # 检测是否包含编码问题的字符
                    if any(ord(c) > 127 and not ('一' <= c <= '鿿') for c in filename):
                        has_encoding_issues = True
                
                if has_chinese_files and not has_encoding_issues:
                    return "utf-8"  # 正常的UTF-8编码
                elif has_encoding_issues:
                    return "mixed"  # 混合编码，需要修复
                else:
                    return "ascii"  # 纯 ASCII文件名
                    
        except Exception:
            return "unknown"  # 无法检测

    def _try_alternative_zip_extraction(self, zip_path: str, temp_dir: str) -> bool:
        """尝试替代的ZIP解压方法"""
        self._log(f"  🔄 尝试替代解压方法...")
        
        try:
            # 方法1：使用不同的zipfile参数
            import codecs
            
            # 尝试使用cp437编码读取
            with zipfile.ZipFile(zip_path, 'r') as zf:
                success_count = 0
                total_count = len([f for f in zf.filelist if not f.filename.endswith('/')])
                
                for file_info in zf.filelist:
                    if file_info.filename.endswith('/'):
                        continue
                        
                    try:
                        # 尝试编码转换
                        original_name = file_info.filename
                        
                        # 尝试多种解码方案
                        for encoding in ['utf-8', 'gbk', 'cp936', 'big5']:
                            try:
                                # 先编码为cp437，再用目标编码解码
                                encoded_bytes = original_name.encode('cp437')
                                decoded_name = encoded_bytes.decode(encoding)
                                
                                # 检查解码后是否包含中文
                                if any('一' <= c <= '鿿' for c in decoded_name):
                                    # 使用解码后的文件名
                                    file_info.filename = decoded_name
                                    self._log(f"    🔧 编码修复: {original_name[:20]}... -> {decoded_name[:20]}...")
                                    break
                                    
                            except (UnicodeDecodeError, UnicodeEncodeError):
                                continue
                        
                        # 确保目录存在
                        file_dir = os.path.dirname(os.path.join(temp_dir, file_info.filename))
                        if file_dir:
                            os.makedirs(file_dir, exist_ok=True)
                        
                        # 解压文件
                        extracted_path = zf.extract(file_info, temp_dir)
                        success_count += 1
                        
                    except Exception as e:
                        # 记录但不停止处理
                        self._log(f"    ⚠️ 跳过文件: {self._safe_basename(file_info.filename)} - {str(e)[:30]}...")
                
                self._log(f"  📊 替代解压结果: {success_count}/{total_count} 文件成功")
                return success_count > 0
                
        except Exception as e:
            self._log(f"  ❌ 替代解压方法也失败: {e}")
            return False

    def _normalize_filename(self, filename: str) -> str:
        """标准化文件名，处理特殊字符和编码问题"""
        try:
            # 移除或替换问题字符
            # 列出一些常见的问题字符
            problem_chars = {
                '（': '(',  # 全角括号
                '）': ')',
                '，': ',',  # 全角逗号
                '、': ',',  # 中文逗号
                '：': ':',  # 全角冒号
                '；': ';',  # 全角分号
                '“': '"', # 中文引号
                '”': '"',
                '‘': "'",
                '’': "'",
            }
            
            normalized = filename
            for old_char, new_char in problem_chars.items():
                normalized = normalized.replace(old_char, new_char)
            
            # 移除不可见字符和控制字符
            normalized = ''.join(c for c in normalized if c.isprintable() or ord(c) >= 0x4e00)
            
            return normalized if normalized else "清理后的文件"
            
        except Exception:
            return filename  # 如果处理失败，返回原文件名
        """标准化文件名，处理特殊字符和编码问题"""
        try:
            # 移除或替换问题字符
            # 列出一些常见的问题字符
            problem_chars = {
                '（': '(',  # 全角括号
                '）': ')',
                '，': ',',  # 全角逗号
                '、': ',',  # 中文逗号
                '：': ':',  # 全角冒号
                '；': ';',  # 全角分号
                '“': '"', # 中文引号
                '”': '"',
                '‘': "'",
                '’': "'",
            }
            
            normalized = filename
            for old_char, new_char in problem_chars.items():
                normalized = normalized.replace(old_char, new_char)
            
            # 移除不可见字符和控制字符
            normalized = ''.join(c for c in normalized if c.isprintable() or ord(c) >= 0x4e00)
            
            return normalized if normalized else "清理后的文件"
            
        except Exception:
            return filename  # 如果处理失败，返回原文件名

    def _load_markdown_rules(self, md_file: Path):
        try:
            content = md_file.read_text(encoding='utf-8')
            rule_blocks = re.split(r'\n#\s+', content)
            if not rule_blocks[0].startswith('#'): rule_blocks[0] = '# ' + rule_blocks[0]
            md_rule_count = 0
            for i, block in enumerate(rule_blocks):
                if not block.strip(): continue
                lines = block.strip().split('\n')
                core_issue, rule_content = lines[0].strip().lstrip('# '), "\n".join(lines[1:]).strip()
                if core_issue and rule_content:
                    self.rules.append(RuleItem(序号=1000 + i, 文件类型="整体", 核心问题=core_issue, 规则内容=rule_content, 优先级="极高", 备注="来自通用规则.md"))
                    md_rule_count += 1
            self._log(f"  ✅ 成功加载 {md_rule_count} 条通用Markdown规则")
        except Exception as e:
            self._log(f"❌ 加载通用规则.md失败: {e}")

    def load_rules(self):
        self._log("📋 开始加载规则集...")
        markdown_rule_file = self.rules_dir / "通用规则.md"
        if markdown_rule_file.exists(): self._load_markdown_rules(markdown_rule_file)
        else: self._log("  ℹ️ 未找到通用规则.md文件，跳过加载。")
        for excel_file in self.rules_dir.glob("*.xlsx"):
            self._log(f"  📄 正在加载Excel规则: {excel_file.name}")
            self._load_single_rule_file(excel_file)
        self._log(f"📊 规则集加载完成: 共 {len(self.rules)} 条规则")

    def _load_single_rule_file(self, rules_file: Path):
        try:
            df = pd.read_excel(rules_file)
            file_name = rules_file.name  # 获取文件名
            for _, row in df.iterrows():
                try:
                    # 安全地检查pandas的nan值
                    序号_val = row.get('序号')
                    核心问题_val = row.get('核心问题')
                    
                    # 使用bool()函数显式转换来避免pandas的__bool__问题
                    if bool(pd.notna(序号_val)) and bool(pd.notna(核心问题_val)):
                        # 安全的类型转换
                        try:
                            序号_int = int(序号_val) if 序号_val is not None else 0
                        except (ValueError, TypeError):
                            序号_int = 0
                            
                        rule = RuleItem(
                            序号=序号_int, 
                            文件类型=str(row.get('文件类型', '')).strip(), 
                            核心问题=str(核心问题_val).strip(), 
                            规则内容=str(row.get('规则内容（越详细越好）', '')).strip(), 
                            优先级=str(row.get('优先级', '中')).strip(),
                            source_file=file_name  # 记录来源文件
                        )
                        self.rules.append(rule)
                except Exception as e:
                    self._log(f"    ⚠️ 跳过无效规则行: {e}")
                    continue
        except Exception as e:
            self._log(f"❌ 加载Excel规则 {rules_file.name} 失败: {e}")

    def process_materials_from_zip(self, zip_path: str, temp_dir: str):
        self._log(f"📦 开始从 {os.path.basename(zip_path)} 提取材料...")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref: 
                # 修复中文文件名乱码问题 - 增强版
                fixed_count = 0
                total_files = len(zip_ref.filelist)
                self._log(f"  📁 检测到 {total_files} 个文件/目录")
                
                # 创建一个新的文件信息列表，修复编码问题
                for i, file_info in enumerate(zip_ref.filelist):
                    original_filename = file_info.filename
                    
                    # 跳过空文件名
                    if not original_filename:
                        continue
                        
                    # 显示处理进度
                    if total_files > 10 and i % max(1, total_files // 10) == 0:
                        self._log(f"  🔄 处理文件名进度: {i+1}/{total_files}")
                    
                    # 尝试多种编码修复方案
                    try:
                        # 检测是否包含中文或特殊字符
                        has_chinese = any(ord(c) > 127 for c in original_filename if isinstance(c, str))
                        
                        if has_chinese:
                            # 尝试不同的编码转换方案
                            encoding_attempts = [
                                ('cp437', 'gbk'),      # 常见的Windows ZIP编码问题
                                ('cp437', 'utf-8'),    # 另一种可能的编码
                                ('cp437', 'cp936'),    # 中文Windows编码
                                ('latin1', 'gbk'),     # Latin1到GBK
                                ('iso-8859-1', 'utf-8') # ISO到UTF-8
                            ]
                            
                            for from_enc, to_enc in encoding_attempts:
                                try:
                                    # 尝试编码转换
                                    encoded_bytes = original_filename.encode(from_enc)
                                    fixed_filename = encoded_bytes.decode(to_enc)
                                    
                                    # 验证转换后的文件名是否合理
                                    if fixed_filename != original_filename and len(fixed_filename) > 0:
                                        # 检查是否包含中文字符
                                        if any('一' <= c <= '鿿' for c in fixed_filename):
                                            file_info.filename = fixed_filename
                                            fixed_count += 1
                                            self._log(f"  🔧 修复文件名编码 ({from_enc}->{to_enc}): {original_filename[:30]}... -> {fixed_filename[:30]}...")
                                            break
                                            
                                except (UnicodeEncodeError, UnicodeDecodeError, UnicodeError):
                                    continue
                            
                            # 如果所有编码转换都失败，尝试清理文件名
                            if file_info.filename == original_filename:
                                cleaned_filename = self._normalize_filename(original_filename)
                                if cleaned_filename != original_filename:
                                    file_info.filename = cleaned_filename
                                    fixed_count += 1
                                    self._log(f"  🧼 清理文件名: {original_filename[:30]}... -> {cleaned_filename[:30]}...")
                                    
                    except Exception as e:
                        self._log(f"  ⚠️ 处理文件名时出错: {original_filename[:20]}... - {e}")
                
                if fixed_count > 0:
                    self._log(f"  ✅ 成功修复 {fixed_count} 个文件名的编码问题")
                else:
                    self._log(f"  📝 未发现需要修复的文件名编码问题")
                
                # 执行解压，使用容错模式
                try:
                    self._log(f"  📦 开始解压文件...")
                    zip_ref.extractall(temp_dir)
                    self._log(f"  ✅ 文件解压完成")
                    
                except Exception as extract_error:
                    error_msg = str(extract_error)
                    self._log(f"  ⚠️ 标准解压失败: {error_msg}")
                    
                    # 分析错误类型
                    if "There is no item named" in error_msg:
                        self._log(f"  🔍 检测到文件名编码问题，尝试逐个文件解压...")
                    else:
                        self._log(f"  🔍 检测到其他解压问题，尝试替代方案...")
                    
                    # 逐个文件解压，跳过有问题的文件
                    success_count = 0
                    error_count = 0
                    
                    for file_info in zip_ref.filelist:
                        try:
                            # 跳过目录
                            if file_info.filename.endswith('/'):
                                continue
                                
                            # 确保目录存在
                            file_dir = os.path.dirname(os.path.join(temp_dir, file_info.filename))
                            if file_dir:
                                os.makedirs(file_dir, exist_ok=True)
                            
                            # 解压单个文件
                            zip_ref.extract(file_info, temp_dir)
                            success_count += 1
                            
                        except Exception as file_error:
                            error_count += 1
                            safe_filename = self._safe_basename(file_info.filename)
                            self._log(f"    ❌ 跳过无法解压的文件: {safe_filename} - {str(file_error)[:50]}...")
                    
                    self._log(f"  📊 解压结果: 成功 {success_count} 个文件，跳过 {error_count} 个问题文件")
                    
                    if success_count == 0:
                        raise Exception(f"无法解压任何文件，ZIP文件可能损坏或编码不兼容")
                        
        except Exception as e:
            self._log(f"❌ 解压ZIP文件失败: {e}")
            self._log(f"💡 建议解决方案:")
            self._log(f"  1. 检查ZIP文件是否完整无损坏")
            self._log(f"  2. 尝试使用7-Zip或WinRAR重新打包文件")
            self._log(f"  3. 确保文件名不包含特殊字符如: < > : \" | ? * ")
            self._log(f"  4. 尝试使用UTF-8编码重新创建ZIP文件")
            return
        material_files = self._map_files_to_materials(temp_dir)
        
        # 使用线程池并发处理PDF文件，实现大文件绝对优先的并发策略
        optimal_workers = min(8, len(self.api_rotator.api_keys)) if len(self.api_rotator.api_keys) > 1 else 3  # 提升并发数
        
        # 智能分组：按文件大小严格分组，确保大文件绝对优先
        large_materials = {}  # ≥5MB的材料组
        medium_materials = {}  # 1-5MB的材料组  
        small_materials = {}  # <1MB的材料组
        
        for mid, files in material_files.items():
            if not files:
                continue
                
            # 计算材料组的总文件大小
            total_size = 0
            for file_path in files:
                try:
                    total_size += os.path.getsize(file_path)
                except:
                    pass
            
            # 按总大小分组（确保大材料优先处理）
            if total_size >= 5 * 1024 * 1024:  # ≥5MB
                large_materials[mid] = files
            elif total_size >= 1 * 1024 * 1024:  # 1-5MB  
                medium_materials[mid] = files
            else:  # <1MB
                small_materials[mid] = files
        
        self._log(f"  📊 材料智能分组: 大材料组{len(large_materials)}个 > 中材料组{len(medium_materials)}个 > 小材料组{len(small_materials)}个")
        
        # 三阶段并发处理策略：严格按大小优先
        all_material_groups = [
            (large_materials, "🚀 【第一阶段】大材料组并发处理", optimal_workers),
            (medium_materials, "⚡ 【第二阶段】中材料组并发处理", max(optimal_workers//2, 2)),
            (small_materials, "📝 【第三阶段】小材料组并发处理", max(optimal_workers//3, 1))
        ]
        
        total_processed = 0
        for materials_group, phase_name, workers in all_material_groups:
            if not materials_group:
                continue
                
            self._log(f"  {phase_name}: {len(materials_group)}个材料, 使用{workers}个工作线程")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                extract_func = partial(self._extract_single_file_content_wrapper)
                
                # 提交当前阶段的所有任务
                future_to_mid = {}
                for mid, files in materials_group.items():
                    future = executor.submit(extract_func, mid, files)
                    future_to_mid[future] = mid
                
                # 收集当前阶段结果，改进超时处理
                phase_completed = 0
                unfinished_futures = set(future_to_mid.keys())
                
                try:
                    for future in concurrent.futures.as_completed(future_to_mid, timeout=600):  # 10分钟阶段超时
                        mid = future_to_mid[future]
                        unfinished_futures.discard(future)  # 移除已完成的future
                        
                        try:
                            content = future.result(timeout=180)  # 单任务3分钟超时
                            if content and len(content.strip()) > 50:
                                self.materials[mid].is_empty = False
                                self.materials[mid].content = content
                                phase_completed += 1
                                total_processed += 1
                                self._log(f"  ✅ 材料{mid}处理完成 ({phase_completed}/{len(materials_group)}): {len(content.strip())}字符")
                            else:
                                self._log(f"  ⚠️ 材料{mid}内容过少 ({phase_completed}/{len(materials_group)})")
                                self.materials[mid].content = content or f"材料{mid}内容为空"
                                phase_completed += 1
                                total_processed += 1
                        except Exception as e:
                            error_msg = str(e)[:100]
                            self._log(f"  ❌ 材料{mid}处理失败 ({phase_completed}/{len(materials_group)}): {error_msg}...")
                            self.materials[mid].content = f"材料{mid}处理失败: {error_msg}"
                            phase_completed += 1
                            total_processed += 1
                            
                except concurrent.futures.TimeoutError:
                    self._log(f"  ⏰ {phase_name}阶段超时，有{len(unfinished_futures)}个任务未完成")
                    
                    # 处理未完成的futures
                    for future in unfinished_futures:
                        mid = future_to_mid[future]
                        try:
                            # 尝试取消未完成的任务
                            if not future.done():
                                future.cancel()
                            self.materials[mid].content = f"材料{mid}处理超时"
                            phase_completed += 1
                            total_processed += 1
                            self._log(f"  ⏰ 材料{mid}超时处理 ({phase_completed}/{len(materials_group)})")
                        except Exception as e:
                            self._log(f"  ❌ 材料{mid}超时处理失败: {e}")
                
                # 确保所有材料都被处理（兜底处理）
                for mid in materials_group.keys():
                    if self.materials[mid].content is None:
                        self.materials[mid].content = f"材料{mid}未被处理"
                        phase_completed += 1
                        total_processed += 1
                        self._log(f"  ⚠️ 材料{mid}兜底处理 ({phase_completed}/{len(materials_group)})")
            
            self._log(f"  🏁 {phase_name}完成: {phase_completed}/{len(materials_group)}个材料")
        
        self._log(f"  📊 三阶段处理完成: 总计处理 {total_processed} 个材料")
        
        # 检查材料完整性和规则匹配
        self.check_empty_materials()
        self._match_rules_to_materials()
        
        # 输出处理结果摘要
        total_materials = len(self.materials)
        valid_materials = sum(1 for m in self.materials.values() if not m.is_empty)
        empty_materials = total_materials - valid_materials
        
        self._log(f"  📈 处理结果摘要:")
        self._log(f"    - 有效材料: {valid_materials}/{total_materials}")
        self._log(f"    - 空材料: {empty_materials}/{total_materials}")
        self._log(f"    - 加载规则: {len(self.rules)} 条")
        
        # 显示缓存统计信息
        self.print_cache_stats()
        
        if valid_materials == 0:
            self._log(f"  ⚠️ 警告: 没有有效材料，将生成空报告")
        else:
            self._log(f"  ✅ 系统将继续处理 {valid_materials} 个有效材料")
        
        # 强制推进标记
        self._force_continue = True
    
    def _fallback_individual_extraction(self, zip_ref, temp_dir: str):
        """备用的逐个文件解压方法"""
        self._log(f"  🔄 尝试逐个文件解压...")
        success_count = 0
        error_count = 0
        
        for file_info in zip_ref.filelist:
            try:
                # 跳过目录
                if file_info.filename.endswith('/'):
                    continue
                    
                # 确保目录存在
                file_dir = os.path.dirname(os.path.join(temp_dir, file_info.filename))
                if file_dir:
                    os.makedirs(file_dir, exist_ok=True)
                
                # 解压单个文件
                zip_ref.extract(file_info, temp_dir)
                success_count += 1
                
            except Exception as file_error:
                error_count += 1
                safe_filename = self._safe_basename(file_info.filename)
                self._log(f"    ❌ 跳过无法解压的文件: {safe_filename} - {str(file_error)[:50]}...")
        
        self._log(f"  📊 解压结果: 成功 {success_count} 个文件，跳过 {error_count} 个问题文件")
        
        if success_count == 0:
            raise Exception(f"无法解压任何文件，ZIP文件可能损坏或编码不兼容")
    
    def _extract_single_file_content_wrapper(self, mid: int, files: List[str]) -> str:
        """包装器函数，优化处理顺序：严格按大文件优先，增强多API并发处理"""
        contents = []
        material_name = self.MATERIAL_NAMES.get(mid, f"材料{mid}")
        processed_files = set()  # 防止重复处理
        
        try:
            self._log(f"    🔄 开始处理材料{mid}({material_name}): {len(files)}个文件 [大文件优先+增强并发模式]")
            
            # 去重处理：确保同一个文件不会被重复处理
            unique_files = list(dict.fromkeys(files))  # 保持顺序的去重
            if len(unique_files) != len(files):
                self._log(f"      🔄 发现重复文件，去重后: {len(unique_files)}个文件")
                files = unique_files
            
            # 智能文件排序：严格按大小降序，确保大文件绝对优先
            try:
                files_with_size = []
                for file_path in files:
                    try:
                        size = os.path.getsize(file_path)
                        files_with_size.append((file_path, size))
                    except:
                        files_with_size.append((file_path, 0))
                
                # 严格按文件大小排序（大文件绝对优先）
                files_with_size.sort(key=lambda x: x[1], reverse=True)
                files = [f[0] for f in files_with_size]
                
                # 显示文件处理顺序
                total_size = sum(f[1] for f in files_with_size)
                self._log(f"      📁 文件总大小: {total_size/1024/1024:.1f}MB")
                for i, (file_path, size) in enumerate(files_with_size[:3]):  # 只显示前3个最大的文件
                    filename = self._safe_basename(file_path)
                    self._log(f"      📋 处理顺序 #{i+1}: {filename} ({size/1024/1024:.1f}MB)")
                    
            except Exception as e:
                self._log(f"      ⚠️ 文件大小检查失败，使用原顺序: {e}")
            
            total_content_length = 0  # 跟踪总内容长度
            max_total_length = 300000  # 单个材料最大总长度
            
            # 重新分类文件：调整阈值，更多文件可以并发处理
            large_files = []  # 大文件列表，用于高优先级并发处理
            medium_files = []  # 中等文件列表，用于中优先级并发处理
            small_files = []  # 小文件列表，用于低优先级处理
            
            large_file_threshold = 5 * 1024 * 1024   # 5MB以上为大文件
            medium_file_threshold = 1 * 1024 * 1024  # 1MB-5MB为中等文件
            
            for file_path in files:
                try:
                    file_size = os.path.getsize(file_path)
                    if file_path.endswith('.pdf'):
                        if file_size >= large_file_threshold:
                            large_files.append(file_path)
                        elif file_size >= medium_file_threshold:
                            medium_files.append(file_path)
                        else:
                            small_files.append(file_path)
                    else:
                        small_files.append(file_path)  # 非PDF文件当作小文件
                except:
                    small_files.append(file_path)  # 无法获取大小的文件当作小文件处理
            
            self._log(f"      📄 智能分类: 大文件({len(large_files)}) > 中等文件({len(medium_files)}) > 小文件({len(small_files)})")
            
            # 第一阶段：高优先级处理大文件（≥5MB）
            if large_files:
                self._log(f"      🚀 【第一阶段】大文件并发处理: {len(large_files)} 个文件")
                large_file_contents = self._process_files_with_enhanced_concurrency(large_files, mid, "大文件")
                contents.extend(large_file_contents)
                
                # 更新已处理文件和内容长度
                for file_path in large_files:
                    processed_files.add(file_path)
                for content_item in large_file_contents:
                    total_content_length += len(content_item)
            
            # 第二阶段：中优先级处理中等文件（1-5MB）
            if medium_files and total_content_length < max_total_length * 0.8:  # 还有80%以上空间时处理
                self._log(f"      ⚡ 【第二阶段】中等文件并发处理: {len(medium_files)} 个文件")
                medium_file_contents = self._process_files_with_enhanced_concurrency(medium_files, mid, "中等文件")
                contents.extend(medium_file_contents)
                
                # 更新已处理文件和内容长度
                for file_path in medium_files:
                    processed_files.add(file_path)
                for content_item in medium_file_contents:
                    total_content_length += len(content_item)
            
            # 第三阶段：低优先级处理小文件（<1MB），采用批量并发或串行
            if small_files and total_content_length < max_total_length * 0.9:  # 还有90%以上空间时处理
                remaining_small_files = [f for f in small_files if f not in processed_files]
                if remaining_small_files:
                    if len(remaining_small_files) > 3 and len(self.api_rotator.api_keys) > 2:
                        # 如果小文件较多且有足够API，使用低强度并发
                        self._log(f"      🔥 【第三阶段】小文件批量并发处理: {len(remaining_small_files)} 个文件")
                        small_file_contents = self._process_files_with_enhanced_concurrency(remaining_small_files, mid, "小文件")
                        contents.extend(small_file_contents)
                        
                        for file_path in remaining_small_files:
                            processed_files.add(file_path)
                        for content_item in small_file_contents:
                            total_content_length += len(content_item)
                    else:
                        # 否则使用优化的串行处理
                        self._log(f"      📝 【第三阶段】小文件串行处理: {len(remaining_small_files)} 个文件")
                        for i, file_path in enumerate(remaining_small_files, 1):
                            filename = self._safe_basename(file_path)
                            self._log(f"      📄 处理小文件 {i}/{len(remaining_small_files)}: {filename}")
                            
                            try:
                                # 使用更精确的缓存键
                                import hashlib
                                file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]
                                cache_prefix = f"material_{mid}_file_{file_hash}"
                                
                                # 检查缓存
                                cached_content = self.cache_manager.get(file_path, cache_prefix)
                                if cached_content:
                                    content = cached_content
                                    self._log(f"      💾 使用缓存: {filename}")
                                else:
                                    # 提取内容
                                    if file_path.endswith('.pdf'):
                                        content = self._extract_pdf_content(file_path)
                                    else:
                                        content = f"跳过非PDF文件: {filename}"
                                    
                                    # 内容长度控制（使用头尾截取）
                                    if content and len(content) > 200000:
                                        self._log(f"      ⚠️ 小文件内容过大，头尾截取: {filename} ({len(content)}字符)")
                                        content = self._smart_truncate_content(content, max_length=200000, head_size=5000, tail_size=5000)
                                    
                                    # 存入缓存
                                    if content and content.strip():
                                        self.cache_manager.set(file_path, content, cache_prefix)
                                
                                if content and content.strip():
                                    content_length = len(content)
                                    if total_content_length + content_length > max_total_length:
                                        remaining_space = max_total_length - total_content_length
                                        if remaining_space > 3000:
                                            content = content[:remaining_space-1000] + f"\n\n[总长度限制截取]"
                                            content_length = len(content)
                                        else:
                                            self._log(f"      ⚠️ 材料总长度已达限制，停止处理: {filename}")
                                            break
                                    
                                    # 格式化内容
                                    formatted_content = f"--- 文件: {filename} ---\n{content}"
                                    contents.append(formatted_content)
                                    total_content_length += content_length
                                    processed_files.add(file_path)
                                    
                                    self._log(f"      ✅ 小文件处理成功: {filename} ({content_length}字符)")
                                else:
                                    self._log(f"      ⚠️ 小文件内容为空: {filename}")
                                    contents.append(f"--- 文件: {filename} ---\n文件内容为空")
                                    processed_files.add(file_path)
                                    
                            except Exception as e:
                                error_msg = str(e)
                                self._log(f"      ❌ 小文件处理失败: {filename} - {error_msg[:50]}...")
                                contents.append(f"--- 文件: {filename} ---\n文件处理失败: {error_msg}")
                                processed_files.add(file_path)
            
            # 合并所有内容（再次验证总长度）
            if contents:
                combined_content = "\n\n".join(contents)
                # 最终长度检查
                if len(combined_content) > max_total_length:
                    self._log(f"    ⚠️ 合并后内容仍然过大，最终截取: {len(combined_content)}字符")
                    combined_content = combined_content[:max_total_length] + f"\n\n[注意：材料总长度超限，已最终截取到{max_total_length//1000}K字符]"
            else:
                combined_content = f"材料{mid}({material_name})无可用内容"
            
            self._log(f"    📊 材料{mid}({material_name})处理完成: 总计{len(combined_content)}字符 [防堆叠处理]")
            return combined_content
            
        except Exception as e:
            error_msg = f"材料{mid}({material_name})整体处理失败: {str(e)}"
            self._log(f"    ❌ {error_msg}")
            return error_msg

    def _map_files_to_materials(self, base_dir: str) -> Dict[int, List[str]]:
        """将文件映射到材料类别，确保每个文件只映射到一个材料"""
        material_files = {i: [] for i in range(1, 18)}
        file_mapping_log = {}  # 记录文件映射日志
        
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.startswith('.') or file.startswith('~'): 
                    continue
                    
                file_path = os.path.join(root, file)
                folder_name = os.path.basename(root)
                
                # 使用改进的材料识别逻辑
                material_id = self._identify_material(folder_name, file)
                
                if material_id:
                    # 检查文件是否已经被映射过
                    if file_path in file_mapping_log:
                        existing_mid = file_mapping_log[file_path]
                        self._log(f"  ⚠️ 文件重复映射: {self._safe_basename(file_path)} - 已映射到材料{existing_mid}，跳过材料{material_id}")
                        continue
                    
                    # 映射文件到材料
                    material_files[material_id].append(file_path)
                    file_mapping_log[file_path] = material_id
                    
                    # 记录映射详情
                    self._log(f"  📋 文件映射: {self._safe_basename(file_path)} -> 材料{material_id}({self.MATERIAL_NAMES.get(material_id, f'材料{material_id}')})")
                else:
                    self._log(f"  ❓ 未识别文件: {self._safe_basename(file_path)} (文件夹: {folder_name})")
        
        # 输出映射统计
        total_mapped = sum(len(files) for files in material_files.values())
        self._log(f"  📊 文件映射统计: 总计 {total_mapped} 个文件映射到 {len([mid for mid, files in material_files.items() if files])} 个材料类别")
        
        return material_files

    def _identify_material(self, folder_name: str, filename: str) -> Optional[int]:
        """更精确的材料识别逻辑，优先级：数字前缀 > 文件夹名称 > 文件名关键词"""
        text_to_check = f"{folder_name} {filename}".lower()
        
        # 优先级 1: 检查数字前缀（最高优先级）
        match = re.match(r'^(\d+)', text_to_check)
        if match:
            material_id = int(match.group(1))
            if 1 <= material_id <= 17:
                return material_id
        
        # 优先级 2: 检查文件夹名称中的数字
        folder_match = re.search(r'(\d+)', folder_name)
        if folder_match:
            material_id = int(folder_match.group(1))
            if 1 <= material_id <= 17:
                return material_id
        
        # 优先级 3: 检查文件名中的数字
        file_match = re.search(r'(\d+)', filename)
        if file_match:
            material_id = int(file_match.group(1))
            if 1 <= material_id <= 17:
                return material_id
        
        # 优先级 4: 根据关键词匹配（最低优先级）
        # 使用更精确的关键词匹配，避免误匹配
        keyword_mapping = {
            1: ["教育经历", "学历", "毕业"],
            2: ["工作经历", "工作单位", "任职"],
            3: ["继续教育", "培训情况", "培训"],
            4: ["学术技术兼职", "兼职情况", "兼职"],
            5: ["获奖情况", "奖励", "获奖"],
            6: ["荣誉称号", "荣誉"],
            7: ["科研项目", "基金情况", "科研"],
            8: ["工程技术项目", "工程项目"],
            9: ["论文"],
            10: ["著作", "译作", "教材"],
            11: ["专利", "著作权"],
            12: ["指定标准", "标准情况"],
            13: ["成果被批示", "采纳", "运用", "推广"],
            14: ["资质证书", "证书"],
            15: ["奖惩情况", "奖惩"],
            16: ["考核情况", "考核"],
            17: ["申报材料附件", "附件信息", "附件"]
        }
        
        # 只在关键词完全匹配时才返回结果，避免部分匹配导致的误判
        for mid, keywords in keyword_mapping.items():
            for keyword in keywords:
                if keyword in text_to_check:
                    # 双重验证：确保关键词不是更大单词的一部分
                    if len(keyword) >= 3:  # 只接受较长的关键词，避免误匹配
                        return mid
        
        return None

    def _extract_single_file_content(self, file_path: str, cache_prefix: str = "") -> str:
        """提取单个文件内容，使用改进的缓存策略"""
        
        # 检查改进的缓存管理器
        cached_content = self.cache_manager.get(file_path, cache_prefix)
        if cached_content:
            self._log(f"    - [智能缓存] 使用缓存内容: {self._safe_basename(file_path)}")
            return cached_content
        
        # 提取内容
        if file_path.endswith('.pdf'):
            content = self._extract_pdf_content(file_path)
        else:
            content = f"跳过非PDF文件: {self._safe_basename(file_path)}"
        
        # 将结果存入改进的缓存管理器
        if content and content.strip():
            self.cache_manager.set(file_path, content, cache_prefix)
        
        return content

    def _extract_pdf_content(self, pdf_path: str) -> str:
        filename = self._safe_basename(pdf_path)
        # 直接使用AI识别，完整提取所有内容
        self._log(f"    - [AI完整识别] {filename}")
        return self._extract_pdf_with_ai(pdf_path)

    def _get_pdf_page_count(self, pdf_path: str) -> int:
        """获取PDF文件的页数"""
        try:
            from pypdf import PdfReader
            reader = PdfReader(pdf_path)
            return len(reader.pages)
        except Exception as e:
            self._log(f"    - [警告] 无法获取PDF页数: {self._safe_basename(pdf_path)} - {e}")
            return 0
    
    def _split_pdf_pages(self, pdf_path: str, pages_per_chunk: int = 5) -> List[Tuple[int, int]]:
        """将PDF分割成多个页面范围用于并发处理，确保所有页面都被包含（修复版）"""
        try:
            total_pages = self._get_pdf_page_count(pdf_path)
            filename = self._safe_basename(pdf_path)
            
            # 🔧 修复：确保页数检查准确
            if total_pages <= 0:
                self._log(f"    - [分片错误] 无法获取有效页数: {filename}")
                return []  # 返回空列表而不是默认范围
            
            if total_pages <= pages_per_chunk:
                # 如果总页数不超过分片大小，直接返回整个文档
                self._log(f"    - [分片优化] {total_pages}页≤{pages_per_chunk}页，无需分片")
                return [(1, total_pages)]
            
            chunks = []
            
            # 🚀 生成分片，确保完整覆盖
            for start_page in range(1, total_pages + 1, pages_per_chunk):
                end_page = min(start_page + pages_per_chunk - 1, total_pages)
                chunks.append((start_page, end_page))
                
                # 记录分片信息
                page_count = end_page - start_page + 1
                self._log(f"    - [分片{len(chunks)}] 第{start_page}-{end_page}页（{page_count}页）")
            
            # ✅ 验证分片完整性
            total_covered_pages = sum(end - start + 1 for start, end in chunks)
            if total_covered_pages != total_pages:
                self._log(f"    - [验证失败] 总页数{total_pages}，分片覆盖{total_covered_pages}页！重新生成...")
                # 重新生成更保守的分片
                chunks = [(i, min(i + pages_per_chunk - 1, total_pages)) for i in range(1, total_pages + 1, pages_per_chunk)]
                new_covered = sum(end - start + 1 for start, end in chunks)
                self._log(f"    - [重新验证] 修正后覆盖{new_covered}页")
            else:
                self._log(f"    - [验证成功] {filename} 共{total_pages}页，分为{len(chunks)}个分片，全部覆盖")
            
            return chunks
            
        except Exception as e:
            self._log(f"    - [分片异常] PDF分页失败: {self._safe_basename(pdf_path)} - {e}")
            return []  # 异常时返回空列表
    
    def _extract_pdf_pages_concurrent(self, pdf_path: str, page_ranges: List[Tuple[int, int]]) -> str:
        """并发处理PDF的不同页面范围，防止内容堆叠（使用任务队列动态分配）"""
        filename = self._safe_basename(pdf_path)
        self._log(f"    - [并发] 启动任务队列模式，{len(page_ranges)} 个任务等待API认领: {filename}")
        
        import queue
        import threading
        
        # 创建任务队列和结果存储
        task_queue = queue.Queue()
        results = {}  # {task_id: (start_page, content)}
        results_lock = threading.Lock()
        processed_tasks = set()  # 跟踪已处理的任务ID，防止重复
        
        # 将所有任务放入队列
        for i, (start_page, end_page) in enumerate(page_ranges):
            task_queue.put((i, start_page, end_page))
        
        def worker_thread(worker_id):
            """工作线程，主动认领任务"""
            processed_count = 0
            
            while True:
                try:
                    # 认领任务（超时1秒未获取到任务就退出）
                    task_id, start_page, end_page = task_queue.get(timeout=1)
                    
                    # 检查任务是否已被处理过，防止重复
                    with results_lock:
                        if task_id in processed_tasks:
                            self._log(f"    - [Worker-{worker_id}] 任务 {task_id+1} 已被处理，跳过")
                            task_queue.task_done()
                            continue
                        processed_tasks.add(task_id)
                    
                    self._log(f"    - [Worker-{worker_id}] 认领任务 {task_id+1}: 第{start_page}-{end_page}页")
                    
                    try:
                        # 执行任务
                        content = self._extract_single_page_range(pdf_path, start_page, end_page, worker_id)
                        
                        # 内容长度检查，防止单个分片过大（使用头尾截取）
                        if len(content) > 200000:  # 如果单个分片超过200K字符
                            self._log(f"    - [Worker-{worker_id}] 警告: 第{start_page}-{end_page}页内容过大 ({len(content)}字符)，头尾截取防止堆叠")
                            content = self._smart_truncate_content(content, max_length=200000, head_size=5000, tail_size=5000)
                        
                        # 存储结果
                        with results_lock:
                            results[task_id] = (start_page, content)
                        
                        processed_count += 1
                        self._log(f"    - [Worker-{worker_id}] 完成任务 {task_id+1}: {len(content)} 字符")
                        
                    except Exception as e:
                        error_msg = f"[第{start_page}-{end_page}页处理失败：{str(e)[:100]}]"
                        self._log(f"    - [Worker-{worker_id}] 任务 {task_id+1} 执行失败: {str(e)[:50]}...")
                        
                        # 存储错误信息而不是重新入队，避免无限循环
                        with results_lock:
                            results[task_id] = (start_page, error_msg)
                    
                    # 标记任务完成
                    task_queue.task_done()
                    
                except queue.Empty:
                    # 没有更多任务，退出
                    self._log(f"    - [Worker-{worker_id}] 没有更多任务，线程退出 (处理了{processed_count}个任务)")
                    break
                except Exception as e:
                    self._log(f"    - [Worker-{worker_id}] 线程异常: {str(e)[:50]}...")
                    try:
                        task_queue.task_done()
                    except:
                        pass
                    break
        
        # 启动工作线程（优化：最大化API利用率，移除保守限制）
        max_workers = min(len(page_ranges), len(self.api_rotator.api_keys) * 2, 12)  # 每个API最多2个线程，最多12个并发
        workers = []
        
        self._log(f"    - [管理] 启动 {max_workers} 个工作线程处理 {len(page_ranges)} 个任务")
        
        for i in range(max_workers):
            worker = threading.Thread(target=worker_thread, args=(i+1,))
            worker.daemon = True
            worker.start()
            workers.append(worker)
        
        # 等待所有任务完成（最多等待300秒）
        try:
            task_queue.join()  # 等待所有任务完成
            self._log(f"    - [管理] 所有任务已完成")
        except KeyboardInterrupt:
            self._log(f"    - [管理] 用户中断处理")
        
        # 等待所有线程结束
        for worker in workers:
            worker.join(timeout=5)  # 最多等待5秒
        
        # 按页面顺序排序并合并结果，确保完整性和连续性
        if not results:
            self._log(f"    - [合并错误] 所有分片都处理失败: {filename}")
            return f"[并发处理失败：所有任务都未能完成] - {filename}"
        
        sorted_results = sorted(results.items(), key=lambda x: x[1][0])  # 按起始页面排序
        combined_parts = []
        total_length = 0
        max_combined_length = 500000  # 合并后的最大长度限制
        
        # 检查页面连续性并合并内容
        expected_page = 1
        missing_pages = []
        
        for task_id, (start_page, content) in sorted_results:
            # 检查页面是否连续
            if start_page > expected_page:
                missing_range = list(range(expected_page, start_page))
                missing_pages.extend(missing_range)
                self._log(f"    - [连续性检查] 缺失页面: {missing_range}")
            
            # 检查合并后长度是否会超限
            if total_length + len(content) > max_combined_length:
                remaining_space = max_combined_length - total_length
                if remaining_space > 5000:  # 还有足够空间
                    content = content[:remaining_space-1000] + f"\n\n[注意：总长度限制，已截取剩余{remaining_space//1000}K字符]"
                else:
                    self._log(f"    - [合并] 已达到总长度限制，停止添加更多内容")
                    break
            
            # 清理内容中的重复页面标记（如果AI重复了）
            content = self._clean_page_content(content, start_page)
            combined_parts.append(content)
            total_length += len(content)
            
            # 更新期望页面
            task_range = next((r for r in page_ranges if r[0] == start_page), None)
            if task_range:
                expected_page = task_range[1] + 1
        
        # 构建完整的合并内容
        if missing_pages:
            header = f"[分片处理完成 - 缺失页面: {missing_pages[:10]}{'...' if len(missing_pages) > 10 else ''}]\n\n"
        else:
            header = f"[分片处理完成 - 页面连续]\n\n"
        
        combined_content = header + "\n\n--- 页面分割线 ---\n\n".join(combined_parts)
        
        completed_tasks = len(results)
        total_tasks = len(page_ranges)
        
        self._log(f"    - [合并] 成功完成 {completed_tasks}/{total_tasks} 个任务，合并内容长度: {len(combined_content)} 字符")
        
        # 最终长度检查
        if len(combined_content) > max_combined_length:
            self._log(f"    - [最终检查] 合并内容仍然过大，最终截取: {len(combined_content)}字符")
            combined_content = combined_content[:max_combined_length] + f"\n\n[注意：合并后总长度超限，已最终截取到{max_combined_length//1000}K字符]"
        
        return combined_content
    
    def _clean_page_content(self, content: str, start_page: int) -> str:
        """清理分片内容，移除可能的重复标记和多余信息"""
        if not content:
            return content
        
        # 移除多余的页面标记重复
        import re
        content = re.sub(r'\[第\d+-\d+页\]\s*\[第\d+-\d+页\]', f'[第{start_page}页开始]', content)
        
        # 清理过多的换行
        content = re.sub(r'\n{4,}', '\n\n\n', content)
        
        return content.strip()
    
    def _extract_pdf_pages_to_bytes(self, pdf_path: str, start_page: int, end_page: int) -> bytes:
        """真正的PDF分页：提取指定页面范围为新的PDF字节数据"""
        try:
            from pypdf import PdfReader, PdfWriter
            import io
            
            # 读取原PDF
            reader = PdfReader(pdf_path)
            total_pages = len(reader.pages)
            
            # 调整页码范围（pypdf使用0开始的索引）
            start_idx = max(0, start_page - 1)
            end_idx = min(total_pages, end_page)
            
            if start_idx >= total_pages:
                raise ValueError(f"起始页码{start_page}超出总页数{total_pages}")
            
            # 创建新的PDF写入器
            writer = PdfWriter()
            
            # 添加指定范围的页面
            for page_idx in range(start_idx, end_idx):
                writer.add_page(reader.pages[page_idx])
            
            # 写入到字节流
            output = io.BytesIO()
            writer.write(output)
            output.seek(0)
            
            pdf_bytes = output.read()
            output.close()
            
            self._log(f"    - [分片] 成功提取第{start_page}-{end_page}页，大小: {len(pdf_bytes)/1024:.1f}KB")
            return pdf_bytes
            
        except Exception as e:
            self._log(f"    - [分片错误] 无法提取第{start_page}-{end_page}页: {e}")
            # 降级处理：返回原始PDF
            return Path(pdf_path).read_bytes()
    
    def _extract_single_page_range(self, pdf_path: str, start_page: int, end_page: int, worker_id: int) -> str:
        """提取单个页面范围的内容（真正的分片处理）"""
        filename = self._safe_basename(pdf_path)
        
        # 为并发处理的页面范围使用唯一的缓存键，防止冲突
        import hashlib
        file_hash = hashlib.md5(pdf_path.encode()).hexdigest()[:8]
        cache_prefix = f"pages_{start_page}_{end_page}_file_{file_hash}"
        cached_content = self.cache_manager.get(pdf_path, cache_prefix)
        
        if cached_content:
            self._log(f"    - [Worker-{worker_id}] 使用缓存: 第{start_page}-{end_page}页")
            return cached_content
        
        def ai_call_for_pages(client):
            try:
                # 真正的分片处理：只读取指定页面范围
                split_pdf_bytes = self._extract_pdf_pages_to_bytes(pdf_path, start_page, end_page)
                if len(split_pdf_bytes) == 0:
                    raise ValueError("分片PDF为空")
                
                self._log(f"    - [Worker-{worker_id}] 分片大小: {len(split_pdf_bytes)/1024:.1f}KB (第{start_page}-{end_page}页)")
                
                if start_page == 1 and end_page >= 999:
                    # 处理整个文档（无页数限制时）
                    prompt = f"""请完整提取PDF文件（{filename}）的所有内容：

**提取要求**：
✓ 所有文字信息（标题、正文、注释）
✓ 表格数据和数值信息
✓ 图表标题和说明文字
✓ 页眉页脚信息
✓ 图像中的文字内容（如OCR识别）

**处理原则**：
1. 不要跳过任何内容，尽可能完整提取
2. 保持文档的逻辑结构
3. 对于图像内容，尝试识别其中的文字
4. 使用清晰的格式输出

请开始完整提取。"""
                else:
                    # 处理指定页面范围
                    prompt = f"""请完整提取这个PDF分片（来自{filename}第{start_page}-{end_page}页）的所有内容：

**提取要求**：
✓ 所有文字信息
✓ 表格数据和数值
✓ 图表标题和说明
✓ 图像中的文字内容

**输出格式**: 在开头标注[第{start_page}-{end_page}页]，然后输出完整内容。"""
                    
                return client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Part.from_bytes(
                            data=split_pdf_bytes,
                            mime_type='application/pdf'
                        ),
                        prompt
                    ]
                )
            except Exception as e:
                raise e
        
        try:
            response = self._rotated_api_call(ai_call_for_pages, max_retries=2)
            if response and response.text and response.text.strip():
                content = response.text.strip()
                
                # 检查单个分片内容长度，防止过大（使用头尾截取）
                if len(content) > 200000:  # 如果单个分片超过200K字符
                    self._log(f"    - [Worker-{worker_id}] 警告: 第{start_page}-{end_page}页内容过大 ({len(content)}字符)，使用头尾截取")
                    content = self._smart_truncate_content(content, max_length=200000, head_size=5000, tail_size=5000)
                
                # 将结果存入缓存
                self.cache_manager.set(pdf_path, content, cache_prefix)
                return content
            else:
                return f"[第{start_page}-{end_page}页处理失败：返回空内容]"
        except Exception as e:
            error_msg = str(e)[:100]
            return f"[第{start_page}-{end_page}页处理失败：{error_msg}]"

    def _extract_pdf_with_ai(self, pdf_path: str) -> str:
        """使用Google Gemini AI识别PDF文件内容，智能选择最优处理策略（重构版）"""
        filename = self._safe_basename(pdf_path)
        
        # 检查文件大小和存在性
        try:
            file_size = os.path.getsize(pdf_path)
            max_upload_size = 100 * 1024 * 1024  # 100MB上限
            
            if file_size > max_upload_size:
                self._log(f"    - [警告] 文件过大 ({file_size/1024/1024:.1f}MB)，超过100MB限制: {filename}")
                return f"文件过大({file_size/1024/1024:.1f}MB)，超过100MB限制: {filename}"
                
            if not os.path.exists(pdf_path):
                self._log(f"    - [错误] 文件不存在: {filename}")
                return f"文件不存在: {filename}"
                
        except Exception as e:
            self._log(f"    - [错误] 无法获取文件信息: {filename} - {e}")
            return f"文件访问错误: {filename}"
        
        # 🚀 重构后的简化策略：只看页数，统一阈值
        total_pages = self._get_pdf_page_count(pdf_path)
        api_count = len(self.api_rotator.api_keys)
        
        self._log(f"    - [分析] {filename}: {file_size/1024/1024:.1f}MB, {total_pages}页, {api_count}个API可用")
        
        # 🎯 统一分片策略：页数>8页 且 有多个API 才启用分片
        if total_pages > 8 and api_count > 1:
            self._log(f"    - [分片策略] {total_pages}页>8页 + {api_count}个API：启用分片并发处理")
            return self._extract_pdf_with_concurrent_pages(pdf_path)
        
        # 📄 非分片策略：选择最适合的单API处理方式
        elif file_size > 10 * 1024 * 1024:  # >10MB使用File API
            self._log(f"    - [File API策略] {file_size/1024/1024:.1f}MB>10MB：使用File API处理")
            return self._extract_pdf_with_file_api(pdf_path)
        
        else:  # <=10MB使用直接传输
            self._log(f"    - [直接传输策略] {file_size/1024/1024:.1f}MB≤10MB：使用直接传输处理")
            return self._extract_pdf_direct_transfer(pdf_path)
    
    def _extract_pdf_with_concurrent_pages(self, pdf_path: str) -> str:
        """重构后的分片处理策略：确保正确识别大PDF（修复版）"""
        filename = self._safe_basename(pdf_path)
        
        try:
            # 获取PDF页数
            total_pages = self._get_pdf_page_count(pdf_path)
            api_count = len(self.api_rotator.api_keys)
            
            self._log(f"    - [分片开始] {filename}: {total_pages}页，{api_count}个API")
            
            # 🔧 修复分片逻辑：确保页数检查准确
            if total_pages <= 0:
                self._log(f"    - [错误] 无法获取页数，降级为直接处理: {filename}")
                return self._extract_pdf_with_file_api(pdf_path)
            
            # 🚀 智能分片：根据API数量和页数动态计算最优分片大小
            # 目标：让每个API都有适量任务，避免空闲
            target_chunks = api_count * 2  # 每个API分配2个任务
            optimal_chunk_size = max(2, total_pages // target_chunks)  # 每片最少2页
            
            # 限制单个分片不要太大（避免单片处理时间过长）
            if optimal_chunk_size > 6:
                optimal_chunk_size = 6
            
            # 生成页面分片范围
            page_ranges = self._split_pdf_pages(pdf_path, optimal_chunk_size)
            
            if not page_ranges:
                self._log(f"    - [错误] 分片生成失败，降级处理: {filename}")
                return self._extract_pdf_with_file_api(pdf_path)
            
            self._log(f"    - [分片配置] {total_pages}页 → {len(page_ranges)}个分片(每片≈{optimal_chunk_size}页) → {api_count}个API并发")
            
            # 🔥 执行并发分片处理
            result = self._extract_pdf_pages_concurrent(pdf_path, page_ranges)
            
            # ✅ 验证处理结果
            if result and len(result.strip()) > 100:
                self._log(f"    - [分片成功] {filename} 处理完成，提取 {len(result)} 字符")
                return result
            else:
                self._log(f"    - [分片失败] 结果为空或过短，降级处理: {filename}")
                return self._extract_pdf_with_file_api(pdf_path)
                
        except Exception as e:
            self._log(f"    - [分片异常] 降级为直接处理: {filename} - {str(e)[:100]}")
            return self._extract_pdf_with_file_api(pdf_path)
    
    def _extract_pdf_with_file_api(self, pdf_path: str) -> str:
        """使用直接传输方式处理PDF文件（放弃File API上传方式）"""
        filename = self._safe_basename(pdf_path)
        
        def direct_transfer_call(client):
            try:
                from pathlib import Path
                
                # 直接读取PDF字节数据
                filepath = Path(pdf_path)
                pdf_bytes = filepath.read_bytes()
                
                if len(pdf_bytes) == 0:
                    raise ValueError("PDF文件为空")
                
                self._log(f"    - [直接传输] 文件大小: {len(pdf_bytes)/1024/1024:.1f}MB - {filename}")
                
                # 优化的AI提示词：完整提取所有内容
                optimized_prompt = f"""请完整提取PDF文件（{filename}）中的所有内容：

**提取要求**：
1. 所有可读的文字信息（标题、正文、注释等）
2. 表格中的文字数据和数值
3. 图表的文字说明和标注
4. 页眉、页脚中的文字信息
5. 图像中的文字内容（如果可识别）

**处理策略**：
- 不要跳过任何内容，尽可能完整提取
- 保持原有的文档结构和层次
- 对于图像内容，尝试OCR识别其中的文字
- 使用清洁明了的格式输出

请开始完整提取。"""
                
                # 使用直接传输方式生成内容
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Part.from_bytes(
                            data=pdf_bytes,
                            mime_type='application/pdf'
                        ),
                        optimized_prompt
                    ]
                )
                
                return response
                
            except Exception as e:
                raise e
        
        # 重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._log(f"    - [直接传输] 开始处理 (尝试 {attempt+1}/{max_retries}): {filename}")
                
                response = self._rotated_api_call(direct_transfer_call, max_retries=1)
                
                if response and response.text and response.text.strip():
                    content = response.text.strip()
                    content_length = len(content)
                    
                    # 内容长度检查，防止过大（使用头尾截取）
                    if content_length > 200000:  # 200K字符阈值
                        self._log(f"    - [直接传输] 警告: 文件内容过大 ({content_length}字符)，头尾截取")
                        content = self._smart_truncate_content(content, max_length=200000, head_size=5000, tail_size=5000)
                        content_length = len(content)
                    
                    self._log(f"    - [直接传输] 处理成功: {filename} (提取 {content_length} 字符)")
                    return content
                else:
                    self._log(f"    - [警告] 直接传输返回空内容: {filename}")
                    if attempt < max_retries - 1:
                        self._log(f"    - [重试] 等待后重试...")
                        time.sleep(2)
                        continue
                    else:
                        return f"直接传输识别返回空内容: {filename}"
                        
            except Exception as e:
                error_str = str(e)
                self._log(f"    - [错误] 直接传输处理失败: {filename} - {error_str[:100]}...")
                
                # 特殊错误处理
                if "file too large" in error_str.lower() or "size limit" in error_str.lower():
                    return f"文件过大，直接传输无法处理: {filename}"
                elif "quota" in error_str.lower() or "rate limit" in error_str.lower():
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5
                        self._log(f"    - [限流] API限流，等待{wait_time}秒后重试...")
                        time.sleep(wait_time)
                        continue
                    else:
                        return f"直接传输API调用限流: {filename}"
                else:
                    if attempt < max_retries - 1:
                        self._log(f"    - [重试] 等待后重试...")
                        time.sleep(3)
                        continue
                    else:
                        return f"直接传输处理异常: {filename} - {error_str[:100]}"
        
        # 如果所有重试都失败
        return f"直接传输处理失败，已重试{max_retries}次: {filename}"
    
    def _extract_pdf_direct_transfer(self, pdf_path: str) -> str:
        """使用直接传输方式处理PDF文件（适用于较小文件）"""
        filename = self._safe_basename(pdf_path)
        
        def direct_transfer_call(client):
            try:
                pdf_bytes = Path(pdf_path).read_bytes()
                if len(pdf_bytes) == 0:
                    raise ValueError("PDF文件为空")
                
                # 优化的AI提示词：完整提取所有内容
                smart_prompt = f"""请完整提取PDF文件（{filename}）中的所有内容：

**提取目标**：
✓ 所有文字信息（标题、正文、注释）
✓ 表格数据和数值信息
✓ 图表标题和说明文字
✓ 页眉页脚信息
✓ 图像中的文字内容（如OCR识别）

**处理原则**：
1. 不要跳过任何内容，尽可能完整提取
2. 保持文档的逻辑结构
3. 对于图像内容，尝试识别其中的文字
4. 使用清晰的格式输出

请开始完整提取。"""
                
                return client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Part.from_bytes(
                            data=pdf_bytes,
                            mime_type='application/pdf'
                        ),
                        smart_prompt
                    ]
                )
            except Exception as e:
                raise e
        
        # 重试机制
        max_retries = 2
        for attempt in range(max_retries):
            try:
                self._log(f"    - [直接传输] 开始处理 (尝试 {attempt+1}/{max_retries}): {filename}")
                
                response = self._rotated_api_call(direct_transfer_call, max_retries=1)
                
                if response and response.text and response.text.strip():
                    content = response.text.strip()
                    content_length = len(content)
                    
                    # 内容长度检查，防止过大（使用头尾截取）
                    if content_length > 200000:  # 200K字符阈值
                        self._log(f"    - [直接传输] 警告: 文件内容过大 ({content_length}字符)，头尾截取")
                        content = self._smart_truncate_content(content, max_length=200000, head_size=5000, tail_size=5000)
                        content_length = len(content)
                    
                    self._log(f"    - [直接传输] 处理成功: {filename} (提取 {content_length} 字符)")
                    return content
                else:
                    self._log(f"    - [警告] 直接传输返回空内容: {filename}")
                    if attempt < max_retries - 1:
                        self._log(f"    - [重试] 等待后重试...")
                        time.sleep(1)
                        continue
                    else:
                        return f"直接传输识别返回空内容: {filename}"
                        
            except Exception as e:
                error_str = str(e)
                self._log(f"    - [错误] 直接传输失败: {filename} - {error_str[:100]}...")
                
                # 特殊错误处理
                if "file too large" in error_str.lower():
                    return f"文件过大，直接传输无法处理: {filename}"
                elif "rate limit" in error_str.lower() or "quota" in error_str.lower():
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 3
                        self._log(f"    - [限流] API限流，等待{wait_time}秒后重试...")
                        time.sleep(wait_time)
                        continue
                    else:
                        return f"直接传输API调用限流: {filename}"
                else:
                    if attempt < max_retries - 1:
                        self._log(f"    - [重试] 等待后重试...")
                        time.sleep(2)
                        continue
                    else:
                        return f"直接传输异常: {filename} - {error_str[:100]}"
        
        # 如果所有重试都失败
        return f"直接传输失败，已重试{max_retries}次: {filename}"
    
    def _process_files_with_enhanced_concurrency(self, files: List[str], mid: int, file_type: str) -> List[str]:
        """增强的并发处理函数，支持动态API调度和优先级管理"""
        if not files:
            return []
        
        self._log(f"      🚀 开始{file_type}增强并发处理: {len(files)} 个文件")
        
        import concurrent.futures
        import threading
        import queue
        
        results = []
        results_lock = threading.Lock()
        
        # 根据文件类型调整并发策略（优化：最大化API利用率）
        if file_type == "大文件":
            # 大文件：最大化并发数，每个API最多2个线程
            max_workers = min(len(files), len(self.api_rotator.api_keys) * 2, 16)  # 提升到最多16个并发
            timeout_seconds = 300  # 5分钟超时
        elif file_type == "中等文件":
            # 中等文件：使用中等并发数
            max_workers = min(len(files), len(self.api_rotator.api_keys) * 2, 12)  # 提升到最多12个并发
            timeout_seconds = 180  # 3分钟超时
        else:  # 小文件
            # 小文件：使用较小并发数，但也充分利用API
            max_workers = min(len(files), len(self.api_rotator.api_keys), 8)  # 提升到最多8个并发
            timeout_seconds = 120  # 2分钟超时
        
        self._log(f"      📀 {file_type}并发策略: {max_workers}个工作线程, 超时{timeout_seconds}秒")
        
        def process_single_file_enhanced(file_path: str, worker_id: int) -> str:
            """增强的单文件处理函数"""
            filename = self._safe_basename(file_path)
            
            try:
                # 使用更精确的缓存键，包含文件类型
                import hashlib
                file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]
                cache_prefix = f"enhanced_{file_type}_{mid}_{file_hash}"
                
                # 检查缓存
                cached_content = self.cache_manager.get(file_path, cache_prefix)
                if cached_content:
                    self._log(f"      [Worker-{worker_id}] 💾 使用缓存({file_type}): {filename}")
                    content = cached_content
                else:
                    # 根据文件类型选择处理策略
                    self._log(f"      [Worker-{worker_id}] 🚀 开始处理{file_type}: {filename}")
                    
                    if file_path.endswith('.pdf'):
                        if file_type == "大文件":
                            # 大文件使用优化的处理策略
                            content = self._extract_pdf_with_priority_handling(file_path, "high")
                        elif file_type == "中等文件":
                            # 中等文件使用标准处理
                            content = self._extract_pdf_with_priority_handling(file_path, "medium")
                        else:
                            # 小文件使用快速处理
                            content = self._extract_pdf_with_priority_handling(file_path, "low")
                    else:
                        content = f"跳过非PDF文件: {filename}"
                    
                    # 存入缓存
                    if content and content.strip():
                        self.cache_manager.set(file_path, content, cache_prefix)
                
                # 根据文件类型调整内容长度控制（使用新的头尾截取）
                if content:
                    if file_type == "大文件" and len(content) > 200000:
                        self._log(f"      [Worker-{worker_id}] ⚠️ 大文件内容过大，头尾截取: {filename} ({len(content)}字符)")
                        content = self._smart_truncate_content(content, max_length=200000, head_size=5000, tail_size=5000)
                    elif file_type == "中等文件" and len(content) > 200000:
                        self._log(f"      [Worker-{worker_id}] ⚠️ 中等文件内容过大，头尾截取: {filename} ({len(content)}字符)")
                        content = self._smart_truncate_content(content, max_length=200000, head_size=5000, tail_size=5000)
                    elif file_type == "小文件" and len(content) > 200000:
                        self._log(f"      [Worker-{worker_id}] ⚠️ 小文件内容过大，头尾截取: {filename} ({len(content)}字符)")
                        content = self._smart_truncate_content(content, max_length=200000, head_size=5000, tail_size=5000)
                
                # 格式化内容
                if content and content.strip():
                    formatted_content = f"--- {file_type}文件: {filename} ---\n{content}"
                    self._log(f"      [Worker-{worker_id}] ✅ {file_type}处理成功: {filename} ({len(content)}字符)")
                    return formatted_content
                else:
                    self._log(f"      [Worker-{worker_id}] ⚠️ {file_type}内容为空: {filename}")
                    return f"--- {file_type}文件: {filename} ---\n文件内容为空"
                    
            except Exception as e:
                error_msg = str(e)
                self._log(f"      [Worker-{worker_id}] ❌ {file_type}处理失败: {filename} - {error_msg[:50]}...")
                return f"--- {file_type}文件: {filename} ---\n文件处理失败: {error_msg}"
        
        # 使用线程池并发处理
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交任务
            future_to_file = {}
            for i, file_path in enumerate(files):
                future = executor.submit(process_single_file_enhanced, file_path, i+1)
                future_to_file[future] = file_path
            
            # 收集结果，使用超时机制（改进版）
            completed_count = 0
            unfinished_futures = set(future_to_file.keys())
            
            try:
                for future in concurrent.futures.as_completed(future_to_file, timeout=timeout_seconds):
                    file_path = future_to_file[future]
                    filename = self._safe_basename(file_path)
                    unfinished_futures.discard(future)  # 移除已完成的future
                    
                    try:
                        result = future.result(timeout=30)  # 单个任务超时30秒
                        with results_lock:
                            results.append(result)
                        completed_count += 1
                        self._log(f"      ✅ {file_type}并发处理完成: {filename} ({completed_count}/{len(files)})")
                        
                    except concurrent.futures.TimeoutError:
                        self._log(f"      ⏰ {file_type}处理超时: {filename}")
                        with results_lock:
                            results.append(f"--- {file_type}文件: {filename} ---\n文件处理超时")
                        completed_count += 1
                        
                    except Exception as e:
                        error_msg = str(e)[:50]
                        self._log(f"      ❌ {file_type}并发处理失败: {filename} - {error_msg}...")
                        with results_lock:
                            results.append(f"--- {file_type}文件: {filename} ---\n文件并发处理失败: {error_msg}")
                        completed_count += 1
                        
            except concurrent.futures.TimeoutError:
                self._log(f"      ⏰ {file_type}阶段处理超时，有{len(unfinished_futures)}个任务未完成")
                
                # 处理未完成的任务
                for future in unfinished_futures:
                    file_path = future_to_file[future]
                    filename = self._safe_basename(file_path)
                    try:
                        if not future.done():
                            future.cancel()
                        with results_lock:
                            results.append(f"--- {file_type}文件: {filename} ---\n文件处理超时")
                        completed_count += 1
                        self._log(f"      ⏰ {file_type}超时处理: {filename} ({completed_count}/{len(files)})")
                    except Exception as e:
                        self._log(f"      ❌ {file_type}超时处理失败: {filename} - {e}")
        
        self._log(f"      🏁 {file_type}增强并发处理完成: 成功 {completed_count}/{len(files)} 个文件")
        return results
    

    

        """根据优先级选择最优PDF处理策略"""
    
    def _extract_pdf_with_priority_handling(self, pdf_path: str, priority: str) -> str:
        """根据优先级选择最优PDF处理策略"""
        filename = self._safe_basename(pdf_path)
        
        try:
            file_size = os.path.getsize(pdf_path)
            
            if priority == "high":
                # 高优先级：大文件使用最优策略
                if file_size > 10 * 1024 * 1024:  # >10MB
                    return self._extract_pdf_with_file_api(pdf_path)
                else:
                    return self._extract_pdf_direct_transfer(pdf_path)
                    
            elif priority == "medium":
                # 中优先级：中等文件使用标准策略
                if file_size > 15 * 1024 * 1024:  # >15MB
                    return self._extract_pdf_with_file_api(pdf_path)
                else:
                    return self._extract_pdf_direct_transfer(pdf_path)
                    
            else:  # low priority
                # 低优先级：小文件使用快速策略
                if file_size > 20 * 1024 * 1024:  # >20MB
                    return self._extract_pdf_with_file_api(pdf_path)
                else:
                    return self._extract_pdf_direct_transfer(pdf_path)
                    
        except Exception as e:
            self._log(f"    - [优先级错误] 文件处理失败: {filename} - {e}")
            # 错误时降级到直接传输
            return self._extract_pdf_direct_transfer(pdf_path)

    def _process_large_files_concurrently(self, large_files: List[str], mid: int) -> List[str]:
        """并发处理大文件，利用多个API同时处理"""
        if not large_files:
            return []
        
        self._log(f"      🚀 开始大文件并发处理: {len(large_files)} 个文件")
        
        import concurrent.futures
        import threading
        
        results = []
        results_lock = threading.Lock()
        
        def process_single_large_file(file_path: str, worker_id: int) -> str:
            """处理单个大文件"""
            filename = self._safe_basename(file_path)
            
            try:
                # 使用更精确的缓存键
                import hashlib
                file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]
                cache_prefix = f"large_file_{mid}_{file_hash}"
                
                # 检查缓存
                cached_content = self.cache_manager.get(file_path, cache_prefix)
                if cached_content:
                    self._log(f"      [Worker-{worker_id}] 💾 使用缓存: {filename}")
                    content = cached_content
                else:
                    # AI识别大文件
                    self._log(f"      [Worker-{worker_id}] 🚀 开始处理大文件: {filename}")
                    if file_path.endswith('.pdf'):
                        content = self._extract_pdf_content(file_path)
                    else:
                        content = f"跳过非PDF文件: {filename}"
                    
                    # 存入缓存
                    if content and content.strip():
                        self.cache_manager.set(file_path, content, cache_prefix)
                
                # 内容长度检查（使用头尾截取）
                if content and len(content) > 200000:
                    self._log(f"      [Worker-{worker_id}] ⚠️ 大文件内容过大，头尾截取: {filename} ({len(content)}字符)")
                    content = self._smart_truncate_content(content, max_length=200000, head_size=5000, tail_size=5000)
                
                # 格式化内容
                if content and content.strip():
                    formatted_content = f"--- 文件: {filename} ---\n{content}"
                    self._log(f"      [Worker-{worker_id}] ✅ 大文件处理成功: {filename} ({len(content)}字符)")
                    return formatted_content
                else:
                    self._log(f"      [Worker-{worker_id}] ⚠️ 大文件内容为空: {filename}")
                    return f"--- 文件: {filename} ---\n大文件内容为空"
                    
            except Exception as e:
                error_msg = str(e)
                self._log(f"      [Worker-{worker_id}] ❌ 大文件处理失败: {filename} - {error_msg[:50]}...")
                return f"--- 文件: {filename} ---\n大文件处理失败: {error_msg}"
        
        # 确定并发数量（优化：最大化API利用率）
        max_workers = min(len(large_files), len(self.api_rotator.api_keys) * 2, 12)  # 每个API最多2个线程，最多12个并发
        
        self._log(f"      📊 使用 {max_workers} 个工作线程并发处理 {len(large_files)} 个大文件")
        
        # 使用线程池并发处理
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交任务
            future_to_file = {}
            for i, file_path in enumerate(large_files):
                future = executor.submit(process_single_large_file, file_path, i+1)
                future_to_file[future] = file_path
            
            # 收集结果（改进超时处理）
            completed_count = 0
            unfinished_futures = set(future_to_file.keys())
            
            try:
                for future in concurrent.futures.as_completed(future_to_file, timeout=300):  # 5分钟超时
                    file_path = future_to_file[future]
                    filename = self._safe_basename(file_path)
                    unfinished_futures.discard(future)
                    
                    try:
                        result = future.result(timeout=180)  # 3分钟超时
                        with results_lock:
                            results.append(result)
                        completed_count += 1
                        self._log(f"      ✅ 大文件并发处理完成: {filename} ({completed_count}/{len(large_files)})")
                        
                    except concurrent.futures.TimeoutError:
                        self._log(f"      ⏰ 大文件处理超时: {filename}")
                        with results_lock:
                            results.append(f"--- 文件: {filename} ---\n大文件处理超时")
                        completed_count += 1
                        
                    except Exception as e:
                        error_msg = str(e)[:50]
                        self._log(f"      ❌ 大文件并发处理失败: {filename} - {error_msg}...")
                        with results_lock:
                            results.append(f"--- 文件: {filename} ---\n大文件并发处理失败: {error_msg}")
                        completed_count += 1
                        
            except concurrent.futures.TimeoutError:
                self._log(f"      ⏰ 大文件阶段超时，有{len(unfinished_futures)}个任务未完成")
                
                # 处理未完成的任务
                for future in unfinished_futures:
                    file_path = future_to_file[future]
                    filename = self._safe_basename(file_path)
                    try:
                        if not future.done():
                            future.cancel()
                        with results_lock:
                            results.append(f"--- 文件: {filename} ---\n大文件处理超时")
                        completed_count += 1
                        self._log(f"      ⏰ 大文件超时处理: {filename} ({completed_count}/{len(large_files)})")
                    except Exception as e:
                        self._log(f"      ❌ 大文件超时处理失败: {filename} - {e}")
        
        self._log(f"      🏁 大文件并发处理完成: 成功 {completed_count}/{len(large_files)} 个文件")
        return results
    
    def _extract_pdf_single_api(self, pdf_path: str) -> str:
        """使用单个API进行常规PDF处理"""
        filename = self._safe_basename(pdf_path)
        
        # 使用API轮询机制进行AI识别，取消超时限制
        def ai_call_with_full_content(client):
            import concurrent.futures
            import threading
            
            def actual_ai_call():
                try:
                    pdf_bytes = Path(pdf_path).read_bytes()
                    if len(pdf_bytes) == 0:
                        raise ValueError("PDF文件为空")
                    
                    return client.models.generate_content(
                        model="gemini-2.5-flash", 
                        contents=[
                            types.Part.from_bytes(
                                data=pdf_bytes, 
                                mime_type='application/pdf'
                            ), 
                        f"请完整提取PDF文件（{filename}）的所有内容：\n\n**提取要求**：所有文字、表格数据、图表说明、图像中的文字内容\n**处理原则**：不要跳过任何内容，尽可能完整提取。请保持精准，优先处理清晰可读的文字。"
                        ]
                    )
                except Exception as e:
                    raise e
            
            # 取消超时限制，让AI充分处理
            return actual_ai_call()
        
        # 重试机制（为大型PDF优化）
        max_retries = 2  # 减少重试次数，提升整体速度
        for attempt in range(max_retries):
            try:
                self._log(f"    - [AI] 开始高效识别 (尝试 {attempt+1}/{max_retries}): {filename}")
                
                response = self._rotated_api_call(ai_call_with_full_content, max_retries=1)
                
                if response and response.text and response.text.strip(): 
                    content = response.text.strip()
                    content_length = len(content)
                    
                    # 检查内容长度，防止单个文件过大（使用头尾截取）
                    if content_length > 200000:  # 如果单个文件超过200K字符
                        self._log(f"    - [AI] 警告: 文件内容过大 ({content_length}字符)，使用头尾截取")
                        content = self._smart_truncate_content(content, max_length=200000, head_size=5000, tail_size=5000)
                        content_length = len(content)
                    
                    self._log(f"    - [AI] 完整识别成功: {filename} (提取 {content_length} 字符)")
                    return content
                else:
                    self._log(f"    - [警告] AI返回空内容: {filename}")
                    if attempt < max_retries - 1:
                        self._log(f"    - [重试] 等待后重试...")
                        time.sleep(1)  # 减少等待时间以提升速度
                        continue
                    else:
                        return f"AI识别返回空内容: {filename}"
                        
            except Exception as e:
                error_str = str(e)
                self._log(f"    - [错误] 识别失败: {filename} - {error_str[:100]}...")
                
                # 特殊错误处理
                if "file is too large" in error_str.lower():
                    return f"文件过大，API无法处理: {filename}"
                elif "invalid pdf" in error_str.lower() or "not a pdf" in error_str.lower():
                    return f"无效的PDF文件: {filename}"
                elif "rate limit" in error_str.lower() or "quota" in error_str.lower():
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5  # 减少等待时间，提升整体速度
                        self._log(f"    - [限流] API限流，等待{wait_time}秒后重试...")
                        time.sleep(wait_time)
                        continue
                    else:
                        return f"API调用限流: {filename}"
                else:
                    if attempt < max_retries - 1:
                        self._log(f"    - [重试] 等待2秒后重试...")
                        time.sleep(2)  # 减少等待时间
                        continue
                    else:
                        return f"AI识别异常: {filename} - {error_str[:100]}"
        
        # 如果所有重试都失败
        return f"AI识别失败，已重试{max_retries}次: {filename}"

    def check_empty_materials(self):
        self._log("🔍 正在检查材料完整性...")
        self.validation_results["empty_materials"] = [mid for mid, m in self.materials.items() if m.is_empty]
        self._log(f"  🟡 发现 {len(self.validation_results['empty_materials'])} 项缺失或空材料")

    def _match_rules_to_materials(self):
        self._log("🔗 正在为材料匹配适用规则...")
        
        # 分离专项规则和通用规则
        specific_rules = []  # 专项规则(来自Excel)
        universal_rules = []  # 通用规则(来自Markdown)
        
        for r in self.rules:
            if hasattr(r, 'source_file'):
                if r.source_file.endswith('.md'):
                    universal_rules.append(r)
                elif r.source_file.endswith('.xlsx'):
                    specific_rules.append(r)
        
        self._log(f"  📋 识别到专项规则: {len(specific_rules)} 条，通用规则: {len(universal_rules)} 条")
        
        for m in self.materials.values():
            if not m.is_empty:
                material_id = m.id
                m.applicable_rules = []
                
                # 1. 匹配专项规则：材料ID对应规则文件编号
                # 例如：材料ID=2(工作经历) 对应 2.工作经历规则集.xlsx
                specific_matched = 0
                for r in specific_rules:
                    if r.source_file.startswith(f"{material_id}."):
                        r.rule_type = "专项规则"  # 标记规则类型
                        m.applicable_rules.append(r)
                        specific_matched += 1
                
                # 2. 添加通用规则：所有材料都需要检查通用规则
                for r in universal_rules:
                    r.rule_type = "通用规则"  # 标记规则类型
                    m.applicable_rules.append(r)
                
                self._log(f"  📊 材料{material_id}({m.name}): 专项规则 {specific_matched} 条 + 通用规则 {len(universal_rules)} 条 = 总计 {len(m.applicable_rules)} 条")

    def generate_full_report(self) -> str:
        self._log("⚙️ 开始生成完整报告...")
        self._log("---阶段1: 独立验证与信息提取---")
        
        # 计算需要处理的材料数量
        valid_materials = [material for material in self.materials.values() if not material.is_empty]
        total_materials = len(valid_materials)
        
        if total_materials == 0:
            self._log("⚠️ 未发现任何有效材料，跳过审核流程")
            return self._assemble_report({}, "⚠️ 未发现任何有效材料。")
        
        self._log(f"📊 需要处理 {total_materials} 个有效材料")
        
        # 估算处理时间（每个材料约10-30秒）
        estimated_time = total_materials * 20  # 平均估算
        self._log(f"🕰️ 预计处理时间: {estimated_time//60}分{estimated_time%60}秒（根据API响应速度可能有所不同）")
        
        results, core_infos = {}, {}
        
        # 使用线程池并发处理材料验证和信息提取
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:  # 减少并发线程数以避免资源竞争
            # 提交验证任务
            validation_futures = {}
            info_futures = {}
            
            for mid, material in self.materials.items():
                if not material.is_empty:
                    # 提交独立验证任务
                    validation_future = executor.submit(self._validate_single_material, material)
                    validation_futures[validation_future] = mid
                    
                    # 提交核心信息提取任务
                    info_future = executor.submit(self._extract_core_info, material)
                    info_futures[info_future] = mid
            
            # 收集验证结果，添加超时机制
            self._log(f"  🔍 正在处理 {len(validation_futures)} 个验证任务...")
            validation_completed = 0
            
            try:
                for future in concurrent.futures.as_completed(validation_futures, timeout=600):  # 10分钟超时
                    mid = validation_futures[future]
                    try:
                        validation_text = future.result(timeout=180)  # 3分钟超时
                        results[mid] = validation_text
                        self._parse_and_log_violations(self.materials[mid], validation_text)
                        validation_completed += 1
                        self._log(f"  ✅ 独立验证进度: {validation_completed}/{len(validation_futures)} - {self.materials[mid].name}")
                        
                        # 每完成5个任务显示一次进度提示
                        if validation_completed % 5 == 0 or validation_completed == len(validation_futures):
                            progress_percent = int((validation_completed / len(validation_futures)) * 100)
                            self._log(f"  📊 验证进度: {progress_percent}% ({validation_completed}/{len(validation_futures)})")
                            
                    except concurrent.futures.TimeoutError:
                        self._log(f"  ⏳ 独立验证超时 {self.materials[mid].name}")
                        results[mid] = f"AI分析超时: {self.materials[mid].name}"
                    except Exception as e:
                        self._log(f"  ❌ 独立验证失败 {self.materials[mid].name}: {e}")
                        results[mid] = f"AI分析失败: {e}"
                        
            except concurrent.futures.TimeoutError:
                self._log(f"  ⚠️ 验证阶段整体超时，已完成 {validation_completed}/{len(validation_futures)} 个任务")
            
            # 收集核心信息提取结果，添加超时机制
            self._log(f"  💡 正在处理 {len(info_futures)} 个信息提取任务...")
            info_completed = 0
            
            try:
                for future in concurrent.futures.as_completed(info_futures, timeout=600):  # 10分钟超时
                    mid = info_futures[future]
                    try:
                        core_info = future.result(timeout=180)  # 3分钟超时
                        core_infos[mid] = core_info
                        info_completed += 1
                        self._log(f"  ✅ 信息提取进度: {info_completed}/{len(info_futures)} - {self.materials[mid].name}")
                        
                        # 每完成5个任务显示一次进度提示
                        if info_completed % 5 == 0 or info_completed == len(info_futures):
                            progress_percent = int((info_completed / len(info_futures)) * 100)
                            self._log(f"  📊 信息提取进度: {progress_percent}% ({info_completed}/{len(info_futures)})")
                            
                    except concurrent.futures.TimeoutError:
                        self._log(f"  ⏳ 信息提取超时 {self.materials[mid].name}")
                        core_infos[mid] = {"error": f"核心信息提取超时: {self.materials[mid].name}"}
                    except Exception as e:
                        self._log(f"  ❌ 核心信息提取失败 {self.materials[mid].name}: {e}")
                        core_infos[mid] = {"error": f"核心信息提取失败: {e}"}
                        
            except concurrent.futures.TimeoutError:
                self._log(f"  ⚠️ 信息提取阶段整体超时，已完成 {info_completed}/{len(info_futures)} 个任务")
        
        self._log("✅ 阶段1完成")
        self._log("---阶段2: 核心信息交叉检验---")
        cross_validation_report = self._perform_cross_validation(core_infos)
        self._log("✅ 阶段2完成")
        self._log("---阶段3: 生成最终报告---")
        report = self._assemble_report(results, cross_validation_report)
        self._log("✅ 报告生成完毕!")
        return report

    def _validate_single_material(self, material: MaterialInfo) -> str:
        """分阶段验证材料：先专项规则，再通用规则"""
        validation_results = []
        
        # 分离专项规则和通用规则
        specific_rules = [r for r in material.applicable_rules if getattr(r, 'rule_type', '') == '专项规则']
        universal_rules = [r for r in material.applicable_rules if getattr(r, 'rule_type', '') == '通用规则']
        
        # 阶段1：专项规则验证
        if specific_rules:
            self._log(f"    📋 阶段1: 验证专项规则 ({len(specific_rules)}条)")
            specific_result = self._validate_with_rules(material, specific_rules, "专项规则")
            validation_results.append(f"## 专项规则验证结果\n{specific_result}")
        
        # 阶段2：通用规则验证
        if universal_rules:
            self._log(f"    📋 阶段2: 验证通用规则 ({len(universal_rules)}条)")
            universal_result = self._validate_with_rules(material, universal_rules, "通用规则")
            validation_results.append(f"## 通用规则验证结果\n{universal_result}")
        
        return "\n\n".join(validation_results)
    
    def _validate_with_rules(self, material: MaterialInfo, rules: list, rule_type: str) -> str:
        """使用指定规则集验证材料"""
        sorted_rules = sorted(rules, key=lambda r: {"极高": 4, "高": 3, "中": 2, "低": 1}.get(r.优先级, 0), reverse=True)
        rules_text = "\n".join([f"{i}. 【{r.优先级}】{r.核心问题}: {r.规则内容}" for i, r in enumerate(sorted_rules, 1)])
        
        prompt = f"""你是一位严谨的职称评审专家，请审查《{material.name}》材料，检查是否符合{rule_type}要求。

=== 待审查的{rule_type} ===
{rules_text}

=== 材料内容 ===
{material.content[:5000] if material.content else '材料内容为空'}

=== 审查要求 ===
请严格按照以下标准格式逐条检查每个规则：

规则X: [规则名称]
判断: ✅符合 / ❌违反
理由: [如果违反，详细说明违反的具体内容；如果符合，可简述符合情况]

=== 输出格式示例 ===
规则1: 时间逻辑一致性
判断: ❌违反
理由: 发现工作时间存在重叠，2020年3月在A公司工作的同时，2020年2月已在B公司任职

规则2: 单位信息一致性  
判断: ✅符合
理由: 所有材料中单位名称表述一致

=== 重要说明 ===
1. 必须严格按照"规则X: [名称]\n判断: [结果]\n理由: [说明]"的格式输出
2. 只有确实发现明确违反的情况，才判断为"违反"
3. 如果材料内容不足以判断，请说明"材料信息不足，无法判断"
4. 不要编造或推测没有在材料中明确出现的信息
5. 重点关注时间逻辑、数据一致性、职业资历等关键问题
6. 每个规则必须单独成段，用空行分隔"""
        
        # 使用API轮询机制，降低温度提高准确性
        def ai_call(client):
            return client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=prompt, 
            )
        
        try:
            response = self._rotated_api_call(ai_call)
            return response.text.strip()
        except Exception as e:
            return f"{rule_type}验证失败: {e}"

    def _parse_and_log_violations(self, material: MaterialInfo, validation_text: str):
        sorted_rules = sorted(material.applicable_rules, key=lambda r: {"极高": 4, "高": 3, "中": 2, "低": 1}.get(r.优先级, 0), reverse=True)
        violations = []  # 存储当前材料的违规问题
        
        for i, rule in enumerate(sorted_rules, 1):
            for line in validation_text.split('\n'):
                if (f"规则{i}" in line or line.strip().startswith(f"{i}.")) and ("违反" in line or "不一致" in line):
                    violation_text = f"【{rule.优先级}】{rule.核心问题}: {line.strip()}"
                    violations.append(violation_text)
                    self.high_priority_violations.append(f"在《{material.name}》中发现{rule.优先级}优先级问题: {rule.核心问题}")
                    self._log(f"    - ⚠️ 发现{rule.优先级}优先级违规: {rule.核心问题}")
                    break
        
        # 将违规问题存储到材料对象中
        material.rule_violations = violations

    def _extract_core_info(self, material: MaterialInfo) -> Dict[str, Any]:
        """提取材料核心信息 - 统一提取姓名、工作单位，工作经历材料特殊处理"""
        
        # 根据材料类型构建不同的提取规则
        if material.id == 2:  # 工作经历材料特殊处理
            prompt = f"""请从这份《{material.name}》材料中，提取以下核心信息并以JSON格式返回：

**统一提取字段**：
- "姓名": 申请人的姓名
- "工作单位": 当前或主要工作单位名称

**工作经历特殊字段**：
- "工作经历详情": 包含每段工作经历的详细信息，格式为数组，每个元素包含:
  - "起始时间": 开始工作的时间（年月）
  - "结束时间": 结束工作的时间（年月，如仍在职请标注"至今"）
  - "工作地点": 工作所在的城市或地区
  - "单位名称": 具体的工作单位名称
  - "职务": 在该单位担任的职务

**返回格式示例**：
{{
  "姓名": "张三",
  "工作单位": "某某大学",
  "工作经历详情": [
    {{
      "起始时间": "2018年9月",
      "结束时间": "2021年7月", 
      "工作地点": "北京市",
      "单位名称": "某某科技有限公司",
      "职务": "软件工程师"
    }},
    {{
      "起始时间": "2021年8月",
      "结束时间": "至今",
      "工作地点": "上海市", 
      "单位名称": "某某大学",
      "职务": "讲师"
    }}
  ]
}}

---材料内容---
{material.content[:5000] if material.content else '材料内容为空'}"""
        else:
            # 其他材料的通用提取规则
            prompt = f"""请从这份《{material.name}》材料中，提取以下核心信息并以JSON格式返回：

**必须提取的字段**：
- "姓名": 申请人的姓名


**可选提取的字段**（如果材料中有相关信息）：
- "工作单位": 当前或主要工作单位名称
- "身份证号": 身份证号码（如有）
- "职务": 职务或职称信息（如有）
- "专业": 专业领域或学科（如有）
- "学历": 学历信息（如有）
- "时间范围": 材料涉及的时间范围（如有）

**返回格式示例**：
{{
  "姓名": "张三",
  "工作单位": "某某大学",
  "身份证号": "1234567890",
  "职务": "副教授",
  "专业": "计算机科学与技术"
}}

---材料内容---
{material.content[:5000] if material.content else '材料内容为空'}"""
        
        # 使用API轮询机制
        def ai_call(client):
            return client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=prompt
            )
        
        try:
            response = self._rotated_api_call(ai_call)
            match = re.search(r'{{.*}}', response.text, re.DOTALL)
            if match: 
                result = json.loads(match.group())
                # 确保必须字段存在
                if "姓名" not in result:
                    result["姓名"] = None
                if "工作单位" not in result:
                    result["工作单位"] = None
                return result
            return {"error": "未提取到JSON格式信息"}
        except Exception as e:
            return {"error": f"核心信息提取失败: {e}"}

    def _perform_cross_validation(self, core_infos: Dict[int, Dict]) -> str:
        """执行核心信息交叉检验 - 增强版本，支持工作经历详细检验"""
        report_lines = []
        
        # 1. 基本信息一致性检验
        report_lines.append("### 🔍 基本信息一致性检验")
        report_lines.append("")
        
        # 使用字典推导式和并行处理来提高效率
        all_values = {
            k: [info.get(k) for _, info in core_infos.items() 
                if info and not info.get('error') and info.get(k)] 
            for k in ["姓名", "工作单位", "身份证号"]
        }
        
        for key, values in all_values.items():
            if not values:  # 没有发现该字段信息
                report_lines.append(f"- ℹ️ **{key}**: 未在材料中发现相关信息")
                continue
                
            # 去重并过滤空值
            unique_values = set(filter(lambda x: x and str(x).strip(), values))
            
            if len(unique_values) > 1: 
                # 发现不一致
                if key == "姓名":
                    priority = "🔴 [极高优先级]"
                elif key == "身份证号":
                    priority = "🔴 [极高优先级]"
                else:
                    priority = "🟠 [高优先级]"
                    
                report_lines.append(f"- {priority} **{key}不一致**: 发现 {len(unique_values)} 种不同值 - {', '.join(map(str, unique_values))}")
            elif unique_values: 
                report_lines.append(f"- ✅ **{key}一致**: {list(unique_values)[0]}")
        
        report_lines.append("")
        
        # 2. 工作经历详细检验（如果存在工作经历数据）
        work_experience_data = core_infos.get(2)  # 材料ID=2为工作经历
        if work_experience_data and not work_experience_data.get('error') and work_experience_data.get('工作经历详情'):
            report_lines.append("### 📋 工作经历时间逻辑检验")
            report_lines.append("")
            
            work_history = work_experience_data['工作经历详情']
            if isinstance(work_history, list) and len(work_history) > 0:
                # 检查时间重叠
                time_overlap_result = self._check_time_overlap(work_history)
                report_lines.extend(time_overlap_result)
                
                # 检查时间连续性
                time_continuity_result = self._check_time_continuity(work_history)
                report_lines.extend(time_continuity_result)
                
                # 检查工作地点变迁
                location_change_result = self._check_location_changes(work_history)
                report_lines.extend(location_change_result)
            else:
                report_lines.append("- ℹ️ **工作经历格式**: 数据格式异常或为空")
            
            report_lines.append("")
        
        # 3. 数据完整性检验
        report_lines.append("### 📈 数据完整性检验")
        report_lines.append("")
        
        # 统计信息提取情况
        total_materials = len([info for info in core_infos.values() if info])
        successful_extractions = len([info for info in core_infos.values() 
                                    if info and not info.get('error')])
        failed_extractions = total_materials - successful_extractions
        
        if failed_extractions == 0:
            report_lines.append(f"- ✅ **信息提取成功率**: 100% ({successful_extractions}/{total_materials})")
        else:
            report_lines.append(f"- ⚠️ **信息提取成功率**: {successful_extractions/total_materials*100:.1f}% ({successful_extractions}/{total_materials})")
            report_lines.append(f"- 🟡 [中优先级] **信息提取失败**: {failed_extractions} 个材料的信息提取失败")
        
        # 返回结果
        final_report = "\n".join(report_lines).strip()
        return final_report if final_report else "- ✅ 未发现明显的不一致之处。\n"
    
    def _check_time_overlap(self, work_history: List[Dict]) -> List[str]:
        """检查工作时间是否存在重叠"""
        results = []
        
        # 解析并排序时间段
        time_periods = []
        for i, job in enumerate(work_history):
            start_time = self._parse_time_string(job.get('起始时间', ''))
            end_time = self._parse_time_string(job.get('结束时间', ''))
            if start_time:
                time_periods.append({
                    'index': i,
                    'start': start_time,
                    'end': end_time,
                    'unit': job.get('单位名称', '未知单位'),
                    'job_title': job.get('职务', '')
                })
        
        # 检查重叠
        overlaps_found = False
        for i in range(len(time_periods)):
            for j in range(i + 1, len(time_periods)):
                period1, period2 = time_periods[i], time_periods[j]
                
                # 判断是否重叠（容忍1个月的交接期）
                if self._periods_overlap(period1, period2, tolerance_months=1):
                    overlaps_found = True
                    overlap_type = "🟠 [高优先级]"
                    results.append(f"- {overlap_type} **时间重叠**: 《{period1['unit']}》与《{period2['unit']}》存在时间重叠")
        
        if not overlaps_found:
            results.append("- ✅ **时间重叠检查**: 未发现时间重叠问题")
        
        return results
    
    def _check_time_continuity(self, work_history: List[Dict]) -> List[str]:
        """检查工作时间的连续性"""
        results = []
        
        # 按时间排序
        sorted_jobs = []
        for job in work_history:
            start_time = self._parse_time_string(job.get('起始时间', ''))
            if start_time:
                sorted_jobs.append((start_time, job))
        
        sorted_jobs.sort(key=lambda x: x[0])
        
        # 检查空白期
        gaps_found = False
        for i in range(len(sorted_jobs) - 1):
            current_job = sorted_jobs[i][1]
            next_job = sorted_jobs[i + 1][1]
            
            current_end = self._parse_time_string(current_job.get('结束时间', ''))
            next_start = self._parse_time_string(next_job.get('起始时间', ''))
            
            if current_end and next_start:
                gap_months = self._calculate_month_gap(current_end, next_start)
                if gap_months > 6:  # 超过6个月的空白期
                    gaps_found = True
                    results.append(f"- 🟡 [中优先级] **时间空白**: 《{current_job.get('单位名称', '')}》与《{next_job.get('单位名称', '')}》之间存在{gap_months}个月空白期")
                elif gap_months > 1:
                    results.append(f"- ⚠️ **短期空白**: 《{current_job.get('单位名称', '')}》与《{next_job.get('单位名称', '')}》之间存在{gap_months}个月间隔")
        
        if not gaps_found:
            results.append("- ✅ **时间连续性**: 工作经历时间连续性良好")
        
        return results
    
    def _check_location_changes(self, work_history: List[Dict]) -> List[str]:
        """检查工作地点变迁合理性"""
        results = []
        
        locations = [job.get('工作地点', '') for job in work_history if job.get('工作地点')]
        unique_locations = list(set(filter(None, locations)))
        
        if len(unique_locations) <= 1:
            results.append("- ✅ **地点变迁**: 工作地点相对稳定")
        elif len(unique_locations) <= 3:
            results.append(f"- ℹ️ **地点变迁**: 工作地点包括 {', '.join(unique_locations)}，属于正常范围")
        else:
            results.append(f"- 🟢 [低优先级] **地点变迁频繁**: 工作地点较多 ({len(unique_locations)}个)，建议核实变迁原因")
        
        return results
    
    def _parse_time_string(self, time_str: str) -> Optional[tuple]:
        """解析时间字符串为(year, month)元组"""
        if not time_str or time_str == '至今':
            return None
        
        import re
        # 匹配各种时间格式
        patterns = [
            r'(\d{4})年(\d{1,2})月',  # 2020年1月
            r'(\d{4})\.(\d{1,2})',        # 2020.01
            r'(\d{4})-(\d{1,2})',        # 2020-01
            r'(\d{4})/(\d{1,2})',        # 2020/01
        ]
        
        for pattern in patterns:
            match = re.search(pattern, time_str)
            if match:
                year, month = int(match.group(1)), int(match.group(2))
                return (year, month)
        
        return None
    
    def _periods_overlap(self, period1: Dict, period2: Dict, tolerance_months: int = 0) -> bool:
        """判断两个时间段是否重叠"""
        if not period1['start'] or not period2['start']:
            return False
        
        # 如果某个时间段没有结束时间，表示至今
        end1 = period1['end'] if period1['end'] else (2024, 12)  # 默认当前时间
        end2 = period2['end'] if period2['end'] else (2024, 12)
        
        # 转换为月份数进行比较
        start1_months = period1['start'][0] * 12 + period1['start'][1]
        end1_months = end1[0] * 12 + end1[1]
        start2_months = period2['start'][0] * 12 + period2['start'][1]
        end2_months = end2[0] * 12 + end2[1]
        
        # 考虑容忍度
        return not (end1_months + tolerance_months < start2_months or end2_months + tolerance_months < start1_months)
    
    def _calculate_month_gap(self, end_time: tuple, start_time: tuple) -> int:
        """计算两个时间点之间的月份差"""
        end_months = end_time[0] * 12 + end_time[1]
        start_months = start_time[0] * 12 + start_time[1]
        return start_months - end_months - 1  # 减1是因为相邻月份间隔为0

    def _assemble_report(self, results: Dict, cross_report: str) -> str:
        """组装模板化报告（严格按照模板格式，不允许AI自由发挥）"""
        empty_count = len(self.validation_results["empty_materials"])
        
        # 解析和分类违规问题
        self._log(f"🔍 开始解析违规问题并生成模板化报告...")
        violations_by_priority = self._parse_violations_from_results(results)
        
        # 统计数据
        total_materials = 17
        valid_materials = total_materials - empty_count
        total_issues = sum(len(v) for v in violations_by_priority.values())
        
        # 📊 模板化报告开始
        report = self._generate_templated_report(
            valid_materials=valid_materials,
            total_materials=total_materials,
            total_rules=len(self.rules),
            violations_by_priority=violations_by_priority,
            total_issues=total_issues,
            empty_materials=self.validation_results["empty_materials"],
            cross_validation_report=cross_report
        )
        
        return report
    
    def _generate_templated_report(self, valid_materials: int, total_materials: int, 
                                  total_rules: int, violations_by_priority: Dict, 
                                  total_issues: int, empty_materials: List, 
                                  cross_validation_report: str) -> str:
        """生成严格模板化的报告（不允许AI自由发挥）"""
        
        # 📅 1. 材料概览（严格模板）
        overview_section = self._generate_material_overview_template(
            valid_materials, total_materials, total_rules
        )
        
        # ⚠️ 2. 问题摘要（严格模板）
        summary_section = self._generate_problem_summary_template(
            violations_by_priority, total_issues
        )
        
        # 🚨 3. 详细问题列表（严格模板）
        details_section = self._generate_problem_details_template(
            violations_by_priority, total_issues
        )
        
        # 🔄 4. 核心信息交叉检验（严格模板）
        cross_validation_section = self._generate_cross_validation_template(
            cross_validation_report
        )
        
        # 缺失材料部分（如果有）
        missing_section = ""
        if empty_materials:
            missing_section = self._generate_missing_materials_template(empty_materials)
        
        # 组装最终报告
        final_report = f"""
# 📋 职称评审材料交叉检验报告

{overview_section}

{summary_section}

{details_section}

{cross_validation_section}
{missing_section}
""".strip()
        
        return final_report
    
    def _generate_material_overview_template(self, valid_materials: int, 
                                            total_materials: int, total_rules: int) -> str:
        """生成材料概览模板（严格格式）"""
        from datetime import datetime
        
        return f"""
## 1. 📈 材料概览

| 项目 | 数量 | 状态 |
|------|------|------|
| 总材料数 | {total_materials} 项 | 标准 |
| 有效材料 | {valid_materials} 项 | {'✅ 充足' if valid_materials >= 15 else '⚠️ 不足'} |
| 适用规则 | {total_rules} 条 | ✅ 已加载 |
| 检验日期 | {datetime.now().strftime('%Y-%m-%d %H:%M')} | ✅ 完成 |

**材料完整性评估**: {'✅ 优秀' if valid_materials >= 16 else '⚠️ 良好' if valid_materials >= 14 else '❌ 不合格'}
""".strip()
    
    def _generate_problem_summary_template(self, violations_by_priority: Dict, 
                                          total_issues: int) -> str:
        """生成问题摘要模板（严格格式）"""
        
        if total_issues == 0:
            return """
## 2. ✅ 问题摘要

**检验结果**: 所有材料均符合要求，未发现任何问题。

| 优先级 | 问题数量 | 状态 |
|----------|----------|------|
| 🔴 极高优先级 | 0 个 | ✅ 通过 |
| 🟠 高优先级 | 0 个 | ✅ 通过 |
| 🟡 中优先级 | 0 个 | ✅ 通过 |
| 🟢 低优先级 | 0 个 | ✅ 通过 |

**综合评价**: 🎆 优秀，所有材料均符合审核标准。
""".strip()
        
        # 统计各优先级问题数量
        extreme_count = len(violations_by_priority.get("极高", []))
        high_count = len(violations_by_priority.get("高", []))
        medium_count = len(violations_by_priority.get("中", []))
        low_count = len(violations_by_priority.get("低", []))
        
        # 判断问题严重程度
        if extreme_count > 0:
            severity = "❌ 严重"
            recommendation = "必须立即处理所有极高优先级问题，否则可能导致材料被直接拒绝。"
        elif high_count > 0:
            severity = "⚠️ 较重"
            recommendation = "建议优先处理高优先级问题，提升材料质量。"
        elif medium_count > 0:
            severity = "🟡 一般"
            recommendation = "建议处理中优先级问题，进一步提升材料质量。"
        else:
            severity = "🟢 轻微"
            recommendation = "仅有低优先级问题，可选择性处理。"
        
        return f"""
## 2. ⚠️ 问题摘要

**检验结果**: 发现 **{total_issues}** 个问题，问题严重程度: {severity}

| 优先级 | 问题数量 | 状态 |
|----------|----------|------|
| 🔴 极高优先级 | {extreme_count} 个 | {'❌ 严重' if extreme_count > 0 else '✅ 通过'} |
| 🟠 高优先级 | {high_count} 个 | {'⚠️ 警告' if high_count > 0 else '✅ 通过'} |
| 🟡 中优先级 | {medium_count} 个 | {'🔸 注意' if medium_count > 0 else '✅ 通过'} |
| 🟢 低优先级 | {low_count} 个 | {'🔹 忽略' if low_count > 0 else '✅ 通过'} |

**处理建议**: {recommendation}
""".strip()
    
    def _generate_problem_details_template(self, violations_by_priority: Dict, 
                                          total_issues: int) -> str:
        """生成详细问题列表模板（严格格式）"""
        
        if total_issues == 0:
            return """
## 3. ✅ 详细问题列表

**检验结果**: 未发现任何问题，所有材料均符合要求。

### 🎆 正常状态
- ✅ 所有专项规则检查通过
- ✅ 所有通用规则检查通过
- ✅ 所有交叉验证检查通过
- ✅ 材料内容完整性良好

**结论**: 所有材料均符合职称评审要求，建议通过。
""".strip()
        
        details = []
        details.append("## 3. 🚨 详细问题列表")
        details.append("")
        details.append(f"**问题总数**: {total_issues} 个，按优先级分类如下：")
        details.append("")
        
        # 按优先级顺序显示问题
        priority_configs = [
            ("极高", "🔴", "必须立即处理，可能导致材料被直接拒绝"),
            ("高", "🟠", "需要重点关注和处理"),
            ("中", "🟡", "建议处理以提升材料质量"),
            ("低", "🟢", "可选择性处理")
        ]
        
        for priority, icon, description in priority_configs:
            issues = violations_by_priority.get(priority, [])
            if issues:
                details.append(f"### {icon} {priority}优先级问题 ({len(issues)}个)")
                details.append(f"> {description}")
                details.append("")
                
                # 按材料分组显示问题
                materials_with_issues = {}
                for violation in issues:
                    material_name = violation['material_name']
                    if material_name not in materials_with_issues:
                        materials_with_issues[material_name] = []
                    materials_with_issues[material_name].append(violation)
                
                for material_name, material_violations in materials_with_issues.items():
                    details.append(f"#### 📄 《{material_name}》")
                    for i, violation in enumerate(material_violations, 1):
                        formatted_issue = self._format_violation_description(violation)
                        details.append(f"**问题 {i}**: {formatted_issue}")
                        details.append("")
                
                details.append("---")
                details.append("")
        
        return "\n".join(details).strip()
    
    def _generate_cross_validation_template(self, cross_validation_report: str) -> str:
        """生成交叉检验模板（严格格式）"""
        
        return f"""
## 4. 🔄 核心信息交叉检验

**检验范围**: 姓名、工作单位、身份证号等关键信息在不同材料中的一致性

**检验方法**: 自动提取各材料中的核心信息，进行交叉对比分析

### 检验结果

{cross_validation_report}

**结论**: {'✅ 交叉检验通过' if '不一致' not in cross_validation_report else '⚠️ 存在不一致问题，需要进一步核实'}
""".strip()
    
    def _generate_missing_materials_template(self, empty_materials: List) -> str:
        """生成缺失材料模板（严格格式）"""
        
        missing_list = []
        for mid in empty_materials:
            material_name = self.MATERIAL_NAMES.get(mid, f"未知材料{mid}")
            missing_list.append(f"- **{mid}.** {material_name}")
        
        return f"""

## ❌ 缺失材料详情

**缺失数量**: {len(empty_materials)} 项

**处理建议**: 请尽快补充以下缺失材料，确保申报材料的完整性

### 缺失清单

{chr(10).join(missing_list)}

**注意事项**: 缺失的材料可能影响整体评审结果，建议优先补充。
""".strip()
    
    def _parse_violations_from_results(self, results: Dict) -> Dict[str, List[Dict]]:
        """从AI结果中解析违规问题，按优先级分类。增强版。"""
        violations_by_priority = {
            "极高": [],
            "高": [],
            "中": [],
            "低": []
        }
        
        total_violations = 0
        self._log(f"  🔍 开始解析所有材料的违规问题...")
        
        for mid, result in results.items():
            material = self.materials[mid]
            if material.is_empty:
                continue
                
            # 解析AI结果
            violations = self._extract_violations_from_text(result, material.name)
            material_violation_count = len(violations)
            total_violations += material_violation_count
            
            if material_violation_count > 0:
                self._log(f"    📝 《{material.name}》: 发现 {material_violation_count} 个违规问题")
            
            # 按优先级分类
            for violation in violations:
                priority = violation.get('priority', '中')
                if priority in violations_by_priority:
                    violations_by_priority[priority].append(violation)
                    self._log(f"      → 记录{priority}优先级问题: {violation.get('rule_title', '未知规则')}")
                else:
                    # 如果优先级不在预期列表中，默认归类为中优先级
                    violations_by_priority["中"].append(violation)
                    self._log(f"      ⚠️ 未知优先级'{priority}'，归类为中优先级: {violation.get('rule_title', '未知规则')}")
        
        # 统计总体情况
        priority_counts = {p: len(v) for p, v in violations_by_priority.items() if len(v) > 0}
        if priority_counts:
            stats_summary = ", ".join([f"{p}: {c}个" for p, c in priority_counts.items()])
            self._log(f"  📊 违规问题统计 - 总计: {total_violations}个，分布: {stats_summary}")
        else:
            self._log(f"  ✅ 未发现任何违规问题")
        
        return violations_by_priority
    
    def _extract_violations_from_text(self, text: str, material_name: str) -> List[Dict]:
        """从文本中提取违规问题（增强版，支持多种AI输出格式）"""
        violations = []
        lines = text.split('\n')
        
        current_rule_info = {
            'rule_number': '',
            'rule_title': '',
            'priority': '中',
            'judgment': '',
            'reason': ''
        }
        
        # 记录调试信息
        self._log(f"    🔍 开始解析《{material_name}》的AI验证结果...")
        
        for line_idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # 匹配多种规则标题格式
            # 格式1: "规则1: 时间逻辑一致性"
            rule_match = re.search(r'规则(\d+)[:：]\s*(.+)', line)
            if rule_match:
                current_rule_info['rule_number'] = rule_match.group(1)
                current_rule_info['rule_title'] = rule_match.group(2).strip()
                # 从标题中提取优先级（如果有的话）
                priority_in_title = re.search(r'【(极高|高|中|低)】', current_rule_info['rule_title'])
                if priority_in_title:
                    current_rule_info['priority'] = priority_in_title.group(1)
                    current_rule_info['rule_title'] = re.sub(r'【[^】]*】', '', current_rule_info['rule_title']).strip()
                self._log(f"      📋 解析规则{current_rule_info['rule_number']}: {current_rule_info['rule_title']} [优先级: {current_rule_info['priority']}]")
                continue
            
            # 格式2: "1. 【高】时间逻辑一致性" 或 "1. 【高】时间逻辑一致性: xxx"
            priority_rule_match = re.search(r'(\d+)\.\s*【(极高|高|中|低)】(.+)', line)
            if priority_rule_match:
                current_rule_info['rule_number'] = priority_rule_match.group(1)
                current_rule_info['priority'] = priority_rule_match.group(2)
                title_part = priority_rule_match.group(3).strip()
                # 如果标题包含冒号，取冒号前的部分作为标题
                if ':' in title_part or '：' in title_part:
                    current_rule_info['rule_title'] = re.split(r'[:：]', title_part)[0].strip()
                else:
                    current_rule_info['rule_title'] = title_part
                self._log(f"      📋 解析规则{current_rule_info['rule_number']}: {current_rule_info['rule_title']} [优先级: {current_rule_info['priority']}]")
                continue
            
            # 格式3: 直接的优先级标记行 "【极高】" 或 "优先级: 高"
            priority_only_match = re.search(r'【(极高|高|中|低)】|优先级[:：]\s*(极高|高|中|低)', line)
            if priority_only_match:
                priority_found = priority_only_match.group(1) or priority_only_match.group(2)
                if priority_found:
                    current_rule_info['priority'] = priority_found
                    self._log(f"      🎯 更新优先级为: {current_rule_info['priority']}")
                continue
            
            # 匹配判断结果
            judgment_match = re.search(r'判断[:：]\s*(❌违反|✅符合|违反|符合|不符合)', line)
            if judgment_match:
                current_rule_info['judgment'] = judgment_match.group(1)
                self._log(f"      ⚖️ 判断结果: {current_rule_info['judgment']}")
                continue
            
            # 匹配理由
            reason_match = re.search(r'理由[:：]\s*(.+)', line)
            if reason_match:
                current_rule_info['reason'] = reason_match.group(1).strip()
                self._log(f"      📝 理由: {current_rule_info['reason'][:50]}...")
                
                # 检查是否为违反情况
                is_violation = (
                    '违反' in current_rule_info.get('judgment', '') or 
                    '❌' in current_rule_info.get('judgment', '') or
                    '不符合' in current_rule_info.get('judgment', '')
                )
                
                if is_violation:
                    # 确保有有效的规则信息和理由
                    skip_keywords = ['材料信息不足', '无法判断', '符合要求', '无明显问题', '暂无发现']
                    if current_rule_info['reason'] and not any(skip_word in current_rule_info['reason'] for skip_word in skip_keywords):
                        violation = {
                            'material_name': material_name,
                            'priority': current_rule_info.get('priority', '中'),
                            'rule_title': current_rule_info.get('rule_title', '规则检查'),
                            'rule_number': current_rule_info.get('rule_number', ''),
                            'problem_description': f"违反规则{current_rule_info.get('rule_number', '')}: {current_rule_info.get('rule_title', '')}",
                            'reason': current_rule_info['reason'],
                            'suggestion': ''  # 可以后续从AI输出中提取建议
                        }
                        violations.append(violation)
                        self._log(f"      🚨 记录{current_rule_info['priority']}优先级违规: {current_rule_info['rule_title']}")
                    else:
                        self._log(f"      ℹ️ 跳过无效违规记录: {current_rule_info['reason'][:30]}...")
                
                # 重置当前规则信息，准备处理下一个规则
                current_rule_info = {
                    'rule_number': '',
                    'rule_title': '',
                    'priority': '中',
                    'judgment': '',
                    'reason': ''
                }
                continue
        
        self._log(f"    ✅ 《{material_name}》解析完成，发现 {len(violations)} 个违规问题")
        
        # 按优先级统计
        priority_stats = {}
        for violation in violations:
            priority = violation['priority']
            priority_stats[priority] = priority_stats.get(priority, 0) + 1
        
        if priority_stats:
            stats_str = ', '.join([f"{p}: {c}个" for p, c in priority_stats.items()])
            self._log(f"    📊 优先级分布: {stats_str}")
        
        return violations
    
    def _format_violation_description(self, violation: Dict[str, str]) -> str:
        """格式化违规问题描述"""
        formatted_parts = []
        
        # 规则信息 - 清晰显示
        rule_title = violation.get('rule_title', '').strip()
        if rule_title and rule_title != '规则检查':
            formatted_parts.append(f"📋 **规则**: {rule_title}")
        
        # 问题描述 - 简洁明了
        reason = violation.get('reason', '').strip()
        if reason:
            # 清理理由文本，移除多余的符号和空格
            clean_reason = re.sub(r'^[*\-\s]+', '', reason)  # 移除开头的符号
            clean_reason = re.sub(r'\s+', ' ', clean_reason)  # 规范化空格
            if clean_reason:
                formatted_parts.append(f"⚠️ **问题**: {clean_reason}")
        
        # 处理建议
        suggestion = violation.get('suggestion', '').strip()
        if suggestion:
            clean_suggestion = re.sub(r'^[*\-\s]+', '', suggestion)
            clean_suggestion = re.sub(r'\s+', ' ', clean_suggestion)
            if clean_suggestion:
                formatted_parts.append(f"💡 **建议**: {clean_suggestion}")
        
        # 如果没有有效内容，返回通用描述
        if not formatted_parts:
            return "⚠️ 发现问题，但具体信息不完整"
        
        return '\n   '.join(formatted_parts)


