"""聚水潭 - 查询/统计API"""

import json
from datetime import datetime, timedelta

from core.jst_client import JST_CONFIG, JST_TOKEN, DEFAULT_SHOP_ID
from core.jst_client import generate_sign, get_timestamp, call_jushuitan_api_dict


from domains.order_api import query_orders_paginated


# ==================== 订单统计 ====================

def query_order_stats(modified_begin: str = None, modified_end: str = None,
                      shop_id: int = None) -> dict:
    """
    查询订单统计信息（总数、金额、商品分布）

    Args:
        modified_begin: 开始时间
        modified_end: 结束时间
        shop_id: 店铺ID

    Returns:
        统计信息
    """
    result = query_orders_paginated(modified_begin, modified_end, shop_id, max_pages=5)
    if result.get("code") != 0:
        return result

    orders = result.get("orders", [])
    total_amount = sum(float(o.get("pay_amount", 0) or 0) for o in orders)
    total_freight = sum(float(o.get("freight", 0) or 0) for o in orders)
    status_counts = {}
    shop_counts = {}
    product_counts = {}

    for o in orders:
        status = o.get("status", "未知")
        status_counts[status] = status_counts.get(status, 0) + 1

        shop_name = o.get("shop_name", f"店铺{o.get('shop_id','')}")
        shop_counts[shop_name] = shop_counts.get(shop_name, 0) + 1

        for item in o.get("items", []):
            sku = item.get("sku_id", "")
            name = item.get("name", sku)
            qty = int(item.get("qty", 0) or 0)
            product_counts[name] = product_counts.get(name, 0) + qty

    top_products = sorted(product_counts.items(), key=lambda x: x[1], reverse=True)[:15]

    return {
        "code": 0,
        "total_orders": len(orders),
        "total_amount": round(total_amount, 2),
        "total_freight": round(total_freight, 2),
        "status_distribution": status_counts,
        "shop_distribution": shop_counts,
        "top_products": [{"name": n, "qty": q} for n, q in top_products]
    }
# ==================== 店铺查询 ====================

def query_shops(page_size: int = 100) -> dict:
    """
    获取店铺列表（带正确datas字段解析）

    Returns:
        店铺列表，包含 shop_id, shop_name, shop_site, platform
    """
    result = call_jushuitan_api_dict("shops.query", {
        "page_index": 1,
        "page_size": page_size
    })
    if result.get("code") == 0 and "datas" in result:
        return {"code": 0, "shops": result["datas"]}
    return result

# ==================== 库存查询 ====================

def query_inventory(sku_ids: list = None, page_size: int = 100) -> dict:
    """
    查询商品库存

    Args:
        sku_ids: SKU ID列表或逗号分隔字符串。
                 注意：传了 sku_ids 就不要传时间，否则参数冲突
        page_size: 每页数量

    Returns:
        库存列表，每个包含: sku_id, name, qty(总库存),
        order_lock(订单占用), pick_lock(拣货锁定),
        virtual_qty(虚拟库存), purchase_qty(采购在途)
    """
    data = {"page_index": 1, "page_size": page_size}
    if sku_ids:
        if isinstance(sku_ids, list):
            data["sku_ids"] = ",".join(sku_ids)
        else:
            data["sku_ids"] = sku_ids

    result = call_jushuitan_api_dict("inventory.query", data)
    if result.get("code") == 0:
        return {
            "code": 0,
            "inventory": result.get("inventorys", []),
            "total_count": result.get("data_count", 0),
            "has_next": result.get("has_next", False)
        }
    return result
def query_wms_inventory(sku_ids: list = None, page_size: int = 200) -> dict:
    """
    查询WMS仓库物理库存（与ERP库存不同，此为仓库实物库存）

    Args:
        sku_ids: SKU ID列表或逗号分隔字符串
        page_size: 每页数量

    Returns:
        库存列表，每个包含: sku_id, qty(实物库存), lock_qty(锁定),
        wms_co_id(仓库ID)
    """
    data = {"page_index": 1, "page_size": page_size}
    if sku_ids:
        if isinstance(sku_ids, list):
            data["sku_ids"] = ",".join(sku_ids)
        else:
            data["sku_ids"] = sku_ids

    result = call_jushuitan_api_dict("jushuitan.wms.inventory.query", data)
    if result.get("code") == 0:
        return {
            "code": 0,
            "inventory": result.get("datas", []),
            "total_count": result.get("data_count", 0),
            "has_next": result.get("has_next", False)
        }
    return result

# ==================== 店铺列表查询 ====================

def get_shop_list() -> dict:
    """
    获取店铺列表

    Returns:
        店铺列表
    """
    ts = get_timestamp()
    sys_params = {"token": JST_TOKEN, "ts": ts}
    sign = generate_sign("shops.query", sys_params)

    api_url = JST_CONFIG["api_url_legacy"]
    url = f"{api_url}?method=shops.query&partnerid={JST_CONFIG['app_key']}&token={JST_TOKEN}&ts={ts}&sign={sign}"

    data = {"page_index": 1, "page_size": 100}

    headers = {"Content-Type": "application/json; charset=utf-8"}
    json_str = json.dumps(data, ensure_ascii=False)

    try:
        response = requests.post(url, data=json_str.encode('utf-8'), headers=headers, timeout=30)
        return response.json()
    except Exception as e:
        return {"code": -1, "msg": str(e)}