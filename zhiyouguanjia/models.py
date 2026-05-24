"""直邮管家 — 数据模型（dataclass版）"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class OrderItem:
    """商品项"""
    sku_id: str = ""
    name: str = ""
    qty: int = 1
    price: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WeChatOrder:
    """订单数据"""
    order_id: str = ""
    receiver_name: str = ""
    receiver_phone: str = ""
    receiver_province: str = ""
    receiver_city: str = ""
    receiver_district: str = ""
    receiver_address: str = ""
    id_card: str = ""
    items: List[OrderItem] = field(default_factory=list)
    buyer_message: str = ""  # 买家留言
    shop_id: str = ""
    pay_amount: float = 0.0
    freight: float = 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data['items'] = [item.to_dict() for item in self.items]
        return data
