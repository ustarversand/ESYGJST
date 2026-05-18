#!/usr/bin/env python3
"""
聚水潭ERP 智能管理系统
统一 CLI：查询店铺/商品/订单/统计/管理

用法:
  python jst_manager.py shops                    # 列出所有店铺
  python jst_manager.py skus [--days 7]          # 查询SKU列表
  python jst_manager.py stats [--days 3]         # 订单统计
  python jst_manager.py orders [--shop 18442196] [--days 7] [--limit 10]
  python jst_manager.py search <订单号|收件人>     # 搜索订单
  python jst_manager.py order <o_id>             # 查看订单详情
  python jst_manager.py remark <o_id> <备注>      # 写卖家备注
|  python jst_manager.py ship <o_id> <快递公司> <单号>  # 登记快递
  python jst_manager.py syncinv              # 同步JST库存→ECShop
  python jst_manager.py syncinv --virtual   # 含虚拟库存
  python jst_manager.py syncinv --lwh=35    # 从商城直邮仓同步
  python jst_manager.py syncinv --alert=20  # 同步+低库存预警(≤20)
  python jst_manager.py items help           # 商品/类目管理（新API）
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta

# 添加项目路径
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, '..'))  # ustar_jst/
sys.path.insert(0, script_dir)  # cli/

from domains.query_api import (
    query_shops, query_order_stats, query_inventory, query_wms_inventory,
)
from domains.order_api import (
    query_order, query_orders_by_time, query_orders_paginated,
    update_order_remark, register_express, update_order_address,
    cancel_order, call_jushuitan_api,
)
from domains.aftersale_api import (
    aftersale_noinfo_upload, aftersale_upload, aftersale_confirm,
    aftersale_unconfirm, aftersale_cancel, aftersale_confirm_goods,
    aftersale_set_labels,
)
from domains.item_api import (
    query_sku, query_category, query_mall_items, query_combine_sku,
    query_sku_detail, query_sku_map, add_or_update_category,
    bind_sku_links, save_supplier_sku, batch_upload_sku, upload_sku_map,
    call_new_api,
)
from workflows.order_push_flow import OrderPushSystem


# ==================== 格式化输出 ====================

def _get_datas(result: dict) -> list:
    """从API响应中提取datas列表（处理data嵌套和null值）"""
    data = result.get("data", result)
    if isinstance(data, dict) and data.get("datas") is not None:
        return data["datas"]
    raw = result.get("datas")
    return raw if raw is not None else []

def format_shops(result: dict) -> str:
    """格式化店铺列表"""
    shops = result.get("shops", [])
    if not shops:
        return "❌ 未找到店铺"

    lines = ["## 🏪 店铺列表", "", f"共 **{len(shops)}** 个店铺", "", "| ID | 名称 | 平台 | 昵称 |", "|---|------|------|------|"]
    for s in shops:
        sid = s.get("shop_id", 0)
        name = (s.get("shop_name") or "").strip()
        site = (s.get("shop_site") or "").strip()
        nick = (s.get("nick") or "").strip()
        lines.append(f"| {sid} | {name} | {site} | {nick} |")
    return "\n".join(lines)


def format_skus(result: dict) -> str:
    """格式化SKU列表"""
    skus = result.get("skus", result.get("datas", []))
    if not skus:
        return "❌ 未找到SKU"

    lines = ["## 📦 商品SKU列表", "", f"共 **{len(skus)}** 个SKU", "",
             "| SKU ID | 名称 | 售价 | 成本 | 库存 |", "|--------|------|:----:|:----:|:----:|"]
    for s in skus:
        sku_id = s.get("sku_id", "")
        name = (s.get("name") or "")[:35]
        price = s.get("sale_price", "—")
        cost = s.get("cost_price", "—")
        lines.append(f"| {sku_id} | {name} | ¥{price} | ¥{cost} | — |")

    if result.get("has_next"):
        lines.append("", "*⚠️ 还有更多，请缩小时间范围或指定SKU ID*")
    return "\n".join(lines)


def format_stats(result: dict) -> str:
    """格式化订单统计"""
    if result.get("code") != 0:
        return f"❌ 查询失败: {result.get('msg', '未知错误')}"

    lines = [
        "## 📊 订单统计",
        "",
        f"**总订单**: {result['total_orders']} 单",
        f"**总金额**: ¥{result['total_amount']:,.2f}",
        f"**总运费**: ¥{result['total_freight']:,.2f}",
        "",
        "### 状态分布",
    ]
    for status, count in sorted(result.get("status_distribution", {}).items(),
                                 key=lambda x: -x[1]):
        lines.append(f"- **{status}**: {count}单")

    lines.extend(["", "### 店铺排名"])
    for shop, count in sorted(result.get("shop_distribution", {}).items(),
                              key=lambda x: -x[1])[:10]:
        lines.append(f"- {shop}: **{count}单**")

    lines.extend(["", "### 热销商品 TOP 15"])
    for i, p in enumerate(result.get("top_products", []), 1):
        lines.append(f"{i}. {p['name'][:35]} — {p['qty']}件")

    return "\n".join(lines)


def format_orders(result: dict, title: str = "订单列表") -> str:
    """格式化订单列表"""
    if result.get("code") != 0:
        return f"❌ 查询失败: {result.get('msg', '未知错误')}"
    orders = result.get("orders", [])
    if not orders:
        return "❌ 未找到订单"

    lines = [f"## {title}", "", f"共 {len(orders)} 单", "",
             "| o_id | 线上单号 | 状态 | 金额 | 收件人 | 店铺 |", "|------|---------|:----:|:----:|:------:|:----:|"]
    for o in orders:
        lines.append(
            f"| {o['o_id']} | {str(o.get('so_id',''))[:20]} | {o.get('status','')[:10]} "
            f"| ¥{o.get('pay_amount',0)} | {o.get('receiver_name','')[:8]} "
            f"| {o.get('shop_name','')[:10]} |"
        )
    return "\n".join(lines)


def format_order_detail(o: dict) -> str:
    """格式化单个订单详情"""
    lines = [
        f"## 📋 订单 #{o['o_id']}",
        "",
        "### 基本信息",
        f"- **线上单号**: {o.get('so_id', '—')}",
        f"- **店铺**: {o.get('shop_name', '—')} (ID: {o.get('shop_id', '—')})",
        f"- **状态**: {o.get('status', '—')}",
        f"- **类型**: {o.get('type', '—')}",
        f"- **下单时间**: {o.get('order_date', '—')}",
        f"- **修改时间**: {o.get('modified', '—')}",
        "",
        "### 收货信息",
        f"- **收件人**: {o.get('receiver_name', '—')}",
        f"- **手机**: {o.get('receiver_mobile', '—')}",
        f"- **电话**: {o.get('receiver_phone', '—')}",
        f"- **地址**: {o.get('receiver_state', '')} {o.get('receiver_city', '')} {o.get('receiver_district', '')} {o.get('receiver_address', '')}",
        "",
        "### 物流信息",
        f"- **快递公司**: {o.get('logistics_company', '—')}",
        f"- **快递单号**: {o.get('l_id', '—')}",
        f"- **国际单号**: {o.get('cb_l_id', '—')}",
        "",
        "### 金额信息",
        f"- **应付金额**: ¥{o.get('pay_amount', 0)}",
        f"- **已付金额**: ¥{o.get('paid_amount', 0)}",
        f"- **运费**: ¥{o.get('freight', 0)}",
        f"- **重量**: {o.get('weight', 0)} kg",
        "",
        "### 备注",
        f"- **买家留言**: {o.get('buyer_message', '—')}",
        f"- **卖家备注**: {o.get('remark', '—')}",
        "",
        "### 商品明细",
    ]

    items = o.get("items", [])
    if items:
        lines.extend([
            "| SKU ID | 名称 | 数量 | 单价 | 小计 |",
            "|--------|------|:---:|:----:|:----:|"
        ])
        for item in items:
            lines.append(
                f"| {item.get('sku_id', '')} | {item.get('name', '')[:25]} "
                f"| {item.get('qty', 0)} | ¥{item.get('price', 0)} "
                f"| ¥{item.get('amount', 0)} |"
            )
    else:
        lines.append("- *无商品明细*")

    return "\n".join(lines)


def format_category(result: dict) -> str:
    """格式化分类列表"""
    if result.get("code") != 0:
        return f"❌ 查询失败: {result.get('msg', '未知错误')}"
    data = result.get("data", result)
    cats = _get_datas(result)
    if not cats:
        return "❌ 未找到分类"
    lines = ["## 📂 商品分类", "", f"共 **{len(cats)}** 个分类", "",
             "| 分类ID | 父分类ID | 名称 |", "|--------|:--------:|------|"]
    for c in cats:
        lines.append(f"| {c.get('c_id','')} | {c.get('parent_c_id',0)} | {c.get('name','')} |")
    return "\n".join(lines)


def format_mall_items(result: dict) -> str:
    """格式化商城商品信息"""
    if result.get("code") != 0:
        return f"❌ 查询失败: {result.get('msg', '未知错误')}"
    datas = _get_datas(result)
    if not datas:
        return "❌ 未找到商品"
    lines = ["## 🏪 商城商品", "", f"共 **{len(datas)}** 个商品", "",
             "| SKU ID | 名称 | 品牌 | 售价 | 库存 | 重量 |",
             "|--------|------|:----:|:----:|:----:|:----:|"]
    for d in datas:
        skus = d.get("skus", [d])
        for s in skus:
            name = (s.get("name") or d.get("name") or "")[:30]
            brand = (s.get("brand") or d.get("brand") or "—")[:12]
            sku_id = s.get("sku_id") or d.get("i_id") or "—"
            price = s.get("sale_price", "—")
            qty = s.get("stock_qty", "—")
            weight = s.get("weight", "—")
            lines.append(f"| {sku_id} | {name} | {brand} | ¥{price} | {qty} | {weight}kg |")
    return "\n".join(lines)


def format_combine_sku(result: dict) -> str:
    """格式化组合SKU"""
    if result.get("code") != 0:
        return f"❌ 查询失败: {result.get('msg', '未知错误')}"
    datas = _get_datas(result)
    if not datas:
        return "❌ 未找到组合SKU"
    lines = ["## 🔗 组合SKU", "", f"共 **{len(datas)}** 个", "",
             "| SKU ID | 名称 | 售价 | 组成数量 | 标签 |",
             "|--------|------|:----:|:--------:|:----:|"]
    for d in datas:
        name = (d.get("name") or "")[:30]
        price = d.get("sale_price", "—")
        qty = d.get("sku_qty", "—")
        labels = ", ".join(d.get("labels", [])) if isinstance(d.get("labels"), list) else (d.get("labels") or "—")
        lines.append(f"| {d.get('sku_id','')} | {name} | ¥{price} | {qty} | {labels[:20]} |")
    return "\n".join(lines)


def format_sku_detail(result: dict) -> str:
    """格式化SKU详情"""
    if result.get("code") != 0:
        return f"❌ 查询失败: {result.get('msg', '未知错误')}"
    datas = _get_datas(result)
    if not datas:
        return "❌ 未找到SKU"
    lines = ["## 📦 SKU详情", "", f"共 **{len(datas)}** 个", "",
             "| SKU ID | 名称 | 条码 | 售价 | 成本 |",
             "|--------|------|:----:|:----:|:----:|"]
    for d in datas:
        name = (d.get("name") or "")[:35]
        lines.append(f"| {d.get('sku_id','')} | {name} | {d.get('barcode','')} | ¥{d.get('sale_price','—')} | ¥{d.get('cost_price','—')} |")
    return "\n".join(lines)


# ==================== 主入口 ====================

def main():
    parser = argparse.ArgumentParser(description="聚水潭ERP 智能管理系统")
    parser.add_argument("command", nargs="?",
                        choices=["shops", "skus", "stats", "orders", "search", "order", "remark", "ship", "address", "inv", "inventory", "invwms", "syncinv", "cancel", "as", "aftersale", "items", "test", "push"],
                        help="命令")
    parser.add_argument("args", nargs="*", help="额外参数")
    parser.add_argument("--shop", type=int, help="店铺ID过滤")
    parser.add_argument("--days", type=int, default=3, help="查询天数")
    parser.add_argument("--limit", type=int, default=20, help="最大返回数")
    parser.add_argument("--status", help="订单状态过滤")
    parser.add_argument("--sku", nargs="+", help="指定SKU IDs")
    parser.add_argument("--begin", help="开始时间 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--end", help="结束时间 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--idcard", help="身份证号（18位）")
    parser.add_argument("--buyer", help="买家账号")
    parser.add_argument("-p", "--push", action="store_true", help="直接推送（跳过预览确认）")

    args = parser.parse_args()

    cmd = args.command
    now = datetime.now()

    if args.begin and args.end:
        begin = args.begin
        end = args.end
    else:
        end = now.strftime("%Y-%m-%d %H:%M:%S")
        begin = (now - timedelta(days=args.days)).strftime("%Y-%m-%d 00:00:00")

    result = None

    if cmd == "shops":
        result = query_shops()
        print(format_shops(result))

    elif cmd == "skus":
        # sku.query 时间范围不能超过7天
        sku_begin = begin
        sku_end = end
        try:
            dt_end = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
            dt_begin = datetime.strptime(begin, "%Y-%m-%d %H:%M:%S")
            if (dt_end - dt_begin).days > 7:
                sku_begin = (dt_end - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
        except: pass
        # nargs="+" 传的是 list
        sku_ids = args.sku if args.sku else None
        result = query_sku(sku_ids=sku_ids)
        print(format_skus(result))

    elif cmd in ("inv", "inventory"):
        sku_ids = args.sku if args.sku else None
        result = query_inventory(sku_ids=sku_ids)
        if result.get("code") == 0:
            inv = result.get("inventory", [])
            if not inv:
                print("❌ 未找到库存数据（请用 --sku 指定SKU，或查7天内变动的商品）")
            else:
                print(f"## 📦 实时库存 ({result['total_count']})")
                print()
                print(f"| {'SKU ID':<30} | {'库存':>6} | {'已占':>6} | {'可发':>6} | {'名称'}")
                print(f"| {'-'*30} | {'-'*6}:| {'-'*6}:| {'-'*6}:| {'-'*20}")
                alert = []
                for i in inv:
                    sku = i.get('sku_id','')
                    qty = i.get('qty',0)
                    lock = i.get('order_lock',0) + i.get('pick_lock',0)
                    avail = qty - lock
                    name = i.get('name','')[:20]
                    flag = " ⚠️" if avail < 10 else ""
                    if flag: alert.append(f"  {sku}: 库存{qty} 可发{avail}")
                    print(f"| {sku:<30} | {qty:>6} | {lock:>6} | {avail:>6} | {name}{flag}")
                if alert:
                    print()
                    print("⚠️ **低库存预警** (可发<10):")
                    for a in alert:
                        print(a)
        else:
            print(f"❌ 查询失败: {result.get('msg', '未知错误')}")

    elif cmd == "invwms":
        # WMS仓库实物库存
        sku_ids = args.sku if args.sku else None
        result = query_wms_inventory(sku_ids=sku_ids)
        if result.get("code") == 0:
            inv = result.get("inventory", [])
            if not inv:
                print("❌ 未找到库存数据")
            else:
                print(f"## 🏭 WMS仓库实物库存 ({result['total_count']})")
                print()
                print(f"{'SKU ID':<30}  {'库存':>6}  {'锁定':>6}  {'名称'}")
                print("-"*60)
                for i in inv:
                    print(f"{i.get('sku_id',''):<30}  {i.get('qty',0):>6}  {i.get('lock_qty',0):>6}  {i.get('name','')[:20]}")
        else:
            print(f"❌ 查询失败: {result.get('msg', '未知错误')}")

    elif cmd == "syncinv":
        """同步ECShop库存（从JST拉取真实库存）"""
        from workflows.sync_inventory import sync_inventory
        dry_run = "--dry-run" in args.args or "-n" in args.args
        verbose = "--verbose" in args.args or "-v" in args.args
        use_virtual = "--virtual" in args.args
        lwh_id = None
        for a in args.args:
            if a.startswith("--lwh="):
                try: lwh_id = int(a.split("=")[1])
                except: pass
            if a.startswith("--virtual-warehouse="):
                try: lwh_id = int(a.split("=")[1])
                except: pass
        alert = None
        for a in args.args:
            if a.startswith("--alert="):
                try: alert = int(a.split("=")[1])
                except: pass
        if args.args and args.args[0].lstrip("-").isdigit():
            alert = int(args.args[0])
        mode = "主仓"
        if lwh_id: mode = f"虚拟仓(lwh_id={lwh_id})"
        elif use_virtual: mode = "主仓+虚拟库存"
        print(f"{'🔍 [DRY-RUN] ' if dry_run else ''}📦 同步聚水潭库存 → ECShop（{mode}）")
        sync_inventory(dry_run=dry_run, verbose=verbose, use_virtual=use_virtual, lwh_id=lwh_id)

    elif cmd == "cancel":
        if len(args.args) < 1:
            print("❌ 用法: jst_manager.py cancel <so_id或o_id> [--shop 店铺ID] [--status 原因]")
            print("   示例: jst_manager.py cancel WX0511135897 --shop 18442196")
            return
        so_id = args.args[0]
        shop_id = args.shop or DEFAULT_SHOP_ID
        remark = args.status or "客户取消"
        # 判断是 o_id 还是 so_id
        is_o_id = so_id.isdigit()
        if is_o_id:
            result = cancel_order(shop_id, o_id=so_id, remark=remark)
        else:
            result = cancel_order(shop_id, so_id=so_id, remark=remark)
        if result.get("code") == 0:
            print(f"✅ 取消成功！")
        else:
            print(f"❌ 取消失败: {result.get('msg', result)}")
        print(json.dumps(result, ensure_ascii=False, indent=2)[:300])

    elif cmd == "stats":
        result = query_order_stats(modified_begin=begin, modified_end=end,
                                   shop_id=args.shop)
        print(format_stats(result))

    elif cmd == "orders":
        result = query_orders_paginated(
            modified_begin=begin, modified_end=end,
            shop_id=args.shop, status=args.status,
            max_pages=min(args.limit // 100 + 1, 10)
        )
        # 截断到limit
        if result.get("code") == 0:
            result["orders"] = result["orders"][:args.limit]
        print(format_orders(result, f"订单列表 ({args.days}天)"))

    elif cmd == "search":
        keyword = args.args[0] if args.args else ""
        # 搜索so_id或receiver_name
        result = query_orders_paginated(
            modified_begin=begin, modified_end=end,
            shop_id=args.shop, status=args.status,
            max_pages=5, page_size=100
        )
        if result.get("code") == 0:
            matched = []
            for o in result["orders"]:
                so_id = str(o.get("so_id", "") or "")
                name = str(o.get("receiver_name", "") or "")
                o_id = str(o.get("o_id", "") or "")
                if keyword in so_id or keyword in name or keyword in o_id:
                    matched.append(o)
            result["orders"] = matched
        print(format_orders(result, f"搜索 \"{keyword}\""))

    elif cmd == "order":
        o_id = args.args[0] if args.args else ""
        if not o_id:
            print("❌ 请提供订单号 o_id")
            return
        result = query_order(o_id=o_id)
        if result.get("code") == 0:
            orders = result.get("orders", [])
            if orders:
                print(format_order_detail(orders[0]))
            else:
                # 可能查不到但能写备注
                print(f"ℹ️ o_id={o_id} 查询返回0条（可能无法查询但可写入备注）")
                print(f"返回: {json.dumps(result, ensure_ascii=False, indent=2)}")
        else:
            print(f"❌ 查询失败: {result.get('msg', '未知错误')}")
            print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "remark":
        if len(args.args) < 2:
            print("❌ 用法: jst_manager.py remark <o_id> <备注内容>")
            return
        o_id = args.args[0]
        remark = " ".join(args.args[1:])
        print(f"✏️ 写入卖家备注 o_id={o_id}")
        result = update_order_remark(o_id, remark)
        if result.get("code") == 0:
            print(f"✅ 写入成功！")
        else:
            print(f"❌ 写入失败: {result.get('msg', result)}")

    elif cmd == "ship":
        if len(args.args) < 3:
            print("❌ 用法: jst_manager.py ship <o_id> <快递编码> <快递单号>")
            print("   快递编码: SF=顺丰, JD=京东, YT=圆通, ZTO=中通, STO=申通")
            return
        o_id, lc_id, l_id = args.args[0], args.args[1], args.args[2]
        print(f"📦 登记快递 o_id={o_id}, 公司={lc_id}, 单号={l_id}")
        result = register_express(lc_id, o_id, l_id)
        if result.get("code") == 0:
            print(f"✅ 登记成功！")
        else:
            print(f"❌ 登记失败: {result.get('msg', result)}")

    elif cmd == "address":
        if len(args.args) < 2:
            print("❌ 用法: jst_manager.py address <o_id> <name> <phone> [省] [市] [区] [地址]")
            return
        o_id = args.args[0]
        kwargs = {}
        if len(args.args) > 1: kwargs["receiver_name"] = args.args[1]
        if len(args.args) > 2: kwargs["receiver_phone"] = args.args[2]
        if len(args.args) > 3: kwargs["receiver_province"] = args.args[3]
        if len(args.args) > 4: kwargs["receiver_city"] = args.args[4]
        if len(args.args) > 5: kwargs["receiver_district"] = args.args[5]
        if len(args.args) > 6: kwargs["receiver_address"] = args.args[6]
        print(f"📍 更新地址 o_id={o_id}: {kwargs}")
        result = update_order_address(o_id, **kwargs)
        if result.get("code") == 0:
            print(f"✅ 地址更新成功！")
        else:
            print(f"❌ 更新失败: {result.get('msg', result)}")

    elif cmd in ("as", "aftersale"):
        sub = args.args[0] if args.args else "help"
        if sub == "help" or not args.args:
            print("""## 🛒 售后API命令

