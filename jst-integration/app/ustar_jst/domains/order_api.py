"""聚水潭 - 订单域API"""

import time
import json
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from core.jst_client import JST_CONFIG, JST_TOKEN, DEFAULT_BUYER_ID, DEFAULT_SHOP_ID
from core.jst_client import generate_sign, get_timestamp, call_jushuitan_api_dict, call_jushuitan_api


# ==================== 订单查询 ====================

def query_order(so_id: str = None, o_id: str = None, start_time: str = None, end_time: str = None) -> dict:
    """
    查询单个订单详情（包括快递单号）

    Args:
        so_id: 线上订单号（平台订单号）
        o_id: 聚水潭内部订单号
        start_time: 开始时间 (格式: 2026-02-01 00:00:00)
        end_time: 结束时间

    Returns:
        订单详情，包含 logistics_company(快递公司) 和 l_id(快递单号)
    """
    ts = get_timestamp()
    sys_params = {"token": JST_TOKEN, "ts": ts}
    sign = generate_sign("orders.single.query", sys_params)

    api_url = JST_CONFIG["api_url_legacy"]
    url = f"{api_url}?method=orders.single.query&partnerid={JST_CONFIG['app_key']}&token={JST_TOKEN}&ts={ts}&sign={sign}"

    # 默认查询最近30天
    if not start_time:
        start_time = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
    if not end_time:
        end_time = datetime.now().strftime("%Y-%m-%d 23:59:59")

    # 查询参数
    query_params = {
        "start_time": start_time,
        "end_time": end_time,
        "page_index": 1,
        "page_size": 50
    }
    if so_id:
        query_params["so_ids"] = [so_id]
    if o_id:
        query_params["o_id"] = o_id

    headers = {"Content-Type": "application/json; charset=utf-8"}
    json_str = json.dumps(query_params, ensure_ascii=False)

    try:
        response = requests.post(url, data=json_str.encode('utf-8'), headers=headers, timeout=30)
        return response.json()
    except Exception as e:
        return {"code": -1, "msg": str(e)}
def query_orders_by_date(shop_id: int, start_time: str, end_time: str, page_size: int = 100) -> dict:
    """
    按日期和店铺查询订单

    Args:
        shop_id: 店铺ID
        start_time: 开始时间
        end_time: 结束时间
        page_size: 每页数量

    Returns:
        订单列表
    """
    ts = get_timestamp()
    sys_params = {"token": JST_TOKEN, "ts": ts}
    sign = generate_sign("orders.single.query", sys_params)

    api_url = JST_CONFIG["api_url_legacy"]
    url = f"{api_url}?method=orders.single.query&partnerid={JST_CONFIG['app_key']}&token={JST_TOKEN}&ts={ts}&sign={sign}"

    # 使用 modified_begin/modified_end 参数（不是 start_time/end_time）
    query_params = {
        "modified_begin": start_time,
        "modified_end": end_time,
        "shop_id": shop_id,
        "page_index": 1,
        "page_size": page_size
    }

    headers = {"Content-Type": "application/json; charset=utf-8"}
    json_str = json.dumps(query_params, ensure_ascii=False)

    try:
        response = requests.post(url, data=json_str.encode('utf-8'), headers=headers, timeout=30)
        return response.json()
    except Exception as e:
        return {"code": -1, "msg": str(e)}
def get_express_number(so_id: str) -> dict:
    """
    获取订单的快递单号

    Args:
        so_id: 订单号

    Returns:
        {"express_company": "快递公司", "express_no": "快递单号"} 或错误信息
    """
    result = query_order(so_id=so_id)
    if result.get("code") == 0:
        order = result.get("order", {})
        return {
            "express_company": order.get("logistics_company", ""),
            "express_no": order.get("l_id", ""),
            "cb_l_id": order.get("cb_l_id", ""),  # 国际单号
            "status": order.get("status", ""),
            "receiver_name": order.get("receiver_name", "")
        }
    return result
