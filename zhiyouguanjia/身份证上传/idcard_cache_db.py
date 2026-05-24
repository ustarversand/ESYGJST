"""
身份证缓存数据库模块
操作本地 SQLite 数据库缓存身份证查询结果
惰性初始化：首次调用时加载，不污染启动
"""
import sqlite3
import os
import logging

logger = logging.getLogger("idcard-cache")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "idcard_cache.db")

# 内存缓存
_memory_cache = {}
_query_count = {}
_initialized = False


def get_connection():
    return sqlite3.connect(DB_PATH)


def _ensure_loaded():
    """惰性初始化：首次调用时建表+加载数据"""
    global _initialized
    if _initialized:
        return
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS idcard_cache (
            id_card_number TEXT PRIMARY KEY,
            id_card_name TEXT,
            is_authenticated INTEGER DEFAULT 0,
            checked_at TEXT
        )
    """)
    conn.commit()
    cursor.execute("SELECT id_card_number, id_card_name, is_authenticated FROM idcard_cache")
    global _memory_cache, _query_count
    _memory_cache = {}
    _query_count = {}
    for row in cursor.fetchall():
        num, name, verified = row
        _memory_cache[num] = {
            "id_card_number": num,
            "id_card_name": name,
            "verified": bool(verified)
        }
        _query_count[num] = 0
    conn.close()
    _initialized = True
    logger.info(f"已加载 {len(_memory_cache)} 条缓存到内存")


def get_name_by_number(id_card_number: str) -> str:
    """快捷查询：通过身份证号获取持证人姓名"""
    _ensure_loaded()
    cached = _memory_cache.get(id_card_number)
    if cached:
        return cached.get("id_card_name")
    return None


def check_local(id_card_name: str, id_card_number: str) -> dict:
    """检查本地缓存（通过姓名+身份证号）"""
    _ensure_loaded()
    if id_card_number in _memory_cache:
        cached = _memory_cache[id_card_number]
        if cached["id_card_name"] == id_card_name:
            return cached
    return None


def check_local_by_number(id_card_number: str) -> dict:
    """检查本地缓存（仅通过身份证号）"""
    _ensure_loaded()
    return _memory_cache.get(id_card_number)


def check_local_by_name(id_card_name: str) -> list:
    """检查本地缓存（仅通过姓名），返回匹配的列表"""
    _ensure_loaded()
    results = []
    for num, data in _memory_cache.items():
        if data.get("id_card_name") == id_card_name and num:
            results.append(data)
    return results


def save_to_local(id_card_name: str, id_card_number: str, verified: bool):
    """保存到本地缓存（同时写数据库和内存）"""
    _ensure_loaded()
    _memory_cache[id_card_number] = {
        "id_card_number": id_card_number,
        "id_card_name": id_card_name,
        "verified": verified
    }
    _query_count[id_card_number] = 0
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO idcard_cache (id_card_number, id_card_name, is_authenticated, checked_at)
        VALUES (?, ?, ?, datetime('now'))
    """, (id_card_number, id_card_name, 1 if verified else 0))
    conn.commit()
    conn.close()


def increment_query_count(id_card_number: str):
    """增加查询计数"""
    if id_card_number in _query_count:
        _query_count[id_card_number] += 1


def get_query_count(id_card_number: str) -> int:
    """获取查询计数"""
    return _query_count.get(id_card_number, 0)
