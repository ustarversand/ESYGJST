#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聚水潭订单同步脚本
从聚水潭拉取订单+运单号，存到本地SQLite
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# 导入聚水潭API
from domains.order_api import query_orders_by_date

# 配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "orders.db")
LOG_PATH = os.path.join(BASE_DIR, "order_sync.log")

# 店铺配置 (从jst_push.py)
SHOPS = {
    "AUSTARWX": {"id": 18442196, "name": "AUSTARWX"},
    "沐浴阳光PDD": {"id": 18020520, "name": "沐浴阳光PDD"},
    "武姐": {"id": 18283794, "name": "武姐"},
    "韦峥": {"id": 18331345, "name": "韦峥"},
    "夏总WX": {"id": 18614842, "name": "夏总WX"},
    "夏总天海易购": {"id": 16631713, "name": "夏总天海易购"},
    "甘总-付总": {"id": 17288013, "name": "甘总-付总"},
    "乔妈": {"id": 16612947, "name": "乔妈"},
}

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def init_db():
    """初始化订单数据库"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            o_id TEXT UNIQUE,           -- 聚水潭订单号
            so_id TEXT,                 -- 平台订单号
            shop_id INTEGER,             -- 店铺ID
            shop_name TEXT,            -- 店铺名称
            receiver_name TEXT,        -- 收件人
            receiver_phone TEXT,      -- 电话
            receiver_province TEXT, -- 省
            receiver_city TEXT,     -- 市
            receiver_district TEXT, -- 区
            receiver_address TEXT,   -- 地址
            logistics_company TEXT, -- 快递公司
            tracking_no TEXT,       -- 运单号
            status TEXT,            -- 订单状态
            pay_amount REAL,         -- 支付金额
            created_time TEXT,      -- 创建时间
            modified_time TEXT,      -- 修改时间
            synced_at TEXT          -- 同步时间
        )
    """)
    
    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_o_id ON orders(o_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracking_no ON orders(tracking_no)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_so_id ON orders(so_id)")
    
    conn.commit()
    return conn


def parse_order(order: dict, shop_name: str) -> dict:
    """解析聚水潭订单"""
    # 提取字段
    receiver = order.get("receiver", {})
    
    return {
        "o_id": order.get("o_id", ""),
        "so_id": order.get("so_id", ""),
        "shop_id": order.get("shop_id", ""),
        "shop_name": shop_name,
        "receiver_name": receiver.get("name", ""),
        "receiver_phone": receiver.get("phone", ""),
        "receiver_province": receiver.get("province", ""),
        "receiver_city": receiver.get("city", ""),
        "receiver_district": receiver.get("district", ""),
        "receiver_address": receiver.get("address", ""),
        "logistics_company": order.get("logistics_company", ""),
        "tracking_no": order.get("l_id", ""),  # 快递单号
        "status": order.get("status", ""),
        "pay_amount": order.get("pay_amount", 0),
        "created_time": order.get("created", ""),
        "modified_time": order.get("modified", ""),
    }


def sync_orders_by_shop(shop_id: int, shop_name: str, conn: sqlite3.Connection, 
                       start_time: str = None, end_time: str = None) -> int:
    """同步单个店铺的订单"""
    
    # 默认查询最近3天
    if not end_time:
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not start_time:
        start_time = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    
    logger.info(f"📥 同步店铺 {shop_name}({shop_id}) {start_time} ~ {end_time}")
    
    try:
        result = query_orders_by_date(shop_id, start_time, end_time, page_size=100)
        
        if result.get("code") != 0:
            logger.warning(f"⚠️ 店铺 {shop_name} 查询失败: {result.get('msg')}")
            return 0
        
        orders = result.get("orders", [])
        if not orders:
            logger.info(f"  店铺 {shop_name} 无新订单")
            return 0
        
        logger.info(f"  店铺 {shop_name} 获取到 {len(orders)} 条订单")
        
        # 写入数据库
        cursor = conn.cursor()
        synced = 0
        
        for order in orders:
            order_data = parse_order(order, shop_name)
            order_data["synced_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # upsert
            cursor.execute("""
                INSERT OR REPLACE INTO orders (
                    o_id, so_id, shop_id, shop_name,
                    receiver_name, receiver_phone,
                    receiver_province, receiver_city, receiver_district, receiver_address,
                    logistics_company, tracking_no,
                    status, pay_amount, created_time, modified_time, synced_at
                ) VALUES (
                    :o_id, :so_id, :shop_id, :shop_name,
                    :receiver_name, :receiver_phone,
                    :receiver_province, :receiver_city, :receiver_district, :receiver_address,
                    :logistics_company, :tracking_no,
                    :status, :pay_amount, :created_time, :modified_time, :synced_at
                )
            """, order_data)
            synced += 1
        
        conn.commit()
        logger.info(f"  ✅ 店铺 {shop_name} 同步 {synced} 条订单")
        return synced
        
    except Exception as e:
        logger.error(f"❌ 店铺 {shop_name} 同步失败: {e}")
        return 0


def sync_all_orders(days: int = 3) -> dict:
    """同步所有店铺的订单"""
    
    conn = init_db()
    
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    
    total = {"shops": 0, "orders": 0}
    
    for shop_key, shop_info in SHOPS.items():
        synced = sync_orders_by_shop(
            shop_info["id"], 
            shop_info["name"],
            conn,
            start_time,
            end_time
        )
        if synced > 0:
            total["shops"] += 1
            total["orders"] += synced
    
    conn.close()
    
    logger.info(f"📊 总计: {total['shops']} 个店铺, {total['orders']} 条订单")
    return total


def query_local_orders(shop_id: int = None, days: int = 7, has_tracking: bool = True) -> List[dict]:
    """
    查询本地订单
    
    Args:
        shop_id: 店铺ID (可选)
        days: 最近几天
        has_tracking: 是否只查有运单号的
    
    Returns:
        订单列表
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 构建查询
    sql = "SELECT * FROM orders WHERE 1=1"
    params = []
    
    if shop_id:
        sql += " AND shop_id = ?"
        params.append(shop_id)
    
    if days:
        sql += " AND modified_time >= ?"
        params.append((datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"))
    
    if has_tracking:
        sql += " AND tracking_no IS NOT NULL AND tracking_no != ''"
    
    sql += " ORDER BY modified_time DESC"
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def show_recent_orders(days: int = 3, limit: int = 20):
    """显示最近的订单"""
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT o_id, shop_name, receiver_name, tracking_no, 
               logistics_company, status, modified_time
        FROM orders 
        WHERE modified_time >= ?
        ORDER BY modified_time DESC
        LIMIT ?
    """, ((datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"), limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        print("暂无订单")
        return
    
    print(f"\n📦 最近 {days} 天订单 (前 {limit} 条):")
    print("-" * 80)
    print(f"{'店铺':<12} {'收件人':<10} {'运单号':<20} {'快递':<8} {'状态':<10}")
    print("-" * 80)
    
    for row in rows:
        print(f"{row['shop_name']:<12} {row['receiver_name']:<10} "
              f"{row['tracking_no'] or '-':<20} {row['logistics_company'] or '-':<8} "
              f"{row['status']:<10}")


# ==================== CLI ====================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="聚水潭订单同步")
    parser.add_argument("--sync", action="store_true", help="同步订单")
    parser.add_argument("--days", type=int, default=3, help="同步最近N天")
    parser.add_argument("--shop", type=str, help="指定店铺(key)")
    parser.add_argument("--show", action="store_true", help="显示订单")
    parser.add_argument("--limit", type=int, default=20, help="显示数量")
    
    args = parser.parse_args()
    
    if args.sync:
        result = sync_all_orders(days=args.days)
        print(f"✅ 同步完成: {result['shops']} 个店铺, {result['orders']} 条订单")
    
    elif args.show:
        show_recent_orders(days=args.days, limit=args.limit)
    
    else:
        parser.print_help()