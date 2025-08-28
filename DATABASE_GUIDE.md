# 数据库集成使用指南

## 概述

系统已成功集成SQLite数据库，实现了：
- ✅ 任务状态和历史记录的持久化存储
- ✅ 用户可查看历史分析报告
- ✅ 支持任务恢复和断点续传
- ✅ 完整的任务生命周期管理

## 功能特性

### 1. 任务状态存储
- **持久化存储**: 所有任务信息保存在SQLite数据库中
- **状态跟踪**: pending → processing → complete/error
- **时间记录**: 创建时间、开始时间、结束时间、处理时长
- **详细信息**: 文件信息、进度百分比、当前步骤

### 2. 历史记录查看
- **Web界面**: 访问 `/history` 查看所有历史任务
- **状态过滤**: 按任务状态筛选（完成、错误、处理中等）
- **详细信息**: 查看任务详情、处理时间、文件大小等
- **操作按钮**: 查看报告、删除任务、恢复任务

### 3. 断点续传
- **任务恢复**: 错误或中断的任务可以重新启动
- **状态检测**: 自动检测长时间未更新的处理中任务
- **文件检查**: 恢复前验证原始文件是否存在
- **日志保留**: 保留之前的处理日志

### 4. 数据库管理
- **自动备份**: 支持数据库备份和导出
- **清理功能**: 自动清理过期任务和日志
- **统计信息**: 提供详细的使用统计
- **优化工具**: 数据库维护和优化

## 数据库结构

### 任务表 (tasks)
```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,           -- 任务ID
    status TEXT NOT NULL,               -- 状态 (pending/processing/complete/error)
    created_at REAL NOT NULL,           -- 创建时间
    updated_at REAL NOT NULL,           -- 更新时间
    start_time REAL,                    -- 开始处理时间
    end_time REAL,                      -- 结束时间
    zip_file_path TEXT,                 -- ZIP文件路径
    excel_file_path TEXT,               -- Excel文件路径
    zip_file_name TEXT,                 -- ZIP文件名
    excel_file_name TEXT,               -- Excel文件名
    progress_percent REAL DEFAULT 0.0,  -- 进度百分比
    current_step TEXT,                  -- 当前步骤
    total_materials INTEGER DEFAULT 0,  -- 总材料数
    processed_materials INTEGER DEFAULT 0, -- 已处理材料数
    report_content TEXT,                -- 报告内容
    formatted_report TEXT,              -- 格式化报告
    error_message TEXT,                 -- 错误信息
    file_size_mb REAL DEFAULT 0.0,      -- 文件大小(MB)
    processing_time_seconds REAL DEFAULT 0.0, -- 处理时间(秒)
    cache_hits INTEGER DEFAULT 0,       -- 缓存命中次数
    cache_misses INTEGER DEFAULT 0      -- 缓存未命中次数
);
```

### 日志表 (task_logs)
```sql
CREATE TABLE task_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT, -- 日志ID
    task_id TEXT NOT NULL,              -- 关联任务ID
    timestamp REAL NOT NULL,            -- 时间戳
    level TEXT NOT NULL,                -- 日志级别 (INFO/WARN/ERROR/DEBUG)
    message TEXT NOT NULL,              -- 日志消息
    step TEXT,                          -- 步骤标识
    FOREIGN KEY (task_id) REFERENCES tasks (task_id)
);
```

## 环境配置

### 数据库路径设置
在 `.env` 文件中配置数据库路径：
```env
# 数据库配置（可选）
DATABASE_PATH=./database.db
```

如果不设置，将使用默认路径 `./database.db`

### 权限设置
确保应用有权限在工作目录创建和访问数据库文件：
- Windows: 确保目录不是只读
- Linux/Mac: 确保有适当的文件权限

## API接口

### 任务管理API

#### 获取任务列表
```http
GET /api/tasks?status=all&limit=20
```

#### 删除任务
```http
POST /api/task/{task_id}/delete
```

#### 恢复任务
```http
POST /api/task/{task_id}/resume
```

