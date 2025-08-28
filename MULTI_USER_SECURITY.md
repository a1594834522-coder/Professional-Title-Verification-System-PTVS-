# 🔐 多用户隔离安全配置指南

## 📋 概述

本文档详细说明了职称评审材料交叉检验系统的多用户隔离机制，确保局域网内多个用户同时使用时的数据安全和隐私保护。

## 🛡️ 安全特性

### 核心隔离机制

1. **用户会话隔离**
   - ✅ 每个用户获得唯一的会话ID (UUID)
   - ✅ 会话数据完全分离，无法跨用户访问
   - ✅ 自动过期清理（2小时无活动后清理）

2. **文件存储隔离**
   - ✅ 每个用户拥有独立的临时目录
   - ✅ 临时文件路径包含用户ID，确保隔离
   - ✅ 文件上传完成后立即清理

3. **数据处理隔离**
   - ✅ AI分析结果仅对当前用户可见
   - ✅ 上传历史记录按用户分别存储
   - ✅ 处理过程完全独立

## 🏗️ 技术架构

### 会话管理
```python
user_sessions = {
    'user_id_1': {
        'temp_dirs': [],          # 用户专用临时目录
        'upload_history': [],     # 上传历史记录
        'last_activity': time     # 最后活动时间
    },
    'user_id_2': { ... }
}
```

### 临时目录结构
```
/tmp/title_review_system/
├── user_id_1/
│   ├── upload_1640123456_abc123/
│   └── upload_1640123789_def456/
├── user_id_2/
│   ├── upload_1640124000_ghi789/
│   └── upload_1640124234_jkl012/
```

### 数据流隔离
1. **用户A上传** → **用户A专用目录** → **用户A的分析结果**
2. **用户B上传** → **用户B专用目录** → **用户B的分析结果**
3. **用户C上传** → **用户C专用目录** → **用户C的分析结果**

## 👥 多用户使用场景

### 典型使用场景

1. **办公室团队使用**
   - 多名员工同时使用同一服务器
   - 每人处理自己的评审材料
   - 数据完全隔离，互不干扰

2. **评审委员会**
   - 多名评审专家同时工作
   - 各自审查不同申请人的材料
   - 确保评审公正性和保密性

3. **教育机构**
   - 多名教师同时使用
   - 处理不同学生的材料
   - 保护学生隐私

## 🔧 配置和部署

### 安全配置检查

```bash
# 检查系统安全配置
python -c "
import app
print('会话密钥:', bool(app.app.secret_key))
print('用户隔离:', hasattr(app, 'user_sessions'))
print('清理机制:', hasattr(app, 'cleanup_expired_sessions'))
"
```

### 生产环境建议

1. **强化Session配置**
   ```python
   app.config['SECRET_KEY'] = os.urandom(32)  # 使用强随机密钥
   app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS环境启用
   app.config['SESSION_COOKIE_HTTPONLY'] = True
   app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
   ```

2. **定期清理配置**
   ```python
   # 每10分钟清理一次过期会话
   from apscheduler.schedulers.background import BackgroundScheduler
   scheduler = BackgroundScheduler()
   scheduler.add_job(cleanup_expired_sessions, 'interval', minutes=10)
   scheduler.start()
   ```

3. **日志记录**
   ```python
   import logging
   logging.basicConfig(level=logging.INFO)
   # 记录用户活动日志
   ```

## 🔍 安全监控

### 实时监控指标

1. **用户会话状态**
   - 当前在线用户数
   - 会话持续时间
   - 活动频率

2. **资源使用情况**
   - 临时文件数量
   - 磁盘使用情况
   - 内存占用

3. **安全事件**
   - 异常访问尝试
   - 会话超时
   - 数据清理记录

### 监控API接口

```bash
# 获取系统状态
curl http://localhost:5000/session_info

# 响应示例
{
  "user_id": "abc12345",
  "total_sessions": 3,
  "upload_count": 2,
  "temp_dirs_count": 1,
  "session_age": 1800
}
```

## 🛠️ 用户操作指南

### 用户界面功能

1. **会话信息显示**
   - 🆔 会话ID（前8位）
   - 👥 在线用户数
   - 📊 使用次数

2. **数据管理**
   - 🗑️ 清理我的数据
   - ℹ️ 会话详情
   - 🔒 隐私保护提示

3. **自动功能**
   - ⏰ 2小时后自动清理
   - 🔄 30秒状态更新
   - 🧹 实时垃圾回收

### 用户操作步骤

1. **首次访问**
   ```
   用户打开网页 → 系统自动分配会话ID → 显示会话信息
   ```

2. **上传文件**
   ```
   选择文件 → 上传到用户专用目录 → 处理完成后清理
   ```

3. **查看结果**
   ```
   只能看到自己的分析结果 → 其他用户数据完全隔离
   ```

4. **清理数据**
   ```
   点击"清理我的数据" → 确认操作 → 立即清理所有个人数据
   ```

## ⚠️ 安全注意事项

### 重要安全提醒

1. **网络安全**
   - 仅在可信局域网中使用
   - 避免在公共网络中部署
   - 考虑使用VPN加密连接

2. **数据保护**
   - 敏感文件处理完成后立即清理
   - 避免长期存储用户数据
   - 定期检查临时目录

3. **访问控制**
   - 监控异常访问行为
   - 设置访问频率限制
   - 记录用户操作日志

### 已知限制

1. **内存存储**
   - 会话数据存储在内存中
   - 服务器重启后会话丢失
   - 大量用户时需要考虑内存使用

2. **无持久化**
   - 当前版本不支持数据库存储
   - 适合临时使用场景
   - 不建议长期大规模部署

## 🚀 扩展建议

### 生产环境增强

1. **数据库集成**
   ```python
   # 使用Redis存储会话数据
   import redis
   session_store = redis.Redis(host='localhost', port=6379)
   ```

2. **用户认证**
   ```python
   # 添加登录认证
   from flask_login import LoginManager, login_required
   ```

3. **审计日志**
   ```python
   # 详细的操作日志
   import logging
   audit_logger = logging.getLogger('audit')
   ```

4. **负载均衡**
   ```python
   # 多服务器部署
   from flask_session import Session
   ```

## 📞 技术支持

如需更高级的安全配置或遇到问题，请：

1. 检查系统日志：`/var/log/title_review_system.log`
2. 验证会话隔离：访问 `/session_info` 接口
3. 监控资源使用：检查临时目录大小
4. 测试数据隔离：使用多个浏览器同时访问

---

**🔒 数据安全是我们的首要任务，每个用户的隐私都得到严格保护！**