用法: jst_manager.py as <子命令> [参数]

子命令:
  create <shop_id> <so_id> <o_id> <sku_id> <qty>  创建售后单
  confirm <as_id>                                   确认售后
  cancel <as_id>                                    取消售后
  goods <as_id>                                     确认收货
  label <as_id> <标签>                               设置标签
  search <so_id/o_id>                               查找售后(通过订单查询)
""")
        elif sub == "create":
            if len(args.args) < 6:
                print("❌ 用法: as create <shop_id> <so_id> <o_id> <sku_id> <qty>")
                return
            shop_id, so_id, o_id, sku_id, qty = int(args.args[1]), args.args[2], int(args.args[3]), args.args[4], int(args.args[5])
            items = [{"sku_id": sku_id, "qty": qty}]
            ts = str(int(__import__('time').time()))
            result = aftersale_noinfo_upload(shop_id, so_id, o_id, items)
            print(f"创建售后: {json.dumps(result, ensure_ascii=False, indent=2)[:400]}")
        elif sub == "confirm":
            result = aftersale_confirm(args.args[1])
            print(f"确认售后: {json.dumps(result, ensure_ascii=False, indent=2)[:300]}")
        elif sub == "cancel":
            result = aftersale_cancel(args.args[1])
            print(f"取消售后: {json.dumps(result, ensure_ascii=False, indent=2)[:300]}")
        elif sub == "goods":
            result = aftersale_confirm_goods(args.args[1])
            print(f"确认收货: {json.dumps(result, ensure_ascii=False, indent=2)[:300]}")
        elif sub == "label":
            if len(args.args) < 3:
                print("❌ 用法: as label <as_id> <标签>")
                return
            result = aftersale_set_labels(args.args[1], " ".join(args.args[2:]))
            print(f"设置标签: {json.dumps(result, ensure_ascii=False, indent=2)[:300]}")
        elif sub == "search":
            keyword = args.args[1] if len(args.args) > 1 else ""
            r = query_orders_paginated(modified_begin=begin, modified_end=end, max_pages=3)
            if r.get("code") == 0:
                orders = r["orders"]
                matched = [o for o in orders if keyword in str(o.get("so_id","")) or keyword in str(o.get("o_id",""))]
                if matched:
                    print(f"找到 {len(matched)} 个订单:")
                    for o in matched:
                        print(f"  o_id={o['o_id']} | so_id={o.get('so_id','')[:25]} | "
                              f"金额=¥{o.get('pay_amount',0)} | {o.get('receiver_name','')} | "
                              f"状态={o.get('status','')}")
                        print(f"  要创建售后: as create {o.get('shop_id')} {o.get('so_id')} {o['o_id']} <sku_id> <qty>")
                else:
                    print("未找到匹配订单")
        else:
            print(f"❌ 未知子命令: {sub}，可用: create/confirm/cancel/goods/label/search/help")

    elif cmd == "items":
        sub = args.args[0] if args.args else "help"
        if sub == "help" or not args.args:
            print("""## 📦 商品/类目管理命令

