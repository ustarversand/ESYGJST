"""聚水潭 - 售后域API"""

import json

from core.jst_client import call_new_api


# ==================== 售后API ====================

def aftersale_noinfo_upload(shop_id, so_id, o_id, items):
    """上传售后单（无信息），返回as_id"""
    return call_new_api("/open/aftersale/noinfo/upload",
                        {"data": [{"shop_id": shop_id, "so_id": so_id,
                                    "o_id": o_id, "items": items}]})
def aftersale_upload(as_id, shop_id, so_id, o_id, type_name="普通退货",
                     reason="", items=None, **kw):
    """创建售后单"""
    import time as _t
    rec = {"as_id": as_id, "shop_id": shop_id, "so_id": so_id, "o_id": o_id,
           "type": type_name, "reason": reason,
           "outer_as_id": kw.pop("outer_as_id", f"AS{int(_t.time())}")}
    rec.update(kw)
    if items: rec["items"] = items
    return call_new_api("/open/aftersale/upload", [rec])
def aftersale_confirm(as_id, shop_id=None):
    return call_new_api("/open/webapi/aftersaleapi/open/confirm",
                        {"as_id": as_id} | ({"shop_id": shop_id} if shop_id else {}))
def aftersale_unconfirm(as_id, shop_id=None):
    return call_new_api("/open/webapi/aftersaleapi/open/unconfirm",
                        {"as_id": as_id} | ({"shop_id": shop_id} if shop_id else {}))
def aftersale_cancel(as_id, shop_id=None):
    return call_new_api("/open/webapi/aftersaleapi/open/cancel",
                        {"as_id": as_id} | ({"shop_id": shop_id} if shop_id else {}))
def aftersale_confirm_goods(as_id, shop_id=None, uid=None):
    d = {"as_id": as_id}
    if shop_id: d["shop_id"] = shop_id
    if uid: d["uid"] = uid
    return call_new_api("/open/webapi/aftersaleapi/confirmgoods", d)
def aftersale_set_labels(as_id, labels, shop_id=None):
    d = {"as_id": as_id, "labels": labels}
    if shop_id: d["shop_id"] = shop_id
    return call_new_api("/open/webapi/aftersaleapi/setaslabels", d)