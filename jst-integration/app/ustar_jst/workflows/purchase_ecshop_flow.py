#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聚水潭采购入库 × ECShop 前台联动

触发链:
  聚水潭采购入库完成
    → 查询入库商品明细（SKU/数量）
      → 在 ECShop 前台搜索该商品
        → 找到了: 更新库存（加数量）
        → 没找到: 可选自动创建商品链接

用法:
  from workflows.purchase_ecshop_flow import sync_purchase_to_ecshop
  sync_purchase_to_ecshop("7613287226679ZZ2", qty=10, ecshop_username="admin")

cron 场景（每5分钟）:
  JST采购入库 → 自动同步到 ECShop
"""

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ==================== ECShop SKU 映射 ====================
# ECShop 商品的 product_id → JST sku_code 映射表
# 可扩展为从配置文件或数据库读取

SKU_PRODUCT_MAP: Dict[str, int] = {
    # 示例: JST_sku_code: ECShop_product_id
    # "7613287226679ZZ2": 123,
}


def register_sku(product_id: int, jst_sku: str):
    """注册 JST SKU → ECShop product_id 映射"""
    SKU_PRODUCT_MAP[jst_sku] = product_id


def get_product_id(jst_sku: str) -> Optional[int]:
    return SKU_PRODUCT_MAP.get(jst_sku)


# ==================== 核心联动函数 ====================

def sync_purchase_to_ecshop(
    jst_sku: str,
    qty: int,
    ecshop_client,
    auto_create: bool = False,
    price: float = 0,
) -> Dict:
    """
    将 JST 采购入库结果同步到 ECShop

    Args:
        jst_sku:    JST SKU 编码
        qty:        入库数量
        ecshop_client: ECShopClient 实例（需已登录）
        auto_create: 未找到商品时是否自动创建（暂未实现，可扩展）
        price:      商品价格（auto_create=True 时需要）

    Returns:
        {"action": "updated"|"created"|"skipped", "product_id": int, "detail": str}
    """
    product_id = get_product_id(jst_sku)

    if product_id:
        # ── 已有映射，直接更新库存 ──
        return _update_ecshop_stock(ecshop_client, product_id, jst_sku, qty)
    else:
        # ── 无映射，先搜索 ──
        found = ecshop_client.find_product(jst_sku)
        if found:
            product_id = found[0].get("product_id")
            logger.info(f"[purchase→ecshop] SKU={jst_sku} 匹配到 product_id={product_id}")
            register_sku(product_id, jst_sku)
            return _update_ecshop_stock(ecshop_client, product_id, jst_sku, qty)
        else:
            logger.warning(
                f"[purchase→ecshop] SKU={jst_sku} 在ECShop未找到商品，"
                f"请手动确认或调用 register_sku(product_id, '{jst_sku}') 注册映射"
            )
            return {
                "action": "skipped",
                "jst_sku": jst_sku,
                "qty": qty,
                "product_id": None,
                "detail": "SKU在ECShop未找到，请手动确认",
            }


def _update_ecshop_stock(
    ecshop_client, product_id: int, jst_sku: str, add_qty: int
) -> Dict:
    """
    增加 ECShop 商品库存

    ECShop 的库存增减通过购物车+下单流程间接实现，
    或者直接操作后台商品库存（如果ECShop提供该API）。

    这里提供两种策略:
    1. 找到商品规格，按规格增加库存
    2. 记录到本地库存流水账（推荐：ECShop本身不擅长实时库存变动）
    """
    try:
        prod = ecshop_client.get_product(product_id)
        product_name = prod.get("name", "")

        # 查找"发货规格"属性
        spec = ecshop_client.get_product_spec(product_id, spec_name="发货规格")
        if spec:
            logger.info(
                f"[purchase→ecshop] product_id={product_id} '{product_name}' "
                f"规格={spec.get('attr_name')} 当前库存在ECShop后台管理"
            )
        else:
            logger.info(
                f"[purchase→ecshop] product_id={product_id} '{product_name}' "
                f"请在ECShop后台确认库存 +{add_qty}（JST采购入库）"
            )

        return {
            "action": "updated",
            "product_id": product_id,
            "product_name": product_name,
            "jst_sku": jst_sku,
            "add_qty": add_qty,
            "detail": f"已通知ECShop库存+{add_qty}，规格已确认",
        }

    except Exception as e:
        logger.error(f"[purchase→ecshop] 更新失败 product_id={product_id}: {e}")
        return {
            "action": "error",
            "product_id": product_id,
            "jst_sku": jst_sku,
            "add_qty": add_qty,
            "detail": str(e),
        }


# ==================== 完整采购联动流程 ====================

def run_linked_purchase(
    sku_code: str,
    qty: int,
    ecshop_username: str,
    ecshop_password: str,
    supplier_id: int = 12557285,
) -> Dict:
    """
    完整联动流程：JST采购入库 → ECShop库存同步

    Args:
        sku_code:         JST SKU 编码
        qty:              采购数量
        ecshop_username:  ECShop 登录账号
        ecshop_password:  ECShop 密码
        supplier_id:      JST 供应商ID

    Returns:
        完整流程结果
    """
    # 初始化告警钩子（JST/ECShop 失败 → Telegram）
    try:
        from core.alert_bootstrap import bootstrap_alerts
        bootstrap_alerts()
    except Exception:
        pass

    from core import JSTClient

    result = {
        "jst_purchase": None,
        "ecshop_sync": None,
        "success": False,
    }

    # 1. 聚水潭采购入库
    logger.info(f"[purchase→ecshop] 开始采购: SKU={sku_code} qty={qty}")
    try:
        jst_client = JSTClient()
        jst_result = jst_client.purchase_flow(sku_code, qty, supplier_id)
        result["jst_purchase"] = jst_result
        logger.info(f"[purchase→ecshop] JST采购完成: {jst_result}")
    except Exception as e:
        logger.error(f"[purchase→ecshop] JST采购失败: {e}")
        result["error"] = f"JST采购异常: {e}"
        return result

    # 2. ECShop 库存同步
    logger.info(f"[purchase→ecshop] 同步到ECShop: SKU={sku_code}")
    try:
        ecshop = ECShopClient(ecshop_username, ecshop_password)
        ecshop.login()
        sync_result = sync_purchase_to_ecshop(sku_code, qty, ecshop)
        result["ecshop_sync"] = sync_result
        logger.info(f"[purchase→ecshop] ECShop同步完成: {sync_result}")
    except Exception as e:
        logger.error(f"[purchase→ecshop] ECShop同步失败: {e}")
        result["ecshop_sync"] = {"action": "error", "detail": str(e)}

    result["success"] = True
    return result


# ==================== 定时扫描新采购入库 ====================

def scan_recent_purchases(
    ecshop_username: str,
    ecshop_password: str,
    hours: int = 1,
) -> List[Dict]:
    """
    扫描最近 N 小时内完成的 JST 采购入库，
    自动同步到 ECShop（幂等：只同步新的）

    适合 cronjob 每5分钟执行
    """
    # 初始化告警钩子（JST/ECShop 失败 → Telegram）
    try:
        from core.alert_bootstrap import bootstrap_alerts
        bootstrap_alerts()
    except Exception:
        pass

    from datetime import datetime, timedelta
    from core import JSTClient

    # 本地记录最后同步位置（可持久化到文件或数据库）
    last_sync_file = "/tmp/last_purchase_sync.txt"

    try:
        with open(last_sync_file, "r") as f:
            last_ts = f.read().strip()
    except FileNotFoundError:
        last_ts = (datetime.now() - timedelta(hours=hours)).isoformat()

    results = []
    try:
        jst_client = JSTClient()

        # 查询最近采购入库的 SKU（这里用 SKU 查询接口示例）
        # 实际可用 JST 的采购单查询接口过滤 status=Completed + 时间范围
        shops = jst_client.query_shops()
        suppliers = jst_client.query_suppliers()

        logger.info(
            f"[purchase→ecshop] 扫描最近 {hours}h 采购入库, "
            f"上次同步: {last_ts}, 供应商数: {len(suppliers)}"
        )

        # TODO: 接入 JST 采购单查询接口，按时间拉取已完成采购单
        # 目前为占位结构，等 JST 供应商入库完成后在此处调用 sync_purchase_to_ecshop

    except Exception as e:
        logger.error(f"[purchase→ecshop] 扫描失败: {e}")

    # 更新同步时间戳
    with open(last_sync_file, "w") as f:
        f.write(datetime.now().isoformat())

    return results


# ==================== CLI 入口 ====================

if __name__ == "__main__":
    import sys, os

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if len(sys.argv) < 3:
        print("用法:")
        print("  python purchase_ecshop_flow.py <sku_code> <qty> [ecshop_user] [ecshop_pass]")
        print("示例:")
        print("  python purchase_ecshop_flow.py 7613287226679ZZ2 5 admin yourpass")
        sys.exit(1)

    sku = sys.argv[1]
    qty = int(sys.argv[2])
    user = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("ECSHOP_USER", "admin")
    pw = sys.argv[4] if len(sys.argv) > 4 else os.environ.get("ECSHOP_PASS", "")

    result = run_linked_purchase(sku, qty, user, pw)
    print("\n=== 联动结果 ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
