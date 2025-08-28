import os
import uuid
import time
import socket
import shutil
import tempfile
import markdown
import threading
from flask import Flask, request, jsonify, render_template, flash, redirect, url_for
from werkzeug.utils import secure_filename
from markupsafe import Markup
from cross_validator import CrossValidator
from dotenv import load_dotenv
from database_manager import DatabaseManager, TaskInfo, TaskLog

# 加载.env文件
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())

# 初始化数据库管理器
db_manager = DatabaseManager(
    db_path=os.environ.get('DATABASE_PATH'),
    progress_callback=lambda msg: print(f"[DB] {msg}")
)

# 兼容性：保持TASKS字典接口，但实际使用数据库
class TasksProxy:
    """任务代理类，提供字典接口但实际使用数据库"""
    
    def __contains__(self, task_id: str) -> bool:
        return db_manager.get_task(task_id) is not None
    
    def __getitem__(self, task_id: str) -> dict:
        task_info = db_manager.get_task(task_id)
        if not task_info:
            raise KeyError(f"Task {task_id} not found")
        
        # 转换为旧格式字典
        return {
            'status': task_info.status,
            'log': self._get_log_messages(task_id),
            'start_time': task_info.start_time or task_info.created_at,
            'last_update': task_info.updated_at,
            'report': task_info.report_content,
            'formatted_report': task_info.formatted_report,
            'error': task_info.error_message,
            # 扩展字段
            'progress_percent': task_info.progress_percent,
            'current_step': task_info.current_step,
            'total_materials': task_info.total_materials,
            'processed_materials': task_info.processed_materials,
        }
    
    def __setitem__(self, task_id: str, value: dict):
        # 获取现有任务或创建新任务
        existing_task = db_manager.get_task(task_id)
        current_time = time.time()
        
        if existing_task:
            # 更新现有任务
            updates = {}
            if 'status' in value:
                updates['status'] = value['status']
            if 'report' in value:
                updates['report_content'] = value['report']
            if 'formatted_report' in value:
                updates['formatted_report'] = value['formatted_report']
            if 'error' in value:
                updates['error_message'] = value['error']
            
            # 处理时间字段
            if value.get('status') == 'processing' and not existing_task.start_time:
                updates['start_time'] = current_time
            elif value.get('status') in ['complete', 'error']:
                updates['end_time'] = current_time
                if existing_task.start_time:
                    updates['processing_time_seconds'] = current_time - existing_task.start_time
            
            # 如果有log字段，将最后一条日志添加到数据库
            if 'log' in value and isinstance(value['log'], list) and value['log']:
                latest_message = value['log'][-1]  # 只取最后一条日志
                log_entry = TaskLog(
                    log_id=None,
                    task_id=task_id,
                    timestamp=current_time,
                    level='INFO',
                    message=latest_message
                )
                db_manager.add_task_log(log_entry)
            
            db_manager.update_task(task_id, updates)
        else:
            # 创建新任务
            task_info = TaskInfo(
                task_id=task_id,
                status=value.get('status', 'pending'),
                created_at=current_time,
                updated_at=current_time,
                start_time=value.get('start_time'),
                report_content=value.get('report'),
                formatted_report=value.get('formatted_report'),
                error_message=value.get('error')
            )
            db_manager.create_task(task_info)
            
            # 如果有日志，添加到数据库
            if 'log' in value and isinstance(value['log'], list):
                for message in value['log']:
                    log_entry = TaskLog(
                        log_id=None,
                        task_id=task_id,
                        timestamp=current_time,
                        level='INFO',
                        message=message
                    )
                    db_manager.add_task_log(log_entry)
    
    def _get_log_messages(self, task_id: str) -> list:
        """获取任务日志消息列表"""
        logs = db_manager.get_task_logs(task_id)
        return [log.message for log in logs]
    
    def get(self, task_id: str, default=None):
        try:
            return self[task_id]
        except KeyError:
            return default
    
    def keys(self):
        # 返回最近的任务ID列表
        recent_tasks = db_manager.get_recent_tasks(100)
        return [task.task_id for task in recent_tasks]
    
    def items(self):
        # 返回最近的任务项目
        recent_tasks = db_manager.get_recent_tasks(100)
        return [(task.task_id, self[task.task_id]) for task in recent_tasks]

