"""直邮管家 — 推单记录管理（JSON持久化+防重推+物流追踪）"""
import json
import os
import logging
from datetime import datetime



logger = logging.getLogger("push-records")

# 内存缓存（避免每次操作读写JSON）
_records_cache = None
_records_loaded = False


def _ensure_loaded():
    global _records_cache, _records_loaded
    if _records_loaded:
        return
    _records_cache = _load_impl()
    _records_loaded = True


RECORDS_FILE = os.path.join(os.path.dirname(__file__), "data", "pushed_orders.json")


def _load_impl() -> dict:
    if not os.path.exists(RECORDS_FILE):
        return {}
    try:
        with open(RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        logger.warning(f"推单记录文件损坏，重置: {RECORDS_FILE}")
        return {}


def _save(records: dict):
    global _records_cache
    _records_cache = records
    os.makedirs(os.path.dirname(RECORDS_FILE), exist_ok=True)
    with open(RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def is_duplicate(so_id: str) -> bool:
    """检查订单是否已推送过（防重复推）"""
    _ensure_loaded()
    records = _records_cache
    return so_id in records


def save_push_record(order: dict, push_result: dict):
    """推单成功后保存记录"""
    so_id = push_result.get("so_id", "")
    if not so_id:
        return
    _ensure_loaded()
    records = _records_cache
    records[so_id] = {
        "so_id": so_id,
        "pushed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "shop_name": push_result.get("shop_name", ""),
        "o_id": push_result.get("o_id", ""),
        "receiver_name": order.get("receiver_name", ""),
        "receiver_phone": order.get("receiver_phone", ""),
        "receiver_state": order.get("receiver_state", ""),
        "receiver_city": order.get("receiver_city", ""),
        "receiver_district": order.get("receiver_district", ""),
        "receiver_address": order.get("receiver_address", ""),
        "id_card_number": order.get("id_card_number", ""),
        "buyer_message": order.get("buyer_message", ""),
        "items": order.get("items", []),
        "pay_amount": order.get("pay_amount", 0),
        "tracking_no": push_result.get("tracking_no", ""),
        "domestic_no": push_result.get("domestic_no", ""),
        "logistics_state": push_result.get("logistics_state", ""),
    }
    _save(records)
    logger.info(f"[记录] 保存推单记录: {so_id}")


def update_tracking(so_id: str, tracking_no: str = "", domestic_no: str = "", logistics_state: str = ""):
    """推单后补充物流信息"""
    _ensure_loaded()
    records = _records_cache
    if so_id in records:
        if tracking_no:
            records[so_id]["tracking_no"] = tracking_no
        if domestic_no:
            records[so_id]["domestic_no"] = domestic_no
        if logistics_state:
            records[so_id]["logistics_state"] = logistics_state
        _save(records)


def get_record(so_id: str) -> dict:
    _ensure_loaded()
    records = _records_cache
    return records.get(so_id, {})


def search_records(keyword: str = "", limit: int = 20) -> list:
    _ensure_loaded()
    records = _records_cache
    result = []
    keyword = keyword.strip().lower()
    for so_id, rec in records.items():
        if keyword:
            if (keyword in so_id.lower() or
                keyword in rec.get("receiver_name", "").lower() or
                keyword in rec.get("receiver_phone", "") or
                keyword in rec.get("receiver_address", "").lower()):
                result.append(rec)
        else:
            result.append(rec)
    result.sort(key=lambda x: x.get("pushed_at", ""), reverse=True)
    return result[:limit]


def get_all_records(limit: int = 50) -> list:
    return search_records("", limit)


def update_record(so_id: str, record: dict):
    _ensure_loaded()
    records = _records_cache
    if so_id in records:
        records[so_id].update(record)
        _save(records)
        logger.info(f"[记录] 更新推单记录: {so_id}")