def query_orders_by_time(modified_begin: str = None, modified_end: str = None,
                         shop_id: int = None, status: str = None,
                         page_index: int = 1, page_size: int = 100) -> dict:
    """
    按时间范围查询订单（增强版，支持多种过滤条件）

    Args:
        modified_begin: 修改开始时间（默认最近7天）
        modified_end: 修改结束时间
        shop_id: 店铺ID（可选）
        status: 订单状态（可选，如 WaitConfirm, Confirmed, Cancelled 等）
        page_index: 页码
        page_size: 每页数量（最大100）

    Returns:
        订单列表 + 分页信息
    """
    if not modified_end:
        modified_end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not modified_begin:
        modified_begin = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")

    data = {
        "page_index": page_index,
        "page_size": page_size,
        "modified_begin": modified_begin,
        "modified_end": modified_end
    }
    if shop_id:
        data["shop_id"] = shop_id
    if status:
        data["status"] = status

    return call_jushuitan_api_dict("orders.single.query", data)
def query_orders_paginated(modified_begin: str, modified_end: str,
                           shop_id: int = None, status: str = None,
                           max_pages: int = 10, page_size: int = 100) -> dict:
    """
    分页查询所有订单（自动翻页）

    Args:
        modified_begin: 开始时间
        modified_end: 结束时间（与begin间隔≤7天）
        shop_id: 店铺ID
        status: 订单状态
        max_pages: 最多翻页数
        page_size: 每页数量

    Returns:
        所有订单列表
    """
    all_orders = []
    page = 1
    has_next = True

    while has_next and page <= max_pages:
        result = query_orders_by_time(
            modified_begin=modified_begin,
            modified_end=modified_end,
            shop_id=shop_id,
            status=status,
            page_index=page,
            page_size=page_size
        )
        if result.get("code") != 0:
            return {"code": result.get("code", -1), "msg": result.get("msg", "查询失败"),
                    "orders": all_orders}

        orders = result.get("orders", [])
        all_orders.extend(orders)

        has_next = result.get("has_next", False) or len(orders) >= page_size
        page += 1

    return {"code": 0, "orders": all_orders, "total_count": len(all_orders),
            "pages_fetched": page - 1}
# ==================== 订单取消 ====================

def cancel_order(shop_id: int, so_id: str = None, o_id: str = None,
                 remark: str = "客户取消") -> dict:
    """
    取消订单

    Args:
        shop_id: 店铺ID
        so_id: 外部订单号（so_id 和 o_id 二选一）
        o_id: 聚水潭内部订单号
        remark: 取消原因

    Returns:
        取消结果
    """
    items = [{"shop_id": shop_id, "remark": remark}]
    if so_id:
        items[0]["so_id"] = so_id
    if o_id:
        items[0]["o_id"] = o_id

    return call_jushuitan_api("jushuitan.orders.cancel", items)
# ==================== 订单推送 ====================

