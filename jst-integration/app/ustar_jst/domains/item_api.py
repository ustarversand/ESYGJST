"""聚水潭 - 商品/类目域API"""

import json
from typing import Optional

from core.jst_client import JST_CONFIG, JST_TOKEN, call_jushuitan_api_dict
from core.jst_client import call_new_api


# ==================== 商品SKU查询 (旧API) ====================

def query_sku(modified_begin: str = None, modified_end: str = None,
              page_size: int = 100, sku_ids: list = None) -> dict:
    """
    查询商品SKU列表（时间范围不能超过7天）

    Args:
        modified_begin: 修改开始时间
        modified_end: 修改结束时间（与begin间隔≤7天）
        page_size: 每页数量
        sku_ids: 指定SKU ID列表（可选，与时间二选一）

    Returns:
        SKU列表
    """
    data = {"page_index": 1, "page_size": page_size}
    if modified_begin and modified_end:
        data["modified_begin"] = modified_begin
        data["modified_end"] = modified_end
    if sku_ids:
        if isinstance(sku_ids, list):
            data["sku_ids"] = ",".join(sku_ids)
        else:
            data["sku_ids"] = sku_ids

    result = call_jushuitan_api_dict("sku.query", data)
    # sku.query 返回的数据在 datas 字段中（不是 skus）
    if result.get("code") == 0 and "datas" in result:
        return {"code": 0, "skus": result["datas"], "total_count": result.get("data_count", 0),
                "page_index": result.get("page_index", 1), "has_next": result.get("has_next", False)}
    return result

# ==================== 商品/类目 API (新API) ====================

def query_category(page_size=100, page_index=1):
    """查询商品分类列表"""
    if page_size > 100:
        page_size = 100
    return call_new_api("/open/category/query",
                        {"page_size": page_size, "page_index": page_index})
def query_mall_items(sku_ids=None, page_size=20, page_index=1):
    """查询商城商品信息
    
    Args:
        sku_ids: 逗号分隔的SKU ID字符串，如 "1SFCC97001079SHY,1SFCC9700731EHY"
    """
    biz = {"page_size": page_size, "page_index": page_index}
    if sku_ids:
        biz["sku_ids"] = sku_ids
    return call_new_api("/open/mall/item/query", biz)
def query_combine_sku(sku_ids=None, page_size=20, page_index=1):
    """查询组合SKU信息"""
    biz = {"page_size": page_size, "page_index": page_index}
    if sku_ids:
        biz["sku_ids"] = sku_ids
    return call_new_api("/open/combine/sku/query", biz)
def query_sku_detail(sku_ids=None, page_size=20, page_index=1):
    """查询SKU详情（新API）"""
    biz = {"page_size": page_size, "page_index": page_index}
    if sku_ids:
        biz["sku_ids"] = sku_ids
    return call_new_api("/open/sku/query", biz)
def query_sku_map(sku_codes=None, page_size=100, page_index=1,
                  modified_begin=None, modified_end=None):
    """查询SKU映射关系
    
    时间参数用 modified_begin/modified_end，间隔不能超过7天
    """
    biz = {"page_size": page_size, "page_index": page_index}
    if sku_codes:
        biz["sku_codes"] = sku_codes
    if modified_begin:
        biz["modified_begin"] = modified_begin
    if modified_end:
        biz["modified_end"] = modified_end
    return call_new_api("/open/skumap/query", biz)
def add_or_update_category(name, c_id=None, parent_c_id=0, sort=None):
    """新增或更新商品分类"""
    data = {"name": name, "parent_c_id": parent_c_id}
    if c_id is not None:
        data["c_id"] = c_id
    if sort is not None:
        data["sort"] = sort
    return call_new_api("/open/webapi/itemapi/category/addorupdate", data)
def bind_sku_links(sku_id, sku_codes, source_shop_id=None, target_platform=None):
    """绑定SKU链接（平台SKU ↔ 系统SKU）"""
    if isinstance(sku_codes, str):
        sku_codes = [sku_codes]
    data = {"sku_id": sku_id, "sku_codes": sku_codes}
    if source_shop_id:
        data["source_shop_id"] = source_shop_id
    if target_platform:
        data["target_platform"] = target_platform
    return call_new_api("/open/webapi/itemapi/skulink/bindskulinks", data)
def save_supplier_sku(sku_id, supplier_sku_id, supplier_name=None, cost_price=None):
    """保存供应商提供的SKU信息"""
    data = {"sku_id": sku_id, "supplier_sku_id": supplier_sku_id}
    if supplier_name:
        data["supplier_name"] = supplier_name
    if cost_price:
        data["cost_price"] = cost_price
    return call_new_api("/open/webapi/itemapi/suppliersku/save", data)
def batch_upload_sku(items):
    """批量上传/更新商品SKU
    
    Args:
        items: [{"sku_id": "...", "name": "...", ...}, ...]
    """
    if not items:
        return {"code": -1, "msg": "商品列表为空"}
    return call_new_api("/open/webapi/itemapi/itemsku/itemskubatchupload",
                        {"data": items})
def upload_sku_map(items):
    """上传SKU映射关系
    
    Args:
        items: [{"sku_code": "...", "sku_id": "...", ...}, ...]
    """
    if not items:
        return {"code": -1, "msg": "映射列表为空"}
    return call_new_api("/open/jushuitan/skumap/upload", {"items": items})