# 创建任务代理实例
TASKS = TasksProxy()

def _safe_filename(filename: str) -> str:
    """安全地处理文件名，确保中文文件名正确显示"""
    try:
        if isinstance(filename, bytes):
            # 尝试用不同编码解码
            for encoding in ['utf-8', 'gbk', 'cp936']:
                try:
                    return filename.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return filename.decode('utf-8', errors='replace')
        return filename
    except Exception:
        return "未知文件"

def run_analysis_task(task_id, zip_path, excel_path):
    """The actual analysis function that runs in a background thread."""
    def progress_callback(message):
        """增强的进度回调函数，支持数据库日志记录"""
        current_time = time.time()
        
        # 添加日志到数据库
        log_entry = TaskLog(
            log_id=None,
            task_id=task_id,
            timestamp=current_time,
            level='INFO',
            message=message
        )
        db_manager.add_task_log(log_entry)
        
        # 更新任务的最后更新时间和当前步骤
        db_manager.update_task(task_id, {
            'current_step': message[:200],  # 限制步骤描述长度
            'updated_at': current_time
        })
    
    # 定时发送心跳消息的功能
    def send_heartbeat():
        """ 发送心跳消息以保持连接活跃 """
        while task_id in TASKS and TASKS[task_id]['status'] == 'processing':
            current_time = time.time()
            last_update = TASKS[task_id].get('last_update', current_time)
            
            # 如果超过30秒没有更新，发送心跳消息
            if current_time - last_update > 30:
                progress_callback("💬 系统正在处理中，请耐心等待...")
            
            time.sleep(10)  # 每10秒检查一次
    
    # 启动心跳线程
    heartbeat_thread = threading.Thread(target=send_heartbeat, daemon=True)
    heartbeat_thread.start()

    try:
        TASKS[task_id]['status'] = 'processing'
        progress_callback("🚀 准备开始处理...")
        
        # 配置API密钥（支持多个API密钥轮询）
        api_keys = []
        
        # 从环境变量中读取多个API密钥（支持多种格式）
        
        # 方法1：优先检查批量配置（支持换行+逗号混合分隔）
        batch_keys = os.environ.get('GOOGLE_API_KEYS')
        if batch_keys:
            # 使用换行和逗号混合分隔的批量配置
            # 先按换行分割，再按逗号分割，然后合并
            keys_list = []
            for line in batch_keys.split('\n'):
                if line.strip():
                    # 对每行按逗号分割
                    line_keys = [key.strip() for key in line.split(',') if key.strip()]
                    keys_list.extend(line_keys)
            
            for idx, key in enumerate(keys_list, 1):
                api_keys.append(key)
                progress_callback(f"🔑 加载批量API密钥 #{idx}: {key[:10]}...")
        else:
            # 方法2：检查GOOGLE_API_KEY是否包含多个密钥（逗号分隔）
            default_key = os.environ.get('GOOGLE_API_KEY')
            if default_key:
                # 检查是否包含逗号（多个API密钥）
                if ',' in default_key:
                    # 按逗号分割多个密钥
                    key_list = [key.strip() for key in default_key.split(',') if key.strip()]
                    for idx, key in enumerate(key_list, 1):
                        api_keys.append(key)
                        progress_callback(f"🔑 加载API密钥 #{idx}: {key[:10]}...")
                else:
                    # 单个密钥
                    api_keys.append(default_key)
                    progress_callback(f"🔑 加载默认API密钥: {default_key[:10]}...")
            
            # 方法3：传统的分别配置方式（GOOGLE_API_KEY_2等）
            i = 2
            while True:
                key_name = f'GOOGLE_API_KEY_{i}'
                api_key = os.environ.get(key_name)
                if not api_key:
                    break  # 没有更多密钥时停止
                
                api_keys.append(api_key)
                progress_callback(f"🔑 加载API密钥 #{i}: {api_key[:10]}...")
                i += 1
        
        # 检查是否找到任何API密钥
        if not api_keys:
            raise ValueError("未配置任何Google API密钥。请在.env文件中设置GOOGLE_API_KEYS（支持逗号、换行分隔）或GOOGLE_API_KEY等")
        
        progress_callback(f"🔄 启用API轮询模式: {len(api_keys)}个API密钥")
        
        # 缓存配置
        cache_config = {
            'max_age_hours': 24,  # 缓存有24小时
            'max_memory_items': 50,  # 内存缓存最多50个条目
            'max_disk_size_mb': 500,  # 磁盘缓存最大500MB
            'enable_redis': False,  # 默认不启用Redis
        }
        
        # 检查是否配置了Redis
        redis_url = os.environ.get('REDIS_URL')
        if redis_url:
            cache_config['enable_redis'] = True
            cache_config['redis_url'] = redis_url
            progress_callback("🔴 检测到Redis配置，启用Redis缓存")
        
        # 创建 CrossValidator 实例
        if len(api_keys) > 1:
            validator = CrossValidator(api_keys=api_keys, rules_dir="rules", progress_callback=progress_callback, cache_config=cache_config)
        else:
            validator = CrossValidator(api_key=api_keys[0], rules_dir="rules", progress_callback=progress_callback, cache_config=cache_config)
            
        progress_callback("📦 开始提取和识别材料...")
        validator.process_materials_from_zip(zip_path, os.path.dirname(zip_path))
        
        progress_callback("📊 材料提取完成，开始审核和报告生成...")
        progress_callback("🕰️ 此过程可能需要几分钟，请耐心等待...")
        
        report = validator.generate_full_report()

        # 使用原子更新，避免竞态条件
        TASKS[task_id] = {
            'status': 'complete',
            'report': report,
            'formatted_report': format_report_html(report)
        }
        progress_callback("🎉 全部任务处理完成!")

    except Exception as e:
        import traceback
        error_message = f"后台任务失败: {e}\n{traceback.format_exc()}"
        progress_callback(error_message)
        if task_id in TASKS:
            TASKS[task_id]['status'] = 'error'
            TASKS[task_id]['error'] = error_message

