# 异步队列系统使用指南

## 概述

本系统已升级为基于 **Celery + Redis** 的异步队列架构，替代了原有的简单ThreadPoolExecutor，提供了以下改进：

- ✅ **任务优先级支持** - 根据任务类型和系统负载自动分配优先级
- ✅ **智能负载均衡** - 动态调整任务分发策略
- ✅ **更好的资源管理** - 避免系统过载，提高稳定性
- ✅ **实时监控** - 任务状态追踪和性能统计
- ✅ **容错能力** - 任务重试和故障恢复

## 系统架构

```
┌─────────────────┐    ┌──────────────┐    ┌─────────────────┐
│   Flask Web应用  │────│ Queue Manager│────│   Load Balancer │
└─────────────────┘    └──────────────┘    └─────────────────┘
         │                       │                     │
         │                       ▼                     ▼
         │               ┌──────────────┐    ┌─────────────────┐
         │               │ Redis Message│    │ System Monitor  │
         │               │    Broker    │    │  (CPU/Memory)   │
         │               └──────────────┘    └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐    ┌──────────────────────────────────┐
│  Progress Tracker│    │        Celery Workers           │
└─────────────────┘    │  ┌─────────┐ ┌─────────┐ ┌────────┐
                       │  │PDF提取  │ │文件处理 │ │交叉验证│
                       │  │ Queue   │ │ Queue   │ │ Queue  │
                       │  └─────────┘ └─────────┘ └────────┘
                       └──────────────────────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

新增的依赖包括：
- `celery>=5.3.0` - 异步任务队列
- `redis>=4.5.0` - 消息代理
- `kombu>=5.3.0` - 消息传输
- `psutil>=5.9.0` - 系统监控

### 2. 启动Redis服务

**Windows:**
```bash
# 下载并安装Redis，然后启动
redis-server
```

**Linux/macOS:**
```bash
# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# macOS
brew install redis
brew services start redis
```

### 3. 配置环境变量

更新 `.env` 文件：
```env
# 原有配置保持不变
GOOGLE_API_KEY=your_api_keys_here

# 新增Redis配置
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### 4. 启动Celery Worker

**方法1: 使用批处理脚本 (Windows)**
```bash
start_celery.bat
```

**方法2: 使用Python脚本**
```bash
python start_worker.py
```

**方法3: 直接使用Celery命令**
```bash
celery -A celery_app worker --loglevel=info --concurrency=4
```

### 5. 启动Web应用

```bash
python app.py
```

## 核心组件说明

### 1. 队列管理器 (queue_manager.py)

负责任务的提交、监控和管理：

```python
from queue_manager import queue_manager

# 提交PDF提取批任务
task_id = queue_manager.submit_pdf_extraction_batch(
    file_materials={'material_1': ['file1.pdf', 'file2.pdf']},
    priority=7,
    progress_callback=my_progress_callback
)

# 获取任务状态
status = queue_manager.get_task_status(task_id)
print(f"进度: {status['progress']}%")

# 获取结果
result = queue_manager.get_task_result(task_id, timeout=60)
```

### 2. 负载均衡器 (load_balancer.py)

智能调度和资源管理：

```python
from load_balancer import load_balancer

# 选择最优队列
queue, priority = load_balancer.select_optimal_queue('pdf_extraction')

# 检查是否应该限制任务
if load_balancer.should_throttle_tasks():
    print("系统负载较高，建议延缓任务提交")

# 获取推荐批大小
batch_size = load_balancer.get_recommended_batch_size('file_processing')
```

### 3. 异步适配器 (async_adapter.py)

提供向后兼容的ThreadPoolExecutor接口：

```python
from async_adapter import AsyncThreadPoolExecutor, async_as_completed

# 与原ThreadPoolExecutor完全兼容的用法
with AsyncThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(process_file, file) for file in files]
    
    for future in async_as_completed(futures):
        result = future.result()
        print(f"处理结果: {result}")
```

## 任务优先级系统

### 优先级定义

| 优先级 | 任务类型 | 说明 |
|--------|----------|------|
| 9-10   | 紧急任务 | 用户交互任务，需要立即响应 |
| 7-8    | PDF提取  | 高计算量任务，优先处理 |
| 5-6    | 文件处理 | 常规处理任务 |
| 3-4    | 交叉验证 | 后台分析任务 |
| 1-2    | 清理任务 | 系统维护任务 |

