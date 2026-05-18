"""
认证系统 API 对接模块
用于查询和上传身份证到认证系统
"""

import hashlib
import hmac
import base64
import json
import os
from typing import Optional, Dict, Any


# API 配置
API_URL = "http://ccs.ustarvs.com/api/certificate/update"
API_INFO_URL = "http://ccs.ustarvs.com/api/certificate/info"
# APP_KEY - 原始字符串（带 base64: 前缀）
APP_KEY = "base64:Wfxt/ngwZJ9KcAfpiZgPk3XH2f+f0ocyPFuDJRe3mgM="


def generate_sign(params: dict) -> str:
    """
    生成API签名
    
    签名算法（与PHP一致）：
    1. 将参数按key排序（ksort）
    2. 拼接成 key=value& 格式
    3. 使用HMAC-SHA1算法签名
    4. Base64编码
    """
    sign_key = APP_KEY.encode('utf-8')  # 转为bytes
    sorted_params = sorted(params.items(), key=lambda x: x[0])
    
    param_parts = []
    for key, value in sorted_params:
        if value is None or value == '' or key == 'sign':
            continue
        param_parts.append(f"{key.strip()}={str(value).strip()}&")
    
    param_string = "".join(param_parts)
    if param_string.endswith("&"):
        param_string = param_string[:-1]
    
    sha1_hash = hmac.new(sign_key, param_string.encode('utf-8'), hashlib.sha1).digest()
    sign = base64.b64encode(sha1_hash).decode('utf-8')
    
    return sign


def check_idcard_exists(id_card_name: str, id_card_number: str) -> Dict[str, Any]:
    """
    查询身份证是否已存在于认证系统中
    
    Args:
        id_card_name: 身份证姓名
        id_card_number: 身份证号码
        
    Returns:
        {
            "exists": bool,
            "message": str,
            "data": dict | None
        }
    """
    try:
        import urllib.request
        import urllib.parse
        
        data = {
            "id_card_name": id_card_name,
            "id_card_number": id_card_number
        }
        
        sign = generate_sign(data)
        data["sign"] = sign
        
        # 使用 urllib
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(API_INFO_URL, data=encoded_data)
        
        with urllib.request.urlopen(req, timeout=30) as response:
            result_json = json.loads(response.read().decode('utf-8'))
        
        if result_json.get("code") == 0 or result_json.get("code") == 200:
            return {
                "exists": True,
                "message": "身份证已存在于认证系统",
                "data": result_json.get("data")
            }
        else:
            return {
                "exists": False,
                "message": result_json.get("msg", "身份证不存在"),
                "data": None
            }
        
    except Exception as e:
        return {
            "exists": False,
            "message": f"查询异常: {str(e)}",
            "data": None
        }


def upload_idcard(
    id_card_name: str,
    id_card_number: str,
    id_card_front_path: str,
    id_card_reverse_path: str
) -> Dict[str, Any]:
    """
    上传身份证正反面到认证系统
    
    注意：此API只需签名包含图片文件名，实际文件可通过其他方式处理
    
    Args:
        id_card_name: 身份证姓名
        id_card_number: 身份证号码
        id_card_front_path: 身份证正面图片路径（带头像）
        id_card_reverse_path: 身份证反面图片路径（带国徽）
        
    Returns:
        {
            "success": bool,
            "message": str,
            "data": dict | None
        }
    """
    try:
        # 签名参数需要包含图片文件名
        front_filename = os.path.basename(id_card_front_path)
        reverse_filename = os.path.basename(id_card_reverse_path)
        
        sign_params = {
            "id_card_name": id_card_name,
            "id_card_number": id_card_number,
            "id_card_front": front_filename,
            "id_card_reverse": reverse_filename
        }
        
        sign = generate_sign(sign_params)
        
        # 构建请求数据 - 需要发送全部参数！
        data = {
            "id_card_name": id_card_name,
            "id_card_number": id_card_number,
            "id_card_front": front_filename,
            "id_card_reverse": reverse_filename,
            "sign": sign
        }
        
        # 使用 urllib 发送请求
        import urllib.request
        import urllib.parse
        
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(API_URL, data=encoded_data)
        
        with urllib.request.urlopen(req, timeout=60) as response:
            result = response.read().decode('utf-8')
            result_json = json.loads(result)
        
        if result_json.get("code") == 0 or result_json.get("code") == 200:
            return {
                "success": True,
                "message": "上传成功",
                "data": result_json.get("data")
            }
        else:
            return {
                "success": False,
                "message": result_json.get("msg", "上传失败"),
                "data": result_json
            }
            
    except urllib.error.URLError as e:
        return {
            "success": False,
            "message": f"网络请求失败: {str(e)}",
            "data": None
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"上传异常: {str(e)}",
            "data": None
        }


def get_idcard_merge_image(id_card_number: str) -> Optional[str]:
    """
    获取身份证合成图URL
    
    Args:
        id_card_number: 身份证号码
        
    Returns:
        合成图URL，如果不存在则返回None
    """
    MERGE_IMAGE_BASE_URL = "http://image.ccs.ustarvs.com/storage/app/public/uploads/merge/"
    
    # 合成图命名规则: {身份证号}_merge.jpg
    image_url = f"{MERGE_IMAGE_BASE_URL}{id_card_number}_merge.jpg"
    
    # 检查图片是否存在
    try:
        response = requests.head(image_url, timeout=10)
        if response.status_code == 200:
            return image_url
    except:
        pass
    
    return None