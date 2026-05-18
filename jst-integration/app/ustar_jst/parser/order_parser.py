#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订单解析模块 - 文本解析 + 数据模型
"""
import re
import datetime
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

from core.jst_client import DEFAULT_SHOP_ID, DEFAULT_BUYER_ID

class OrderStatus(Enum):
    """订单状态"""
    PENDING = "待确认"
    CONFIRMED = "已确认"
    PUSHED = "已推送"
    FAILED = "推送失败"

@dataclass
class OrderItem:
    """订单商品项"""
    sku_id: str = ""
    name: str = ""
    qty: int = 1
    price: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class WeChatOrder:
    """微信订单数据"""
    order_id: str = ""
    receiver_name: str = ""
    receiver_phone: str = ""
    receiver_province: str = ""
    receiver_city: str = ""
    receiver_district: str = ""
    receiver_address: str = ""
    id_card: str = ""
    items: List[OrderItem] = field(default_factory=list)
    remark: str = ""  # 买家留言
    seller_remark: str = ""  # 卖家备注（商家填写）
    shop_id: int = DEFAULT_SHOP_ID
    status: OrderStatus = OrderStatus.PENDING

    def to_dict(self) -> dict:
        data = asdict(self)
        data['status'] = self.status.value
        data['items'] = [item.to_dict() for item in self.items]
        return data

class OrderParser:
    """订单解析器"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def parse_text(self, text: str) -> WeChatOrder:
        """
        解析文本格式的微信订单

        支持格式：
        1. 姓名 电话 地址 商品-数量
        2. 姓名，电话，地址，商品
        3. 收件人：xxx 电话：xxx 地址：xxx 商品：xxx
        """
        order = WeChatOrder()

        # 清理文本
        text = text.strip()
        text = text.replace('\n', ' ').replace('\t', ' ')

        # 生成订单号（规则：年月日+店铺缩写+序列号）
        now = datetime.datetime.now()
        today_str = now.strftime('%y%m%d')  # 260511
        
        # 从shop_config导入店铺缩写获取函数
        from core.config import get_shop_abbr
        shop_abbr = get_shop_abbr(order.shop_id) if hasattr(order, 'shop_id') else "AUSTAR"

        # 生成序列号（当天顺序递增，简单用时间戳后3位）
        seq = now.strftime('%H%M%S')
        
        order.order_id = f"{today_str}{shop_abbr}{seq}"

        # 提取电话（11位手机号）
        phone_pattern = r'1[3-9]\d{9}'
        phone_match = re.search(phone_pattern, text)
        if phone_match:
            order.receiver_phone = phone_match.group()
            # 移除电话部分，避免干扰其他提取
            text = text.replace(order.receiver_phone, '')

        # 提取姓名（通常在开头）
        name_patterns = [
            r'^([^\s\d]{2,4})[\s,，]',  # 姓名+分隔符
            r'收件人[：:]\s*([^\s\d]{2,4})',  # 收件人：xxx
            r'姓名[：:]\s*([^\s\d]{2,4})',  # 姓名：xxx
        ]
        for pattern in name_patterns:
            match = re.search(pattern, text)
            if match:
                order.receiver_name = match.group(1)
                break

        # 提取地址（省市区）
        province_pattern = r'(江苏省|浙江省|安徽省|福建省|甘肃省|广东省|广西省|贵州省|海南省|河北省|河南省|黑龙江省|湖北省|湖南省|吉林省|江西省|辽宁省|青海省|山东省|山西省|陕西省|四川省|台湾省|云南省|重庆市|北京市|天津市|上海市|香港|澳门|内蒙古|宁夏|新疆|西藏)'
        province_match = re.search(province_pattern, text)
        if province_match:
            order.receiver_province = province_match.group(1)
            # 提取市
            city_pattern = f'{order.receiver_province}([^市{{}}市{{}}区]{{2,7}}市)'
            city_match = re.search(city_pattern, text)
            if city_match:
                order.receiver_city = city_match.group(1)
            # 提取区
            district_pattern = f'{order.receiver_province}{order.receiver_city}([^区{{}}区]{{2,7}}区)'
            district_match = re.search(district_pattern, text)
            if district_match:
                order.receiver_district = district_match.group(1)

            # 提取详细地址
            address_pattern = f'{order.receiver_province}{order.receiver_city}{order.receiver_district}(.+?)(?=商品|$)'
            address_match = re.search(address_pattern, text)
            if address_match:
                raw_address = address_match.group(1).strip()
                # 清理混入地址的商品信息（奶粉、快递等）
                cleaned = re.sub(r'白金\d*[段盒]*[*×x]\d+\s*(顺丰|京东|中通|圆通|韵达|邮政)?', '', raw_address)
                cleaned = re.sub(r'(顺丰|京东|中通|圆通|韵达|邮政)\s*$', '', cleaned)
                cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                order.receiver_address = cleaned if cleaned else raw_address

