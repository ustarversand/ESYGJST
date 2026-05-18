#!/usr/bin/env python3
"""
列出已同步 vs 未同步的商品库存明细
"""

import os, sys, json, time, hashlib, logging
from typing import List, Dict, Set, Tuple
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.jst_client import JST_CONFIG
from workflows.sync_inventory import ssh_mysql, fetch_jst_inventory, BATCH_SIZE

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("list_inv")

HEADER = "\n" + "=" * 100


def load_all_goods() -> Tuple[Dict[str, dict], Dict[str, dict], Dict[str, dict]]:
    """加载所有商品信息"""
    # 单规格
    sql_goods = (
        "SELECT g.goods_id, g.goods_sn, g.goods_name, g.goods_number, "
        "  (SELECT COUNT(*) FROM ecs_products p WHERE p.goods_id = g.goods_id) AS has_product "
        "FROM ecs_goods g "
        "WHERE g.goods_sn != '' AND g.goods_sn NOT LIKE '-%%' "
        "  AND g.is_delete = 0 AND g.is_on_sale = 1"
    )
    rows_goods = ssh_mysql(sql_goods)
    
    goods_map = {}
    goods_multi_map = {}  # 多规格母商品
    for row in rows_goods:
        goods_id, goods_sn, goods_name, goods_number, has_product = row
        goods_id = int(goods_id)
        goods_sn = goods_sn.strip()
        goods_number = int(goods_number or 0)
        has_product = int(has_product or 0)
        
        entry = {"goods_id": goods_id, "name": goods_name, "stock": goods_number, "has_product": has_product}
        if has_product:
            goods_multi_map[goods_sn] = entry
        else:
            goods_map[goods_sn] = entry
    
    # 多规格子商品
    sql_products = (
        "SELECT p.product_id, p.goods_id, p.product_sn, p.product_number, g.goods_name, g.goods_sn "
        "FROM ecs_products p "
        "JOIN ecs_goods g ON p.goods_id = g.goods_id "
        "WHERE p.product_sn != '' AND p.product_sn IS NOT NULL "
        "  AND g.is_delete = 0"
    )
    rows_prod = ssh_mysql(sql_products)
    
    prod_map = {}
    for row in rows_prod:
        product_id, goods_id, product_sn, product_number, goods_name, goods_sn = row
        product_sn = product_sn.strip()
        product_number = int(product_number or 0)
        prod_map[product_sn] = {
            "product_id": int(product_id),
            "goods_id": int(goods_id),
            "name": goods_name.strip(),
            "stock": product_number,
            "goods_sn": goods_sn.strip(),
        }
    
    return goods_map, goods_multi_map, prod_map


def format_stock(val):
    """格式化库存数值"""
    if val is None:
        return "?"
    return str(val)


