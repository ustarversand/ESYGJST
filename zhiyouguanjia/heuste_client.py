"""直邮管家 — 货易达物流查询客户端

通过货易达看板 API 查询物流信息（国际/国内运单号）。
"""
import json
import time
import urllib.request
import urllib.parse
import logging
from typing import Optional

logger = logging.getLogger("heuste-client")

# 货易达看板地址（容器内通过宿主IP访问）
HEUTE_DASHBOARD_URL = "http://192.168.178.26:8890"


def _fetch_json(url: str, timeout: int = 10) -> Optional[dict]:
    """GET请求并返回JSON"""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except Exception as e:
        logger.warning(f"[货易达] 请求失败: {url} → {e}")
        return None


def _load_all_orders(month: str, max_pages: int = 25) -> list:
    """分页加载货易达所有订单（每页200条）"""
    all_orders = []
    for page in range(1, max_pages + 1):
        url = f"{HEUTE_DASHBOARD_URL}/api/orders/recent?limit=200&month={month}&page={page}"
        orders = _fetch_json(url)
        if not isinstance(orders, list) or len(orders) == 0:
            break
        all_orders.extend(orders)
        logger.info(f"[货易达] {month}月 第{page}页: {len(orders)}条")
    logger.info(f"[货易达] {month}月 共加载 {len(all_orders)} 条订单")
    return all_orders


# 轨迹缓存（内存，30分钟TTL）
_TRACK_CACHE = {}  # {tracking_no: {city, status_name, timestamp}}
_TRACK_CACHE_TTL = 1800  # 30分钟


def _get_cached_track(tracking_no: str) -> dict:
    """获取缓存的轨迹数据，过期返回空"""
    entry = _TRACK_CACHE.get(tracking_no)
    if entry and time.time() - entry.get("ts", 0) < _TRACK_CACHE_TTL:
        return entry
    return {}


def _set_cached_track(tracking_no: str, data: dict):
    """缓存轨迹数据"""
    data["ts"] = time.time()
    _TRACK_CACHE[tracking_no] = data


def _skip_track_for_state(state_code) -> bool:
    """状态已知不变 → 跳过轨迹查询"""
    return state_code in (5, -6, 0)  # 签收/已撤销/已作废 不会变