def format_report_html(report_text):
    """Formats the AI-generated report into beautiful HTML."""
    html = markdown.markdown(report_text, extensions=['extra', 'codehilite'])
    # Simplified styling for brevity
    return Markup(html)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    zip_file = request.files.get('zip_file')
    if not zip_file or not zip_file.filename or not zip_file.filename.lower().endswith('.zip'):
        flash('请上传一个ZIP文件')
        return redirect(url_for('index'))

    temp_dir = tempfile.mkdtemp(prefix='review_task_')
    # 使用原始文件名，但确保安全
    original_filename = _safe_filename(zip_file.filename or "upload.zip")
    safe_filename_result = secure_filename(original_filename)
    # 如果secure_filename丢失了中文，使用时间戳
    if not safe_filename_result or safe_filename_result != original_filename:
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename_result = f"upload_{timestamp}.zip"
    
    zip_path = os.path.join(temp_dir, safe_filename_result)
    zip_file.save(zip_path)

    excel_path = None
    excel_original = None  # 初始化变量
    excel_file = request.files.get('excel_file')
    if excel_file:
        excel_original = _safe_filename(excel_file.filename or "excel_file.xlsx")
        excel_safe = secure_filename(excel_original)
        if not excel_safe or excel_safe != excel_original:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = os.path.splitext(excel_original)[1] if '.' in excel_original else '.xlsx'
            excel_safe = f"excel_{timestamp}{ext}"
        excel_path = os.path.join(temp_dir, excel_safe)
        excel_file.save(excel_path)

    task_id = str(uuid.uuid4())
    
    # 创建任务信息
    current_time = time.time()
    task_info = TaskInfo(
        task_id=task_id,
        status='pending',
        created_at=current_time,
        updated_at=current_time,
        zip_file_path=zip_path,
        excel_file_path=excel_path,
        zip_file_name=original_filename,
        excel_file_name=excel_original if excel_file else None,
        current_step='任务已创建，正在等待后台线程处理...'
    )
    
    # 保存到数据库
    db_manager.create_task(task_info)
    
    # 添加初始日志
    initial_log = TaskLog(
        log_id=None,
        task_id=task_id,
        timestamp=current_time,
        level='INFO',
        message='任务已创建，正在等待后台线程处理...'
    )
    db_manager.add_task_log(initial_log)

    thread = threading.Thread(target=run_analysis_task, args=(task_id, zip_path, excel_path))
    thread.daemon = True
    thread.start()

    return redirect(url_for('status_page', task_id=task_id))

