#!/usr/bin/env python3
"""
定时盯价调度辅助脚本

用法:
    # 设置每日自动盯价（Windows 任务计划程序）
    python setup_schedule.py add "男装" --time 08:00
    python setup_schedule.py add "蓝牙耳机" --time 09:00 --pages 2 --csv --json
    python setup_schedule.py add "露营灯" --time 20:00 --alert-up 10

    # 列出所有盯价任务
    python setup_schedule.py list

    # 删除盯价任务
    python setup_schedule.py remove "男装"

注意：
    本脚本创建 Windows 任务计划程序任务，使用 schtasks 命令。
    需要以管理员权限运行或使用 /create /f（强制覆盖）。
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def get_python_path() -> str:
    """获取当前 Python 可执行文件路径"""
    return sys.executable


def get_cli_path() -> str:
    """获取 cli.py 的绝对路径"""
    return str(Path(__file__).parent / "cli.py")


def add_task(keyword: str, time_str: str, pages: int = 1,
             alert_up: float = 0, alert_down: float = 0,
             export_csv: bool = False, export_json: bool = False,
             show_browser: bool = False) -> None:
    """添加 Windows 定时任务"""
    python_exe = get_python_path()
    cli_py = get_cli_path()

    # 构建命令行参数
    args_list = [f'"{cli_py}"', f'"{keyword}"', "-m", "--pages", str(pages)]

    if alert_up > 0:
        args_list.extend(["--alert-up", str(alert_up)])
    if alert_down > 0:
        args_list.extend(["--alert-down", str(alert_down)])
    if export_csv:
        args_list.append("--csv")
    if export_json:
        args_list.append("--json")
    if show_browser:
        args_list.append("--no-headless")

    cmd = f'{python_exe} {" ".join(args_list)}'

    task_name = f"TAgent盯价_{keyword}"
    hour, minute = map(int, time_str.split(":"))

    schtasks_cmd = (
        f'schtasks /create /tn "{task_name}" '
        f'/tr "{cmd}" '
        f'/sc daily /st {time_str}:00 '
        f'/f /rl limited'
    )

    print(f"  📋 正在创建定时任务: {task_name}")
    print(f"  ⏰ 执行时间: 每天 {hour:02d}:{minute:02d}")
    print(f"  💻 命令: {cmd}")
    print()

    try:
        result = subprocess.run(
            schtasks_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            print(f"  ✅ 定时任务创建成功!")
            print(f"  📝 任务名称: {task_name}")
            print(f"  🕐 每天 {time_str} 自动盯价「{keyword}」")
        else:
            print(f"  ⚠ 创建失败 (返回码 {result.returncode})")
            print(f"  输出: {result.stderr.strip() or result.stdout.strip()}")
            print()
            print("  💡 提示: 请以管理员身份运行此脚本")
    except FileNotFoundError:
        print("  ✗ 找不到 schtasks.exe，请确认 Windows 系统")
    except subprocess.TimeoutExpired:
        print("  ✗ 超时，请重试")


def list_tasks() -> None:
    """列出所有 TAgent 相关定时任务"""
    print("  📋 正在查询 TAgent 盯价定时任务...")
    print()

    try:
        result = subprocess.run(
            'schtasks /query /v /fo csv /tn "TAgent盯价*"',
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                print(f"  共 {len(lines)-1} 个盯价任务:\n")
                for line in lines[:1]:  # 表头
                    print(f"  {line.replace(',', ' │ ')}")
                print("  " + "-" * 70)
                for line in lines[1:]:
                    print(f"  {line.replace(',', ' │ ')}")
            else:
                print("  📭 暂无盯价定时任务")
        else:
            print("  📭 暂无盯价定时任务")
    except FileNotFoundError:
        print("  ✗ 找不到 schtasks.exe")
    except subprocess.TimeoutExpired:
        print("  ✗ 超时，请重试")


def remove_task(keyword: str) -> None:
    """删除指定关键词的定时盯价任务"""
    task_name = f"TAgent盯价_{keyword}"
    print(f"  🗑 正在删除定时任务: {task_name}")

    try:
        result = subprocess.run(
            f'schtasks /delete /tn "{task_name}" /f',
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            print(f"  ✅ 已删除盯价任务: {task_name}")
        else:
            print(f"  ⚠ 删除失败: {result.stderr.strip() or result.stdout.strip()}")
    except subprocess.TimeoutExpired:
        print("  ✗ 超时，请重试")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="🕐 TAgent 定时盯价调度 — Windows 任务计划程序管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python setup_schedule.py add "男装" --time 08:00
  python setup_schedule.py add "蓝牙耳机" --time 09:00 --pages 2 --csv
  python setup_schedule.py list
  python setup_schedule.py remove "男装"
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="操作类型")

    # add
    add_parser = subparsers.add_parser("add", help="添加盯价定时任务")
    add_parser.add_argument("keyword", help="盯价品类关键词")
    add_parser.add_argument("--time", default="08:00", help="执行时间 HH:MM (默认: 08:00)")
    add_parser.add_argument("--pages", "-p", type=int, default=1, help="翻页数 (默认: 1)")
    add_parser.add_argument("--alert-up", type=float, default=0, help="涨价 ¥ 提醒门槛")
    add_parser.add_argument("--alert-down", type=float, default=0, help="降价 ¥ 提醒门槛")
    add_parser.add_argument("--csv", action="store_true", help="自动导出 CSV")
    add_parser.add_argument("--json", action="store_true", help="自动导出 JSON")
    add_parser.add_argument("--show", action="store_true", help="显示浏览器窗口")

    # list
    subparsers.add_parser("list", help="列出所有盯价定时任务")

    # remove
    remove_parser = subparsers.add_parser("remove", help="删除盯价定时任务")
    remove_parser.add_argument("keyword", help="要删除的盯价品类关键词")

    args = parser.parse_args()

    if args.command == "add":
        add_task(
            keyword=args.keyword,
            time_str=args.time,
            pages=args.pages,
            alert_up=args.alert_up,
            alert_down=args.alert_down,
            export_csv=args.csv,
            export_json=args.json,
            show_browser=args.show,
        )
    elif args.command == "list":
        list_tasks()
    elif args.command == "remove":
        remove_task(args.keyword)
    else:
        parser.print_help()