#### 获取统计信息
```http
GET /api/statistics
```

#### 清理旧任务
```http
POST /api/cleanup
Content-Type: application/json
{"days": 30}
```

## 数据库管理工具

### 命令行工具
使用 `manage_database.py` 进行数据库管理：

```bash
# 初始化数据库
python manage_database.py init

# 显示统计信息
python manage_database.py stats

# 备份数据库
python manage_database.py backup --dir backups

# 清理30天前的旧任务
python manage_database.py cleanup --days 30

# 列出最近10个任务
python manage_database.py list --limit 10

# 列出可恢复的任务
python manage_database.py resumable

# 优化数据库
python manage_database.py optimize

# 导出任务数据
python manage_database.py export <task_id> --dir exports
```

## 使用示例

### 1. 查看历史任务
```python
# 访问历史页面
http://localhost:5000/history

# 按状态过滤
http://localhost:5000/history?status=complete

# API方式获取
import requests
response = requests.get('http://localhost:5000/api/tasks')
tasks = response.json()['tasks']
```

### 2. 恢复中断的任务
```python
# Web界面操作
# 1. 访问 /history 页面
# 2. 找到状态为 error 或 processing 的任务
# 3. 点击"恢复任务"按钮

# API方式恢复
import requests
response = requests.post(f'http://localhost:5000/api/task/{task_id}/resume')
result = response.json()
```

### 3. 编程方式访问数据库
```python
from database_manager import DatabaseManager

# 初始化数据库管理器
db_manager = DatabaseManager()

# 获取最近任务
recent_tasks = db_manager.get_recent_tasks(10)

# 获取特定任务
task_info = db_manager.get_task(task_id)

# 获取任务日志
logs = db_manager.get_task_logs(task_id)

# 获取统计信息
stats = db_manager.get_task_statistics()
```

## 性能优化

### 1. 数据库维护
```bash
# 定期优化数据库
python manage_database.py optimize

# 清理旧数据
python manage_database.py cleanup --days 30
```

### 2. 监控建议
- 定期检查数据库大小
- 监控任务处理时间
- 清理失败的任务
- 备份重要数据

### 3. 存储建议
- 定期清理临时文件
- 监控磁盘空间使用
- 考虑日志轮转策略

## 故障排除

### 常见问题

1. **数据库文件权限错误**
   ```
   解决方案: 确保应用有读写权限
   Windows: 检查文件夹属性
   Linux: chmod 755 database.db
   ```

2. **数据库锁定错误**
   ```
   解决方案: 确保没有其他进程占用数据库
   重启应用或等待超时释放
   ```

3. **任务恢复失败**
   ```
   解决方案: 检查原始文件是否存在
   确认任务状态是否允许恢复
   查看错误日志获取详细信息
   ```

4. **历史页面加载慢**
   ```
   解决方案: 清理旧任务减少数据量
   优化数据库索引
   限制显示数量
   ```

### 日志查看
```bash
# 查看应用日志
tail -f app.log

# 查看数据库操作日志
python manage_database.py stats
```

## 数据安全

### 1. 备份策略
```bash
# 每日备份
python manage_database.py backup --dir daily_backups

# 压缩备份
tar -czf backup_$(date +%Y%m%d).tar.gz database.db
```

### 2. 数据导出
```bash
# 导出重要任务
python manage_database.py export task_id_here

# 批量导出
for task_id in $(python manage_database.py list | grep task_); do
    python manage_database.py export $task_id
done
```

### 3. 恢复测试
定期测试备份文件的完整性和可恢复性。

## 升级说明

### 从内存存储迁移
系统自动兼容旧版本，无需手动迁移。首次启动时会：
1. 自动创建数据库表结构
2. 保持API接口兼容性
3. 新任务将保存到数据库

### 数据库结构升级
系统启动时会自动检查并升级数据库结构，添加新字段。

---

**注意**: 数据库功能已完全集成，用户可以正常使用所有功能，包括任务历史查看、断点续传和数据管理。如有问题，请查看日志输出或使用管理工具进行诊断。