def push_order_to_jushuitan(order: dict, shop_id: str) -> dict:
    """
    推送单个订单到聚水潭ERP

    Args:
        order: 订单数据，包含以下字段：
            - order_id: 订单号
            - receiver_name: 收件人姓名
            - receiver_phone: 收件人电话
            - receiver_province: 省
            - receiver_city: 市
            - receiver_district: 区
            - receiver_address: 详细地址
            - items: 商品列表 [{sku_id, name, qty, price}]
            - pay_amount: 应付金额
            - freight: 运费
            - remark: 备注
        shop_id: 店铺编号

    Returns:
        推送结果
    """
    # 构建聚水潭订单格式
    jst_order = {
        "shop_id": shop_id,
        "so_id": order.get("order_id", ""),
        "order_date": order.get("order_date", time.strftime("%Y-%m-%d %H:%M:%S")),
        "shop_status": "WAIT_SELLER_SEND_GOODS",  # 等待卖家发货
        "shop_buyer_id": order.get("buyer_nick", "微信接单"),  # 买家账号
        "receiver_name": order.get("receiver_name", ""),
        "receiver_mobile": order.get("receiver_phone", ""),
        "receiver_state": order.get("receiver_province", ""),
        "receiver_city": order.get("receiver_city", ""),
        "receiver_district": order.get("receiver_district", ""),
        "receiver_address": order.get("receiver_address", ""),
        "pay_amount": order.get("pay_amount", 0),
        "freight": order.get("freight", 0),
        "buyer_message": order.get("remark", ""),
        "items": []
    }

    # 转换商品列表
    for item in order.get("items", []):
        jst_item = {
            "sku_id": item.get("sku_id", ""),
            "name": item.get("name", ""),
            "qty": item.get("qty", 1),
            "price": item.get("price", 0),
            "amount": item.get("qty", 1) * item.get("price", 0)
        }
        jst_order["items"].append(jst_item)

    # 添加支付信息（对象格式，不是数组）
    jst_order["pay"] = {
        "payment": "其他",
        "pay_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "amount": order.get("pay_amount", 0),
        "outer_pay_id": order.get("order_id", "")
    }

    # 调用API - 直接传订单数组
    result = call_jushuitan_api("orders.upload", [jst_order])

    return result
def push_orders_batch(orders: List[dict], shop_id: str) -> dict:
    """
    批量推送订单到聚水潭ERP（最多50个）

    Args:
        orders: 订单列表
        shop_id: 店铺编号

    Returns:
        推送结果
    """
    if len(orders) > 50:
        return {"code": -1, "msg": "单次最多推送50个订单"}

    jst_orders = []
    for order in orders:
        jst_order = {
            "shop_id": shop_id,
            "so_id": order.get("order_id", ""),
            "order_date": order.get("order_date", time.strftime("%Y-%m-%d %H:%M:%S")),
            "shop_status": "WAIT_SELLER_SEND_GOODS",
            "receiver_name": order.get("receiver_name", ""),
            "receiver_mobile": order.get("receiver_phone", ""),
            "receiver_state": order.get("receiver_province", ""),
            "receiver_city": order.get("receiver_city", ""),
            "receiver_district": order.get("receiver_district", ""),
            "receiver_address": order.get("receiver_address", ""),
            "pay_amount": order.get("pay_amount", 0),
            "freight": order.get("freight", 0),
            "buyer_message": order.get("remark", ""),
            "items": [],
            "pay": [{
                "payment": "其他",
                "pay_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                "amount": order.get("pay_amount", 0),
                "outer_pay_id": order.get("order_id", "")
            }]
        }

        for item in order.get("items", []):
            jst_item = {
                "sku_id": item.get("sku_id", ""),
                "name": item.get("name", ""),
                "qty": item.get("qty", 1),
                "price": item.get("price", 0),
                "amount": item.get("qty", 1) * item.get("price", 0)
            }
            jst_order["items"].append(jst_item)

        jst_orders.append(jst_order)

    # 调用API - 直接传订单数组
    result = call_jushuitan_api("orders.upload", jst_orders)

    return result
# ==================== 订单格式转换 ====================

def convert_wechat_order_to_jst(wechat_order: dict) -> dict:
    """
    将微信订单格式转换为聚水潭格式

    Args:
        wechat_order: 微信订单数据（按照订单模版格式）
            - 订单号, 收件人, 身份证号, 省, 市, 区,
            - 收件人地址街道, 电话号码, 商品名称, 数量, 备注, 商品简称

    Returns:
        聚水潭订单格式
    """
    return {
        "order_id": wechat_order.get("订单号", ""),
        "receiver_name": wechat_order.get("收件人", ""),
        "receiver_phone": wechat_order.get("电话号码", ""),
        "receiver_province": wechat_order.get("省", ""),
        "receiver_city": wechat_order.get("市", ""),
        "receiver_district": wechat_order.get("区", ""),
        "receiver_address": wechat_order.get("收件人地址街道", ""),
        "remark": wechat_order.get("备注", ""),
        "items": [{
            "sku_id": wechat_order.get("商品简称", ""),
            "name": wechat_order.get("商品名称", ""),
            "qty": int(wechat_order.get("数量", 1)),
            "price": 0  # 价格需要从商品库获取
        }],
        "pay_amount": 0,  # 需要计算
        "freight": 0
    }
