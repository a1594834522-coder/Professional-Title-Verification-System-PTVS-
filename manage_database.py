#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库管理脚本
提供数据库初始化、备份、清理、统计等功能
"""

import os
import sys
import argparse
import time
from datetime import datetime
from pathlib import Path
from database_manager import DatabaseManager, TaskInfo, TaskLog

def init_database(db_path=None):
    """初始化数据库"""
    print("🚀 正在初始化数据库...")
    
    db_manager = DatabaseManager(
        db_path=db_path,
        progress_callback=lambda msg: print(f"[DB] {msg}")
    )
    
    print("✅ 数据库初始化完成")
    return db_manager

def backup_database(db_manager, backup_dir="backups"):
    """备份数据库"""
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"database_backup_{timestamp}.db"
    
    print(f"💾 正在备份数据库到: {backup_path}")
    
    if db_manager.backup_database(str(backup_path)):
        print("✅ 数据库备份成功")
        return str(backup_path)
    else:
        print("❌ 数据库备份失败")
        return None

def show_statistics(db_manager):
    """显示统计信息"""
    print("📊 数据库统计信息:")
    print("=" * 50)
    
    stats = db_manager.get_task_statistics()
    
    print(f"📋 总任务数: {stats.get('total_tasks', 0)}")
    print(f"📈 最近7天任务: {stats.get('recent_tasks_7days', 0)}")
    print(f"✅ 成功率: {stats.get('success_rate_percent', 0):.1f}%")
    print(f"⏱️ 平均处理时间: {stats.get('average_processing_time_seconds', 0):.1f} 秒")
    print(f"💽 数据库大小: {stats.get('database_size_mb', 0):.1f} MB")
    
    status_counts = stats.get('status_counts', {})
    if status_counts:
        print("\n📊 任务状态分布:")
        for status, count in status_counts.items():
            print(f"   {status}: {count}")

def cleanup_old_tasks(db_manager, days=30):
    """清理旧任务"""
    print(f"🧹 正在清理 {days} 天前的旧任务...")
    
    deleted_count = db_manager.cleanup_old_tasks(days)
    
    if deleted_count > 0:
        print(f"✅ 已清理 {deleted_count} 个旧任务")
    else:
        print("ℹ️ 没有找到需要清理的旧任务")

def export_task(db_manager, task_id, output_dir="exports"):
    """导出任务数据"""
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)
    
    print(f"📤 正在导出任务: {task_id}")
    
    task_data = db_manager.export_task_data(task_id)
    if not task_data:
        print("❌ 任务不存在或导出失败")
        return
    
    output_file = output_dir / f"task_{task_id}_{int(time.time())}.json"
    
    import json
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(task_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 任务数据已导出到: {output_file}")

def list_resumable_tasks(db_manager):
    """列出可恢复的任务"""
    print("🔄 可恢复的任务:")
    print("=" * 50)
    
    tasks = db_manager.get_resumable_tasks()
    
    if not tasks:
        print("ℹ️ 没有找到可恢复的任务")
        return
    
    for task in tasks:
        print(f"📋 任务ID: {task.task_id}")
        print(f"   状态: {task.status}")
        print(f"   创建时间: {datetime.fromtimestamp(task.created_at)}")
        print(f"   最后更新: {datetime.fromtimestamp(task.updated_at)}")
        print(f"   当前步骤: {task.current_step or '未知'}")
        print()

def optimize_database(db_manager):
    """优化数据库"""
    print("🔧 正在优化数据库...")
    
    if db_manager.optimize_database():
        print("✅ 数据库优化完成")
    else:
        print("❌ 数据库优化失败")

def list_recent_tasks(db_manager, limit=10):
    """列出最近的任务"""
    print(f"📋 最近 {limit} 个任务:")
    print("=" * 50)
    
    tasks = db_manager.get_recent_tasks(limit)
    
    if not tasks:
        print("ℹ️ 没有找到任务")
        return
    
    for task in tasks:
        print(f"📋 {task.task_id}")
        print(f"   状态: {task.status}")
        print(f"   创建: {datetime.fromtimestamp(task.created_at)}")
        print(f"   文件: {task.zip_file_name or '未知'}")
        if task.processing_time_seconds:
            print(f"   耗时: {task.processing_time_seconds:.1f}s")
        print()

def main():
    parser = argparse.ArgumentParser(description='数据库管理工具')
    parser.add_argument('--db', help='数据库文件路径')
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # 初始化命令
    subparsers.add_parser('init', help='初始化数据库')
    
    # 备份命令
    backup_parser = subparsers.add_parser('backup', help='备份数据库')
    backup_parser.add_argument('--dir', default='backups', help='备份目录')
    
    # 统计命令
    subparsers.add_parser('stats', help='显示统计信息')
    
    # 清理命令
    cleanup_parser = subparsers.add_parser('cleanup', help='清理旧任务')
    cleanup_parser.add_argument('--days', type=int, default=30, help='清理多少天前的任务')
    
    # 导出命令
    export_parser = subparsers.add_parser('export', help='导出任务数据')
    export_parser.add_argument('task_id', help='任务ID')
    export_parser.add_argument('--dir', default='exports', help='导出目录')
    
    # 可恢复任务命令
    subparsers.add_parser('resumable', help='列出可恢复的任务')
    
    # 优化命令
    subparsers.add_parser('optimize', help='优化数据库')
    
    # 列出任务命令
    list_parser = subparsers.add_parser('list', help='列出最近的任务')
    list_parser.add_argument('--limit', type=int, default=10, help='显示数量')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        # 初始化数据库管理器
        db_manager = init_database(args.db)
        
        # 执行命令
        if args.command == 'init':
            print("✅ 数据库已初始化")
            
        elif args.command == 'backup':
            backup_database(db_manager, args.dir)
            
        elif args.command == 'stats':
            show_statistics(db_manager)
            
        elif args.command == 'cleanup':
            cleanup_old_tasks(db_manager, args.days)
            
        elif args.command == 'export':
            export_task(db_manager, args.task_id, args.dir)
            
        elif args.command == 'resumable':
            list_resumable_tasks(db_manager)
            
        elif args.command == 'optimize':
            optimize_database(db_manager)
            
        elif args.command == 'list':
            list_recent_tasks(db_manager, args.limit)
            
    except Exception as e:
        print(f"❌ 操作失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()