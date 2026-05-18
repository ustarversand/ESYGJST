"""
聚水潭订单推送模块
方便其他智能体调用
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from domains.order_api import push_order_to_jushuitan, push_orders_batch

# 尝试导入身份证查询模块
try:
    from 身份证上传.upload_idcard import batch_query_idcards
    from 身份证上传 import idcard_cache_db as cache_db
    ID_CARD_CHECK_AVAILABLE = True
except ImportError:
    ID_CARD_CHECK_AVAILABLE = False
    print("警告: 身份证查询模块不可用")

# 常用店铺配置
SHOPS = {
    "AUSTARWX": {"id": "18442196", "name": "AUSTARWX", "need_idcard": True},
    "沐浴阳光PDD": {"id": "18020520", "name": "沐浴阳光PDD", "need_idcard": False},
    "武姐": {"id": "18283794", "name": "武姐", "need_idcard": True},
    "韦峥": {"id": "18331345", "name": "韦峥", "need_idcard": True},
    "夏总WX": {"id": "18614842", "name": "夏总WX", "need_idcard": True},
    "夏总天海易购": {"id": "16631713", "name": "夏总天海易购", "need_idcard": True},
    "甘总-付总": {"id": "17288013", "name": "甘总-付总", "need_idcard": False},
    "乔妈": {"id": "16612947", "name": "乔妈", "need_idcard": True},
}


def check_idcard_verified(id_card_number: str, id_card_name: str) -> bool:
    """
    检查身份证是否已在认证系统认证
    
    Args:
        id_card_number: 身份证号码
        id_card_name: 身份证姓名
        
    Returns:
        bool: 是否已认证
    """
    if not ID_CARD_CHECK_AVAILABLE:
        return True  # 如果模块不可用，默认通过
    
    if not id_card_number or not id_card_name:
        return False
    
    try:
        result = batch_query_idcards(
            [], 
            id_cards=[{"id_card_number": id_card_number, "id_card_name": id_card_name}],
            use_cache=True
        )
        return result.get("found", 0) > 0
    except Exception as e:
        print(f"身份证查询失败: {e}")
        return False


def match_idcard_by_name(id_card_name: str) -> str:
    """
    通过姓名匹配本地缓存的身份证号
    
    Args:
        id_card_name: 收件人姓名
        
    Returns:
        str: 匹配的身份证号，如果没有则返回空
    """
    if not ID_CARD_CHECK_AVAILABLE or not id_card_name:
        return ""
    
    try:
        # 先确保缓存已加载
        if not cache_db._memory_cache:
            cache_db.load_to_memory()
        
        # 按姓名查找
        matches = cache_db.check_local_by_name(id_card_name)
        
        if not matches:
            return ""
        
        # 如果有多条，返回已认证的那个
        for m in matches:
            if m.get("verified"):
                return m.get("id_card_number", "")
        
        # 如果没有已认证的，返回第一个
        return matches[0].get("id_card_number", "")
        
    except Exception as e:
        print(f"姓名匹配失败: {e}")
        return ""


def push_order(order_info: dict, shop_key: str = "AUSTARWX") -> dict:
    """
    推送单个订单
    
    Args:
        order_info: 订单信息 dict，包含 receiver_name, receiver_phone, 
                   receiver_province, receiver_city, receiver_district,
                   receiver_address, items (list), pay_amount, remark
        shop_key: 店铺key，如 "武姐", "韦峥" 等
    
    Returns:
        dict: 推送结果
    """
    shop = SHOPS.get(shop_key)
    if not shop:
        return {"success": False, "message": f"未知店铺: {shop_key}"}
    
    # 获取身份证号和姓名
    id_card_number = order_info.get("id_card_number", "")
    id_card_name = order_info.get("receiver_name", "")
    
    # 如果没有提供身份证号，尝试从本地缓存匹配
    if not id_card_number and id_card_name and shop.get("need_idcard", True):
        matched_id = match_idcard_by_name(id_card_name)
        if matched_id:
            id_card_number = matched_id
            order_info["id_card_number"] = matched_id
            print(f"通过姓名匹配到身份证号: {id_card_name} -> {matched_id}")
        else:
            print(f"本地缓存未找到 {id_card_name} 的身份证记录")
    
    # 检查身份证是否已认证
    is_verified = check_idcard_verified(id_card_number, id_card_name)
    
    # 如果未认证，在备注里添加提示
    if not is_verified and shop.get("need_idcard", True):
        original_remark = order_info.get("remark", "")
        if original_remark:
            order_info["remark"] = f"{original_remark} | 未上传身份证照片"
        else:
            order_info["remark"] = "未上传身份证照片"
        print(f"警告: 收件人 {id_card_name} 身份证未认证，备注已添加提示")
    
    return push_order_to_jushuitan(order_info, shop_id=shop["id"])

def push_orders(orders: list, shop_key: str = "AUSTARWX") -> dict:
    """
    批量推送订单（最多50个）
    """
    shop = SHOPS.get(shop_key)
    if not shop:
        return {"success": False, "message": f"未知店铺: {shop_key}"}
    
    # 检查每个订单的身份证认证状态
    for order in orders:
        id_card_number = order.get("id_card_number", "")
        id_card_name = order.get("receiver_name", "")
        
        # 如果没有提供身份证号，尝试从本地缓存匹配
        if not id_card_number and id_card_name and shop.get("need_idcard", True):
            matched_id = match_idcard_by_name(id_card_name)
            if matched_id:
                id_card_number = matched_id
                order["id_card_number"] = matched_id
                print(f"通过姓名匹配到身份证号: {id_card_name} -> {matched_id}")
        
        is_verified = check_idcard_verified(id_card_number, id_card_name)
        
        # 如果未认证，在备注里添加提示
        if not is_verified and shop.get("need_idcard", True):
            original_remark = order.get("remark", "")
            if original_remark:
                order["remark"] = f"{original_remark} | 未上传身份证照片"
            else:
                order["remark"] = "未上传身份证照片"
            print(f"警告: 收件人 {id_card_name} 身份证未认证，备注已添加提示")
    
    return push_orders_batch(orders, shop_id=shop["id"])