def convert_template2_order(order_data: dict, buyer_id: str = None) -> dict:
    """
    将模版2格式订单转换为聚水潭API格式

    模版2字段（15列）:
    店铺ID, 订单号, 收件人, 身份证号, 省, 市, 区, 收件人地址街道,
    电话号码, 商品名称, 商品编码, 数量, 价格, 备注, 商品简称

    Args:
        order_data: 模版2订单数据字典
        buyer_id: 买家账号（如果为None则使用默认值"微信接单"）

    Returns:
        聚水潭订单格式
    """
    # 清理字段中可能的制表符
    def clean_value(val):
        if isinstance(val, str):
            return val.strip().replace('\t', '')
        return val

    shop_id = int(order_data.get("店铺ID", 0) or 0)
    # 如果没有提供店铺ID，使用默认店铺
    if shop_id == 0:
        shop_id = DEFAULT_SHOP_ID
    order_id = clean_value(order_data.get("订单号", ""))
    price = float(order_data.get("价格", 0) or 0)
    qty_str = clean_value(str(order_data.get("数量", 1) or 1))
    qty = int(qty_str) if qty_str.isdigit() else 1

    # 使用传入的buyer_id或默认值
    if buyer_id is None:
        buyer_id = DEFAULT_BUYER_ID

    # 获取商品编码，优先使用商品编码字段，否则用商品简称
    sku_id = clean_value(order_data.get("商品编码", "")) or clean_value(order_data.get("商品简称", ""))
    product_name = clean_value(order_data.get("商品名称", "")) or clean_value(order_data.get("商品简称", ""))

    jst_order = {
        "shop_id": shop_id,
        "so_id": order_id,
        "order_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "shop_status": "WAIT_SELLER_SEND_GOODS",
        "shop_buyer_id": buyer_id,
        "receiver_state": clean_value(order_data.get("省", "")),
        "receiver_city": clean_value(order_data.get("市", "")),
        "receiver_district": clean_value(order_data.get("区", "")),
        "receiver_address": clean_value(order_data.get("收件人地址街道", "")),
        "receiver_name": clean_value(order_data.get("收件人", "")),
        "receiver_mobile": clean_value(order_data.get("电话号码", "")),
        "receiver_country": "CN",
        "pay_amount": price,
        "freight": 0,
        "buyer_message": clean_value(order_data.get("备注", "")),
        "items": [
            {
                "sku_id": sku_id,
                "shop_sku_id": sku_id,
                "amount": price,
                "base_price": price / qty if qty > 0 else price,
                "qty": qty,
                "name": product_name,
                "outer_oi_id": f"{order_id}_001",
            }
        ],
        "pay": {
            "outer_pay_id": f"PAY{order_id}",
            "pay_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "payment": "线下",
            "amount": price,
        }
    }

    # 如果有身份证信息，添加card字段
    card_number = clean_value(order_data.get("身份证号", ""))
    if card_number:
        jst_order["card"] = {
            "name": clean_value(order_data.get("收件人", "")),
            "id_no": card_number,
            "outer_oi_id": f"{order_id}_card"
        }

    return jst_order
def push_template2_orders(orders_data: List[dict], buyer_id: str = None) -> dict:
    """
    推送模版2格式的订单列表到聚水潭

    Args:
        orders_data: 模版2格式的订单列表
        buyer_id: 买家账号（如果为None则使用"微信接单"）

    Returns:
        推送结果
    """
    jst_orders = []
    for order_data in orders_data:
        jst_order = convert_template2_order(order_data, buyer_id)
        jst_orders.append(jst_order)

    return call_jushuitan_api("orders.upload", jst_orders)
# ==================== 订单备注更新 ====================

