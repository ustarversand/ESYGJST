"""
身份证处理统一入口模块
整合：图像处理 + 认证系统 + OCR识别

支持场景：
1. 单张正面图片 → 查询认证系统 → 需要反面则提示
2. 单张反面图片 → 匹配待处理队列 → 上传认证系统
3. 单张拼图 → 自动分割 → 处理
4. 两张图片 → 自动识别正反面 → 处理
"""

import os
import sys
import json
from typing import List, Dict, Optional
from datetime import datetime

# 模块路径
IDCard_DIR = os.path.dirname(os.path.abspath(__file__))

# 导入子模块
try:
    from .image_processor import (
        process_idcard_images,
        process_split_image,
        is_split_image,
        identify_front_back,
        add_pending,
        get_pending,
        remove_pending
    )
    from .auth_system import (
        check_idcard_exists,
        upload_idcard
    )
except ImportError:
    # 兼容独立运行
    sys.path.insert(0, IDCard_DIR)
    from image_processor import (
        process_idcard_images,
        process_split_image,
        is_split_image,
        identify_front_back,
        add_pending,
        get_pending,
        remove_pending
    )
    from auth_system import (
        check_idcard_exists,
        upload_idcard
    )


# 待处理队列文件
PENDING_FILE = "/tmp/idcard_pending.json"


def save_pending(user_id: str, data: dict):
    """保存用户待处理数据"""
    pending = load_all_pending()
    pending[user_id] = data
    with open(PENDING_FILE, 'w') as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)


def load_all_pending() -> dict:
    """加载所有待处理数据"""
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, 'r') as f:
            return json.load(f)
    return {}


def get_user_pending(user_id: str) -> Optional[dict]:
    """获取用户待处理数据"""
    pending = load_all_pending()
    return pending.get(user_id)


def clear_user_pending(user_id: str):
    """清除用户待处理数据"""
    pending = load_all_pending()
    if user_id in pending:
        del pending[user_id]
        with open(PENDING_FILE, 'w') as f:
            json.dump(pending, f)


def idcard_auth_flow(
    image_paths: List[str],
    user_id: str = None,
    ocr_func=None
) -> Dict:
    """
    身份证认证完整流程
    
    Args:
        image_paths: 图片路径列表
        user_id: 用户ID（用于分次上传）
        ocr_func: OCR识别函数 (path) -> {"name": str, "id_number": str}
        
    Returns:
        处理结果 dict
    """
    # ========== 步骤1: 图片处理 ==========
    img_result = process_idcard_images(image_paths)
    
    # 需要更多图片
    if img_result["status"] == "need_more":
        if user_id:
            # 保存当前图片到待处理队列
            save_pending(user_id, {
                "images": image_paths,
                "step": "waiting_reverse"
            })
        return {
            "status": "need_more",
            "message": img_result["message"],
            "action": "upload_reverse"
        }
    
    # 分割完成或错误
    if img_result["status"] in ["error", "split_done"]:
        if img_result["status"] == "error":
            return img_result
        
        # 分割成功
        front_path = img_result.get("front_path")
        reverse_path = img_result.get("reverse_path")
        
        if user_id:
            # 检查是否有待处理
            prev = get_user_pending(user_id)
            if prev and prev.get("images"):
                # 合并图片
                front_path = prev["images"][0]
        
        return process_auth(front_path, reverse_path, ocr_func)
    
    # ========== 步骤2: 已有2张图片 ==========
    if img_result["status"] == "ready":
        front_path = img_result["front_path"]
        reverse_path = img_result["reverse_path"]
        
        # 检查分次上传情况
        if user_id:
            prev = get_user_pending(user_id)
            if prev and prev.get("images"):
                # 之前有正面，现在有反面
                front_path = prev["images"][0]
                reverse_path = image_paths[0]
                clear_user_pending(user_id)
        
        return process_auth(front_path, reverse_path, ocr_func)
    
    return {"status": "error", "message": "未知状态"}