# 提取商品（先移除备注相关内容，避免误匹配）
        # 先移除身份证，避免干扰商品解析
        text_no_idcard = re.sub(r'身份证[：:]\s*\d{17}[\dXx]', '', text)
        # 再移除卖家备注和备注行，避免干扰商品解析
        text_clean = re.sub(r'卖家备注[：:].+?(?=\n|$)', '', text_no_idcard)
        text_clean = re.sub(r'备注[：:].+?(?=\n|$)', '', text_clean)
        
        # 提取商品 - 支持多行商品格式
        product_patterns = [
            r'商品[：:]\s*(.+?)(?=商品名称|身份证|备注|$)',  # 商品：xxx
            r'商品名称[：:]\s*(.+?)(?=数量|商品|身份证|备注|$)',  # 商品名称：xxx
        ]
        
        for pattern in product_patterns:
            matches = re.findall(pattern, text_clean)
            for match in matches:
                product_info = match.strip()
                if not product_info:
                    continue
                # 检查是否有数量
                qty_match = re.search(r'[-×x]\s*(\d+)(?:罐|盒|袋)?', product_info)
                if qty_match:
                    product_name = re.sub(r'[-×x]\s*\d+(?:罐|盒|袋)?\s*$', '', product_info).strip()
                    qty = int(qty_match.group(1))
                else:
                    # 检查是否有 "数量：x" 或 "数量：x"
                    qty_match2 = re.search(r'数量[：:]\s*(\d+)', text_no_idcard)
                    if qty_match2:
                        qty = int(qty_match2.group(1))
                        product_name = product_info
                    else:
                        product_name = product_info
                        qty = 1
                if product_name:
                    order.items.append(OrderItem(name=product_name, qty=qty))
        
# 如果没匹配到，尝试更简单的模式（排除"卖家"关键词）
        if not order.items:
            simple_pattern = r'([^\s]+[合一段罐盒袋])\s*[-×x]?\s*(\d+)(?!\s*卖家)'
            simple_matches = re.findall(simple_pattern, text_clean)
            for name, qty in simple_matches:
                order.items.append(OrderItem(name=name, qty=int(qty)))

# 提取卖家备注和备注
        
        # 找到卖家备注的内容 - 包含"卖家备"关键词
        if '卖家备注：' in text:
            # 找到关键词后面位置
            start = text.find('卖家备注：') + 5
            # 找到这段内容的结束（下一个关键词或字符串结尾）
            end = len(text)
            for kw in [' 备注：', '商品：', '身份证']:
                kw_pos = text.find(kw, start)
                if kw_pos > 0 and kw_pos < end:
                    end = kw_pos
                    
            order.seller_remark = text[start:end].strip()
        
        # 找买家备注 - 通过定位非seller的备注
        # 思路：先把text中seller部分 temporarily替换，然后在剩余里找
        temp_text = text
        if order.seller_remark:
            # 把seller部分替换为空字符串
            temp_text = temp_text.replace('卖家备注：' + order.seller_remark, '')
        
        # 然后找普通备注
        if '备注：' in temp_text:
            start = temp_text.find('备注：') + 3
            # 找到内容结束
            end = len(temp_text)
            for kw in ['商品：', '身份证']:
                kw_pos = temp_text.find(kw, start)
                if kw_pos > 0 and kw_pos < end:
                    end = kw_pos
            
            order.remark = temp_text[start:end].strip()

        # 提取身份证（18位）- 最后提取
        idcard_pattern = r'([1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx])'
        idcard_match = re.search(idcard_pattern, text)
        if idcard_match:
            order.id_card = idcard_match.group(1)

        self.logger.info(f"解析订单: {order.receiver_name} - {order.receiver_phone}")
        return order
