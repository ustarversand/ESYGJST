#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
库存同步引擎 v1.0 — JST → ECShop
=================================
从聚水潭拉取真实库存，更新本地ECShop商城库存。

工作模式：主仓模式（Phase 1）
  - 调用 inventory.query 获取主仓实时库存
  - 用 goods_sn / product_sn 匹配 ECShop 商品
  - 单规格 → 更新 ecs_goods.goods_number
  - 多规格 → 更新 ecs_products.product_number
  - 可发量 = qty - order_lock - pick_lock

用法:
  python3 sync_inventory.py                    # 正常执行
  python3 sync_inventory.py --dry-run          # 只预览不更新
  python3 sync_inventory.py --verbose          # 详细日志
  python3 sync_inventory.py --sku XXXXX XXX    # 只同步指定SKU
"""

import os
import sys
import json
import time
import hashlib
import logging
import argparse
import subprocess
from datetime import datetime
from typing import List, Dict, Set, Tuple, Optional

# 添加项目根到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.jst_client import JST_CONFIG

# ==================== 配置 ====================

SSH_HOST = "192.168.178.26"
SSH_USER = "ustar"
SSH_PASS = "Hilden11031980"
MYSQL_CONTAINER = "hermes-agent-ecshop"
MYSQL_USER = "root"
MYSQL_PASS = "Ecshop@2026!"
MYSQL_DB = "ecshop_renzheng"

BATCH_SIZE = 50  # 每批查询的SKU数量

# ==================== 日志 ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_inventory")


# ==================== MySQL 查询 ====================

def ssh_mysql(sql: str) -> List[tuple]:
    """通过SSH在ECShop容器内执行MySQL查询"""
    sql_clean = sql.replace("'", "'\\''")
    cmd = (
        f"docker exec {MYSQL_CONTAINER} mysql "
        f"-u {MYSQL_USER} -p{MYSQL_PASS} {MYSQL_DB} "
        f"--default-character-set=utf8mb4 "
        f"-B -e '{sql_clean}'"
    )
    ssh_cmd = [
        "sshpass", "-p", SSH_PASS, "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{SSH_USER}@{SSH_HOST}",
        cmd,
    ]
    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        logger.error(f"SSH/MySQL 失败: {result.stderr[:200]}")
        return []
    lines = result.stdout.strip().split("\n")
    if not lines or len(lines) < 2:
        return []
    # 第一行是表头，后面是数据
    rows = []
    for line in lines[1:]:
        if line.strip():
            rows.append(tuple(line.split("\t")))
    return rows


# ==================== 低库存检测 ====================

LOW_STOCK_THRESHOLD = 10  # 默认阈值

def check_low_stock(jst_inventory: Dict[str, dict], threshold: int = LOW_STOCK_THRESHOLD) -> List[dict]:
    """
    检查低库存商品。
    
    Returns:
        [{"sku", "name", "available", "qty", "virtual_qty"}, ...]
    """
    low = []
    for sku, inv in sorted(jst_inventory.items()):
        avail = inv["available"]
        if 0 < avail <= threshold:
            low.append({
                "sku": sku,
                "name": inv.get("name", ""),
                "available": avail,
                "qty": inv["qty"],
                "virtual_qty": inv["virtual_qty"],
                "status": "⚠️ 紧张" if avail <= threshold else "✅",
            })
        elif avail == 0 and inv["qty"] > 0:
            low.append({
                "sku": sku,
                "name": inv.get("name", ""),
                "available": 0,
                "qty": inv["qty"],
                "virtual_qty": inv["virtual_qty"],
                "status": "🔴 售罄",
            })
    return low


def ssh_mysql_update(sql: str) -> Tuple[bool, str]:
    """执行MySQL更新/删除等写操作"""
    sql_clean = sql.replace("'", "'\\''")
    cmd = (
        f"docker exec {MYSQL_CONTAINER} mysql "
        f"-u {MYSQL_USER} -p{MYSQL_PASS} {MYSQL_DB} "
        f"--default-character-set=utf8mb4 "
        f"-e '{sql_clean}'"
    )
    ssh_cmd = [
        "sshpass", "-p", SSH_PASS, "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{SSH_USER}@{SSH_HOST}",
        cmd,
    ]
    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        logger.error(f"UPDATE 失败: {result.stderr[:200]}")
        return False, result.stderr[:200]
    return True, result.stdout.strip()


# ==================== 读取 ECShop 商品信息 ====================

def load_ecshop_goods() -> Dict[str, dict]:
    """
    从ECShop读取所有商品库存信息。
    
    Returns:
        {goods_sn: {goods_id, goods_name, goods_number, has_product}}
    """
    sql = (
        "SELECT g.goods_id, g.goods_sn, g.goods_name, g.goods_number, "
        "  (SELECT COUNT(*) FROM ecs_products p WHERE p.goods_id = g.goods_id) AS has_product "
        "FROM ecs_goods g "
        "WHERE g.goods_sn != '' AND g.goods_sn NOT LIKE '-%%' "
        "  AND g.is_delete = 0 AND g.is_on_sale = 1"
    )
    rows = ssh_mysql(sql)
    goods_map = {}
    for row in rows:
        if len(row) < 5:
            continue
        goods_id, goods_sn, goods_name, goods_number, has_product = row
        goods_sn = goods_sn.strip()
        goods_name = goods_name.strip()
        try:
            goods_id = int(goods_id)
            goods_number = int(goods_number or 0)
            has_product = int(has_product or 0)
        except ValueError:
            continue
        if not goods_sn:
            continue
        goods_map[goods_sn] = {
            "goods_id": goods_id,
            "goods_name": goods_name,
            "goods_number": goods_number,
            "has_product": has_product > 0,
        }
    return goods_map


def load_ecshop_products() -> Dict[str, dict]:
    """
    读取多规格商品的SKU映射。
    
    Returns:
        {product_sn: {product_id, goods_id, product_number, goods_name}}
    """
    sql = (
        "SELECT p.product_id, p.goods_id, p.product_sn, p.product_number, "
        "  g.goods_name, g.goods_sn "
        "FROM ecs_products p "
        "JOIN ecs_goods g ON p.goods_id = g.goods_id "
        "WHERE p.product_sn != '' AND p.product_sn IS NOT NULL "
        "  AND g.is_delete = 0"
    )
    rows = ssh_mysql(sql)
    prod_map = {}
    for row in rows:
        if len(row) < 6:
            continue
        product_id, goods_id, product_sn, product_number, goods_name, goods_sn = row
        product_sn = product_sn.strip()
        goods_name = goods_name.strip()
        try:
            product_id = int(product_id)
            goods_id = int(goods_id)
            product_number = int(product_number or 0)
        except ValueError:
            continue
        if not product_sn:
            continue
        prod_map[product_sn] = {
            "product_id": product_id,
            "goods_id": goods_id,
            "goods_name": goods_name,
            "product_number": product_number,
            "goods_sn": goods_sn.strip(),
        }
    return prod_map


# ==================== JST 库存查询 ====================

def fetch_jst_inventory(sku_ids: List[str]) -> Dict[str, dict]:
    """
    从聚水潭拉取库存。
    batch分批，合并返回。
    
    Returns:
        {sku_id: {qty, order_lock, pick_lock, available, name}}
    """
    import requests as _req
    
    all_inv = {}
    batches = [sku_ids[i:i + BATCH_SIZE] for i in range(0, len(sku_ids), BATCH_SIZE)]
    
    for batch_idx, batch in enumerate(batches):
        sku_str = ",".join(batch)
        method = "inventory.query"
        ts = str(int(time.time()))
        params = {"token": JST_CONFIG["token"], "ts": ts}
        
        # 签名
        sorted_str = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
        sign_str = method + JST_CONFIG["app_key"] + sorted_str + JST_CONFIG["app_secret"]
        sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest().lower()
        
        url = (
            f"{JST_CONFIG['api_url_legacy']}"
            f"?method={method}&partnerid={JST_CONFIG['app_key']}"
            f"&token={JST_CONFIG['token']}&ts={ts}&sign={sign}"
        )
        
        data = {"page_index": 1, "page_size": 200, "sku_ids": sku_str}
        
        try:
            resp = _req.post(
                url,
                data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=30,
            )
            result = resp.json()
        except Exception as e:
            logger.error(f"批次 {batch_idx + 1}/{len(batches)} API调用异常: {e}")
            continue
        
        if result.get("code") != 0:
            logger.warning(f"批次 {batch_idx + 1}/{len(batches)} 返回: {result.get('msg', '未知错误')}")
            continue
        
        for inv in result.get("inventorys", []):
            sku_id = inv.get("sku_id", "")
            qty = int(inv.get("qty", 0) or 0)
            order_lock = int(inv.get("order_lock", 0) or 0)
            pick_lock = int(inv.get("pick_lock", 0) or 0)
            virtual_qty = int(inv.get("virtual_qty", 0) or 0)
            available = max(0, qty - order_lock - pick_lock)
            available_virtual = max(0, available + virtual_qty)
            all_inv[sku_id] = {
                "qty": qty,
                "order_lock": order_lock,
                "pick_lock": pick_lock,
                "virtual_qty": virtual_qty,
                "available": available,
                "available_virtual": available_virtual,
                "name": inv.get("name", ""),
            }
        
        if batch_idx < len(batches) - 1:
            time.sleep(0.3)  # 避免限流
    
    return all_inv


# ==================== 虚拟仓库存查询 ====================

LWH_MALL_DIRECT_MAIL = 35  # 商城直邮仓

# ====== 商城直邮仓 SKU 映射表 ======
# JST虚拟仓SKU ID → ECShop goods_sn
# 获取方式：getvirtualstock 时间范围全量扫描后，匹配 ECShop 商品
WAREHOUSE_SKU_MAP = {
    # 直接匹配（仓库SKU = ECShop goods_sn）
    "0712067SYY": "0712067SYY",  # Fitline Omega 3 Vegan 素鱼油
    "39000004009": "39000004009",  # LifeWave X39
    "1sfbaoxian": "1sfbaoxian",  # 现货顺丰保险
    # 后缀匹配（仓库SKU = goods_sn + 后缀）
    "0708023XH": "0708023",    # PM小红
    "0702037XB": "0702037",    # Fitline Restorate小白
    "0702058XB": "0702058",    # Fitline Restorate Exotic
    "0702069PDY": "0702069",   # D-Drink排毒饮
    "0704022AJS": "0704022",   # Proshape Amino氨基酸
    "0704026HLJ": "0704026",   # 活力健Munogen
    "0705012FHDB": "0705012",  # PowerCocktail
    "0705017EB": "0705017",    # 儿童倍适
    "0705018DB": "0705018",    # 普通大白
    "0707008KYH": "0707008",   # 抗氧化450g
    "0707009PGKYH": "0707009", # 苹果味抗氧化
    "0708062QNXH": "0708062",  # 青柠小红
    "0709006CBC": "0709006",   # 草本茶Herbaslim
    "0709011GGJ": "0709011",   # 骨骼健
    "0709028TM": "0709028",    # 肽美/胶原蛋白
    "0709031RQDB": "0709031",  # Whey乳清蛋白
    "0709040BLJ": "0709040",   # Men倍力健
    "0709048XF": "0709048",    # C-balance小粉
    "0712014FM": "0712014",    # 辅酶Q10 Plus
    "0712021YHT": "0712021",   # 异黄酮素
    "0712053KFFB": "0712053",  # 口服发宝
    "07120630SGX": "0712063",   # 新版素顾心
    # 新智能店铺仓映射
    "0712020YHS": "0712020X",  # Fitline Lutein 叶黄素
    "0711048NLB": "0711048DE", # 圣诞节能量棒
    "0709065JS": "0709065",    # PM Fitline Creatine+ 肌酸
    "0709048XFTK": "0709048",  # Fitline C-balance 小粉（另一规格）
    "0116076WYFB": "0116076",  # 菲莱PM Fitline 外用发健
    # 奶粉映射（智能店铺仓专用SKU → ECShop goods_sn）
    "4056631003459BJ1": "4008976022909",  # 爱他美白金1段
    "4056631003473BJ2": "4056631001349",  # 爱他美白金2段
    "4056631001226LG1": "4056631001226",  # 爱他美蓝罐1段
}

# 反向映射（ECShop goods_sn → JST仓库SKU）
ECSHOP_SN_TO_WAREHOUSE = {v: k for k, v in WAREHOUSE_SKU_MAP.items()}


def _resolve_sku_to_ecshop(warehouse_sku: str) -> str:
    """将虚拟仓SKU ID 映射回 ECShop goods_sn"""
    # 1. 精准映射表匹配
    if warehouse_sku in WAREHOUSE_SKU_MAP:
        return WAREHOUSE_SKU_MAP[warehouse_sku]
    # 2. 前缀匹配：如果仓库SKU以某个ECShop goods_sn开头
    #    按goods_sn长度从长到短排序，优先匹配更长的前缀
    ecshop_sns = sorted(ECSHOP_SN_TO_WAREHOUSE.keys(), key=len, reverse=True)
    for sn in ecshop_sns:
        if warehouse_sku.startswith(sn) and sn != warehouse_sku:
            return sn
    # 3. 直接返回原值
    return warehouse_sku


def _find_warehouse_sku_for_ecshop(goods_sn: str) -> List[str]:
    """找到ECShop goods_sn 对应的所有可能虚拟仓SKU ID"""
    candidates = [goods_sn]  # 先试直接匹配
    if goods_sn in ECSHOP_SN_TO_WAREHOUSE:
        candidates.append(ECSHOP_SN_TO_WAREHOUSE[goods_sn])
    return list(set(candidates))


def fetch_virtual_warehouse_inventory(
    sku_ids: List[str] = None,
    lwh_id: int = LWH_MALL_DIRECT_MAIL,
    use_time_range: bool = True,
) -> Dict[str, dict]:
    """
    从聚水潭虚拟仓查询库存（新API）。
    
    使用 modified_begin/end 时间范围拉全量，然后通过 SKU 映射表
    将仓库SKU ID 转回 ECShop goods_sn。
    
    Args:
        sku_ids: 可选，限制查询的SKU列表。为None时查全量
        lwh_id: 虚拟仓ID（默认35=商城直邮仓）
        use_time_range: 是否使用时间范围模式拉全量（默认True）
    
    Returns:
        {ecshop_goods_sn: {qty, order_able_qty, available, name, warehouse_sku}}
        已通过映射表将仓库SKU 转回 ECShop 的 goods_sn
    """
    import requests as _req
    import time as _time
    
    result_data = {}
    
    # === 策略：用时间范围拉全量 ===
    if use_time_range:
        page = 1
        while True:
            biz_data = {
                "sku_ids": [],
                "page": {"current_page": str(page), "page_size": "200"},
                "modified_begin": "2020-01-01 00:00:00",
                "modified_end": "2026-12-31 23:59:59",
            }
            
            ts = str(int(_time.time()))
            biz = json.dumps(biz_data, separators=(",", ":"))
            params = {
                "app_key": JST_CONFIG["app_key"],
                "access_token": JST_CONFIG["token"],
                "timestamp": ts,
                "charset": "utf-8",
                "version": "2",
                "biz": biz,
            }
            sorted_str = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
            sign = hashlib.md5(
                (JST_CONFIG["app_secret"] + sorted_str).encode("utf-8")
            ).hexdigest().lower()
            params["sign"] = sign
            
            try:
                resp = _req.post(
                    f"{JST_CONFIG['api_url_new']}/open/webapi/itemapi/iteminventory/getvirtualstock",
                    data=params,
                    timeout=30,
                )
                result = resp.json()
            except Exception as e:
                logger.error(f"虚拟仓API时间范围查询 第{page}页 异常: {e}")
                break
            
            if result.get("code") != 0:
                msg = result.get("msg", "未知错误")
                logger.warning(f"虚拟仓API时间范围查询 第{page}页: {msg}")
                break
            
            wrapper = result.get("data", {})
            items = wrapper.get("data", []) if isinstance(wrapper, dict) else []
            
            if not items:
                break
            
            for item in items:
                sku = item.get("sku_id", "")
                for stock_entry in item.get("stocks", []):
                    if stock_entry.get("lwh_id") != lwh_id:
                        continue  # 只看目标虚拟仓
                    
                    qty = int(stock_entry.get("qty", 0) or 0)
                    order_able = int(stock_entry.get("order_able_qty", 0) or 0)
                    order_lock = int(stock_entry.get("order_lock", 0) or 0)
                    pick_lock = int(stock_entry.get("pick_lock", 0) or 0)
                    wh_name = stock_entry.get("name", "")
                    
                    # 映射回 ECShop goods_sn
                    ecshop_sn = _resolve_sku_to_ecshop(sku)
                    
                    # 多个仓库SKU映射到同个ECShop SN时，取较大的可售值
                    if ecshop_sn in result_data:
                        existing = result_data[ecshop_sn]
                        if max(0, order_able) > existing["available"]:
                            result_data[ecshop_sn] = {
                                "qty": qty,
                                "order_able_qty": order_able,
                                "available": max(0, order_able),
                                "order_lock": order_lock,
                                "pick_lock": pick_lock,
                                "warehouse_name": wh_name,
                                "name": "",
                                "warehouse_sku": sku,
                            }
                    else:
                        result_data[ecshop_sn] = {
                            "qty": qty,
                            "order_able_qty": order_able,
                            "available": max(0, order_able),
                            "order_lock": order_lock,
                            "pick_lock": pick_lock,
                            "warehouse_name": wh_name,
                            "name": "",
                            "warehouse_sku": sku,
                        }
            
            page += 1
            _time.sleep(0.3)
        
        return result_data
    
    # === 兼容旧模式：按SKU ID批量查（不推荐） ===
    if not sku_ids:
        return result_data
    
    batches = [sku_ids[i:i + 50] for i in range(0, len(sku_ids), 50)]
    
    for batch_idx, batch in enumerate(batches):
        biz_data = {
            "sku_ids": batch,
            "page": {"current_page": "1", "page_size": "200"},
        }
        
        ts = str(int(_time.time()))
        biz = json.dumps(biz_data, separators=(",", ":"))
        params = {
            "app_key": JST_CONFIG["app_key"],
            "access_token": JST_CONFIG["token"],
            "timestamp": ts,
            "charset": "utf-8",
            "version": "2",
            "biz": biz,
        }
        sorted_str = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
        sign = hashlib.md5(
            (JST_CONFIG["app_secret"] + sorted_str).encode("utf-8")
        ).hexdigest().lower()
        params["sign"] = sign
        
        try:
            resp = _req.post(
                f"{JST_CONFIG['api_url_new']}/open/webapi/itemapi/iteminventory/getvirtualstock",
                data=params,
                timeout=30,
            )
            result = resp.json()
        except Exception as e:
            logger.error(f"虚拟仓API批次 {batch_idx + 1}/{len(batches)} 异常: {e}")
            continue
        
        if result.get("code") != 0:
            msg = result.get("msg", "未知错误")
            logger.warning(f"虚拟仓API批次 {batch_idx + 1}/{len(batches)}: {msg}")
            continue
        
        wrapper = result.get("data", {})
        items = wrapper.get("data", []) if isinstance(wrapper, dict) else []
        
        for item in items:
            sku = item.get("sku_id", "")
            for stock_entry in item.get("stocks", []):
                if stock_entry.get("lwh_id") != lwh_id:
                    continue
                
                qty = int(stock_entry.get("qty", 0) or 0)
                order_able = int(stock_entry.get("order_able_qty", 0) or 0)
                order_lock = int(stock_entry.get("order_lock", 0) or 0)
                pick_lock = int(stock_entry.get("pick_lock", 0) or 0)
                wh_name = stock_entry.get("name", "")
                
                result_data[sku] = {
                    "qty": qty,
                    "order_able_qty": order_able,
                    "available": max(0, order_able),
                    "order_lock": order_lock,
                    "pick_lock": pick_lock,
                    "warehouse_name": wh_name,
                    "name": "",
                }
        
        if batch_idx < len(batches) - 1:
            time.sleep(0.3)
    
    return result_data


# ==================== 更新 ECShop 库存 ====================

def update_goods_number(goods_id: int, new_number: int, dry_run: bool = False) -> bool:
    """更新单规格商品库存"""
    sql = f"UPDATE ecs_goods SET goods_number = {new_number} WHERE goods_id = {goods_id}"
    if dry_run:
        logger.info(f"  [DRY-RUN] UPDATE: {sql}")
        return True
    ok, _ = ssh_mysql_update(sql)
    return ok


def update_product_number(product_id: int, new_number: int, dry_run: bool = False) -> bool:
    """更新多规格商品库存"""
    sql = f"UPDATE ecs_products SET product_number = {new_number} WHERE product_id = {product_id}"
    if dry_run:
        logger.info(f"  [DRY-RUN] UPDATE: {sql}")
        return True
    ok, _ = ssh_mysql_update(sql)
    return ok


def _report_unmatched_warehouse_items(jst_inventory: Dict[str, dict], goods: Dict[str, dict]):
    """报告虚拟仓中有但ECShop没有匹配的商品"""
    unmatched = []
    for ecshop_sn in jst_inventory:
        if ecshop_sn not in goods:
            info = jst_inventory[ecshop_sn]
            unmatched.append((ecshop_sn, info.get("warehouse_sku", ecshop_sn), info.get("qty", 0)))
    
    if unmatched:
        logger.info(f"  ⚠️  仓库中有 {len(unmatched)} 个商品不在ECShop中（可能是新产品或SKU未同步）：")
        for ecshop_sn, wh_sku, qty in sorted(unmatched, key=lambda x: -x[2]):
            logger.info(f"    ECShop SN: {ecshop_sn:<20} 仓库SKU: {wh_sku:<20} 库存: {qty}")


# ==================== 主逻辑 ====================

def sync_inventory(dry_run: bool = False, sku_filter: Set[str] = None, verbose: bool = False, use_virtual: bool = False, lwh_id: int = None):
    """库存同步主流程"""
    start_time = time.time()
    mode = "主仓"
    if lwh_id:
        mode = f"虚拟仓(lwh_id={lwh_id})"
    elif use_virtual:
        mode = "主仓+虚拟库存"
    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}====== 库存同步开始（模式: {mode}）======")
    
    # 1. 读取ECShop商品
    logger.info("步骤1/4: 读取ECShop商品信息...")
    goods = load_ecshop_goods()
    products = load_ecshop_products()
    logger.info(f"  找到 {len(goods)} 个有SKU的商品, {len(products)} 个多规格子商品")
    
    if not goods:
        logger.warning("没有找到有效商品，跳过")
        return
    
    # 2. 收集所有需要查询的SKU
    goods_sku_set = set(goods.keys())
    product_sku_set = set(products.keys())
    all_skus = goods_sku_set | product_sku_set
    
    # 按SKU筛选
    if sku_filter:
        all_skus = all_skus & sku_filter
        logger.info(f"  筛选后: {len(all_skus)} 个SKU")
    
    if not all_skus:
        logger.warning("筛选后没有需要查询的SKU")
        return
    
    # 3. 拉取JST库存
    if lwh_id:
        logger.info(f"步骤2/4: 查询商城直邮仓虚拟库存 (lwh_id={lwh_id}, 时间范围拉全量)...")
        jst_inventory = fetch_virtual_warehouse_inventory(lwh_id=lwh_id)
    else:
        logger.info(f"步骤2/4: 查询聚水潭库存 ({len(all_skus)} 个SKU, 分{ (len(all_skus) + BATCH_SIZE - 1) // BATCH_SIZE }批)...")
        jst_inventory = fetch_jst_inventory(list(all_skus))
    logger.info(f"  返回 {len(jst_inventory)} 个SKU库存数据")
    
    if not jst_inventory:
        logger.warning("聚水潭未返回任何库存数据")
        return
    
    # 4. 对比并生成更新计划
    logger.info("步骤3/4: 对比库存差异...")
    changes = []  # [(type, identifier, goods_name, old_val, new_val)]
    
    # 按goods_id分组所有变体
    products_by_goods = {}
    for product_sn, p in products.items():
        products_by_goods.setdefault(p["goods_id"], []).append((product_sn, p))
    
    def get_pack_size(product_sn):
        """从product_sn前缀提取份数（支持多位数）"""
        pack_str = ""
        for c in product_sn:
            if c.isdigit():
                pack_str += c
            else:
                break
        return int(pack_str) if pack_str else 1
    
    # 4a. 单规格商品 (goods_sn -> goods_number)
    for goods_sn, g in goods.items():
        if g["has_product"] and not lwh_id:  # 主仓模式跳过
            continue
        if g["has_product"] and lwh_id:
            continue  # 虚拟仓模式：多规格由4c份数分配处理
        if goods_sn not in jst_inventory:
            if goods_sn not in all_skus:
                continue
            if verbose:
                logger.debug(f"  SKU '{goods_sn}' ({g['goods_name'][:20]}...) 在聚水潭无库存数据")
            continue
        
        jst = jst_inventory[goods_sn]
        current = g["goods_number"]
        new_val = jst["available_virtual"] if use_virtual else jst["available"]
        
        if current != new_val:
            changes.append(("goods", goods_sn, g["goods_name"], current, new_val, g["goods_id"], jst))
    
    # 4b. 主仓模式：多规格走product_level
    if not lwh_id:
        for product_sn, p in products.items():
            if product_sn not in jst_inventory:
                continue
            jst = jst_inventory[product_sn]
            current = p["product_number"]
            new_val = jst["available_virtual"] if use_virtual else jst["available"]
            if current != new_val:
                changes.append(("product", product_sn, p["goods_name"], current, new_val, p["product_id"], jst))
    
    # 4c. 虚拟仓模式：多规格按份数分配（pack_size）
    if lwh_id:
        for goods_sn, g in goods.items():
            if not g["has_product"]:
                continue  # 跳过单规格
            if goods_sn not in jst_inventory:
                continue
            
            total_jst = jst_inventory[goods_sn]["available_virtual"] if use_virtual else jst_inventory[goods_sn]["available"]
            if total_jst <= 0:
                continue
            
            goods_changed = False
            new_variant_values = {}  # product_sn → new_value
            
            for product_sn, p in products_by_goods.get(g["goods_id"], []):
                # 规则2：忽略*65特价款
                if "*65" in product_sn:
                    continue
                # 规则3：忽略已停用变体（当前库存=0）
                if p["product_number"] == 0:
                    continue
                
                pack_size = get_pack_size(product_sn)
                new_val = total_jst // pack_size
                new_variant_values[product_sn] = new_val
                
                if new_val != p["product_number"]:
                    goods_changed = True
                    changes.append(("product_pack", product_sn, p["goods_name"], p["product_number"], new_val, p["product_id"], jst_inventory[goods_sn]))
                    if verbose:
                        logger.info(f"  [PACK] {p['goods_name'][:25]:<25} {product_sn:<30} {p['product_number']:>5}→{new_val:>5} (总{total_jst}÷{pack_size}份)")
            
            if goods_changed:
                # 重算goods_number = 更新后所有变体之和
                all_current = {}
                for product_sn, p in products_by_goods.get(g["goods_id"], []):
                    all_current[product_sn] = p["product_number"]
                all_current.update(new_variant_values)
                new_goods_number = sum(all_current.values())
                
                if new_goods_number != g["goods_number"]:
                    changes.append(("goods", goods_sn, g["goods_name"], g["goods_number"], new_goods_number, g["goods_id"], jst_inventory[goods_sn]))
                    if verbose:
                        logger.info(f"  [SUM] {g['goods_name'][:25]:<25} goods_number: {g['goods_number']}→{new_goods_number}")
    
    if not changes:
        logger.info("✅ 所有商品库存与聚水潭一致，无需更新")
        
        # 虚拟仓模式：额外报告仓库中有但ECShop没有的商品
        if lwh_id:
            _report_unmatched_warehouse_items(jst_inventory, goods)
        
        duration = time.time() - start_time
        logger.info(f"====== 同步完成 ({duration:.1f}s) ======")
        return
    
    # 5. 执行更新
    logger.info(f"步骤4/4: 更新 {len(changes)} 个商品库存...")
    
    updated_goods = 0
    updated_products = 0
    failed = 0
    
    for ctype, sku, name, old_val, new_val, obj_id, jst in changes:
        if new_val < 0:
            new_val = 0  # 可发量为负时归零
        
        if verbose or dry_run:
            arrow = "→" if dry_run else "→"
            vq = jst.get("virtual_qty", 0)
            vtag = f" | 虚拟: {vq}" if vq > 0 else ""
            logger.info(
                f"  [{ctype.upper()}] {name[:25]:<25} | "
                f"SKU: {sku:<20} | "
                f"库存: {old_val:<5} {arrow} {new_val:<5}{vtag}"
            )
        
        if dry_run:
            continue
        
        if ctype == "goods":
            if update_goods_number(obj_id, new_val):
                updated_goods += 1
            else:
                failed += 1
        elif ctype in ("product", "product_pack"):
            if update_product_number(obj_id, new_val):
                updated_products += 1
            else:
                failed += 1
    
    # 统计
    duration = time.time() - start_time
    if dry_run:
        logger.info(f"====== [DRY-RUN] 将更新 {len(changes)} 个商品 ({duration:.1f}s) ======")
    else:
        logger.info(
            f"====== 同步完成 | "
            f"更新单规格: {updated_goods}, "
            f"更新多规格: {updated_products}, "
            f"失败: {failed}, "
            f"耗时: {duration:.1f}s ======"
        )
    
    # 虚拟仓模式：额外报告未匹配商品
    if lwh_id:
        _report_unmatched_warehouse_items(jst_inventory, goods)


# ==================== CLI ====================

def main():
    parser = argparse.ArgumentParser(description="聚水潭 → ECShop 库存同步引擎")
    parser.add_argument("--dry-run", action="store_true", help="只预览不更新")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    parser.add_argument("--sku", nargs="+", help="只同步指定SKU（多个用空格分隔）")
    parser.add_argument("--virtual", action="store_true", help="启用虚拟库存（可发量=实体+虚拟）")
    parser.add_argument("--virtual-warehouse", "--lwh", "--wh", type=int, default=0,
                        help="虚拟仓ID（如35=商城直邮仓），替换主仓模式。使用时间范围API全量查询+SKU映射")
    parser.add_argument("--alert-threshold", type=int, default=0, help="低库存预警阈值（0=不预警）")
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    sku_filter = set(args.sku) if args.sku else None
    
    sync_inventory(
        dry_run=args.dry_run,
        sku_filter=sku_filter,
        verbose=args.verbose,
        use_virtual=args.virtual,
        lwh_id=args.virtual_warehouse if args.virtual_warehouse > 0 else None,
    )
    
    # 低库存预警
    if args.alert_threshold > 0 and not args.dry_run:
        goods = load_ecshop_goods()
        products = load_ecshop_products()
        all_skus = set(goods.keys()) | set(products.keys())
        if sku_filter:
            all_skus = all_skus & sku_filter
        
        jst_inv = fetch_jst_inventory(list(all_skus))
        low_items = check_low_stock(jst_inv, threshold=args.alert_threshold)
        
        if low_items:
            print()
            print(f"⚠️  **低库存预警** (可发量≤{args.alert_threshold}):")
            print(f"{'SKU':<25} {'可发':>5} {'总库':>5} {'虚拟':>5}  {'名称':<25}")
            print(f"{'-'*25} {'-'*5} {'-'*5} {'-'*5}  {'-'*25}")
            for item in low_items:
                name = (item['name'] or '')[:25]
                print(f"{item['sku']:<25} {item['available']:>5} {item['qty']:>5} {item['virtual_qty']:>5}  {name:<25}  {item['status']}")
            print(f"共 {len(low_items)} 个商品需要关注")
        else:
            print(f"\n✅ 低库存检查通过（无可发量≤{args.alert_threshold}的商品）")


if __name__ == "__main__":
    main()