用法: jst_manager.py items <子命令> [参数]

子命令:
  help                              显示此帮助
  category                          查询商品分类列表
  mall [--sku SKU_ID]              查询商城商品信息
  combine [--sku SKU_ID]           查询组合SKU
  sku [--sku SKU_ID]               查询SKU详情（新API）
  skumap [--sku SKU_CODE]          查询SKU映射关系
  catadd <名称> [--pid 父ID]       新增分类
  bind <sku_id> <sku_code>         绑定SKU链接
  sup <sku_id> <供应商sku_id>       保存供应商SKU
  upload <json_file>               批量上传SKU（JSON文件）
  mapupload <json_file>            上传SKU映射（JSON文件）

可选参数:
  --sku SKU_ID  指定SKU（逗号分隔多个）
""")
        elif sub == "category":
            result = query_category(page_size=100)
            print(format_category(result))
        elif sub == "mall":
            sku_ids = ",".join(args.sku) if args.sku else None
            result = query_mall_items(sku_ids=sku_ids)
            print(format_mall_items(result))
        elif sub == "combine":
            sku_ids = ",".join(args.sku) if args.sku else None
            result = query_combine_sku(sku_ids=sku_ids)
            print(format_combine_sku(result))
        elif sub == "sku":
            sku_ids = ",".join(args.sku) if args.sku else None
            result = query_sku_detail(sku_ids=sku_ids)
            print(format_sku_detail(result))
        elif sub == "skumap":
            codes = ",".join(args.sku) if args.sku else None
            # skumap 时间间隔不能超7天
            skm_begin = begin
            try:
                dt_end = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
                dt_begin = datetime.strptime(begin, "%Y-%m-%d %H:%M:%S")
                if (dt_end - dt_begin).days > 7:
                    skm_begin = (dt_end - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
            except: pass
            result = query_sku_map(sku_codes=codes,
                                   modified_begin=skm_begin, modified_end=end)
            if result.get("code") == 0:
                maps = _get_datas(result)
                print(f"## 🗺️ SKU映射 (共{len(maps)}条)")
                print()
                for m in maps:
                    print(f"  {m.get('sku_code','')} → {m.get('sku_id','')}  [{m.get('shop_name','')}]")
            else:
                print(f"❌ 查询失败: {result.get('msg', result)}")
        elif sub == "catadd":
            if len(args.args) < 2:
                print("❌ 用法: items catadd <分类名称> [--pid 父分类ID]")
                return
            name = " ".join(args.args[1:])
            pid = getattr(args, 'shop', None)  # 复用 --shop 参数作为 parent_c_id
            result = add_or_update_category(name, parent_c_id=pid or 0)
            if result.get("code") == 0:
                print(f"✅ 分类「{name}」创建/更新成功！")
            else:
                print(f"❌ 失败: {result.get('msg', result)}")
        elif sub == "bind":
            if len(args.args) < 3:
                print("❌ 用法: items bind <sku_id> <sku_code>")
                return
            result = bind_sku_links(args.args[1], args.args[2])
            print(json.dumps(result, ensure_ascii=False, indent=2)[:300])
        elif sub == "sup":
            if len(args.args) < 3:
                print("❌ 用法: items sup <sku_id> <供应商sku_id>")
                return
            result = save_supplier_sku(args.args[1], args.args[2])
            print(json.dumps(result, ensure_ascii=False, indent=2)[:300])
        elif sub == "upload":
            if len(args.args) < 2:
                print("❌ 用法: items upload <json_file>")
                return
            with open(args.args[1]) as f:
                items = json.load(f)
            result = batch_upload_sku(items)
            print(json.dumps(result, ensure_ascii=False, indent=2)[:400])
        elif sub == "mapupload":
            if len(args.args) < 2:
                print("❌ 用法: items mapupload <json_file>")
                return
            with open(args.args[1]) as f:
                items = json.load(f)
            result = upload_sku_map(items)
            print(json.dumps(result, ensure_ascii=False, indent=2)[:400])
        else:
            print(f"❌ 未知子命令: {sub}，可用: category/mall/combine/sku/skumap/catadd/bind/sup/upload/mapupload/help")

    elif cmd == "test":
        # 综合测试
        print("## 🔬 聚水潭API综合测试\n")
        print("### 1️⃣ 店铺查询")
        s = query_shops()
        print(f"✅ 店铺数: {len(s.get('shops',[]))}\n")
        print("### 2️⃣ SKU查询")
        sk = query_sku(page_size=5)
        print(f"✅ SKU数: {len(sk.get('skus',[]))}\n")
        print("### 3️⃣ 订单统计")
        st = query_order_stats(modified_begin=begin, modified_end=end)
        print(f"✅ 订单: {st.get('total_orders',0)}单 ¥{st.get('total_amount',0):,.2f}\n")
        print("### 4️⃣ 订单写入备注测试")
        # 找一个近期的o_id测试
        orders_res = query_orders_by_time(page_size=1)
        if orders_res.get("code") == 0 and orders_res.get("orders"):
            test_o_id = orders_res["orders"][0]["o_id"]
            r = update_order_remark(test_o_id, "[JST Manager 测试备注]")
            print(f"✅ 备注写入 o_id={test_o_id}: {'成功' if r.get('code')==0 else '失败'}")
        print("\n✅ 所有API测试完成！")

    # ── push: 订单推送 ───────────────────────────────────────────
    elif cmd == "push":
        order_text = " ".join(args.args)
        if not order_text:
            print("❌ 用法: jst_manager.py push <订单文本> [--shop ID] [--idcard X] [--buyer X] [-p]")
            print()
            print("示例:")
            print("  # 预览模式（不推送）")
            print("  jst_manager.py push \"张三 13800138000 广东省深圳市 三合一x2\"")
            print()
            print("  # 直接推送")
            print("  jst_manager.py push \"张三 13800138000 广东省深圳市 三合一x2\" --shop 18442196 --idcard 510902197001011234 -p")
            return

        shop_id = args.shop or 20941412
        print(f"📋 订单解析中... (店铺: {shop_id})")

        system = OrderPushSystem()
        result = system.process_order(
            order_text=order_text,
            shop_id=shop_id,
            buyer_id=args.buyer,
            id_card=args.idcard,
            auto_push=args.push,
        )

        if result.get("success"):
            if result.get("preview"):
                # 预览模式
                orders = result.get("orders", [])
                print(f"\n📋 预览 ({len(orders)} 个子订单):")
                for i, o in enumerate(orders):
                    items = o.get("items", [])
                    item_str = " / ".join(
                        f"{it.get('name','?')}×{it.get('qty',0)}" for it in items
                    ) or "未识别到商品"
                    print(f"  {i+1}. {o.get('receiver_name','?')} | {o.get('receiver_phone','?')}")
                    print(f"     {o.get('receiver_province','')}{o.get('receiver_city','')}{o.get('receiver_district','')}{o.get('receiver_address','')}")
                    print(f"     {item_str}")
                    if o.get("id_card"):
                        print(f"     身份证: {o['id_card'][:6]}****{o['id_card'][-4:]}")
                print(f"\n回复「确认」或「推送」正式推送，或加 -p 直接推送")
            else:
                # 已推送
                orders = result.get("orders", [])
                pushed = len(orders)
                verified = result.get("verified", False)
                jst_o_id = result.get("jst_o_id")
                print(f"\n✅ 成功推送 {pushed} 个订单")
                if verified:
                    print(f"   JST o_id: {jst_o_id}")
        else:
            code = result.get("code", "")
            msg = result.get("msg", "未知错误")
            name_mismatch = result.get("name_mismatch", False)

            if code == -2:
                # 需要身份证上传
                print(f"\n📷 {msg}")
            elif code == -3 or name_mismatch:
                # P3 姓名不匹配
                print(f"\n🚨 身份证姓名与收件人不一致 — 订单已阻断")
                print(msg)
            else:
                print(f"\n❌ 推送失败: {msg}")
                if result.get("order"):
                    o = result["order"]
                    print(f"   订单: {o.get('receiver_name','?')} | {o.get('receiver_phone','?')}")

        # push 命令不参加后面的 code!=0 检查
        sys.exit(0)

    if result is not None and result.get("code") != 0 and cmd not in ("remark", "ship", "address", "test"):
        print(f"\n⚠️ API返回错误: {result.get('msg', '')}", file=sys.stderr)


if __name__ == "__main__":
    main()
