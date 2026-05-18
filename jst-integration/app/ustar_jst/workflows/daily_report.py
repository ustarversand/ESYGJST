#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店铺销售明细即时查询脚本
用法: python query_shop_sales.py <店铺名称或ID> [天数]

示例:
  python query_shop_sales.py AUSTARWX 7        # 查询AUSTARWX最近7天销售
  python query_shop_sales.py 18442196 30    # 查询店铺ID 18442196 最近30天销售
  python query_shop_sales.py A路久           # 查询A路久最近7天(默认)
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from domains.order_api import query_orders_by_date
from core.config import SHOP_CONFIG, SHOP_ABBR_MAP


def normalize_shop_input(shop_input: str) -> tuple:
    """
    将用户输入的店铺名称/ID转换为标准的店铺ID
    
    支持的输入格式:
    - 店铺名称: "AUSTARWX", "A路久"
    - 店铺ID: "18442196"
    - 简写: "路久", "清田" 等
    
    Returns:
        (shop_id: int, shop_name: str, platform: str)
    """
    shop_input = shop_input.strip()
    
    # 1. 尝试直接作为数字ID处理
    if shop_input.isdigit():
        shop_id = int(shop_input)
        # 查找店铺名
        for name, config in SHOP_CONFIG.items():
            if str(config.get("id")) == str(shop_id):
                return shop_id, config.get("name"), config.get("platform", "未知")
        return shop_id, f"店铺{shop_id}", "未知"
    
    # 2. 精确匹配店铺名称
    if shop_input in SHOP_CONFIG:
        config = SHOP_CONFIG[shop_input]
        return int(config["id"]), config["name"], config.get("platform", "未知")
    
    # 3. 尝试简写匹配
    for full_name, abbr in SHOP_ABBR_MAP.items():
        if abbr == shop_input or full_name.startswith(shop_input):
            config = SHOP_CONFIG[full_name]
            return int(config["id"]), config["name"], config.get("platform", "未知")
    
    # 4. 模糊匹配（在名称中包含输入字符串）
    for name, config in SHOP_CONFIG.items():
        if shop_input in name:
            return int(config["id"]), config["name"], config.get("platform", "未知")
    
    raise ValueError(f"未找到店铺: {shop_input}")


def query_shop_sales(shop_name_or_id: str, days: int = 7) -> dict:
    """
    查询指定店铺的销售明细
    
    Args:
        shop_name_or_id: 店铺名称或ID
        days: 查询天数（默认7天）
    
    Returns:
        销售明细字典
    """
    # 解析店铺
    shop_id, shop_name, platform = normalize_shop_input(shop_name_or_id)
    
    # 计算日期范围
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days-1)
    
    start_time = start_date.strftime("%Y-%m-%d 00:00:00")
    end_time = end_date.strftime("%Y-%m-%d 23:59:59")
    
    # 查询订单
    print(f"正在查询 {shop_name}(ID: {shop_id}) 最近{days}天销售...")
    result = query_orders_by_date(shop_id, start_time, end_time)
    
    if result.get("code") != 0:
        return {
            "success": False,
            "error": result.get("msg", "查询失败"),
            "shop_id": shop_id,
            "shop_name": shop_name
        }
    
    orders = result.get("orders", [])
    
    # 统计销售数据
    total_orders = len(orders)
    total_amount = 0.0
    product_stats = {}
    
    for order in orders:
        # 计算订单金额
        amount = float(order.get("pay_amount", 0) or 0)
        total_amount += amount
        
        # 统计商品
        items = order.get("order_items", [])
        for item in items:
            product_name = item.get("product_name", "未知商品")
            quantity = int(item.get("quantity", 0) or 0)
            price = float(item.get("price", 0) or 0)
            
            if product_name in product_stats:
                product_stats[product_name]["qty"] += quantity
                product_stats[product_name]["amount"] += price * quantity
            else:
                product_stats[product_name] = {
                    "qty": quantity,
                    "amount": price * quantity
                }
    
    # 按销售额排序商品
    top_products = sorted(
        product_stats.items(),
        key=lambda x: x[1]["amount"],
        reverse=True
    )[:10]
    
    return {
        "success": True,
        "shop_id": shop_id,
        "shop_name": shop_name,
        "platform": platform,
        "date_range": f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
        "days": days,
        "total_orders": total_orders,
        "total_amount": total_amount,
        "top_products": [
            {"name": name, "qty": stats["qty"], "amount": stats["amount"]}
            for name, stats in top_products
        ]
    }


def format_report(data: dict) -> str:
    """将销售数据格式化为Markdown报告"""
    if not data.get("success"):
        return f"❌ 查询失败: {data.get('error')}"
    
    lines = [
        f"## 📊 {data['shop_name']} 销售明细",
        "",
        f"**平台**: {data['platform']}",
        f"**店铺ID**: {data['shop_id']}",
        f"**查询周期**: {data['date_range']} ({data['days']}天)",
        "",
        "---",
        "",
        f"### 📈 销售概览",
        "",
        f"- **订单数**: {data['total_orders']} 单",
        f"- **销售金额**: ¥{data['total_amount']:,.2f}",
        "",
    ]
    
    if data["top_products"]:
        lines.extend([
            "---",
            "",
            "### 🏆 TOP 10 热销商品",
            "",
        ])
        
        for i, product in enumerate(data["top_products"], 1):
            lines.append(
                f"{i}. **{product['name']}** - "
                f"{product['qty']}件 / ¥{product['amount']:,.2f}"
            )
    
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="查询店铺销售明细")
    parser.add_argument("shop", help="店铺名称或ID")
    parser.add_argument("days", nargs="?", type=int, default=7, help="查询天数(默认7天)")
    
    args = parser.parse_args()
    
    try:
        result = query_shop_sales(args.shop, args.days)
        print(format_report(result))
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 查询出错: {e}")
        sys.exit(1)