@app.route('/status/<task_id>')
def status_page(task_id):
    if task_id not in TASKS:
        return "任务未找到!", 404
    return render_template('status.html', task_id=task_id)

@app.route('/api/status/<task_id>')
def api_status(task_id):
    try:
        if task_id not in TASKS:
            return jsonify({
                'status': 'not_found',
                'log': ['❌ 任务未找到，请返回首页重新开始']
            }), 404
        
        task = TASKS[task_id]
        
        # 确保返回的数据结构完整
        response_data = {
            'status': task.get('status', 'unknown'),
            'log': task.get('log', [])
        }
        
        # 添加额外信息
        if task.get('status') == 'error':
            response_data['error'] = task.get('error', '未知错误')
        
        return jsonify(response_data)
        
    except Exception as e:
        # 如果出现未预期的错误，返回友好的错误消息
        return jsonify({
            'status': 'error',
            'log': [f'❌ 服务器内部错误: {str(e)}']
        }), 500

@app.route('/result/<task_id>')
def result_page(task_id):
    task_info = db_manager.get_task(task_id)
    if not task_info or task_info.status != 'complete':
        return redirect(url_for('status_page', task_id=task_id))
    
    # 获取任务日志
    logs = db_manager.get_task_logs(task_id)
    log_messages = [log.message for log in logs]
    
    return render_template('result.html', 
                         report=task_info.formatted_report,
                         raw_report=task_info.report_content,
                         progress_log=log_messages,
                         task_info=task_info.to_dict())

@app.route('/history')
def history_page():
    """历史任务页面"""
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', 'all')
    
    # 获取任务列表
    if status_filter == 'all':
        tasks = db_manager.get_recent_tasks(50)
    else:
        tasks = db_manager.get_tasks_by_status(status_filter, 50)
    
    # 获取统计信息
    stats = db_manager.get_task_statistics()
    
    return render_template('history.html', 
                         tasks=[task.to_dict() for task in tasks],
                         stats=stats,
                         current_status=status_filter)

