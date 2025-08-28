# 智能缓存系统配置指南

## 概述

项目现已集成智能缓存管理系统，支持：
- 基于MD5哈希的智能缓存键
- 多层缓存架构（内存 + 磁盘 + Redis可选）
- 自动过期机制和文件变更检测
- LRU内存淘汰策略
- 缓存大小管理

## 缓存架构

### 三级缓存结构
1. **内存缓存** - 最快访问，用于热点数据
2. **Redis缓存** - 中等速度，支持分布式（可选）
3. **文件缓存** - 持久化存储，重启后仍有效

### 缓存键设计
- 基于文件MD5哈希 + 前缀的智能缓存键
- 大文件（>10MB）使用优化的部分哈希算法
- 支持前缀区分不同类型的缓存内容

## 配置参数

### 基本配置
```python
cache_config = {
    'cache_dir': None,              # 缓存目录，默认为系统临时目录
    'max_age_hours': 24,            # 缓存有效期（小时）
    'max_memory_items': 100,        # 内存缓存最大条目数
    'max_disk_size_mb': 1000,       # 磁盘缓存最大大小（MB）
    'enable_redis': False,          # 是否启用Redis缓存
    'redis_url': None               # Redis连接URL
}
```

### 环境变量配置
在`.env`文件中添加以下配置：

```env
# Redis缓存配置（可选）
REDIS_URL=redis://localhost:6379/0

# 缓存配置（可选）
CACHE_MAX_AGE_HOURS=24
CACHE_MAX_MEMORY_ITEMS=100
CACHE_MAX_DISK_SIZE_MB=1000
```

## 功能特性

### 1. 智能文件变更检测
- 基于文件大小和修改时间
- 文件变更后自动失效相关缓存
- 确保缓存内容始终与文件同步

### 2. 过期机制
- 基于时间的自动过期
- 启动时自动清理过期缓存
- 支持自定义过期时间

### 3. 内存管理
- LRU（最近最少使用）淘汰策略
- 动态内存使用监控
- 超出限制时自动清理25%最旧条目

### 4. 磁盘空间管理
- 监控磁盘缓存大小
- 超出限制时自动清理旧文件
- 按文件修改时间排序清理

### 5. 缓存统计
- 命中率统计
- 各级缓存命中次数
- 缓存大小和条目数监控

## 使用方法

### 基本使用
```python
from cross_validator import CrossValidator

# 使用默认缓存配置
validator = CrossValidator(
    api_key="your_api_key",
    rules_dir="rules",
    progress_callback=callback
)

# 自定义缓存配置
cache_config = {
    'max_age_hours': 48,        # 缓存48小时
    'max_memory_items': 200,    # 内存缓存200个条目
    'enable_redis': True,       # 启用Redis
    'redis_url': 'redis://localhost:6379/0'
}

validator = CrossValidator(
    api_key="your_api_key",
    rules_dir="rules",
    progress_callback=callback,
    cache_config=cache_config
)
```

### 缓存管理
```python
# 获取缓存统计
stats = validator.get_cache_stats()
print(f"缓存命中率: {stats['hit_rate_percent']}%")

# 打印详细统计
validator.print_cache_stats()

# 清空所有缓存
validator.clear_cache()
```

## Redis配置

### 安装Redis（可选）
```bash
# Windows（使用Chocolatey）
choco install redis-64

# Ubuntu/Debian
sudo apt-get install redis-server

# macOS（使用Homebrew）
brew install redis
```

### 启动Redis
```bash
# 启动Redis服务
redis-server

# 验证Redis运行
redis-cli ping
```

### Redis配置
在`.env`文件中配置Redis URL：
```env
REDIS_URL=redis://localhost:6379/0
```

支持的Redis URL格式：
- `redis://localhost:6379/0` - 本地Redis
- `redis://user:password@hostname:port/db` - 带认证的Redis
- `redis://localhost:6379/0?socket_timeout=5` - 带参数的Redis

## 性能优化建议

### 内存缓存
- 根据系统内存调整`max_memory_items`
- 建议设置为50-200之间
- 处理大量小文件时可适当增加

### 磁盘缓存
- SSD建议设置1000-2000MB
- HDD建议设置500-1000MB
- 根据可用磁盘空间调整

### Redis缓存
- 适合多进程或分布式环境
- 单机环境可选择不启用
- 确保Redis内存足够

## 故障排除

### 常见问题

1. **缓存未命中**
   - 检查文件路径是否正确
   - 验证文件是否被修改
   - 确认缓存未过期

2. **Redis连接失败**
   - 检查Redis服务是否运行
   - 验证Redis URL配置
   - 确认网络连接正常

3. **磁盘空间不足**
   - 检查缓存目录磁盘空间
   - 调整`max_disk_size_mb`参数
   - 手动清理缓存目录

4. **内存使用过高**
   - 减少`max_memory_items`设置
   - 监控内存使用情况
   - 及时清理不需要的缓存

### 日志排查
缓存系统会输出详细的操作日志：
```
💾 智能缓存管理器初始化完成
   📁 缓存目录: /tmp/pdf_content_cache
   ⏰ 缓存有效期: 24 小时
   🧠 内存缓存限制: 100 个条目
   💽 磁盘缓存限制: 1000 MB
```

### 测试缓存系统
运行测试脚本验证缓存功能：
```bash
python test_cache_system.py
```

## 最佳实践

1. **开发环境**
   - 使用较短的过期时间（1-2小时）
   - 启用详细日志
   - 定期清理缓存

2. **生产环境**
   - 设置合适的过期时间（24-48小时）
   - 监控缓存命中率
   - 配置Redis以提高性能

3. **大文件处理**
   - 适当增加磁盘缓存大小
   - 使用SSD存储缓存
   - 考虑启用Redis缓存

4. **多用户环境**
   - 启用Redis缓存
   - 设置合理的内存限制
   - 监控系统资源使用

## 升级说明

从旧版本升级时：
1. 旧的内存缓存会自动迁移
2. 缓存键格式已优化，旧缓存会逐渐失效
3. 新的缓存系统向后兼容
4. 建议清理一次缓存以获得最佳性能

---

**注意**: 缓存系统会自动处理大部分情况，通常无需手动干预。如有问题，请查看日志输出或运行测试脚本进行诊断。