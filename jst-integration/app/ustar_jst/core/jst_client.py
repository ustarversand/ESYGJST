#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聚水潭统一 SDK（合并版）
======================

整合来源：
  - core/jst_base_client.py  — 基类（retry + alert hook）
  - core/jst_api.py          — 旧版函数（call_jushuitan_api 等）
  - core/jst_api_lib.py      — 新版 JSTClient 类

所有 API 调用统一走 JSTClient 类，
以后只改这一个文件。

用法：
  from core.jst_client import JSTClient
  client = JSTClient()
  shops = client.query_shops()
"""

import os
import time
import json
import logging
import hashlib
import requests
from typing import Dict, List, Any, Optional, Callable
from functools import wraps

# ==================== 日志 ====================
logger = logging.getLogger(__name__)

# ==================== 全局配置 ====================
JST_CONFIG = {
    "app_key": os.environ.get("JST_APP_KEY", "d561deb348274f1ba3505ec4578870fd"),
    "app_secret": os.environ.get("JST_APP_SECRET", "84ad2c023b9b49378b1161ea569e383c"),
    "token": os.environ.get("JST_TOKEN", "cfda23ff97664494bc6fc5ab46f8ea48"),
    "callback_url": os.environ.get(
        "JST_CALLBACK_URL",
        "https://gateway-cn.jieztech.com/apos.aps/api/JuShuiTanSpi/CallBack",
    ),
    "api_url_legacy": "https://open.erp321.com/api/open/query.aspx",
    "api_url_new": "https://openapi.jushuitan.com",
}

DEFAULT_SHOP_ID = 20941412
DEFAULT_BUYER_ID = "微信接单"
JST_TOKEN = JST_CONFIG["token"]  # 兼容旧代码单独导出

# ==================== 重试装饰器（来自 jst_base_client.py） ====================
DEFAULT_MAX_RETRIES = int(os.environ.get("JST_MAX_RETRIES", "3"))
DEFAULT_RETRY_DELAY = float(os.environ.get("JST_RETRY_DELAY", "1.0"))
DEFAULT_TIMEOUT = int(os.environ.get("JST_TIMEOUT", "30"))


def retry_on_failure(
    max_retries: int = None,
    delay: float = None,
    backoff: float = 2.0,
    retriable_codes: set = None,
):
    """
    API 重试装饰器（指数退避）

    Args:
        max_retries:     最大重试次数（默认 3）
        delay:           初始重试间隔秒数（默认 1.0）
        backoff:         退避倍率（默认 2.0，即 1s → 2s → 4s）
        retriable_codes: 可重试的 code 集合（默认 {-1, 99999} 表示网络异常）
    """
    max_retries = max_retries if max_retries is not None else DEFAULT_MAX_RETRIES
    delay = delay if delay is not None else DEFAULT_RETRY_DELAY
    retriable_codes = retriable_codes or {-1, 99999}

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_result = None
            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    last_result = result
                    if isinstance(result, dict):
                        code = result.get("code", 0)
                        if code == 0:
                            return result
                        if code in retriable_codes:
                            msg = result.get("msg", "Unknown")
                            logger.warning(
                                f"[{func.__name__}] code={code} {msg} "
                                f"| attempt {attempt + 1}/{max_retries + 1}"
                            )
                            if attempt < max_retries:
                                time.sleep(delay * (backoff ** attempt))
                                continue
                        return result
                    return result
                except Exception as e:
                    last_result = {"code": -1, "msg": str(e)}
                    logger.warning(
                        f"[{func.__name__}] exception={e} "
                        f"| attempt {attempt + 1}/{max_retries + 1}"
                    )
                    if attempt < max_retries:
                        time.sleep(delay * (backoff ** attempt))
                        continue
            return last_result or {"code": -1, "msg": "Max retries exceeded"}

        return wrapper

    return decorator


# ==================== 告警钩子（来自 jst_base_client.py） ====================

class JSTAlertHook:
    """API 告警钩子（可扩展接入 Telegram/飞书等）"""

    def __init__(self):
        self._handlers: List[Callable] = []

    def register(self, handler: Callable[[str, Dict], None]):
        """注册告警处理器，签名: (title: str, context: Dict) -> None"""
        self._handlers.append(handler)

    def alert(self, title: str, context: Dict):
        for h in self._handlers:
            try:
                h(title, context)
            except Exception as e:
                logger.error(f"Alert handler error: {e}")

    def alert_api_failure(self, func_name: str, result: Dict, retries: int):
        self.alert(
            f"⚠️ JST API 失败 [{func_name}]",
            {"result": result, "retries": retries},
        )


# 全局告警钩子
alert_hook = JSTAlertHook()


def register_telegram_alert(bot_token: str, chat_id: str):
    """快捷注册 Telegram 告警"""
    import requests as _r

    def _handler(title: str, context: Dict):
        msg = f"{title}\n```\n{json.dumps(context, ensure_ascii=False, indent=2)}\n```"
        try:
            _r.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Telegram alert failed: {e}")

    alert_hook.register(_handler)


# ==================== 统一 SDK 客户端 ====================

class JSTClient:
    """
    聚水潭统一 API 客户端

    统一 retry + alert hook，统一旧版/新版 API，
    统一 config 读取。以后只改这一个文件。

    用法：
        client = JSTClient()
        shops = client.query_shops()
        orders = client.query_orders_single(so_id="SO123456")
        result = client.purchase_flow("7613287226679ZZ2", 5)
    """

    config: Dict[str, str] = {}
    _api_base: str = JST_CONFIG["api_url_legacy"]

    def __init__(self, config: Optional[Dict] = None):
        self.cfg = {**JST_CONFIG, **self.config, **(config or {})}
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json; charset=utf-8"})

    # ─────────────── 签名 ───────────────

    def _sign_legacy(self, method: str, params: Dict) -> str:
        """旧版 API 签名：MD5(method + app_key + sorted_kv + app_secret)"""
        sorted_str = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
        sign_str = method + self.cfg["app_key"] + sorted_str + self.cfg["app_secret"]
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().lower()

    def _sign_new_api(self, params: Dict) -> str:
        """新版 API 签名 (openapi.jushuitan.com)"""
        sorted_str = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
        return hashlib.md5(
            (self.cfg["app_secret"] + sorted_str).encode("utf-8")
        ).hexdigest().lower()

    def _timestamp(self) -> str:
        return str(int(time.time()))

    # ─────────────── 底层请求 ───────────────

    def _post_legacy(self, method: str, biz_data: Any, timeout: int = None) -> Dict:
        """旧版 API POST（自动 retry + alert）"""
        timeout = timeout or DEFAULT_TIMEOUT
        ts = self._timestamp()
        sys_params = {"token": self.cfg["token"], "ts": ts}
        sign = self._sign_legacy(method, sys_params)
        url = (
            f"{JST_CONFIG['api_url_legacy']}"
            f"?method={method}&partnerid={self.cfg['app_key']}"
            f"&token={self.cfg['token']}&ts={ts}&sign={sign}"
        )
        resp = self._session.post(
            url,
            data=json.dumps(biz_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            timeout=timeout,
        )
        return resp.json()

    def _post_new(self, path: str, biz_data: Any, timeout: int = None) -> Dict:
        """新版 API POST（自动 retry + alert）"""
        timeout = timeout or DEFAULT_TIMEOUT
        ts = self._timestamp()
        params = {
            "app_key": self.cfg["app_key"],
            "access_token": self.cfg["token"],
            "timestamp": ts,
            "charset": "utf-8",
            "version": "2",
            "biz": json.dumps(biz_data, ensure_ascii=False, separators=(",", ":")),
        }
        params["sign"] = self._sign_new_api(params)
        resp = self._session.post(
            f"{JST_CONFIG['api_url_new']}{path}",
            data=params,
            timeout=timeout,
        )
        return resp.json()

    # ─────────────── 旧版 API 方法 ───────────────

    @retry_on_failure()
    def call_legacy(self, method: str, biz_data: Any, timeout: int = None) -> Dict:
        """调用旧版 API（list/dict body 通用）"""
        result = self._post_legacy(method, biz_data, timeout=timeout)
        if isinstance(result, dict) and result.get("code") != 0:
            alert_hook.alert_api_failure(f"call_legacy({method})", result, DEFAULT_MAX_RETRIES)
        return result

    @retry_on_failure()
    def call_new(self, path: str, biz_data: Any, timeout: int = None) -> Dict:
        """调用新版 API（openapi.jushuitan.com）"""
        result = self._post_new(path, biz_data, timeout=timeout)
        if isinstance(result, dict) and result.get("code") != 0:
            alert_hook.alert_api_failure(f"call_new({path})", result, DEFAULT_MAX_RETRIES)
        return result

    # ─────────────── 兼容旧函数式签名 ───────────────
    # 以下方法让旧代码（call_jushuitan_api / call_jushuitan_api_dict / call_new_api）
    # 无痛迁移，无需改任何调用方

    def call_jushuitan_api(self, method: str, orders_list: list, use_prod: bool = True) -> Dict:
        """旧版 orders.upload 类 API（传 list）"""
        return self.call_legacy(method, orders_list)

    def call_jushuitan_api_dict(self, method: str, data: dict, use_prod: bool = True) -> Dict:
        """旧版查询类 API（传 dict）"""
        return self.call_legacy(method, data)

    def call_new_api(self, path: str, biz_data, timeout: int = 15) -> Dict:
        """新版 API（兼容 domains/aftersale_api.py 等）"""
        return self.call_new(path, biz_data, timeout=timeout)

    # ─────────────── 基础查询 ───────────────

    def query_shops(self, page_index: int = 1, page_size: int = 10) -> List[Dict]:
        """店铺查询"""
        result = self.call_new("/open/shops/query", {"page_index": page_index, "page_size": page_size})
        return result.get("data", {}).get("datas", [])

    def query_suppliers(self, page_index: int = 1, page_size: int = 10) -> List[Dict]:
        """供应商查询"""
        result = self.call_new("/open/supplier/query", {"page_index": page_index, "page_size": page_size})
        return result.get("data", {}).get("datas", [])

    def query_logistics_companies(self, page_index: int = 1, page_size: int = 10) -> List[Dict]:
        """物流公司查询"""
        result = self.call_new("/open/logisticscompany/query", {"page_index": page_index, "page_size": page_size})
        return result.get("data", {}).get("datas", [])

    def query_categories(self, page_index: int = 1, page_size: int = 50) -> List[Dict]:
        """商品类目查询"""
        result = self.call_new("/open/category/query", {"page_index": page_index, "page_size": page_size})
        return result.get("data", {}).get("datas", [])

    def query_warehouses(self, page_index: int = 1, page_size: int = 10) -> List[Dict]:
        """仓库查询"""
        result = self.call_new("/open/wms/partner/query", {"page_index": page_index, "page_size": page_size})
        return result.get("data", {}).get("datas", [])

    # ─────────────── 虚拟仓 ───────────────

    def query_virtual_warehouses(self, page_index: int = 1, page_size: int = 50) -> List[Dict]:
        """虚拟仓列表"""
        result = self.call_new(
            "/open/webapi/itemapi/lockwarehouse/getwarehouselist",
            {"page_index": page_index, "page_size": page_size},
        )
        return result.get("data", [])

    # ─────────────── 采购 API ───────────────

    def create_purchase(self, sku_code: str, qty: int, supplier_id: int = 12557285) -> Dict:
        """创建采购单"""
        external_id = f"CG{int(time.time())}"
        biz = {
            "external_id": external_id,
            "supplier_id": supplier_id,
            "items": [{"sku_code": sku_code, "sku_id": sku_code, "qty": qty}],
        }
        result = self.call_new("/open/jushuitan/purchase/upload", biz)
        return {"external_id": external_id, "po_id": result["data"]["data"]["po_id"]}

    def create_booking(
        self,
        po_id: int,
        sku_code: str,
        qty: int,
        supplier_id: int = 12557285,
        warehouse_id: int = 13659696,
    ) -> Dict:
        """预约入库"""
        external_id = f"YY{int(time.time())}"
        biz = {
            "po_id": po_id,
            "supplier_id": supplier_id,
            "external_id": external_id,
            "warehouse_id": warehouse_id,
            "planned_date": time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400)),
            "items": [{"sku_code": sku_code, "sku_id": sku_code, "external_id": f"{external_id}_1", "qty": qty}],
        }
        result = self.call_new("/open/jushuitan/appointmentin/upload", biz)
        return {"external_id": external_id, "booking_id": result["data"]["data"]["po_id"]}

    def confirm_purchase(self, po_id: int) -> str:
        """确认采购单 (option=1)"""
        result = self.call_new(
            "/open/jushuitan/purchase/change/status",
            {"po_ids": [po_id], "option": 1},
        )
        return result["data"]["result"][0]["status"]

    def complete_purchase(self, po_id: int) -> str:
        """完成采购入库 (option=4)"""
        result = self.call_new(
            "/open/jushuitan/purchase/change/status",
            {"po_ids": [po_id], "option": 4},
        )
        return result["data"]["result"][0]["status"]

    def purchase_flow(self, sku_code: str, qty: int, supplier_id: int = 12557285) -> Dict:
        """采购入库完整流程（创建→预约→确认→完成）"""
        purchase = self.create_purchase(sku_code, qty, supplier_id)
        booking = self.create_booking(purchase["po_id"], sku_code, qty, supplier_id)
        self.confirm_purchase(purchase["po_id"])
        status = self.complete_purchase(purchase["po_id"])
        return {
            "po_id": purchase["po_id"],
            "external_id": purchase["external_id"],
            "status": status,
        }

    # ─────────────── 库存 API ───────────────

    def create_inventory_check(self, sku_code: str, check_qty: int, warehouse: int = 4) -> str:
        """新建盘点单"""
        external_id = f"PD{int(time.time())}"
        biz = {
            "external_id": external_id,
            "so_id": external_id,
            "warehouse": warehouse,
            "items": [{"sku_code": sku_code, "sku_id": sku_code, "check_qty": check_qty}],
        }
        result = self.call_new("/open/jushuitan/inventoryv2/upload", biz)
        return result["data"]["data"]["so_id"]

    # ─────────────── 健康检查 ───────────────

    def health_check(self) -> Dict:
        """健康检查"""
        try:
            return self.call_new("/open/shops/query", {"page_index": 1, "page_size": 1})
        except Exception as e:
            return {"code": -1, "msg": str(e)}


# ==================== 兼容函数（来自 core/jst_api.py，透传到 JSTClient） ====================
# 旧代码 from core.jst_api import call_jushuitan_api / call_new_api 等
# 迁移后直接 from core.jst_client import call_jushuitan_api ...

_client_instance: Optional[JSTClient] = None


def _get_client() -> JSTClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = JSTClient()
    return _client_instance


def call_jushuitan_api(method: str, orders_list: list, use_prod: bool = True) -> dict:
    return _get_client().call_jushuitan_api(method, orders_list, use_prod)


def call_jushuitan_api_dict(method: str, data: dict, use_prod: bool = True) -> dict:
    return _get_client().call_jushuitan_api_dict(method, data, use_prod)


def call_new_api(path: str, biz_data=None, timeout: int = 15) -> dict:
    return _get_client().call_new_api(path, biz_data, timeout=timeout)


def generate_sign(method: str, params: dict) -> str:
    """旧版 API 签名：MD5(method + app_key + sorted_kv + app_secret)"""
    sorted_str = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
    sign_str = method + JST_CONFIG["app_key"] + sorted_str + JST_CONFIG["app_secret"]
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().lower()


def get_timestamp() -> str:
    return str(int(time.time()))


# ==================== main（测试入口） ====================

if __name__ == "__main__":
    client = JSTClient()

    print("=== 聚水潭统一 SDK 测试 ===\n")

    print("0. 健康检查:")
    health = client.health_check()
    print(f"   -> {health}")

    print("1. 店铺列表:")
    shops = client.query_shops()
    print(f"   -> {len(shops)} 条")

    print("2. 供应商:")
    suppliers = client.query_suppliers()
    print(f"   -> {len(suppliers)} 条")

    print("3. 物流公司:")
    logistics = client.query_logistics_companies()
    print(f"   -> {len(logistics)} 条")

    print("4. 商品类目:")
    categories = client.query_categories()
    print(f"   -> {len(categories)} 条")

    print("5. 虚拟仓:")
    vws = client.query_virtual_warehouses()
    print(f"   -> {len(vws)} 条")

    print("\n6. 采购入库流程测试:")
    try:
        result = client.purchase_flow("7613287226679ZZ2", 5)
        print(f"   -> po_id={result['po_id']}, status={result['status']}")
    except Exception as e:
        print(f"   -> {e}")
