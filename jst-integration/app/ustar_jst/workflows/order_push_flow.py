#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聚水潭ERP智能订单推送系统 v2.0 - 主推送模块
"""
import re
import os
import sys
import json
import time
import hashlib
import logging
import requests
import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

from parser.order_parser import OrderStatus, OrderItem, WeChatOrder, OrderParser
from parser.sku_map import MILK_POWDER_KEYWORDS, MILK_POWDER_SKU, PRODUCT_SKU_MAP
from parser.sku_map import SHOPS_REQUIRING_IDCARD, SHOP_CONFIG
from parser.sku_map import ProductMapper, MilkPowderSplitter
from core.jst_client import DEFAULT_SHOP_ID, DEFAULT_BUYER_ID

# 身份证缓存（用于实名校验）
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from 身份证上传.idcard_cache_db import get_name_by_number
except Exception:
    get_name_by_number = None  # 兼容：模块不存在时跳过


# ==================== Pydantic 验证模型 (可选使用) ====================
#   from pydantic import BaseModel, Field, validator
#   order = OrderInput(phone="13800138000", idcard="110101199001011234")
#   order.clean()  # 自动验证，错误会抛异常

try:
    from pydantic import BaseModel, Field, field_validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    # 如果没装 pydantic，用下面的简单验证
    BaseModel = object

if PYDANTIC_AVAILABLE:
    class OrderInput(BaseModel):
        """订单输入验证模型 - 像填表格一样简单！
        
        用法:
            order = OrderInput(
                phone="13800138000",
                idcard="110101199001011234",
                sku="1SFCC97001079SHY",
                quantity=2
            )
            order.clean()  # 自动验证，错了会报错
        """
        phone: str = Field(description="手机号，11位数字")
        receiver_name: str = Field(min_length=2, max_length=50, description="收件人姓名")
        address: str = Field(min_length=5, max_length=200, description="收货地址")
        sku: str = Field(description="商品SKU编码")
        quantity: int = Field(gt=0, le=100, description="商品数量")
        idcard: Optional[str] = Field(default=None, description="身份证号(18位)")
        
        @field_validator('phone')
        @classmethod
        def validate_phone(cls, v: str) -> str:
            """手机号验证：必须是11位，以1开头"""
            # 去除空格和横线
            v = v.strip().replace(' ', '').replace('-', '')
            # 只保留数字
            digits = ''.join(c for c in v if c.isdigit())
            if len(digits) != 11:
                raise ValueError(f"手机号必须是11位，现在是 {len(digits)} 位")
            if not digits.startswith('1'):
                raise ValueError("手机号必须以1开头")
            if digits[1] not in '3456789':
                raise ValueError("手机号第二位必须是3-9")
            return digits
        
        @field_validator('idcard')
        @classmethod
        def validate_idcard(cls, v: Optional[str]) -> Optional[str]:
            """身份证验证：18位，最后一位可以是X"""
            if v is None:
                return None
            v = v.strip().upper()
            if len(v) != 18:
                raise ValueError(f"身份证必须是18位，现在是 {len(v)} 位")
            # 检查前17位必须是数字
            if not v[:17].isdigit():
                raise ValueError("身份证前17位必须是数字")
            # 最后一位必须是数字或X
            if v[-1] not in '0123456789Xx':
                raise ValueError("身份证最后一位必须是数字或X")
            return v
        
        @field_validator('sku')
        @classmethod
        def validate_sku(cls, v: str) -> str:
            """SKU验证：不能为空"""
            v = v.strip()
            if not v:
                raise ValueError("SKU不能为空")
            return v
        
        def clean(self) -> 'OrderInput':
            """验证并返回清理后的数据"""
            return self
    
    class IdCardInput(BaseModel):
        """身份证输入验证模型"""
        id_card_number: str = Field(description="身份证号")
        id_card_name: str = Field(min_length=2, max_length=50, description="姓名")
        
        @field_validator('id_card_number')
        @classmethod
        def validate_idcard(cls, v: str) -> str:
            v = v.strip().upper()
            if len(v) != 18:
                raise ValueError(f"身份证必须是18位，现在是 {len(v)} 位")
            return v
        
        @field_validator('id_card_name')
        @classmethod
        def validate_name(cls, v: str) -> str:
            v = v.strip()
            if len(v) < 2:
                raise ValueError("姓名至少2个字符")
            return v

    # 便捷验证函数
    def validate_order(phone=None, idcard=None, sku=None, quantity=None, **kwargs):
        """一行验证订单所有字段
        
        用法:
            result = validate_order(
                phone="13800138000",
                idcard="110101199001011234",
                sku="1SFCC97001079SHY",
                quantity=2
            )
            if result["valid"]:
                print("✅ 验证通过")
            else:
                print(f"❌ {result['error']}")
        """
        errors = []
        
        # 验证手机号
        if phone:
            try:
                OrderInput.model_validate({"phone": phone, "receiver_name": "测试", "address": "测试地址123", "sku": "TEST", "quantity": 1})
            except Exception as e:
                errors.append(f"手机号: {e}")
        
        # 验证身份证
        if idcard:
            try:
                IdCardInput.model_validate({"id_card_number": idcard, "id_card_name": "测试"})
            except Exception as e:
                errors.append(f"身份证: {e}")
        
        # 验证SKU
        if sku and not sku.strip():
            errors.append("SKU不能为空")
        
        # 验证数量
        if quantity is not None:
            try:
                q = int(quantity)
                if q <= 0 or q > 100:
                    errors.append("数量必须在1-100之间")
            except:
                errors.append("数量必须是数字")
        
        if errors:
            return {"valid": False, "error": "; ".join(errors)}
        return {"valid": True}

else:
    # 简单版（没装 pydantic）
    def validate_order(phone=None, idcard=None, sku=None, quantity=None, **kwargs):
        """简易验证（无 pydantic）"""
        errors = []
        
        if phone:
            digits = ''.join(c for c in str(phone) if c.isdigit())
            if len(digits) != 11:
                errors.append(f"手机号必须是11位")
        
        if idcard:
            v = str(idcard).strip().upper()
            if len(v) != 18:
                errors.append(f"身份证必须是18位")
        
        if sku and not sku.strip():
            errors.append("SKU不能为空")
        
        if errors:
            return {"valid": False, "error": "; ".join(errors)}
        return {"valid": True}

# ==================== 配置部分 ====================
# 聚水潭API配置
# 优先读取环境变量，兜底使用默认值
JST_CONFIG = {
    "app_key": os.environ.get("JST_APP_KEY", "d561deb348274f1ba3505ec4578870fd"),
    "app_secret": os.environ.get("JST_APP_SECRET", "84ad2c023b9b49378b1161ea569e383c"),
    "api_url_prod": "https://open.erp321.com/api/open/query.aspx"
}

# 授权Token
JST_TOKEN = os.environ.get("JST_TOKEN", "cfda23ff97664494bc6fc5ab46f8ea48")

# 默认店铺配置

# ==================== 日志配置 ====================

def setup_logging(log_file: str = "order_push.log") -> logging.Logger:
    """配置日志系统"""
    logger = logging.getLogger("OrderPush")
    logger.setLevel(logging.DEBUG)

    # 文件处理器
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)

    # 控制台处理器
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    # 格式化
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger

# ==================== JST订单格式 ====================
@dataclass
class JSTOrder:
    """聚水潭订单格式"""
    shop_id: int = 0
    so_id: str = ""
    order_date: str = ""
    shop_status: str = "WAIT_SELLER_SEND_GOODS"
    shop_buyer_id: str = ""
    receiver_name: str = ""
    receiver_mobile: str = ""
    receiver_state: str = ""
    receiver_city: str = ""
    receiver_district: str = ""
    receiver_address: str = ""
    receiver_country: str = "CN"
    pay_amount: float = 0
    freight: float = 0
    buyer_message: str = ""
    seller_remark: str = ""  # 卖家备注（商家填写）
    items: List[dict] = field(default_factory=list)
    pay: dict = field(default_factory=dict)
    card: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        # 移除空的card字段
        if not data.get('card'):
            data.pop('card', None)
        return data

class IDCardOCR:
    """双轨OCR识别：本地OCR + 阿里百炼回退"""
    
    # 本地OCR服务配置
    LOCAL_OCR_URL = "http://192.168.178.26:18888/ocr/idcard"
    LOCAL_OCR_TIMEOUT = 30
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._api_key = None
    
    def _get_api_key(self) -> str:
        """获取阿里百炼API Key"""
        if self._api_key is None:
            # 从 .env 读取
            env_path = "/opt/data/.env"
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith("DASHSCOPE_API_KEY="):
                        self._api_key = line.split("=", 1)[1].strip()
                        break
        return self._api_key
    
    def _try_local_ocr(self, image_path: str) -> dict:
        """
        尝试本地OCR识别
        Returns: {"success": True/False, "name": "", "id_card": "", ...}
        """
        import urllib.request
        import urllib.parse
        import json
        
        self.logger.info(f"  [OCR] 尝试本地OCR服务: {self.LOCAL_OCR_URL}")
        
        try:
            # 读取图片
            with open(image_path, 'rb') as f:
                img_data = f.read()
            
            # 构建 multipart 请求
            boundary = '----WebAppBoundary' + str(hash(image_path))[-8:]
            body = b'\r\n'.join([
                b'------' + boundary.encode(),
                b'Content-Disposition: form-data; name="file"; filename="idcard.jpg"',
                b'Content-Type: image/jpeg',
                b'',
                img_data,
                b'------' + boundary.encode() + b'--'
            ])
            
            req = urllib.request.Request(
                self.LOCAL_OCR_URL,
                data=body,
                headers={
                    'Content-Type': f'multipart/form-data; boundary=----{boundary}'
                }
            )
            
            with urllib.request.urlopen(req, timeout=self.LOCAL_OCR_TIMEOUT) as resp:
                result = json.loads(resp.read().decode('utf-8'))
            
            # 解析本地OCR返回结果
            if "error" in result:
                self.logger.info(f"  [OCR] 本地OCR识别无文字: {result.get('error')}")
                return {"success": False, "message": result.get("error", "未检测到文字")}
            
            # 成功解析 - 提取姓名和身份证号
            name = result.get("name") or result.get("姓名") or ""
            id_card = result.get("id_card") or result.get("id_number") or result.get("身份证号") or ""
            
            # 尝试从text字段解析
            text = result.get("text", "")
            if isinstance(text, dict):
                name = name or text.get("姓名")
                id_card = id_card or text.get("身份证号")
            elif isinstance(text, str) and text:
                import re
                name_match = re.search(r'姓名[：:]\s*([^\s,，]+)', text)
                id_match = re.search(r'(\d{17}[\dXx])', text)
                if name_match:
                    name = name_match.group(1)
                if id_match:
                    id_card = id_match.group(1)
            
            if name or id_card:
                self.logger.info(f"  [OCR] 本地OCR成功: 姓名={name}, ID={id_card[:6] if id_card else 'None'}***")
                return {
                    "success": True,
                    "name": name or "",
                    "id_card": id_card or "",
                    "message": "本地OCR识别成功"
                }
            else:
                self.logger.info(f"  [OCR] 本地OCR返回格式未知: {result}")
                return {"success": False, "message": "无法解析本地OCR结果"}
                
        except urllib.error.URLError as e:
            self.logger.warning(f"  [OCR] 本地OCR连接失败: {str(e)}")
            return {"success": False, "message": f"本地OCR连接失败: {str(e)}"}
        except Exception as e:
            self.logger.warning(f"  [OCR] 本地OCR异常: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def recognize(self, image_path: str) -> dict:
        """
        双轨识别身份证：本地OCR优先，失败则阿里百炼
        
        Args:
            image_path: 身份证图片路径（正反面合并或单张）
            
        Returns:
            {
                "success": True/False,
                "name": 姓名,
                "id_card": 身份证号,
                "address": 地址,
                "gender": 性别,
                "nation": 民族,
                "birthday": 出生日期,
                "message": 识别结果描述
            }
        """
        # ========== 第1步：尝试本地OCR ==========
        self.logger.info("[OCR] =============================")
        self.logger.info(f"[OCR] 开始识别: {image_path}")
        self.logger.info("[OCR] 优先尝试本地OCR服务...")
        
        local_result = self._try_local_ocr(image_path)
        
        if local_result.get("success"):
            # 本地OCR成功，补充完整字段结构
            self.logger.info("[OCR] 本地OCR识别成功 ✓")
            return {
                "success": True,
                "name": local_result.get("name", ""),
                "id_card": local_result.get("id_card", ""),
                "gender": "",
                "birthday": "",
                "nation": "",
                "address": "",
                "issuer": "",
                "validity": "",
                "message": "本地OCR识别成功"
            }
        
        # ========== 第2步：本地OCR失败，回退到阿里百炼 ==========
        self.logger.info(f"[OCR] 本地OCR失败: {local_result.get('message')}")
        self.logger.info("[OCR] 回退到阿里百炼OCR...")
        
        try:
            import base64
            import requests
            
            api_key = self._get_api_key()
            if not api_key:
                return {"success": False, "message": "未找到 DASHSCOPE_API_KEY"}
            
            # 读取图片并转为 base64
            with open(image_path, "rb") as f:
                image_base64 = base64.b64encode(f.read()).decode("utf-8")
            
            # 调用阿里百炼视觉模型 API (HTTP)
            url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "qwen-vl-max",
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"image": f"data:image/jpeg;base64,{image_base64}"},
                                {"text": '''请识别这张身份证的图片内容。
如果这是身份证正面，请提取：姓名、身份证号码、性别、出生日期、民族、地址。
如果这是身份证反面，请提取：签发机关、有效期。
请以JSON格式返回，不要其他文字。
格式：{"姓名":"", "身份证号":"", "性别":"", "出生日期":"", "民族":"", "地址":"", "签发机关":"", "有效期":""}'''}
                            ]
                        }
                    ]
                },
                "parameters": {"format": "message"}
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            result = response.json()
            
            if response.status_code == 200:
                # 解析响应
                content = result.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
                if isinstance(content, list) and len(content) > 0:
                    content = content[0].get("text", "")
                
                self.logger.info(f"  识别原始结果: {content[:200]}...")
                
                # 解析JSON
                import re
                json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    return {
                        "success": True,
                        "name": data.get("姓名", ""),
                        "id_card": data.get("身份证号", ""),
                        "gender": data.get("性别", ""),
                        "birthday": data.get("出生日期", ""),
                        "nation": data.get("民族", ""),
                        "address": data.get("地址", ""),
                        "issuer": data.get("签发机关", ""),
                        "validity": data.get("有效期", ""),
                        "message": "识别成功"
                    }
                else:
                    return {"success": False, "message": "无法解析识别结果"}
            else:
                return {"success": False, "message": f"API调用失败: {result}"}
                
        except Exception as e:
            self.logger.error(f"  身份证识别异常: {str(e)}")
            return {"success": False, "message": f"识别异常: {str(e)}"}

class AuthSystemUploader:
    """认证系统上传器"""
    
    API_URL = "http://ccs.ustarvs.com/api/certificate/update"
    API_INFO_URL = "http://ccs.ustarvs.com/api/certificate/info"
    APP_KEY = "base64:Wfxt/ngwZJ9KcAfpiZgPk3XH2f+f0ocyPFuDJRe3mgM="
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def check_idcard_exists(self, id_card_name: str, id_card_number: str) -> dict:
        """
        检查身份证是否已在认证系统中存在
        
        Args:
            id_card_name: 姓名
            id_card_number: 身份证号
            
        Returns:
            {"exists": True/False, "message": "...", "data": ...}
        """
        try:
            import requests
            
            # 准备签名参数
            data = {
                "id_card_name": id_card_name,
                "id_card_number": id_card_number
            }
            data["sign"] = self._generate_sign(data)
            
            self.logger.info(f"  检查认证系统: {id_card_name} / {id_card_number[:6]}****{id_card_number[-4:]}")
            
            # 发送请求
            response = requests.post(self.API_INFO_URL, data=data, timeout=30)
            result = response.json()
            
            if result.get("code") == 0 or result.get("code") == 200:
                self.logger.info(f"  ✅ 身份证已存在")
                return {
                    "exists": True,
                    "message": "身份证已存在",
                    "data": result.get("data")
                }
            else:
                self.logger.info(f"  ℹ️ 身份证不存在")
                return {
                    "exists": False,
                    "message": "身份证不存在",
                    "data": None
                }
                
        except Exception as e:
            self.logger.error(f"  检查异常: {str(e)}")
            return {"exists": False, "message": f"检查异常: {str(e)}", "data": None}
    
    def _generate_sign(self, params: dict) -> str:
        """生成API签名"""
        import hmac
        import base64
        
        sign_key = self.APP_KEY.encode('utf-8')
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
    
    def upload(self, id_card_name: str, id_card_number: str,
               front_path: str, back_path: str) -> dict:
        """
        上传身份证到认证系统
        
        Args:
            id_card_name: 姓名
            id_card_number: 身份证号
            front_path: 正面图片路径
            back_path: 反面图片路径
            
        Returns:
            {"success": True/False, "message": "...", "data": ...}
        """
        try:
            import os
            import requests
            from PIL import Image
            
            # 准备签名参数
            data = {
                "id_card_name": id_card_name,
                "id_card_number": id_card_number
            }
            data["sign"] = self._generate_sign(data)
            
            # 压缩图片
            def compress_image(path: str) -> str:
                """压缩图片并返回新路径"""
                if not os.path.exists(path):
                    return path
                    
                temp_path = path + ".compressed.jpg"
                try:
                    with Image.open(path) as img:
                        # 限制最大尺寸
                        max_size = 2000
                        if max(img.size) > max_size:
                            ratio = max_size / max(img.size)
                            new_size = (int(img.width * ratio), int(img.height * ratio))
                            img = img.resize(new_size, Image.LANCZOS)
                        img.save(temp_path, 'JPEG', quality=85, optimize=True)
                    return temp_path
                except:
                    return path
            
            # 压缩图片
            front_compressed = compress_image(front_path)
            back_compressed = compress_image(back_path)
            
            # 准备文件
            files = {}
            for key, path in [("id_card_front", front_compressed), ("id_card_reverse", back_compressed)]:
                if os.path.exists(path):
                    mime = 'image/jpeg'
                    if path.endswith('.png'):
                        mime = 'image/png'
                    files[key] = (os.path.basename(path), open(path, 'rb'), mime)
            
            self.logger.info(f"  上传身份证到认证系统: {id_card_name} / {id_card_number}")
            
            # 发送请求
            response = requests.post(self.API_URL, data=data, files=files, timeout=60)
            result = response.json()
            
            # 关闭文件
            for f in files.values():
                f[1].close()
            
            # 删除临时压缩文件
            for path in [front_compressed, back_compressed]:
                if path != front_path and path != back_path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except:
                        pass
            
            if result.get("code") == 0 or result.get("code") == 200:
                self.logger.info(f"  ✅ 认证系统上传成功")
                # 自动保存到本地数据库
                self.save_to_local_db(id_card_name, id_card_number)
                return {
                    "success": True,
                    "message": "上传成功",
                    "data": result.get("data")
                }
            else:
                self.logger.error(f"  ❌ 认证系统上传失败: {result.get('message')}")
                return {
                    "success": False,
                    "message": result.get("message", "上传失败")
                }
                
        except Exception as e:
            self.logger.error(f"  上传异常: {str(e)}")
            return {"success": False, "message": f"上传异常: {str(e)}"}
    
    def save_to_local_db(self, id_card_name: str, id_card_number: str) -> bool:
        """
        上传成功后自动保存到本地数据库
        
        Args:
            id_card_name: 姓名
            id_card_number: 身份证号
            
        Returns:
            是否保存成功
        """
        import sqlite3
        import datetime
        
        db_path = "/opt/data/workspace/ustar-deploy/app/ustar_jst/idcard_cache.db"
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 检查是否已存在
            cursor.execute(
                "SELECT id_card_number FROM idcard_cache WHERE id_card_number = ?",
                (id_card_number,)
            )
            exists = cursor.fetchone()
            
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if exists:
                # 更新
                cursor.execute("""
                    UPDATE idcard_cache 
                    SET id_card_name = ?, is_authenticated = 1, checked_at = ?
                    WHERE id_card_number = ?
                """, (id_card_name, now, id_card_number))
                self.logger.info(f"  更新本地数据库: {id_card_name} / {id_card_number}")
            else:
                # 插入
                cursor.execute("""
                    INSERT INTO idcard_cache (id_card_number, id_card_name, is_authenticated, checked_at)
                    VALUES (?, ?, 1, ?)
                """, (id_card_number, id_card_name, now))
                self.logger.info(f"  插入本地数据库: {id_card_name} / {id_card_number}")
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            self.logger.error(f"  保存本地数据库失败: {str(e)}")
            return False

class IDCardValidator:
    """身份证校验器"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def validate(self, id_card: str) -> Tuple[bool, str]:
        """
        校验身份证号

        Returns:
            (is_valid, message) 元组
        """
        if not id_card:
            return False, "身份证号为空"

        # 长度校验
        if len(id_card) != 18:
            return False, f"身份证号长度错误: {len(id_card)}位"

        # 格式校验
        if not re.match(r'^[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$', id_card):
            return False, "身份证号格式错误"

        # 校验位校验
        if not self._check_code(id_card):
            return False, "身份证号校验位错误"

        return True, "校验通过"

    def _check_code(self, id_card: str) -> bool:
        """校验身份证最后一位"""
        # 权重因子
        weight = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        # 校验码对应表
        check_code = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']

        total = sum(int(id_card[i]) * weight[i] for i in range(17))
        check_digit = check_code[total % 11]

        return check_digit == id_card[17].upper()


