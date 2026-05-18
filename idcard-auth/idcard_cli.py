#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
身份证处理 CLI 工具

使用方法:
    python3 idcard_cli.py check -n 姓名 -i 身份证号
    python3 idcard_cli.py upload -n 姓名 -i 身份证号 -f 正面.jpg -r 反面.jpg
    python3 idcard_cli.py process -m 图片1.jpg [图片2.jpg ...]
    python3 idcard_cli.py split -f 拼图.jpg
"""

import sys
import os
import json
import argparse

# 添加模块路径
IDCard_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, IDCard_DIR)

from image_processor import (
    process_idcard_images,
    process_split_image,
    is_split_image
)
from auth_system import (
    check_idcard_exists,
    upload_idcard
)


def cmd_check(args):
    """查询身份证"""
    if not args.name or not args.id:
        print("错误: 需要 -n 姓名 和 -i 身份证号")
        return 1
    
    result = check_idcard_exists(args.name, args.id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["exists"] else 1


def cmd_upload(args):
    """上传身份证"""
    if not all([args.name, args.id, args.front, args.reverse]):
        print("错误: 需要 -n 姓名 -i 身份证号 -f 正面 -r 反面")
        return 1
    
    if not os.path.exists(args.front):
        print(f"错误: 正面图片不存在: {args.front}")
        return 1
    if not os.path.exists(args.reverse):
        print(f"错误: 反面图片不存在: {args.reverse}")
        return 1
    
    result = upload_idcard(
        args.name,
        args.id,
        args.front,
        args.reverse
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["success"] else 1


def cmd_process(args):
    """处理图片"""
    if not args.images:
        print("错误: 需要 -m 图片列表")
        return 1
    
    result = process_idcard_images(args.images)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] in ["ready", "split_done"] else 1


def cmd_split(args):
    """分割拼图"""
    if not args.front:
        print("错误: 需要 -f 拼图路径")
        return 1
    
    if not is_split_image(args.front):
        print("提示: 图片不像是拼图（宽高比不足2.2倍）")
    
    result = process_split_image(args.front)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "split_done" else 1


def main():
    parser = argparse.ArgumentParser(
        description="身份证处理CLI工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 查询身份证
    python3 idcard_cli.py check -n 杨萍 -i 510902197004169166
    
    # 上传身份证
    python3 idcard_cli.py upload -n 张三 -i 110000000000000000 -f front.jpg -r reverse.jpg
    
    # 自动处理图片(1-2张)
    python3 idcard_cli.py process -m front.jpg reverse.jpg
    
    # 分割拼图
    python3 idcard_cli.py split -f combined.jpg
        """
    )
    
    parser.add_argument("command", choices=["check", "upload", "process", "split"],
                      help="子命令")
    parser.add_argument("-n", "--name", help="姓名")
    parser.add_argument("-i", "--id", help="身份证号")
    parser.add_argument("-f", "--front", help="正面图片路径")
    parser.add_argument("-r", "--reverse", help="反面图片路径")
    parser.add_argument("-m", "--images", nargs="+", help="图片列表")
    
    args = parser.parse_args()
    
    commands = {
        "check": cmd_check,
        "upload": cmd_upload,
        "process": cmd_process,
        "split": cmd_split
    }
    
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main() or 0)