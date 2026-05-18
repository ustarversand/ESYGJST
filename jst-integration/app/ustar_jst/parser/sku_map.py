#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品SKU映射模块 - SKU映射表 + 商品映射器 + 奶粉拆单
"""
import logging
from typing import List, Tuple
from parser.order_parser import OrderItem, WeChatOrder

MILK_POWDER_KEYWORDS = ["奶粉", "奶粉pre", "奶粉1段", "奶粉2段", "奶粉3段", "奶粉1+", "奶粉2+",
                        "德爱", "爱他美", "喜宝", "BEBA", "至尊", "牛栏", "白金"]

MILK_POWDER_SKU = {
    "德爱白金pre": {"sku": "4056631003435BJP", "price": 195},
    "德爱白金1段": {"sku": "4056631003459BJ1", "price": 195},
    "德爱白金2段": {"sku": "4056631003473BJ2", "price": 195},
    "至尊1+": {"sku": "7613287296085ZZ1+", "price": 145},
    "至尊pre": {"sku": "7613287226631ZZPR", "price": 195},
    "至尊1段": {"sku": "7613036456418ZZ1", "price": 195},
    "至尊2段": {"sku": "7613287226679ZZ2", "price": 195},
}


# 需要身份证的店铺
SHOPS_REQUIRING_IDCARD = [
    18442196,  # AUSTARWX
    16896076,  # A路久
    19437979,  # 德聚小罗
    18559895,  # 阿美奶粉
    18614842,  # 夏总WX
    16631713,  # 夏总天海易购
    18283794,  # 武姐
    18331345,  # 韦峥
]

# 店铺配置
SHOP_CONFIG = {
    18442196: {"name": "AUSTARWX", "buyer_id": "AUSTARWX"},
    18020520: {"name": "沐浴阳光PDD", "buyer_id": "沐浴阳光PDD"},
    17288013: {"name": "甘总-付总", "buyer_id": "甘总-付总"},
    18422496: {"name": "沐浴阳光JD", "buyer_id": "沐浴阳光JD"},
    16896076: {"name": "A路久", "buyer_id": "A路久"},
    19437979: {"name": "德聚小罗", "buyer_id": "德聚小罗"},
    18559895: {"name": "阿美奶粉", "buyer_id": "阿美奶粉"},
    18614842: {"name": "夏总WX", "buyer_id": "夏总WX"},
    16631713: {"name": "夏总天海易购", "buyer_id": "夏总天海易购"},
    18283794: {"name": "武姐", "buyer_id": "武姐"},
    18331345: {"name": "韦峥", "buyer_id": "韦峥"},
    18334864: {"name": "Asweety", "buyer_id": "Asweety"},
}

# 商品SKU映射（常用商品）
PRODUCT_SKU_MAP = {
    "基础三合一套装": "1SFCC97001079SHY",
    "基础二合一套装": "1SFCC9700731EHY",
    "小红": "0708023XH",
    "小白": "0702037XB",
    "大白": "0705018DB",
    "复合大白": "0705012FHDB",
    "桃子小红": "0708065XHTZ",
    "肽美": "0709028TM",
    "小粉": "0709048XF",
    "叶黄素": "0712020YHS",
    "异黄酮": "0712021YHT",
    "氨基酸": "0704022AJS",
    "乐活": "0705044LHTK",
    "排毒饮": "0702069PDY",
    "橙子抗氧化": "0707008KYH",
    "苹果抗氧化": "0707008KYH",
    "德爱白金pre": "4056631003435BJP",
    "德爱白金1段": "4056631003459BJ1",
    "德爱白金2段": "4056631003473BJ2",
    "至尊1+": "7613287296085ZZ1+",
}

class ProductMapper:
    """商品映射器"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.sku_map = PRODUCT_SKU_MAP.copy()

    def get_sku(self, product_name: str) -> Tuple[str, float]:
        """
        获取商品SKU编码和价格

        Returns:
            (sku_id, price) 元组
        """
        if not product_name:
            return "", 0

        name_lower = product_name.lower().strip()

        # 精确匹配
        if name_lower in self.sku_map:
            sku = self.sku_map[name_lower]
            price = self._get_price(sku)
            return sku, price

        # 模糊匹配
        for key, sku in self.sku_map.items():
            if key in name_lower or name_lower in key:
                price = self._get_price(sku)
                self.logger.info(f"商品匹配: {product_name} -> {sku}")
                return sku, price

        # 检查是否是奶粉商品
        for keyword in MILK_POWDER_KEYWORDS:
            if keyword in name_lower:
                for milk_key, milk_info in MILK_POWDER_SKU.items():
                    if milk_key in name_lower:
                        self.logger.info(f"奶粉商品匹配: {product_name} -> {milk_info['sku']}")
                        return milk_info['sku'], milk_info['price']

        self.logger.warning(f"未找到商品SKU: {product_name}")
        return product_name, 0

    def _get_price(self, sku: str) -> float:
        """获取商品价格"""
        # 奶粉特殊价格
        for milk_key, milk_info in MILK_POWDER_SKU.items():
            if milk_info['sku'] == sku:
                return milk_info['price']
        return 0

class MilkPowderSplitter:
    """奶粉拆单器"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def is_milk_powder(self, product_name: str) -> bool:
        """判断是否是奶粉商品"""
        name_lower = product_name.lower()
        return any(keyword in name_lower for keyword in MILK_POWDER_KEYWORDS)

    def split_order(self, order: WeChatOrder) -> List[WeChatOrder]:
        """
        拆分奶粉订单

        规则：奶粉2罐一个订单
        """
        split_orders = []

        for item in order.items:
            if self.is_milk_powder(item.name):
                # 奶粉需要拆单
                qty = item.qty
                split_count = (qty + 1) // 2  # 向上取整

                self.logger.info(f"奶粉拆单: {item.name} x{qty} -> {split_count}个订单")

                for i in range(split_count):
                    new_order = WeChatOrder()
                    new_order.order_id = f"{order.order_id}-{i+1}"
                    new_order.receiver_name = order.receiver_name
                    new_order.receiver_phone = order.receiver_phone
                    new_order.receiver_province = order.receiver_province
                    new_order.receiver_city = order.receiver_city
                    new_order.receiver_district = order.receiver_district
                    new_order.receiver_address = order.receiver_address
                    new_order.id_card = order.id_card
                    new_order.remark = order.remark
                    new_order.shop_id = order.shop_id

                    # 每个子订单2罐
                    item_qty = 2 if (i * 2 + 2) <= qty else (qty - i * 2)
                    new_order.items.append(OrderItem(
                        name=item.name,
                        qty=item_qty,
                        sku_id=item.sku_id,
                        price=item.price
                    ))

                    split_orders.append(new_order)
            else:
                # 非奶粉商品不拆单
                split_orders.append(order)

        return split_orders if split_orders else [order]