# ─────────────── P3: 身份证实名校验（姓名×收件人比对） ───────────────

TELEGRAM_BOT_TOKEN_IDCARD = os.environ.get(
    "TELEGRAM_BOT_TOKEN", "8713145628:AAHvpiAwEMX6-myAvw9mRJKZ0uXgHiJyUkw"
)
HERMES_TELEGRAM_CHAT_ID_IDCARD = os.environ.get("HERMES_TELEGRAM_CHAT_ID", "5573662232")


def _telegram_send_idcard_alert(text: str) -> bool:
    """发送 Telegram 告警（身份证姓名不匹配专用），返回成功/失败。"""
    if not TELEGRAM_BOT_TOKEN_IDCARD:
        logging.warning("[P3] 未配置 TELEGRAM_BOT_TOKEN，跳过姓名不匹配告警")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_IDCARD}/sendMessage",
            json={
                "chat_id": HERMES_TELEGRAM_CHAT_ID_IDCARD,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        result = r.json()
        if result.get("ok"):
            return True
        logging.error(f"[P3] Telegram发送失败: {result.get('description')}")
        return False
    except Exception as e:
        logging.error(f"[P3] Telegram异常: {e}")
        return False


def _build_name_mismatch_message(
    order: "WeChatOrder",
    idcard_holder_name: str,
    receiver_name: str,
) -> str:
    """构建姓名不匹配的 Markdown 告警消息。"""
    shop_info = SHOP_CONFIG.get(order.shop_id, {})
    shop_name = shop_info.get("name", str(order.shop_id))
    item_names = " / ".join(f"{item.name}×{item.qty}" for item in order.items)

    return (
        f"🚨 *P3 身份证姓名不匹配 — 订单已阻断*\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🆔 订单号: `{order.order_id}`\n"
        f"🏪 店铺: {shop_name}\n"
        f"📦 商品: {item_names}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🔴 *收件人姓名*: `{receiver_name}`\n"
        f"🟡 *身份证持证人*: `{idcard_holder_name}`\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⚠️ 收件人与身份证持证人不一致！\n"
        f"请核实是否为同一人，或重新上传正确的身份证。"
    )


class NameMismatchError(Exception):
    """身份证姓名与订单收件人不一致的异常（用于阻断推送）。"""
    def __init__(self, order_dict: dict, idcard_holder_name: str, receiver_name: str):
        super().__init__(f"姓名不匹配: 收件人={receiver_name}, 持证人={idcard_holder_name}")
        self.order_dict = order_dict
        self.idcard_holder_name = idcard_holder_name
        self.receiver_name = receiver_name


class JSTPusher:
    """聚水潭订单推送器"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.config = JST_CONFIG
        self.token = JST_TOKEN

    def generate_sign(self, method: str, params: dict) -> str:
        """生成API签名"""
        partnerid = self.config["app_key"]
        partnerkey = self.config["app_secret"]

        param_str = "".join(str(k) + str(v) for k, v in sorted(params.items()))
        sign_str = method + partnerid + param_str + partnerkey

        return hashlib.md5(sign_str.encode('utf-8')).hexdigest().lower()

    def convert_to_jst_order(self, order: WeChatOrder, buyer_id: str = None) -> JSTOrder:
        """将微信订单转换为聚水潭格式"""
        # 获取商品SKU和价格
        items = []
        total_amount = 0

        for item in order.items:
            sku, price = ProductMapper(self.logger).get_sku(item.name)
            item.sku_id = sku
            if price > 0:
                item.price = price

            items.append({
                "sku_id": item.sku_id,
                "shop_sku_id": item.sku_id,
                "amount": item.price * item.qty,
                "base_price": item.price,
                "qty": item.qty,
                "name": item.name,
                "outer_oi_id": f"{order.order_id}_{items.__len__() + 1:03d}"
            })
            total_amount += item.price * item.qty

        # 获取店铺信息
        shop_info = SHOP_CONFIG.get(order.shop_id, {"name": "未知店铺", "buyer_id": DEFAULT_BUYER_ID})
        if buyer_id:
            shop_buyer_id = buyer_id
        else:
            shop_buyer_id = shop_info.get("buyer_id", DEFAULT_BUYER_ID)

        jst_order = JSTOrder(
            shop_id=order.shop_id,
            so_id=order.order_id,
            order_date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            shop_status="WAIT_SELLER_SEND_GOODS",
            shop_buyer_id=shop_buyer_id,
            receiver_name=order.receiver_name,
            receiver_mobile=order.receiver_phone,
            receiver_state=order.receiver_province,
            receiver_city=order.receiver_city,
            receiver_district=order.receiver_district,
            receiver_address=order.receiver_address,
            receiver_country="CN",
            pay_amount=total_amount,
            freight=0,
            buyer_message=order.remark,
            seller_remark=order.seller_remark,
            items=items,
            pay={
                "outer_pay_id": f"PAY{order.order_id}",
                "pay_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "payment": "线下",
                "amount": total_amount
            }
        )

        # 添加身份证信息（如果需要）
        if order.id_card and order.shop_id in SHOPS_REQUIRING_IDCARD:
            jst_order.card = {
                "name": order.receiver_name,
                "id_no": order.id_card,
                "outer_oi_id": order.order_id
            }

        return jst_order

    def push_order(self, order: WeChatOrder, buyer_id: str = None, verify: bool = True) -> dict:
        """推送单个订单（可选验证）"""
        jst_order = self.convert_to_jst_order(order, buyer_id)

        self.logger.info(f"推送订单: {order.order_id} -> 聚水潭")

        result = self._call_api("orders.upload", [jst_order.to_dict()])
        
        # 推送成功后验证（带重试）
        if verify and result.get('code') == 0:
            self.logger.info(f"验证订单: {order.order_id}")
            # 重试3次，每次等待
            for attempt in range(3):
                time.sleep(2)
                verify_result = self._verify_order(order.order_id)
                if verify_result.get('code') == 0:
                    verified_orders = verify_result.get('orders', [])
                    if verified_orders:
                        order_info = verified_orders[0]
                        result['verified'] = True
                        result['jst_o_id'] = order_info.get('o_id')
                        result['shop_status'] = order_info.get('shop_status')
                        self.logger.info(f"订单验证成功: o_id={order_info.get('o_id')}")
                        break
                    else:
                        self.logger.warning(f"验证尝试 {attempt+1}/3: 订单未找到")
                else:
                    self.logger.warning(f"验证尝试 {attempt+1}/3 失败: {verify_result.get('msg')}")
            else:
                result['verified'] = False
                self.logger.warning(f"订单验证失败: 3次尝试后仍未找到")
        
        return result
    
    def _verify_order(self, so_id: str) -> dict:
        """验证订单是否成功推送到聚水潭"""
        from datetime import datetime, timedelta
        
        ts = str(int(time.time()))
        sys_params = {"token": self.token, "ts": ts}
        sign = self.generate_sign("orders.single.query", sys_params)
        
        url = f"{self.config['api_url_prod']}?method=orders.single.query&partnerid={self.config['app_key']}&token={self.token}&ts={ts}&sign={sign}"
        
        # 查询参数 - 用 so_id 查询
        query_params = {
            "so_ids": [so_id],
        }
        
        headers = {"Content-Type": "application/json; charset=utf-8"}
        json_str = json.dumps(query_params, ensure_ascii=False)
        
        try:
            response = requests.post(url, data=json_str.encode('utf-8'), headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            return {"code": -1, "msg": str(e)}

    def push_orders_batch(self, orders: List[WeChatOrder], buyer_id: str = None, verify: bool = True) -> dict:
        """批量推送订单（最多50个），可选二次验证"""
        if len(orders) > 50:
            return {"code": -1, "msg": "单次最多推送50个订单"}

        jst_orders = [self.convert_to_jst_order(order, buyer_id).to_dict() for order in orders]

        self.logger.info(f"批量推送: {len(orders)}个订单 -> 聚水潭")

        result = self._call_api("orders.upload", jst_orders)

        # 推送成功后逐单验证（带重试）
        if verify and result.get('code') == 0:
            order_ids = [order.order_id for order in orders]
            self.logger.info(f"批量验证: {len(order_ids)}个订单")
            
            verification_results = []
            for so_id in order_ids:
                verified = False
                jst_o_id = None
                shop_status = None
                for attempt in range(3):
                    time.sleep(2)
                    verify_result = self._verify_order(so_id)
                    if verify_result.get('code') == 0:
                        verified_orders = verify_result.get('orders', [])
                        if verified_orders:
                            order_info = verified_orders[0]
                            verified = True
                            jst_o_id = order_info.get('o_id')
                            shop_status = order_info.get('shop_status')
                            self.logger.info(f"订单 {so_id} 验证成功: o_id={jst_o_id}")
                            break
                        else:
                            self.logger.warning(f"订单 {so_id} 验证尝试 {attempt+1}/3: 未找到")
                    else:
                        self.logger.warning(f"订单 {so_id} 验证尝试 {attempt+1}/3 失败")
                verification_results.append({
                    "so_id": so_id,
                    "verified": verified,
                    "jst_o_id": jst_o_id,
                    "shop_status": shop_status
                })
            
            result['verified_count'] = sum(1 for v in verification_results if v['verified'])
            result['total_count'] = len(order_ids)
            result['verifications'] = verification_results
        
        return result

    def _call_api(self, method: str, data: list) -> dict:
        """调用聚水潭API"""
        ts = str(int(time.time()))
        sys_params = {"token": self.token, "ts": ts}
        sign = self.generate_sign(method, sys_params)

        url = f"{self.config['api_url_prod']}?method={method}&partnerid={self.config['app_key']}&token={self.token}&ts={ts}&sign={sign}"

        headers = {"Content-Type": "application/json; charset=utf-8"}
        json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))

        try:
            response = requests.post(url, data=json_str.encode('utf-8'), headers=headers, timeout=30)
            result = response.json()

            if result.get('code') == 0:
                self.logger.info(f"API调用成功: {method}")
            else:
                self.logger.error(f"API调用失败: {result.get('msg')}")

            return result
        except Exception as e:
            self.logger.error(f"API调用异常: {str(e)}")
            return {"code": -1, "msg": str(e)}

class OrderPushSystem:
    """订单推送系统（主控制器）"""
    
    # 身份证状态机常量
    IDCARD_STATE_INIT = "init"           # 初始状态
    IDCARD_STATE_FRONT_OK = "front_ok"     # 正面识别成功，待反面或认证
    IDCARD_STATE_BOTH_OK = "both_ok"       # 正反面上传完成
    IDCARD_STATE_AUTHENTICATED = "authenticated"  # 已认证
    IDCARD_STATE_ERROR = "error"           # 识别/上传失败
    
    def __init__(self):
        self.logger = setup_logging()
        self.parser = OrderParser(self.logger)
        self.mapper = ProductMapper(self.logger)
        self.splitter = MilkPowderSplitter(self.logger)
        self.validator = IDCardValidator(self.logger)
        self.pusher = JSTPusher(self.logger)
        self.idcard_ocr = IDCardOCR(self.logger)  # 阿里百炼OCR
        self.auth_uploader = AuthSystemUploader(self.logger)  # 认证系统上传
        
        # 身份证状态机存储：{idcard_key: {state, name, idcard, front_path, back_path, ...}}
        self._idcard_states = {}
        
        # 初始化身份证数据库连接
        self.idcard_db_path = "/opt/data/workspace/ustar-deploy/app/ustar_jst/idcard_cache.db"
        self._idcard_conn = None

    def _get_idcard_conn(self):
        """获取身份证数据库连接"""
        if self._idcard_conn is None:
            import sqlite3
            self._idcard_conn = sqlite3.connect(self.idcard_db_path)
        return self._idcard_conn

    def _get_idcard_state_key(self, idcard: str) -> str:
        """生成身份证状态唯一键"""
        return idcard[:6] + "****" + idcard[-4:] if len(idcard) == 18 else idcard
    
    def get_idcard_state(self, idcard: str) -> dict:
        """获取身份证状态"""
        key = self._get_idcard_state_key(idcard)
        return self._idcard_states.get(key)
    
    def set_idcard_state(self, idcard: str, state: str, **kwargs) -> None:
        """设置身份证状态"""
        key = self._get_idcard_state_key(idcard)
        if key not in self._idcard_states:
            self._idcard_states[key] = {"state": state, "idcard": idcard}
        else:
            self._idcard_states[key]["state"] = state
        self._idcard_states[key].update(kwargs)
    
    def clear_idcard_state(self, idcard: str) -> None:
        """清除身份证状态"""
        key = self._get_idcard_state_key(idcard)
        if key in self._idcard_states:
            del self._idcard_states[key]
    
    def find_idcard_by_name(self, name: str) -> str:
        """
        根据姓名查找身份证号
        
        Args:
            name: 收件人姓名
            
        Returns:
            身份证号，如果未找到返回 None
        """
        if not name:
            return None
        
        conn = self._get_idcard_conn()
        cursor = conn.cursor()
        
        # 模糊匹配姓名
        cursor.execute(
            "SELECT id_card_number FROM idcard_cache WHERE id_card_name LIKE ? LIMIT 1",
            (f"%{name}%",)
        )
        result = cursor.fetchone()
        
        if result:
            self.logger.info(f"  姓名匹配成功: {name} -> {result[0][:6]}****{result[0][-4:]}")
            return result[0]
        
        self.logger.info(f"  数据库中未找到姓名: {name}")
        return None

    # ─── P3: 身份证实名校验（姓名×收件人比对） ───────────────────────

    def verify_receiver_name_vs_idcard(
        self,
        order: "WeChatOrder",
        id_card: str,
    ) -> Tuple[bool, str | None]:
        """
        P3 核心：验证订单收件人姓名与身份证持证人姓名是否一致。

        流程：
        1. 用身份证号从本地缓存查「持证人姓名」
        2. 与 order.receiver_name 比对（去空格后精确比较）
        3. 不一致 → Telegram 告警 + 返回错误（阻断推送）

        Returns:
            (True, None)               — 一致或无缓存数据，继续流程
            (False, error_message)    — 不一致，已告警并返回错误消息
        """
        if not id_card or len(id_card) != 18:
            # 格式不对，跳过（前面已校验）
            return True, None

        if get_name_by_number is None:
            # 模块导入失败，保守跳过
            self.logger.warning("[P3] 无法导入 idcard_cache_db，跳过姓名校验")
            return True, None

        idcard_holder_name = get_name_by_number(id_card)
        if idcard_holder_name is None:
            # 缓存无记录（OCR 识别后首次录入），无法比对，保守放行
            self.logger.info(
                f"[P3] 身份证 {id_card[:6]}****{id_card[-4:]} "
                f"无本地缓存姓名，跳过姓名比对"
            )
            return True, None

        # 姓名比对（去空格）
        receiver_normalized = order.receiver_name.replace(" ", "").replace("　", "")
        holder_normalized = idcard_holder_name.replace(" ", "").replace("　", "")

        if receiver_normalized == holder_normalized:
            self.logger.info(
                f"[P3] ✅ 姓名一致: 收件人「{receiver_normalized}」"
                f" = 持证人「{holder_normalized}」"
            )
            return True, None

        # ── 不一致：Telegram 告警 + 阻断 ──
        self.logger.warning(
            f"[P3] 🚨 姓名不匹配！"
            f"收件人={receiver_normalized}，持证人={holder_normalized}"
        )

        alert_msg = _build_name_mismatch_message(
            order, idcard_holder_name, order.receiver_name
        )
        _telegram_send_idcard_alert(alert_msg)
        self.logger.info(f"[P3] Telegram 告警已发送")

        # 构建阻断消息（标红）
        error_msg = (
            f"🚨 *身份证姓名与收件人不一致 — 订单已阻断*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"🔴 *收件人姓名*: `{order.receiver_name}`\n"
            f"🟡 *身份证持证人*: `{idcard_holder_name}`\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"请核实是否为同一人，或重新上传正确的身份证。\n"
            f"订单号: `{order.order_id}`"
        )
        return False, error_msg

    def process_idcard_image(self, image_path: str, receiver_name: str, 
                             order_info: dict = None) -> dict:
        """
        处理上传的身份证图片（正面，带头像）
        
        Args:
            image_path: 身份证正面图片路径
            receiver_name: 收件人姓名
            order_info: 订单信息（之前解析的订单）
            
        Returns:
            {
                "success": True/False,
                "recognized": True/False,  # 是否识别成功
                "name": 识别的姓名,
                "id_card": 识别的身份证号,
                "state": 状态,
                "message": 结果描述,
                "order": 完整订单信息（待确认）
            }
        """
        self.logger.info("=" * 50)
        self.logger.info("开始处理身份证图片（正面）")
        self.logger.info("=" * 50)
        
        # 第1步：OCR识别正面
        self.logger.info("[1/4] OCR识别...")
        ocr_result = self.idcard_ocr.recognize(image_path)
        
        if not ocr_result.get("success"):
            self.set_idcard_state(recognized_idcard, self.IDCARD_STATE_ERROR, error=ocr_result.get("message"))
            return {
                "success": False,
                "msg": f"❌ 识别失败: {ocr_result.get('message')}",
                "recognized": False,
                "state": self.IDCARD_STATE_ERROR
            }
        
        recognized_name = ocr_result.get("name", "")
        recognized_idcard = ocr_result.get("id_card", "")
        
        self.logger.info(f"  识别结果: {recognized_name} / {recognized_idcard}")
        
        # 第2步：验证姓名匹配
        if recognized_name and receiver_name:
            # 简单匹配：去掉空格后比较
            if recognized_name.replace(" ", "") != receiver_name.replace(" ", ""):
                self.logger.warning(f"  ⚠️ 姓名不匹配: 期望[{receiver_name}] vs 识别[{recognized_name}]")
                # 仍然继续，但提醒用户确认
        
        # 第3步：校验身份证格式
        if recognized_idcard:
            is_valid, msg = self.validator.validate(recognized_idcard)
            if not is_valid:
                self.set_idcard_state(recognized_idcard, self.IDCARD_STATE_ERROR, error=msg)
                return {
                    "success": False,
                    "msg": f"❌ 身份证格式错误: {msg}",
                    "recognized": False,
                    "state": self.IDCARD_STATE_ERROR
                }
        
# 构建订单信息
        if order_info:
            order_info["id_card"] = recognized_idcard
            order_info["idcard_name"] = recognized_name
            order_info["idcard_info"] = ocr_result
        else:
            order_info = {
                "id_card": recognized_idcard,
                "idcard_name": recognized_name,
                "idcard_info": ocr_result
            }
        
        # 第4步：检查认证系统是否已存在
        self.logger.info("[4/4] 检查认证系统是否已认证...")
        check_result = self.auth_uploader.check_idcard_exists(recognized_name, recognized_idcard)
        
        if check_result.get("exists"):
            # 已认证，状态设为 authenticated
            self.set_idcard_state(
                recognized_idcard, 
                self.IDCARD_STATE_AUTHENTICATED,
                name=recognized_name,
                front_path=image_path,
                idcard_info=ocr_result
            )
            self.logger.info("  ✅ 身份证已认证，可直接推送")
            return {
                "success": True,
                "recognized": True,
                "name": recognized_name,
                "id_card": recognized_idcard,
                "state": self.IDCARD_STATE_AUTHENTICATED,
                "idcard_info": ocr_result,
                "order": order_info,
                "msg": f"✅ 身份证识别成功！\n📋 {recognized_name} / {recognized_idcard[:6]}****{recognized_idcard[-4:]}\n✅ 已认证，可直接推送\n⏳ 请确认订单信息无误后回复「确认推送」"
            }
        else:
            # 未认证，状态设为 front_ok，等待上传反面
            self.set_idcard_state(
                recognized_idcard,
                self.IDCARD_STATE_FRONT_OK,
                name=recognized_name,
                front_path=image_path,
                idcard_info=ocr_result
            )
            self.logger.info("  ℹ️ 身份证未认证，需要上传反面")
            return {
                "success": True,
                "recognized": True,
                "name": recognized_name,
                "id_card": recognized_idcard,
                "state": self.IDCARD_STATE_FRONT_OK,
                "idcard_info": ocr_result,
                "order": order_info,
                "msg": f"✅ 身份证识别成功！\n📋 {recognized_name} / {recognized_idcard[:6]}****{recognized_idcard[-4:]}\n⚠️ 请上传身份证反面（带国徽）\n⏳ 上传后请确认订单信息无误后回复「确认推送」"
            }
    
    def process_idcard_back(self, image_path: str, idcard: str) -> dict:
        """
        处理上传的身份证反面图片（带国徽，无需OCR识别）
        
        Args:
            image_path: 身份证反面图片路径
            idcard: 身份证号（之前正面识别到的）
            
        Returns:
            {"success": True/False, "message": "...", "state": "...", "order": {...}}
        """
        # 获取之前的状态
        state_info = self.get_idcard_state(idcard)
        if not state_info:
            return {
                "success": False,
                "message": "❌ 请先上传身份证正面",
                "state": self.IDCARD_STATE_INIT
            }
        
        # 检查状态
        current_state = state_info.get("state")
        if current_state not in [self.IDCARD_STATE_INIT, self.IDCARD_STATE_FRONT_OK]:
            return {
                "success": False,
                "message": f"❌ 当前状态异常: {current_state}",
                "state": current_state
            }
        
        # 保存反面图片路径
        self.set_idcard_state(
            idcard,
            self.IDCARD_STATE_BOTH_OK,
            back_path=image_path
        )
        
        recognized_name = state_info.get("name", "")
        front_path = state_info.get("front_path", "")
        
        self.logger.info(f"  反面上传成功: {image_path}")
        self.logger.info(f"  准备上传认证: {recognized_name} / {idcard[:6]}****{idcard[-4:]}")
        
        # 上传到认证系统（需要正反面）
        upload_result = self.auth_uploader.upload(
            id_card_name=recognized_name,
            id_card_number=idcard,
            front_path=front_path,
            back_path=image_path
        )
        
        if upload_result.get("success"):
            self.set_idcard_state(idcard, self.IDCARD_STATE_AUTHENTICATED)
            # 保存本地数据库
            self.auth_uploader.save_to_local_db(recognized_name, idcard)
            
            # 构建订单信息
            order_info = {
                "id_card": idcard,
                "idcard_name": recognized_name,
                "idcard_info": state_info.get("idcard_info", {})
            }
            
            return {
                "success": True,
                "message": f"✅ 身份证认证成功！\n📋 {recognized_name} / {idcard[:6]}****{idcard[-4:]}\n⏳ 请确认订单信息无误后回复「确认推送」",
                "state": self.IDCARD_STATE_AUTHENTICATED,
                "order": order_info
            }
        else:
            self.set_idcard_state(idcard, self.IDCARD_STATE_ERROR, error=upload_result.get("message"))
            return {
                "success": False,
                "message": f"❌ 认证失败: {upload_result.get('message')}",
                "state": self.IDCARD_STATE_ERROR
            }
    
    def process_idcard_manual(self, name: str, idcard: str, order_info: dict = None) -> dict:
        """
        手动输入身份证号（兜底方案）
        
        当OCR/上传失败时，用户可以直接输入身份证号
        
        Args:
            name: 姓名
            idcard: 身份证号
            order_info: 订单信息
            
        Returns:
            {"success": True/False, "message": "...", "state": "...", "order": {...}}
        """
        self.logger.info("=" * 50)
        self.logger.info("手动输入身份证（兜底）")
        self.logger.info("=" * 50)
        
        # 校验身份证格式
        is_valid, msg = self.validator.validate(idcard)
        if not is_valid:
            self.set_idcard_state(idcard, self.IDCARD_STATE_ERROR, error=msg)
            return {
                "success": False,
                "message": f"❌ 身份证格式错误: {msg}",
                "state": self.IDCARD_STATE_ERROR
            }
        
        self.logger.info(f"  输入: {name} / {idcard[:6]}****{idcard[-4:]}")
        
        # 检查认证系统是否已存在
        self.logger.info("  检查认证系统是否已认证...")
        check_result = self.auth_uploader.check_idcard_exists(name, idcard)
        
        if check_result.get("exists"):
            # 已认证
            self.set_idcard_state(
                idcard,
                self.IDCARD_STATE_AUTHENTICATED,
                name=name
            )
            # 保存本地数据库
            self.auth_uploader.save_to_local_db(name, idcard)
            
            # 构建订单信息
            if order_info:
                order_info["id_card"] = idcard
                order_info["idcard_name"] = name
            else:
                order_info = {"id_card": idcard, "idcard_name": name}
            
            return {
                "success": True,
                "name": name,
                "id_card": idcard,
                "state": self.IDCARD_STATE_AUTHENTICATED,
                "order": order_info,
                "msg": f"✅ 身份证验证成功！\n📋 {name} / {idcard[:6]}****{idcard[-4:]}\n✅ 已认证，可直接推送\n⏳ 请确认订单信息无误后回复「确认推送」"
            }
        else:
            # 未认证
            self.set_idcard_state(
                idcard,
                self.IDCARD_STATE_INIT,
                name=name
            )
            
            # 构建订单信息（待认证后使用）
            if order_info:
                order_info["id_card"] = idcard
                order_info["idcard_name"] = name
            else:
                order_info = {"id_card": idcard, "idcard_name": name}
            
            return {
                "success": True,
                "name": name,
                "id_card": idcard,
                "state": self.IDCARD_STATE_INIT,
                "order": order_info,
                "msg": f"✅ 身份证验证成功！\n📋 {name} / {idcard[:6]}****{idcard[-4:]}\n⚠️ 身份证未认证\n📷 请上传身份证正面（带头像）进行认证"
            }
    
    def sync_idcard_to_local_db(self, id_card_name: str, id_card_number: str) -> dict:
        """
        手动同步身份证到本地数据库（用于已经认证过的身份证）
        
        Args:
            id_card_name: 姓名
            id_card_number: 身份证号
            
        Returns:
            {"success": True/False, "message": "...", "state": "..."}
        """
        # 检查认证系统是否已存在
        self.logger.info("  检查认证系统是否已存在...")
        check_result = self.auth_uploader.check_idcard_exists(id_card_name, id_card_number)
        
        if check_result.get("exists"):
            # 已认证，直接保存本地数据库
            self.logger.info("  身份证已认证，直接保存本地数据库")
            success = self.auth_uploader.save_to_local_db(id_card_name, id_card_number)
            if success:
                self.set_idcard_state(id_card_number, self.IDCARD_STATE_AUTHENTICATED, name=id_card_name)
                return {
                    "success": True,
                    "message": f"✅ 身份证已认证: {id_card_name} / {id_card_number[:6]}****{id_card_number[-4:]}",
                    "state": self.IDCARD_STATE_AUTHENTICATED
                }
            else:
                return {
                    "success": False,
                    "message": "❌ 本地数据库保存失败"
                }
        
        # 未认证，需要走认证流程
        self.logger.info("  身份证未认证，需要上传正反面")
        return {
            "success": False,
            "message": f"⚠️ 身份证未认证: {id_card_name} / {id_card_number[:6]}****{id_card_number[-4:]}\n请上传身份证正反面图片",
            "state": self.IDCARD_STATE_INIT
        }
    
    def confirm_and_push(self, order_text: str, shop_id: int = DEFAULT_SHOP_ID,
                  buyer_id: str = None, id_card: str = None) -> dict:
        """
        确认并推送订单（用户确认后的正式推送）
        
        Args:
            order_text: 原始订单文本（与预览时相同）
            
        Returns:
            推送结果
        """
        self.logger.info("=" * 50)
        self.logger.info("确认推送订单")
        self.logger.info("=" * 50)
        
        # 调用 process_order with auto_push=True
        return self.process_order(
            order_text=order_text,
            shop_id=shop_id,
            buyer_id=buyer_id,
            id_card=id_card,
            auto_push=True
        )
    
    def generate_preview_message(self, order_text: str, shop_id: int = DEFAULT_SHOP_ID,
                        buyer_id: str = None, id_card: str = None) -> str:
        """
        生成预览消息（供Telegram发送）
        
        Returns:
            格式化的预览消息
        """
        result = self.process_order(
            order_text=order_text,
            shop_id=shop_id,
            buyer_id=buyer_id,
            id_card=id_card,
            auto_push=False
        )
        
        if not result.get("success") and result.get("preview") is None:
            return f"❌ 解析失败: {result.get('msg')}"
        
        orders = result.get("orders", [])
        if not orders:
            return "❌ 无订单数据"
        
        # 生成预览消息
        msg = "📋 **订单预览**\n"
        msg += "="*40 + "\n"
        
        for i, o in enumerate(orders):
            order_id = o.get("order_id", "未知")
            name = o.get("receiver_name", "")
            phone = o.get("receiver_phone", "")
            province = o.get("receiver_province", "")
            city = o.get("receiver_city", "")
            district = o.get("receiver_district", "")
            address = o.get("receiver_address", "")
            id_card = o.get("id_card", "")
            remark = o.get("seller_remark", "")
            
            msg += f"**订单号:** `{order_id}`\n"
            msg += f"**收件人:** {name}\n"
            msg += f"**电话:** {phone}\n"
            msg += f"**地址:** {province} {city} {district}\n"
            msg += f"         {address}\n"
            
            # 商品
            items = o.get("items", [])
            if items:
                for item in items:
                    msg += f"**商品:** {item.get('product', '未知')} x{item.get('qty', 1)}\n"
            else:
                msg += "**商品:** (待识别)\n"
            
            if id_card:
                msg += f"**身份证:** {id_card[:6]}****{id_card[-4:]}\n"
            else:
                msg += "**身份证:** ⚠️ 待提供\n"
            
            if remark:
                msg += f"**备注:** {remark}\n"
            
            msg += "="*40 + "\n"
        
        msg += "✅ **请回复「确认」或「推送」正式推送**"
        
        return msg
    
    def process_order(self, order_text: str, shop_id: int = DEFAULT_SHOP_ID,
                  buyer_id: str = None, id_card: str = None,
                  auto_push: bool = False) -> dict:
        """
        处理订单（解析->校验->拆单->推送）

        Args:
            order_text: 订单文本
            shop_id: 店铺ID
            buyer_id: 买家账号
            id_card: 身份证号
            auto_push: 是否自动推送（默认 False，需要预览确认）

        Returns:
            处理结果
        """
        self.logger.info("=" * 50)
        self.logger.info("开始处理订单")
        self.logger.info("=" * 50)

        # 1. 解析订单
        self.logger.info("[1/5] 解析订单...")
        order = self.parser.parse_text(order_text)
        order.shop_id = shop_id
        if id_card:
            order.id_card = id_card

        if not order.receiver_name:
            return {"success": False, "msg": "无法识别收件人姓名", "order": order.to_dict()}

        if not order.receiver_phone:
            return {"success": False, "msg": "无法识别电话号码", "order": order.to_dict()}

        # 2. 商品SKU映射
        self.logger.info("[2/5] 商品SKU映射...")
        for item in order.items:
            sku, price = self.mapper.get_sku(item.name)
            item.sku_id = sku
            item.price = price
            self.logger.info(f"  商品: {item.name} -> SKU: {sku}, 价格: {price}")

        # 3. 身份证校验
        self.logger.info("[3/5] 身份证校验...")
        if shop_id in SHOPS_REQUIRING_IDCARD:
            if not order.id_card:
                # 第1步：尝试用姓名匹配数据库
                self.logger.info(f"  订单无身份证，尝试姓名匹配: {order.receiver_name}")
                matched_idcard = self.find_idcard_by_name(order.receiver_name)
                
                if matched_idcard:
                    # 匹配成功，使用数据库中的身份证
                    order.id_card = matched_idcard
                    self.logger.info(f"  ✅ 姓名匹配成功，使用身份证: {matched_idcard[:6]}****{matched_idcard[-4:]}")
                else:
                    # 第1步失败：数据库无记录，要求上传身份证
                    return {
                        "success": False, 
                        "code": -2,  # 表示需要上传身份证
                        "msg": f"📷 请上传收件人 {order.receiver_name} 的身份证正反面照片进行认证",
                        "order": order.to_dict(),
                        "require_idcard_upload": True,
                        "receiver_name": order.receiver_name
                    }
            
            # 校验身份证格式
            is_valid, msg = self.validator.validate(order.id_card)
            if not is_valid:
                return {"success": False, "msg": f"身份证校验失败: {msg}", "order": order.to_dict()}
            self.logger.info(f"  身份证校验通过: {order.id_card[:6]}****{order.id_card[-4:]}")

            # ── P3: 身份证姓名 vs 收件人姓名一致性校验 ──
            self.logger.info("[3.5/5] P3 实名校验（姓名×收件人比对）...")
            ok, err_msg = self.verify_receiver_name_vs_idcard(order, order.id_card)
            if not ok:
                self.logger.warning(f"[P3] 姓名不匹配，阻断推送")
                return {
                    "success": False,
                    "code": -3,               # P3 姓名不匹配专用码
                    "name_mismatch": True,     # 前端标红标记
                    "msg": err_msg,
                    "order": order.to_dict(),
                }
            self.logger.info("[P3] ✅ 姓名校验通过")

        # 4. 奶粉拆单
        self.logger.info("[4/5] 奶粉拆单处理...")
        has_milk_powder = any(self.splitter.is_milk_powder(item.name) for item in order.items)

        if has_milk_powder:
            split_orders = self.splitter.split_order(order)
            self.logger.info(f"  订单拆分为 {len(split_orders)} 个子订单")
            for i, o in enumerate(split_orders):
                for item in o.items:
                    self.logger.info(f"    子订单{i+1}: {item.name} x{item.qty}")
        else:
            split_orders = [order]
            self.logger.info("  无需拆单")

        # 5. 推送订单
        if auto_push:
            self.logger.info("[5/5] 推送订单到聚水潭...")
            if len(split_orders) == 1:
                result = self.pusher.push_order(split_orders[0], buyer_id)
            else:
                result = self.pusher.push_orders_batch(split_orders, buyer_id)

            if result.get('code') == 0:
                self.logger.info("订单推送成功!")
                return {
                    "success": True,
                    "msg": f"成功推送 {len(split_orders)} 个订单",
                    "orders": [o.to_dict() for o in split_orders],
                    "result": result,
                    "verified": result.get('verified', False),
                    "jst_o_id": result.get('jst_o_id'),
                    "shop_status": result.get('shop_status')
                }
            else:
                self.logger.error(f"订单推送失败: {result.get('msg')}")
                return {
                    "success": False,
                    "msg": f"推送失败: {result.get('msg')}",
                    "orders": [o.to_dict() for o in split_orders]
                }
        else:
            # 预览模式
            self.logger.info("[5/5] 预览订单（未推送）...")
            return {
                "success": True,
                "msg": "订单解析完成，等待确认推送",
                "preview": True,
                "orders": [o.to_dict() for o in split_orders]
            }

    def push_preview_orders(self, orders: List[dict], shop_id: int = DEFAULT_SHOP_ID,
                            buyer_id: str = None) -> dict:
        """推送预览后的订单"""
        wechat_orders = []

        for order_dict in orders:
            order = WeChatOrder()
            order.order_id = order_dict.get('order_id', '')
            order.receiver_name = order_dict.get('receiver_name', '')
            order.receiver_phone = order_dict.get('receiver_phone', '')
            order.receiver_province = order_dict.get('receiver_province', '')
            order.receiver_city = order_dict.get('receiver_city', '')
            order.receiver_district = order_dict.get('receiver_district', '')
            order.receiver_address = order_dict.get('receiver_address', '')
            order.id_card = order_dict.get('id_card', '')
            order.remark = order_dict.get('remark', '')
            order.shop_id = order_dict.get('shop_id', shop_id)

            # 解析商品
            for item_dict in order_dict.get('items', []):
                order.items.append(OrderItem(
                    name=item_dict.get('name', ''),
                    sku_id=item_dict.get('sku_id', ''),
                    qty=item_dict.get('qty', 1),
                    price=item_dict.get('price', 0)
                ))

            wechat_orders.append(order)

        # 批量推送
        result = self.pusher.push_orders_batch(wechat_orders, buyer_id)

        if result.get('code') == 0:
            return {
                "success": True,
                "msg": f"成功推送 {len(orders)} 个订单",
                "result": result
            }
        else:
            return {
                "success": False,
                "msg": f"推送失败: {result.get('msg')}",
                "result": result
            }

def print_order_preview(orders_data: List[dict]):
    """打印订单预览"""
    print("\n" + "=" * 80)
    print("订单预览")
    print("=" * 80)

    for i, order in enumerate(orders_data, 1):
        print(f"\n【订单 {i}】")
        print(f"  订单号: {order.get('order_id', 'N/A')}")
        print(f"  收件人: {order.get('receiver_name', 'N/A')}")
        print(f"  电话: {order.get('receiver_phone', 'N/A')}")
        print(f"  地址: {order.get('receiver_province', '')}{order.get('receiver_city', '')}{order.get('receiver_district', '')}{order.get('receiver_address', '')}")
        print(f"  身份证: {order.get('id_card', 'N/A')}")
        print(f"  备注: {order.get('remark', 'N/A')}")
        print(f"  商品:")
        for item in order.get('items', []):
            print(f"    - {item.get('name', 'N/A')} x{item.get('qty', 1)} (SKU: {item.get('sku_id', 'N/A')}, 单价: {item.get('price', 0)})")

    print("\n" + "=" * 80)


def interactive_mode():
    """交互模式"""
    system = OrderPushSystem()

    print("\n欢迎使用聚水潭订单推送系统 v2.0")
    print("=" * 50)

    while True:
        print("\n请选择操作:")
        print("1. 解析订单文本（预览）")
        print("2. 解析并推送订单")
        print("3. 批量推送订单（从预览结果）")
        print("0. 退出")

        choice = input("\n请输入选项: ").strip()

        if choice == '0':
            print("感谢使用，再见！")
            break

        elif choice == '1':
            order_text = input("\n请输入订单信息（文本）: ").strip()
            if order_text:
                result = system.process_order(order_text, auto_push=False)
                if result.get('success'):
                    print_order_preview(result.get('orders', []))
                    print(f"\n{result.get('msg')}")

                    # 询问是否推送
                    confirm = input("\n是否推送这些订单? (y/n): ").strip().lower()
                    if confirm == 'y':
                        push_result = system.push_preview_orders(result.get('orders', []))
                        if push_result.get('success'):
                            print(f"\n{push_result.get('msg')}")
                        else:
                            print(f"\n推送失败: {push_result.get('msg')}")
                else:
                    print(f"\n处理失败: {result.get('msg')}")

        elif choice == '2':
            order_text = input("\n请输入订单信息（文本）: ").strip()
            if order_text:
                result = system.process_order(order_text, auto_push=True)
                if result.get('success'):
                    print(f"\n{result.get('msg')}")
                else:
                    print(f"\n处理失败: {result.get('msg')}")

        else:
            print("\n无效选项，请重新选择")


def test_mode():
    """测试模式"""
    system = OrderPushSystem()

    # 测试订单文本
    test_text = """
    张三 13800138000 江苏省无锡市梁溪区金星街道中桥三村47-402
    商品：德爱白金2段 x4
    备注：尽快发货
    """

    print("测试订单解析...")
    result = system.process_order(test_text, shop_id=18283794, auto_push=False)

    if result.get('success'):
        print_order_preview(result.get('orders', []))
        print(f"\n{result.get('msg')}")
    else:
        print(f"\n处理失败: {result.get('msg')}")


if __name__ == '__main__':
    interactive_mode()