@app.route('/api/tasks')
def api_tasks():
    """获取任务列表API"""
    try:
        status_filter = request.args.get('status', 'all')
        limit = min(request.args.get('limit', 20, type=int), 100)
        
        if status_filter == 'all':
            tasks = db_manager.get_recent_tasks(limit)
        else:
            tasks = db_manager.get_tasks_by_status(status_filter, limit)
        
        return jsonify({
            'tasks': [task.to_dict() for task in tasks],
            'total': len(tasks)
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500

@app.route('/api/task/<task_id>/delete', methods=['POST'])
def api_delete_task(task_id):
    """删除任务API"""
    try:
        success = db_manager.delete_task(task_id)
        if success:
            return jsonify({'success': True, 'message': '任务已删除'})
        else:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/task/<task_id>/resume', methods=['POST'])
def api_resume_task(task_id):
    """恢复任务API（断点续传）"""
    try:
        task_info = db_manager.get_task(task_id)
        if not task_info:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        
        if task_info.status not in ['error', 'processing']:
            return jsonify({'success': False, 'message': '只有错误或处理中的任务才能恢复'}), 400
        
        # 检查文件是否还存在
        if not task_info.zip_file_path or not os.path.exists(task_info.zip_file_path):
            return jsonify({'success': False, 'message': '原始文件不存在，无法恢复任务'}), 400
        
        # 重置任务状态
        db_manager.update_task(task_id, {
            'status': 'pending',
            'error_message': None,
            'current_step': '任务正在恢复...'
        })
        
        # 添加恢复日志
        resume_log = TaskLog(
            log_id=None,
            task_id=task_id,
            timestamp=time.time(),
            level='INFO',
            message='🔄 任务正在恢复...'
        )
        db_manager.add_task_log(resume_log)
        
        # 启动新的处理线程
        thread = threading.Thread(target=run_analysis_task, args=(task_id, task_info.zip_file_path, task_info.excel_file_path))
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': '任务已恢复'})
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/statistics')
def api_statistics():
    """获取统计信息API"""
    try:
        stats = db_manager.get_task_statistics()
        return jsonify(stats)
        
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500

@app.route('/api/cleanup', methods=['POST'])
def api_cleanup():
    """清理旧任务API"""
    try:
        days = request.json.get('days', 30) if request.json else 30
        deleted_count = db_manager.cleanup_old_tasks(days)
        
        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'message': f'已清理 {deleted_count} 个旧任务'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    # 设置控制台编码以支持中文显示
    import sys
    if sys.platform.startswith('win'):
        # Windows系统设置：使用更安全的方式处理控制台编码
        try:
            import codecs
            import io
            
            # 设置环境变量来确保Python使用UTF-8编码
            os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
            
            # 尝试使用io.TextIOWrapper来重新包装控制台输出
            if hasattr(sys.stdout, 'buffer'):
                try:
                    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
                except (AttributeError, OSError, ValueError):
                    pass
                    
            if hasattr(sys.stderr, 'buffer'):
                try:
                    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
                except (AttributeError, OSError, ValueError):
                    pass
                    
        except Exception:
            # 如果设置失败，继续使用默认设置
            pass
    
    # 增强的服务器启动配置
    port = 5000
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            print(f"🌐 正在启动服务器... (尝试 {attempt + 1}/{max_retries})")
            print(f"🌐 服务器将在 http://127.0.0.1:{port} 启动")
            print(f"🌐 局域网访问: http://0.0.0.0:{port}")
            
            # 检查端口是否被占用
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                result = s.connect_ex(('127.0.0.1', port))
                if result == 0:
                    print(f"⚠️ 端口 {port} 已被占用，尝试下一个端口...")
                    port += 1
                    continue
            
            # 启动Flask应用
            app.run(
                debug=False,  # 在生产环境中关闭debug模式
                host='0.0.0.0', 
                port=port, 
                threaded=True,
                use_reloader=False,  # 避免重载器引起的线程问题
                use_debugger=False,  # 避免调试器引起的问题
                use_evalex=False,    # 禁用eval异常
                passthrough_errors=False,  # 避免异常直接传递
                request_handler=None  # 使用默认请求处理器
            )
            break  # 如果成功启动，跳出重试循环
            
        except OSError as e:
            if "Address already in use" in str(e) or "WinError 10048" in str(e):
                print(f"❌ 端口 {port} 被占用: {e}")
                port += 1
                if attempt < max_retries - 1:
                    print(f"🔄 尝试使用端口 {port}...")
                    continue
                else:
                    print(f"❌ 所有端口都被占用，请检查网络配置")
                    break
            elif "Permission denied" in str(e):
                print(f"❌ 权限被拒绝: {e}")
                print(f"💡 解决方案:")
                print(f"  1. 以管理员身份运行程序")
                print(f"  2. 检查防火墙设置")
                print(f"  3. 尝试使用其他端口 (如 8080)")
                break
            else:
                print(f"❌ 网络错误: {e}")
                if attempt < max_retries - 1:
                    print(f"🔄 等待 2 秒后重试...")
                    time.sleep(2)
                    continue
                else:
                    break
                    
        except KeyboardInterrupt:
            print(f"\n👋 用户中断，服务器停止")
            break
            
        except Exception as e:
            print(f"❌ 启动失败: {e}")
            if attempt < max_retries - 1:
                print(f"🔄 等待 3 秒后重试...")
                time.sleep(3)
            else:
                print(f"💡 解决建议:")
                print(f"  1. 检查是否有其他程序占用端口")
                print(f"  2. 重启计算机")
                print(f"  3. 检查防火墙和安全软件设置")
                print(f"  4. 尝试使用管理员权限运行")
                break
