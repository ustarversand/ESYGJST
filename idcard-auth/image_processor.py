"""
身份证图像处理模块
支持：
1. 自动识别正面/反面图片
2. 将拼图分割成两张独立图片
3. 完整的认证流程
"""

import os
import json
import cv2
import numpy as np
from PIL import Image
from typing import List, Tuple, Optional, Dict
from datetime import datetime


# 待处理队列文件
PENDING_QUEUE_FILE = "/tmp/idcard_pending.json"


def identify_front_back(image_paths: List[str]) -> Tuple[str, str]:
    """
    识别哪张是正面，哪张是反面
    
    通过图像特征检测：
    - 正面：有人像区域（皮肤色调、面部特征）
    - 反面：有国徽图案（圆形、星形等）
    
    Args:
        image_paths: 图片路径列表 [path1, path2]
    
    Returns:
        (front_path, reverse_path)
    """
    if len(image_paths) != 2:
        raise ValueError("需要2张图片")
    
    scores = []
    for path in image_paths:
        score = detect_idcard_type(path)
        scores.append(score)
    
    # score > 0: 正面, score < 0: 反面
    if scores[0] > scores[1]:
        return image_paths[0], image_paths[1]
    else:
        return image_paths[1], image_paths[0]


def detect_idcard_type(image_path: str) -> float:
    """
    检测身份证类型
    
    返回分数：正值=正面(含人像)，负值=反面(含国徽)
    """
    img = cv2.imread(image_path)
    if img is None:
        return 0
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    
    # 简化的特征检测
    score = 0.0
    
    # 1. 边缘检测 - 反面有更复杂的图案（国徽边缘）
    edges = cv2.Canny(gray, 50, 150)
    edge_density = np.sum(edges) / (h * w * 255)
    
    # 2. 颜色分析
    # 正面：皮肤色调偏多
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    skin_mask = detect_skin_color(hsv)
    skin_ratio = np.sum(skin_mask) / (h * w)
    
    # 3. 中心区域特征
    center_region = gray[h//4:3*h//4, w//4:3*w//4]
    center_var = np.var(center_region)
    
    # 综合评分
    # 正面：皮肤多，方差小（人像区域相对平滑）
    # 反面：边缘复杂，中心方差大（国徽图案）
    
    if skin_ratio > 0.15:  # 有明显皮肤区域
        score += 1.0
    
    if edge_density > 0.05:  # 边缘复杂
        score -= 0.5
    
    if center_var > 1000:
        score -= 0.3
    
    return score


def detect_skin_color(hsv: np.ndarray) -> np.ndarray:
    """检测皮肤色调区域"""
    # HSV 肤色范围
    lower_skin = np.array([0, 20, 70])
    upper_skin = np.array([20, 150, 255])
    
    mask = cv2.inRange(hsv, lower_skin, upper_skin)
    return mask


def split_idcard(image_path: str) -> Tuple[str, str]:
    """
    将身份证拼图分割成正面和反面
    
    拼图格式：左边是反面(国徽)，右边是正面(人像)
    
    Args:
        image_path: 拼图路径
    
    Returns:
        (front_path, reverse_path)
    """
    img = Image.open(image_path)
    width, height = img.size
    
    # 检查是否确实是拼图
    if width < height * 1.3:
        raise ValueError("图片尺寸不符合拼图格式（宽应大于高的1.3倍）")
    
    # 分割：左半边反面，右半边正面
    # 考虑到中间可能有缝隙，加一点偏移
    margin = int(width * 0.02)
    
    # 反面（国徽面）：左半边
    reverse_box = (margin, 0, width//2 - margin, height)
    reverse_half = img.crop(reverse_box)
    
    # 正面（人像面）：右半边
    front_box = (width//2 + margin, 0, width - margin, height)
    front_half = img.crop(front_box)
    
    # 保存
    front_path = save_half(front_half, "front")
    reverse_path = save_half(reverse_half, "reverse")
    
    return front_path, reverse_path


def save_half(img_half: Image.Image, prefix: str) -> str:
    """保存分割后的图片"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    path = f"/tmp/{prefix}_{timestamp}.jpg"
    
    # 转换为RGB保存
    if img_half.mode != 'RGB':
        img_half = img_half.convert('RGB')
    
    img_half.save(path, 'JPEG', quality=90)
    return path


def is_split_image(image_path: str) -> bool:
    """
    判断是否是拼图（宽大于高的2.2倍）
    标准身份证约1.6:1，拼图约3:1，设阈值2.2区分
    """
    img = Image.open(image_path)
    width, height = img.size
    return width > height * 2.2


def load_pending_queue() -> dict:
    """加载待处理队列"""
    if os.path.exists(PENDING_QUEUE_FILE):
        with open(PENDING_QUEUE_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_pending_queue(queue: dict):
    """保存待处理队列"""
    with open(PENDING_QUEUE_FILE, 'w') as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def add_pending(user_id: str, front_path: str):
    """添加待处理队列"""
    queue = load_pending_queue()
    queue[user_id] = {
        "front_path": front_path,
        "added_at": datetime.now().isoformat()
    }
    save_pending_queue(queue)


def get_pending(user_id: str) -> Optional[dict]:
    """获取待处理记录"""
    queue = load_pending_queue()
    return queue.get(user_id)


def remove_pending(user_id: str):
    """移除待处理记录"""
    queue = load_pending_queue()
    if user_id in queue:
        del queue[user_id]
        save_pending_queue(queue)


def process_idcard_single(
    image_path: str,
    user_id: str = None,
    require_reverse: bool = False
) -> Dict:
    """
    处理单张身份证图片
    
    Args:
        image_path: 图片路径
        user_id: 用户ID（用于分次上传场景）
        require_reverse: 是否强制要求反面
    
    Returns:
        处理结果 dict
    """
    # 检查是否是拼图
    if is_split_image(image_path) and not require_reverse:
        return process_split_image(image_path)
    
    # 单张图片，需要另外一张
    if user_id:
        add_pending(user_id, image_path)
        return {
            "status": "need_more",
            "message": "请上传身份证另一面（正面或反面）"
        }
    
    return {
        "status": "need_more",
        "message": "请上传身份证另一面"
    }


def process_split_image(image_path: str) -> Dict:
    """处理拼图"""
    try:
        front_path, reverse_path = split_idcard(image_path)
        return {
            "status": "split_done",
            "front_path": front_path,
            "reverse_path": reverse_path
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"分割失败: {str(e)}"
        }


def process_idcard_images(
    image_paths: List[str],
    allow_fail: bool = True
) -> Dict:
    """
    处理身份证图片列表（自动识别场景）
    
    Args:
        image_paths: 图片路径列表
        allow_fail: 是否允许只有一张的情况
    
    Returns:
        处理结果 dict
    """
    if not image_paths:
        return {"status": "error", "message": "没有图片"}
    
    # ========== 场景1: 2张图片 ==========
    if len(image_paths) == 2:
        try:
            front_path, reverse_path = identify_front_back(image_paths)
        except:
            # 顺序不确定，默认第一张正面
            front_path, reverse_path = image_paths[0], image_paths[1]
        
        return {
            "status": "ready",
            "front_path": front_path,
            "reverse_path": reverse_path
        }
    
    # ========== 场景2: 1张图片 ==========
    if len(image_paths) == 1:
        img_path = image_paths[0]
        
        # 检查是否是拼图
        if is_split_image(img_path):
            return process_split_image(img_path)
        
        # 单张图片
        if allow_fail:
            return {
                "status": "need_more",
                "message": "需要上传另一面（请发送正面或反面）"
            }
        return {
            "status": "error",
            "message": "需要两张身份证图片"
        }
    
    return {"status": "error", "message": "图片数量超出预期"}


# ========== 完整认证流程 ==========

def full_auth_flow(
    image_paths: List[str],
    ocr_func=None,
    auth_check_func=None,
    auth_upload_func=None
) -> Dict:
    """
    完整身份证认证流程
    
    Args:
        image_paths: 图片路径列表（1-2张）
        ocr_func: OCR识别函数 (path) -> {"name": str, "id_number": str}
        auth_check_func: 查询函数 (name, id_number) -> exists dict
        auth_upload_func: 上传函数 (name, id_number, front, reverse) -> upload dict
    
    Returns:
        认证结果 dict
    """
    # 1. 处理图片
    img_result = process_idcard_images(image_paths)
    
    if img_result["status"] == "need_more":
        return {
            "status": "need_more",
            "message": img_result["message"]
        }
    
    if img_result["status"] == "error":
        return img_result
    
    if img_result["status"] == "split_done":
        front_path = img_result["front_path"]
        reverse_path = img_result["reverse_path"]
    else:
        front_path = img_result["front_path"]
        reverse_path = img_result["reverse_path"]
    
    # 2. OCR识别正面
    if ocr_func:
        ocr_result = ocr_func(front_path)
        if not ocr_result:
            return {
                "status": "error",
                "message": "OCR识别失败"
            }
        name, id_number = ocr_result["name"], ocr_result["id_number"]
    else:
        # 简化测试
        name, id_number = "测试用户", "320000000000000000"
    
    # 3. 查询认证系统
    if auth_check_func:
        exists_result = auth_check_func(name, id_number)
        if exists_result["exists"]:
            return {
                "status": "authenticated",
                "message": "已认证，直接推送",
                "name": name,
                "id_number": id_number,
                "system_data": exists_result["data"]
            }
    
    # 4. 上传认证系统
    if auth_upload_func:
        upload_result = auth_upload_func(name, id_number, front_path, reverse_path)
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
    
    # 简化返回
    return {
        "status": "ready",
        "message": "图片处理完成",
        "front_path": front_path,
        "reverse_path": reverse_path,
        "name": name,
        "id_number": id_number
    }


if __name__ == "__main__":
    # 测试
    import sys
    
    if len(sys.argv) > 1:
        # 测试分割
        result = process_split_image(sys.argv[1])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # 测试图片处理
        from PIL import Image
        
        # 创建测试图片
        img1 = Image.new('RGB', (800, 500), (200, 200, 255))
        img2 = Image.new('RGB', (800, 500), (255, 200, 200))
        img1.save('/tmp/test_front.jpg')
        img2.save('/tmp/test_reverse.jpg')
        
        result = process_idcard_images(['/tmp/test_front.jpg', '/tmp/test_reverse.jpg'])
        print(json.dumps(result, indent=2, ensure_ascii=False))