def main():
    print(f"{HEADER}")
    print(" 📊 ECShop 库存状态全览 — 已同步 vs 未同步")
    print(f"{HEADER}")
    
    # 1. 读取ECShop
    print("\n📖 读取ECShop商品...")
    goods_single, goods_multi, products = load_all_goods()
    
    all_sku_set = set()
    for gs in goods_single: all_sku_set.add(gs)
    for gs in goods_multi: all_sku_set.add(gs)
    for ps in products: all_sku_set.add(ps)
    
    print(f"   单规格商品: {len(goods_single)}")
    print(f"   多规格母商品: {len(goods_multi)}")
    print(f"   多规格子商品: {len(products)}")
    print(f"   总计SKU: {len(all_sku_set)}")
    
    # 2. 查JST库存
    print("\n📡 查询聚水潭库存...")
    jst = fetch_jst_inventory(list(all_sku_set))
    print(f"   聚水潭返回: {len(jst)} 个SKU")
    
    jst_sku_set = set(jst.keys())
    no_jst_sku_set = all_sku_set - jst_sku_set
    
    # 3. 分类整理
    
    # === A. 已同步（JST有数据）===
    synced_single = []  # (sku, name, ecshop_stock, jst_available, status)
    synced_multi = []
    
    for sku in sorted(jst_sku_set):
        j = jst[sku]
        avail = j["available"]
        
        if sku in goods_single:
            g = goods_single[sku]
            old = g["stock"]
            status = "✅ 已同步" if old != avail else "✓ 一致"
            synced_single.append((sku, g["name"], g["stock"], avail, status))
        elif sku in products:
            p = products[sku]
            old = p["stock"]
            status = "✅ 已同步" if old != avail else "✓ 一致"
            synced_multi.append((sku, p["name"], p["stock"], avail, status))
        elif sku in goods_multi:
            # 多规格母商品：goods_number 不用于库存，跳过多规格母商品
            pass
    
    # === B. 未同步（JST无数据）===
    unsynced_single = []
    unsynced_multi = []
    
    for sku in sorted(no_jst_sku_set):
        if sku in goods_single:
            g = goods_single[sku]
            unsynced_single.append((sku, g["name"], g["stock"]))
        elif sku in products:
            p = products[sku]
            unsynced_multi.append((sku, p["name"], p["stock"]))
        # 跳过goods_multi
    
    # === 4. 输出 ===
    
    # A1. 单规格 - 已同步
    if synced_single:
        print(f"\n📦 单规格商品 — 已同步（有JST库存数据）: {len(synced_single)}")
        print(f"   {'SKU':<25} {'ECShop':>7} → {'JST可发':>7}  {'名称':<25}")
        print(f"   {'-'*25} {'-'*7}   {'-'*7}  {'-'*25}")
        for sku, name, old, new, status in synced_single:
            changed = old != new
            arrow = "→" if changed else " "
            print(f"   {sku:<25} {format_stock(old):>7} {arrow} {new:>7}  {name[:25]:<25}  {status}")
    
    # A2. 多规格 - 已同步
    if synced_multi:
        print(f"\n📦 多规格商品 — 已同步（有JST库存数据）: {len(synced_multi)}")
        print(f"   {'SKU':<25} {'ECShop':>7} → {'JST可发':>7}  {'名称':<30}")
        print(f"   {'-'*25} {'-'*7}   {'-'*7}  {'-'*30}")
        for sku, name, old, new, status in synced_multi:
            changed = old != new
            arrow = "→" if changed else " "
            print(f"   {sku:<25} {format_stock(old):>7} {arrow} {new:>7}  {name[:30]:<30}  {status}")
    
    # B1. 单规格 - 未同步
    if unsynced_single:
        print(f"\n⚠️  单规格商品 — 未同步（JST无此SKU数据）: {len(unsynced_single)}")
        print(f"   {'SKU':<25} {'库存':>7}  {'名称':<40}")
        print(f"   {'-'*25} {'-'*7}  {'-'*40}")
        for sku, name, stock in sorted(unsynced_single, key=lambda x: -x[2]):
            print(f"   {sku:<25} {format_stock(stock):>7}  {name[:40]:<40}")
    
    # B2. 多规格 - 未同步
    if unsynced_multi:
        print(f"\n⚠️  多规格商品 — 未同步（JST无此SKU数据）: {len(unsynced_multi)}")
        print(f"   {'SKU':<25} {'库存':>7}  {'名称':<40}")
        print(f"   {'-'*25} {'-'*7}  {'-'*40}")
        for sku, name, stock in sorted(unsynced_multi, key=lambda x: -x[2]):
            print(f"   {sku:<25} {format_stock(stock):>7}  {name[:40]:<40}")
    
    # === 汇总 ===
    print(f"\n{'='*100}")
    print(f" 📊 汇总")
    print(f"{'='*100}")
    print(f"   单规格已同步: {len(synced_single)} | 未同步: {len(unsynced_single)}")
    print(f"   多规格已同步: {len(synced_multi)} | 未同步: {len(unsynced_multi)}")
    print(f"   ──────────────────────────────────")
    print(f"   总计: 已同步 {len(synced_single) + len(synced_multi)}, 未同步 {len(unsynced_single) + len(unsynced_multi)}")
    print(f"   匹配率: {(len(synced_single) + len(synced_multi)) * 100 // len(all_sku_set)}%")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()