def process_auth(
    front_path: str,
    reverse_path: str,
    ocr_func=None
) -> Dict:
    """
    处理认证流程
    
    Args:
        front_path: 正面图片路径
        reverse_path: 反面图片路径
        ocr_func: OCR识别函数
        
    Returns:
        认证结果
    """
    # ========== 步骤3: OCR识别 ==========
    if ocr_func:
        try:
            ocr_result = ocr_func(front_path)
            if not ocr_result:
                return {"status": "error", "message": "OCR识别失败"}
            name = ocr_result.get("name")
            id_number = ocr_result.get("id_number")
        except Exception as e:
            return {"status": "error", "message": f"OCR异常: {e}"}
    else:
        # 模拟OCR（实际需要接入OCR服务）
        name = None
        id_number = None
    
    # ========== 步骤4: 查询认证系统 ==========
    if name and id_number:
        exists_result = check_idcard_exists(name, id_number)
        if exists_result["exists"]:
            return {
                "status": "authenticated",
                "message": "已认证，直接推送",
                "name": name,
                "id_number": id_number,
                "system_data": exists_result["data"]
            }
    
    # ========== 步骤5: 上传认证系统 ==========
    if not name or not id_number:
        return {
            "status": "need_info",
            "message": "请提供姓名和身份证号",
            "front_path": front_path,
            "reverse_path": reverse_path
        }
    
    upload_result = upload_idcard(
        id_card_name=name,
        id_card_number=id_number,
        id_card_front_path=front_path,
        id_card_reverse_path=reverse_path
    )
    
    if upload_result["success"]:
        return {
            "status": "authenticated",
            "message": "认证成功",
            "name": name,
            "id_number": id_number,
            "system_id": upload_result["data"]["id"]
        }
    
    return {
        "status": "failed",
        "message": upload_result["message"]
    }


# ========== 便捷函数 ==========

def quick_check(name: str, id_number: str) -> Dict:
    """
    快速查询身份证是否已认证
    
    Args:
        name: 姓名
        id_number: 身份证号
        
    Returns:
        {"exists": bool, "message": str}
    """
    result = check_idcard_exists(name, id_number)
    return {
        "exists": result["exists"],
        "message": result["message"],
        "data": result.get("data")
    }


def quick_upload(
    name: str,
    id_number: str,
    front_path: str,
    reverse_path: str
) -> Dict:
    """
    快速上传身份证
    
    Args:
        name: 姓名
        id_number: 身份证号
        front_path: 正面路径
        reverse_path: 反面路径
        
    Returns:
        {"success": bool, "message": str}
    """
    result = upload_idcard(name, id_number, front_path, reverse_path)
    return {
        "success": result["success"],
        "message": result["message"],
        "system_id": result.get("data", {}).get("id") if result.get("data") else None
    }


# ========== CLI ==========

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="身份证处理工具")
    parser.add_argument("command", choices=["check", "upload", "process", "split"])
    parser.add_argument("--name", "-n", help="姓名")
    parser.add_argument("--id", "-i", help="身份证号")
    parser.add_argument("--front", "-f", help="正面图片路径")
    parser.add_argument("--reverse", "-r", help="反面图片路径")
    parser.add_argument("--images", "-m", nargs="+", help="图片列表")
    
    args = parser.parse_args()
    
    if args.command == "check":
        if not args.name or not args.id:
            print("错误: 需要 --name 和 --id")
            sys.exit(1)
        result = quick_check(args.name, args.id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif args.command == "upload":
        if not all([args.name, args.id, args.front, args.reverse]):
            print("错误: 需要 --name, --id, --front, --reverse")
            sys.exit(1)
        result = quick_upload(args.name, args.id, args.front, args.reverse)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif args.command == "split":
        if not args.front:
            print("错误: 需要 --front")
            sys.exit(1)
        result = process_split_image(args.front)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif args.command == "process":
        if not args.images:
            print("错误: 需要 --images")
            sys.exit(1)
        result = idcard_auth_flow(args.images)
        print(json.dumps(result, indent=2, ensure_ascii=False))