### 动态优先级调整

系统会根据以下因素自动调整任务优先级：

1. **系统负载**: CPU/内存使用率高时降低优先级
2. **队列长度**: 队列拥堵时调整任务分发
3. **文件大小**: 大文件降低优先级，小文件提高优先级
4. **历史性能**: 根据任务执行历史优化调度

## 监控和管理

### 查看队列状态

```python
from queue_manager import queue_manager

# 获取总体统计
stats = queue_manager.get_queue_stats()
print(f"活动任务数: {stats['active_tasks']}")

# 获取性能统计
from load_balancer import load_balancer
perf_stats = load_balancer.get_performance_stats()
print(f"CPU使用率: {perf_stats['system_load']['cpu_percent']}%")
```

### Web界面监控

可以通过以下URL查看任务状态：
- `/status` - 系统状态页面
- `/api/queue/stats` - 队列统计API

### Celery监控工具

```bash
# 查看活动任务
celery -A celery_app inspect active

# 查看队列状态
celery -A celery_app inspect stats

# 启动Flower监控界面
pip install flower
celery -A celery_app flower
```

## 迁移现有代码

### 自动迁移

使用提供的迁移脚本：

```bash
python migrate_to_async.py
```

### 手动迁移

将现有的ThreadPoolExecutor代码替换：

**原代码:**
```python
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(func, arg) for arg in args]
    for future in concurrent.futures.as_completed(futures):
        result = future.result()
```

**新代码:**
```python
from async_adapter import AsyncThreadPoolExecutor, async_as_completed

with AsyncThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(func, arg) for arg in args]
    for future in async_as_completed(futures):
        result = future.result()
```

## 性能优化建议

### 1. 批大小调优

```python
# 根据系统负载动态调整
batch_size = load_balancer.get_recommended_batch_size('pdf_extraction')
```

### 2. 并发数配置

- **CPU密集型任务**: 并发数 = CPU核心数
- **IO密集型任务**: 并发数 = CPU核心数 × 2-4
- **混合型任务**: 动态调整，监控系统负载

### 3. 内存管理

- 设置 `worker_max_memory_per_child` 限制内存使用
- 定期重启Worker进程避免内存泄漏
- 监控Redis内存使用

### 4. 故障恢复

```python
# 任务重试配置
@celery_app.task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3})
def robust_task(self, data):
    try:
        return process_data(data)
    except TemporaryError as e:
        # 暂时性错误，重试
        raise self.retry(countdown=60)
```

## 故障排除

### 常见问题

1. **Redis连接失败**
   ```bash
   # 检查Redis服务状态
   redis-cli ping
   # 应该返回 PONG
   ```

2. **Worker无法启动**
   ```bash
   # 检查Python路径和依赖
   python -c "from celery_app import celery_app; print('OK')"
   ```

3. **任务执行失败**
   ```bash
   # 查看详细日志
   celery -A celery_app worker --loglevel=debug
   ```

4. **内存不足**
   - 减少Worker并发数
   - 增加系统内存
   - 调整批处理大小

### 日志分析

关键日志位置：
- Worker日志: Celery worker输出
- Redis日志: Redis服务日志
- 应用日志: Flask应用日志

## 扩展性考虑

### 水平扩展

1. **多Worker实例**
   ```bash
   # 启动多个Worker
   celery -A celery_app worker --hostname=worker1@%h
   celery -A celery_app worker --hostname=worker2@%h
   ```

2. **分布式部署**
   - 使用Redis Cluster
   - 部署多台Worker机器
   - 负载均衡器分发

3. **队列分离**
   ```python
   # 专用队列配置
   task_routes = {
       'heavy_pdf_tasks': {'queue': 'heavy_processing'},
       'light_tasks': {'queue': 'quick_processing'}
   }
   ```

## 总结

新的异步队列系统相比原有ThreadPoolExecutor提供了：

- **更好的性能**: 智能负载均衡和优先级调度
- **更强的可靠性**: 任务重试和故障恢复
- **更易的监控**: 实时状态追踪和性能统计
- **更强的扩展性**: 支持分布式部署和水平扩展

通过合理配置和使用，可以显著提升系统的处理能力和用户体验。