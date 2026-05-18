"""
ECShop API Client — 封装对本地 NAS ECShop API (localhost:8082/v2) 的所有调用
v2 — 统一重试装饰器 + 告警钩子
"""
import os
import time
import json
import logging
import requests
from functools import wraps
from typing import Optional, Dict, List, Callable

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("ECSHOP_API_URL", "http://192.168.178.26:8082/v2")
AUTH_HEADER = "X-ECAPI-Authorization"

# 默认重试参数
MAX_RETRIES = int(os.environ.get("ECSHOP_MAX_RETRIES", "3"))
RETRY_DELAY = float(os.environ.get("ECSHOP_RETRY_DELAY", "1.0"))


# ==================== 重试装饰器 ====================

def ecshop_retry(func: Callable) -> Callable:
    """ECShop API 重试装饰器（指数退避）"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        last_exc = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                last_exc = e
                logger.warning(
                    f"[{func.__name__}] attempt {attempt + 1}/{MAX_RETRIES + 1} failed: {e}"
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * (2 ** attempt))
        raise last_exc
    return wrapper


# ==================== 告警钩子 ====================

class ECShopAlertHook:
    def __init__(self):
        self._handlers: List[Callable] = []

    def register(self, handler: Callable[[str, Exception], None]):
        self._handlers.append(handler)

    def alert(self, title: str, exc: Exception):
        for h in self._handlers:
            try:
                h(title, exc)
            except Exception as e:
                logger.error(f"ECShop alert handler error: {e}")


_ecshop_alert_hook = ECShopAlertHook()


def register_ecshop_alert(handler: Callable[[str, Exception], None]):
    _ecshop_alert_hook.register(handler)


# ==================== 异常 ====================

class ECShopAPIError(Exception):
    """ECShop API 调用异常"""

    def __init__(self, code: int, desc: str, debug_id: Optional[str] = None):
        self.code = code
        self.desc = desc
        self.debug_id = debug_id
        super().__init__(f"[{code}] {desc} (debug: {debug_id})")

    def to_dict(self) -> Dict:
        return {"code": self.code, "desc": self.desc, "debug_id": self.debug_id}


# ==================== 客户端 ====================

class ECShopClient:
    """ECShop API 客户端，自动管理登录和 token"""

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.token: Optional[str] = None
        self.user_info: Optional[Dict] = None
        self._token_expires_at: float = 0
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # ─────────────── 基础请求 ───────────────

    @ecshop_retry
    def _post(self, endpoint: str, data: dict = None, need_auth: bool = False) -> dict:
        """POST 请求，自动处理 token（已内置重试）"""
        url = f"{BASE_URL}/{endpoint}"
        headers = {"Content-Type": "application/json"}
        if need_auth:
            self._ensure_login()
            headers[AUTH_HEADER] = self.token

        resp = self._session.post(url, json=data or {}, headers=headers, timeout=15)
        result = resp.json()

        if result.get("error_code") and result["error_code"] != 0:
            exc = ECShopAPIError(
                result.get("error_code", -1),
                result.get("error_desc", "未知错误"),
                result.get("debug_id"),
            )
            # 认证失败不重试，直接告警
            if result.get("error_code") in (401, 403):
                _ecshop_alert_hook.alert(f"⚠️ ECShop 认证失败 [{endpoint}]", exc)
            raise exc

        return result

    # ─────────────── 登录 ───────────────

    def _ensure_login(self):
        """确保 token 有效，过期自动重登"""
        if self.token and time.time() < self._token_expires_at:
            return
        result = self._post("ecapi.auth.signin", {
            "username": self.username,
            "password": self.password,
        })
        self.token = result["token"]
        self.user_info = result["user"]
        self._token_expires_at = time.time() + 40000  # ~11小时

    def login(self) -> dict:
        """显式登录，返回用户信息"""
        self._ensure_login()
        return self.user_info

    # ─────────────── 商品 ───────────────

    @ecshop_retry
    def search_products(self, keywords: str, page: int = 1, per_page: int = 10) -> List[Dict]:
        """搜索商品（需登录以获取完整会员等级结果）"""
        result = self._post(
            "ecapi.search.product.list",
            {"keywords": keywords, "page": page, "per_page": per_page},
            need_auth=True,
        )
        return result.get("products", [])

    @ecshop_retry
    def list_products(self, page: int = 1, per_page: int = 10) -> List[Dict]:
        """商品列表（需登录以获取完整会员等级商品）"""
        result = self._post(
            "ecapi.product.list",
            {"page": page, "per_page": per_page},
            need_auth=True,
        )
        return result.get("products", [])

    @ecshop_retry
    def get_product(self, product_id: int) -> Dict:
        """商品详情（含规格/属性/图片）"""
        result = self._post("ecapi.product.get", {"product": product_id})
        return result["product"]

    @ecshop_retry
    def list_categories(self, page: int = 1, per_page: int = 50) -> List[Dict]:
        """分类列表"""
        result = self._post(
            "ecapi.category.list",
            {"page": page, "per_page": per_page},
        )
        return result.get("categories", [])

    # ─────────────── 收货地址 ───────────────

    @ecshop_retry
    def list_consignees(self) -> List[Dict]:
        """收货地址列表"""
        result = self._post("ecapi.consignee.list", {}, need_auth=True)
        return result.get("consignees", [])

    # ─────────────── 购物车 ───────────────

    @ecshop_retry
    def cart_get(self) -> List[Dict]:
        """获取购物车"""
        result = self._post("ecapi.cart.get", {}, need_auth=True)
        groups = result.get("goods_groups", [])
        items = []
        for g in groups:
            items.extend(g.get("goods", []))
        return items

    @ecshop_retry
    def cart_add(
        self, product_id: int, quantity: int = 1, specs: List = None
    ) -> Dict:
        """加购物车（支持规格属性）"""
        data = {"product": product_id, "amount": quantity}
        if specs:
            data["property"] = json.dumps(specs, separators=(",", ":"))
        result = self._post("ecapi.cart.add", data, need_auth=True)
        return result

    @ecshop_retry
    def cart_delete(self, good_id: int) -> Dict:
        """删除购物车项"""
        result = self._post("ecapi.cart.delete", {"good": str(good_id)}, need_auth=True)
        return result

    @ecshop_retry
    def cart_clear(self) -> Dict:
        """清空购物车"""
        result = self._post("ecapi.cart.clear", {}, need_auth=True)
        return result

    @ecshop_retry
    def cart_update(self, good_id: int, quantity: int) -> Dict:
        """更新数量"""
        result = self._post(
            "ecapi.cart.update",
            {"good": str(good_id), "amount": quantity},
            need_auth=True,
        )
        return result

    @ecshop_retry
    def cart_checkout(
        self,
        consignee_id: int,
        shipping_id: int = 25,
        cart_good_ids: List[int] = None,
    ) -> Dict:
        """提交订单（结算）"""
        data = {
            "consignee": consignee_id,
            "shipping": shipping_id,
            "cart_good_id": json.dumps(cart_good_ids or [], separators=(",", ":")),
        }
        result = self._post("ecapi.cart.checkout", data, need_auth=True)
        return result

    @ecshop_retry
    def list_shipping_vendors(self, address_id: int, products: List[Dict]) -> List[Dict]:
        """获取可用配送方式列表
        products: [{"goods_id": int, "num": int}, ...]
        """
        result = self._post("ecapi.shipping.vendor.list", {
            "shop": 1,
            "address": address_id,
            "products": json.dumps(products, separators=(",", ":")),
        }, need_auth=True)
        return result.get("vendors", result.get("data", []))

    @staticmethod
    def _guess_shipping_id(name: str) -> int:
        """根据名称猜配送方式 ID（兜底）"""
        mapping = {
            "只限直邮产品": 25,
            "顺丰速运": 24,
            "中通速递": 21,
            "德国境内": 22,
            "欧盟国际": 23,
        }
        return mapping.get(name, 25)

    # ─────────────── 订单 ───────────────

    @ecshop_retry
    def list_orders(self, page: int = 1, per_page: int = 10) -> List[Dict]:
        """订单列表"""
        result = self._post(
            "ecapi.order.list",
            {"page": page, "per_page": per_page},
            need_auth=True,
        )
        return result.get("orders", [])

    @ecshop_retry
    def get_order(self, order_id: str) -> Dict:
        """订单详情"""
        result = self._post("ecapi.order.get", {"order_id": order_id}, need_auth=True)
        return result["order"]

    # ─────────────── 工具函数 ───────────────

    def find_product(self, keyword: str) -> List[Dict]:
        """智能找商品：先用搜索，再按名称匹配"""
        products = self.search_products(keyword, per_page=20)
        exact = [p for p in products if keyword.lower() in p["name"].lower()]
        if exact:
            return exact
        return products

    def get_product_spec(
        self, product_id: int, spec_name: str = "发货规格", spec_value: str = None
    ) -> Dict:
        """获取商品规格详情"""
        prod = self.get_product(product_id)
        for prop in prod.get("properties", []):
            if spec_name in prop.get("name", ""):
                for attr in prop.get("attrs", []):
                    if spec_value is None or spec_value in attr.get("attr_name", ""):
                        return attr
        return {}

    def get_default_consignee(self) -> Dict:
        """获取默认收货地址"""
        addresses = self.list_consignees()
        for addr in addresses:
            if addr.get("is_default"):
                return addr
        return addresses[0] if addresses else {}

    def find_consignee_by_name(self, name: str) -> Dict:
        """按姓名查找收货地址"""
        addresses = self.list_consignees()
        for addr in addresses:
            if name in addr.get("name", ""):
                return addr
        return {}