def update_order_remark(o_id: str, remark: str) -> dict:
    """
    修改订单卖家备注

    Args:
        o_id: 聚水潭内部订单号
        remark: 新的备注内容

    Returns:
        更新结果
    """
    ts = get_timestamp()
    sys_params = {"token": JST_TOKEN, "ts": ts}
    sign = generate_sign("jushuitan.order.remark.upload", sys_params)

    api_url = JST_CONFIG["api_url_legacy"]
    url = f"{api_url}?method=jushuitan.order.remark.upload&partnerid={JST_CONFIG['app_key']}&token={JST_TOKEN}&ts={ts}&sign={sign}"

    # 构造请求数据
    data = {"o_id": o_id, "remark": remark}

    headers = {"Content-Type": "application/json; charset=utf-8"}
    json_str = json.dumps(data, ensure_ascii=False)

    try:
        response = requests.post(url, data=json_str.encode('utf-8'), headers=headers, timeout=30)
        return response.json()
    except Exception as e:
        return {"code": -1, "msg": str(e)}
# ==================== 订单地址更新 ====================

def update_order_address(o_id: str, **kwargs) -> dict:
    """
    修改订单收货地址信息

    聚水潭API: jushuitan.orderaddress.update
    仅支持状态为"等待审核"、"异常"、"等待买家支付"的订单

    Args:
        o_id: 聚水潭内部订单号（必填）
        receiver_name: 收件人姓名
        receiver_phone: 收件人电话
        receiver_mobile: 收件人手机号
        receiver_country: 国家
        receiver_province: 省
        receiver_city: 市
        receiver_district: 区/县
        receiver_address: 详细地址
        receiver_zip: 邮编

    Returns:
        API返回结果
    """
    ts = get_timestamp()
    sys_params = {"token": JST_TOKEN, "ts": ts}
    sign = generate_sign("jushuitan.orderaddress.update", sys_params)

    api_url = JST_CONFIG["api_url_legacy"]
    url = f"{api_url}?method=jushuitan.orderaddress.update&partnerid={JST_CONFIG['app_key']}&token={JST_TOKEN}&ts={ts}&sign={sign}"

    # 构造请求数据（o_id 必填，其余从 kwargs 取）
    data = {"o_id": o_id}
    valid_fields = ["receiver_name", "receiver_phone", "receiver_mobile",
                    "receiver_country", "receiver_province", "receiver_city",
                    "receiver_district", "receiver_address", "receiver_zip"]
    for field in valid_fields:
        if field in kwargs and kwargs[field] is not None:
            data[field] = kwargs[field]

    headers = {"Content-Type": "application/json; charset=utf-8"}
    json_str = json.dumps(data, ensure_ascii=False)

    try:
        response = requests.post(url, data=json_str.encode('utf-8'), headers=headers, timeout=30)
        return response.json()
    except Exception as e:
        return {"code": -1, "msg": str(e)}
# ==================== 快递登记 ====================

def register_express(lc_id: str, o_id: str, l_id: str) -> dict:
    """
    快递登记（用于待发货订单）

    Args:
        lc_id: 快递公司编码（如 SF, JD）
        o_id: 订单号
        l_id: 快递单号

    Returns:
        登记结果
    """
    ts = get_timestamp()
    sys_params = {"token": JST_TOKEN, "ts": ts}
    sign = generate_sign("express.register.upload", sys_params)

    api_url = JST_CONFIG["api_url_legacy"]
    url = f"{api_url}?method=express.register.upload&partnerid={JST_CONFIG['app_key']}&token={JST_TOKEN}&ts={ts}&sign={sign}"

    data = {
        "lc_id": lc_id,
        "items": [{"o_id": o_id, "l_id": l_id}]
    }

    headers = {"Content-Type": "application/json; charset=utf-8"}
    json_str = json.dumps(data, ensure_ascii=False)

    try:
        response = requests.post(url, data=json_str.encode('utf-8'), headers=headers, timeout=30)
        return response.json()
    except Exception as e:
        return {"code": -1, "msg": str(e)}