def search_orders_by_receiver(name: str, phone: str = "", month: str = "",
                               sender: str = "") -> list:
    """按收件人搜索货易达订单

    优先查本地看板（april/may月），查不到时fallback到货易达主站实时API。
    """
    results = []

    # 直接调货易达主站实时API
    try:
        from heuste_sdk import login as heuste_login
        import ssl

        token = heuste_login()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Referer": "https://www.heute-express.com/members/order-list",
            "Origin": "https://www.heute-express.com",
        }
        # 计算3个月前的日期
        from datetime import datetime, timedelta
        three_months_ago = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        
        payload = {
            "pageIndex": 1, 
            "pageSize": 128, 
            "consigneeName": name.strip(),
            "startDate": three_months_ago,  # 限制3个月内
            "endDate": today,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://www.heute-express.com/Prod/api/app/member-order/get-member-order-list",
            data=body, headers=headers, method="POST"
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for o in data.get("items", []):
            sender_name = o.get("senderName", "").strip()
            if sender and sender.strip().lower() not in sender_name.lower():
                continue
            results.append({
                "sn": o.get("sn", ""),
                "consignee": o.get("consigneeName", ""),
                "tracking_no": o.get("globalWayBillSN", ""),
                "domestic_no": o.get("tempLineSN", ""),
                "state": _state_label(o.get("state", 0)),
                "state_code": o.get("state", 0),
                "line": o.get("lineName", ""),
                "sender": sender_name,
                "weight": o.get("weight", ""),
                "created": o.get("creationTime", ""),
                "merchant_sn": o.get("merchantOrderSN", ""),
                "month": "live",
            })
    except Exception as e:
        logger.warning(f"[货易达] 主站实时查询失败: {e}")

    logger.info(f"[货易达] 搜索 {name} → 找到 {len(results)} 个匹配")

    # 批量查询轨迹信息 → 提取城市名（带缓存+跳过已知不变状态）
    if results:
        try:
            from heuste_sdk import batch_query_tracking
            need_query = []
            for r2 in results:
                tn = r2.get("tracking_no", "")
                sc = r2.get("state_code", 0)
                if not tn:
                    r2["city"] = ""
                    r2["track_status"] = ""
                    continue
                if _skip_track_for_state(sc):
                    # 签收 → 直接写"签收"，跳过API
                    r2["city"] = "签收"
                    r2["track_status"] = "已签收"
                    continue
                cached = _get_cached_track(tn)
                if cached:
                    r2["city"] = cached.get("city", "")
                    r2["track_status"] = cached.get("status_name", "")
                else:
                    need_query.append(r2)
            if need_query:
                tracking_nos = [r2.get("tracking_no", "") for r2 in need_query]
                track_map = batch_query_tracking(tracking_nos)
                for r2 in need_query:
                    tn = r2.get("tracking_no", "")
                    tc = track_map.get(tn, {})
                    if tc:
                        r2["city"] = tc.get("city", "")
                        r2["track_status"] = tc.get("status_name", "")
                        _set_cached_track(tn, tc)
                    else:
                        r2["city"] = ""
                        r2["track_status"] = ""
        except Exception as e:
            logger.warning(f"[货易达] 轨迹查询失败: {e}")

    return results


def _state_label(code) -> str:
    states = {0: "已作废", 1: "待支付", 2: "待入库", 3: "国际运输",
              4: "国内配送", 5: "签收", -6: "已撤销"}
    return states.get(code, f"未知({code})")


def search_by_merchant_sn(so_id: str) -> Optional[dict]:
    """通过商家订单号(so_id)精确匹配货易达订单（直接调主站API）"""
    try:
        from heuste_sdk import search_by_merchant_sn as _sdk_search
        result = _sdk_search(so_id)
        if result.get("found"):
            return {
                "sn": result.get("sn", ""),
                "consignee": result.get("consignee", ""),
                "tracking_no": result.get("tracking_no", ""),
                "domestic_no": result.get("domestic_no", ""),
                "state": result.get("state", ""),
                "state_code": result.get("state_code", 0),
                "line": result.get("line", ""),
                "sender": result.get("sender", ""),
                "weight": result.get("weight", ""),
                "created": result.get("created", ""),
                "merchant_sn": result.get("merchant_sn", ""),
                "month": "",
            }
    except Exception as e:
        logger.warning(f"[货易达] merchant_sn精准匹配失败: {e}")
    return None


def _normalize_order(o: dict, month: str) -> dict:
    """标准化货易达订单字段"""
    return {
        "sn": o.get("sn", ""),
        "consignee": o.get("consignee", o.get("consigneeName", "")),
        "tracking_no": o.get("tracking_no", o.get("globalWayBillSN", "")),
        "domestic_no": o.get("domestic_no", o.get("tempLineSN", "")),
        "state": o.get("state", ""),
        "state_code": o.get("state_code", 0),
        "line": o.get("line", o.get("lineName", "")),
        "sender": o.get("sender", o.get("senderName", "")),
        "weight": o.get("weight", ""),
        "created": o.get("created", o.get("creationTime", "")),
        "merchant_sn": o.get("merchant_sn", o.get("merchantOrderSN", "")),
        "month": month,
    }


def get_logistics_by_so_id(so_id: str, push_record: dict) -> dict:
    """根据推单记录查询物流信息"""
    name = push_record.get("receiver_name", "")
    phone = push_record.get("receiver_phone", "")

    orders = search_orders_by_receiver(name, phone)

    return {
        "so_id": so_id,
        "receiver_name": name,
        "receiver_phone": phone,
        "pushed_at": push_record.get("pushed_at", ""),
        "shop_name": push_record.get("shop_name", ""),
        "items": push_record.get("items", []),
        "logistics": orders,
    }
