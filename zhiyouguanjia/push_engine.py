"""直邮管家 — 聚水潭订单推送引擎（增强版）
集成：重试、身份证校验(P3)、奶粉拆单、预览确认
"""
import time
import json
import hashlib
import logging
import difflib
import re
import requests
from datetime import datetime
from typing import List, Optional, Tuple
from functools import wraps

from config import JST_CONFIG, SHOPS, DEFAULT_SHOP_KEY, DEFAULT_SHOP_ID, DEFAULT_SHOP_NAME, DEFAULT_BUYER_ID, PM_PRODUCTS
from models import WeChatOrder, OrderItem

# 身份证数据库
try:
    from 身份证上传 import idcard_cache_db as idcard_db
    HAS_IDCARD_DB = True
except Exception:
    idcard_db = None
    HAS_IDCARD_DB = False

logger = logging.getLogger("zygj-push")
logger.setLevel(logging.DEBUG)

# ==================== 重试装饰器 ====================

def retry_on_failure(max_retries=3, delay=1.0, backoff=2.0, retriable_codes=None):
    """API调用重试装饰器（网络错误+特定返回码重试）"""
    if retriable_codes is None:
        retriable_codes = {400, 500, 502, 503, 504}
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            current_delay = delay
            for attempt in range(1, max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    code = result.get("code", 0)
                    if code == 0:
                        return result
                    if code in retriable_codes and attempt < max_retries:
                        logger.warning(f"[重试] 返回码{code}, 第{attempt}次重试 ({current_delay}s后)...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                        continue
                    return result
                except (requests.ConnectionError, requests.Timeout) as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning(f"[重试] 网络错误: {e}, 第{attempt}次重试 ({current_delay}s后)...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                        continue
                    return {"code": -1, "msg": f"网络错误(重试{max_retries}次后): {e}"}
                except Exception as e:
                    return {"code": -1, "msg": str(e)}
            return {"code": -1, "msg": f"重试{max_retries}次后仍失败: {last_error}"}
        return wrapper
    return decorator


# ==================== JST API 客户端 ====================

class JSTClient:
    """聚水潭 API 客户端（签名 + 调用 + 重试）"""

    def __init__(self):
        self.config = JST_CONFIG

    def generate_sign(self, method: str, params: dict) -> str:
        partnerid = self.config["app_key"]
        partnerkey = self.config["app_secret"]
        param_str = "".join(str(k) + str(v) for k, v in sorted(params.items()))
        sign_str = method + partnerid + param_str + partnerkey
        return hashlib.md5(sign_str.encode('utf-8')).hexdigest().lower()

    @retry_on_failure(max_retries=3, delay=1.0)
    def call_api(self, method: str, data: list) -> dict:
        """调用 JST 旧版 API（签名参数放URL query，业务数据放POST body）"""
        ts = str(int(time.time()))
        sys_params = {
            "token": self.config["token"],
            "ts": ts,
        }
        sign = self.generate_sign(method, sys_params)
        url = (
            f"{self.config['api_url_legacy']}"
            f"?method={method}"
            f"&partnerid={self.config['app_key']}"
            f"&token={self.config['token']}"
            f"&ts={ts}&sign={sign}"
        )
        import json as _json
        resp = requests.post(
            url,
            data=_json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=30,
        )
        result = resp.json()
        logger.debug(f"[JST] {method} → code={result.get('code')}, msg={result.get('msg','')[:80]}")
        return result

    def build_jst_order(self, order: dict, shop_id: str) -> dict:
        """将订单字典转换为聚水潭格式"""
        so_id = order.get("so_id") or f"PM{datetime.now().strftime('%m%d%H%M%S')}{int(time.time()*1000)%1000:03d}"
        pay_amount = order.get("pay_amount", 0)
        jst_order = {
            "shop_id": shop_id,
            "so_id": so_id,
            "order_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "shop_status": "WAIT_SELLER_SEND_GOODS",
            "shop_buyer_id": order.get("buyer_id", DEFAULT_BUYER_ID),
            "receiver_name": order.get("receiver_name", ""),
            "receiver_mobile": order.get("receiver_phone", ""),
            "receiver_state": order.get("receiver_state", ""),
            "receiver_city": order.get("receiver_city", ""),
            "receiver_district": order.get("receiver_district", ""),
            "receiver_address": order.get("receiver_address", ""),
            "receiver_country": "CN",
            "pay_amount": pay_amount,
            "freight": order.get("freight", 0),
            "buyer_message": order.get("buyer_message", ""),
            "items": [],
            "pay": {
                "outer_pay_id": f"PAY{so_id}",
                "pay_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "payment": "线下",
                "amount": pay_amount,
            }
        }
        for i, item in enumerate(order.get("items", [])):
            qty = int(item.get("qty", 1))
            price = float(item.get("price", 0))
            sku_id = item.get("sku_id", "").strip()
            if not sku_id and item.get("name"):
                sku_id = fuzzy_match_sku(item["name"])
            jst_item = {
                "sku_id": sku_id,
                "shop_sku_id": sku_id,
                "name": item.get("name", ""),
                "qty": qty,
                "price": price,
                "amount": price * qty,
                "outer_oi_id": f"{so_id}_{i+1:03d}",
            }
            jst_order["items"].append(jst_item)
        # 身份证 card 对象
        id_card = order.get("id_card_number", "").strip() or order.get("id_card", "").strip()
        if id_card:
            jst_order["card"] = {
                "card_id": id_card,
                "card_name": order.get("receiver_name", ""),
                "outer_oi_id": f"{so_id}_card",
            }
        return jst_order


# 全局 JSTClient 实例
_jst_client = JSTClient()


# ==================== 签名 & 基础调用（兼容旧接口）====================

def get_timestamp() -> str:
    return str(int(time.time()))


# 兼容旧版 call_jushuitan_api（app.py 等仍用）
def call_jushuitan_api(method: str, data: list) -> dict:
    return _jst_client.call_api(method, data)


# ==================== SKU 搜索 ====================

PRODUCT_NAME_MAP = {v["sku"]: k for k, v in PM_PRODUCTS.items()}

MASTER_PRODUCT_CATALOG = [
    (v["sku"], k) for k, v in PM_PRODUCTS.items()
]

_BRAND_PREFIXES = ["PM Fitline", "PM", "Fitline"]

_NAME_TO_SKU = {}
_SKU_TO_NAME = {}
PRODUCT_ALIASES = {}


def _build_index():
    global _NAME_TO_SKU, _SKU_TO_NAME, PRODUCT_ALIASES
    _NAME_TO_SKU = {}
    _SKU_TO_NAME = {}
    for sku, name in MASTER_PRODUCT_CATALOG:
        if sku:
            _NAME_TO_SKU[name] = sku
            _SKU_TO_NAME[sku] = name
    for sku, name in PRODUCT_NAME_MAP.items():
        _NAME_TO_SKU[name] = sku
        _SKU_TO_NAME[sku] = name
    aliases = {}
    for name, sku in _NAME_TO_SKU.items():
        if name not in aliases:
            aliases[name] = sku
        for prefix in _BRAND_PREFIXES:
            if name.startswith(prefix):
                short = name[len(prefix):]
                if short and short not in aliases:
                    aliases[short] = sku
    PRODUCT_ALIASES = aliases

_build_index()


def search_products(query: str, limit: int = 10) -> list:
    if not query or not query.strip():
        return []
    query = query.strip().lower()
    # 1. 精确别名匹配
    if query in PRODUCT_ALIASES:
        sku = PRODUCT_ALIASES[query]
        name = _SKU_TO_NAME.get(sku, "")
        price = PM_PRODUCTS.get(name, {}).get("price", 0)
        return [{"sku": sku, "name": name, "price": price, "match_type": "exact"}]
    # 2. 子串匹配
    matches = []
    for name, sku in _NAME_TO_SKU.items():
        if query in name.lower():
            price = PM_PRODUCTS.get(name, {}).get("price", 0)
            matches.append({"sku": sku, "name": name, "price": price, "match_type": "contains"})
        elif name.lower() in query:
            matches.append({"sku": sku, "name": name, "match_type": "contains"})
    if matches:
        return matches[:limit]
    # 3. 别名子串
    for alias, sku in PRODUCT_ALIASES.items():
        if query in alias.lower():
            name = _SKU_TO_NAME.get(sku, "")
            matches.append({"sku": sku, "name": name, "match_type": "alias_contains"})
    if matches:
        return matches[:limit]
    # 4. 模糊匹配
    scored = []
    for name, sku in _NAME_TO_SKU.items():
        ratio = difflib.SequenceMatcher(None, query, name.lower()).ratio()
        if ratio > 0.5:
            scored.append((ratio, {"sku": sku, "name": name, "match_type": "fuzzy"}))
    scored.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    unique = []
    for _, m in scored:
        if m["sku"] not in seen:
            unique.append(m)
            seen.add(m["sku"])
    return unique[:limit]


def fuzzy_match_sku(product_name_text: str) -> str:
    if not product_name_text:
        return ""
    results = search_products(product_name_text, limit=1)
    if results:
        sku = results[0]["sku"]
        logger.info(f"[SKU匹配] \"{product_name_text}\" → {sku} ({results[0]['name']}, {results[0]['match_type']})")
        return sku
    logger.info(f"[SKU匹配] \"{product_name_text}\" → 无匹配")
    return ""


# ==================== 身份证校验 ====================

class IDCardValidator:
    """身份证格式 + P3姓名一致性校验"""

    @staticmethod
    def validate_format(id_card: str) -> Tuple[bool, str]:
        """严格校验18位身份证格式"""
        if not id_card:
            return False, "身份证号不能为空"
        v = id_card.strip().upper()
        if len(v) != 18:
            return False, f"身份证号必须是18位，当前{len(v)}位"
        if not v[:17].isdigit():
            return False, "身份证号前17位必须是数字"
        if v[-1] not in '0123456789X':
            return False, "身份证号最后一位必须是数字或X"
        # 校验生日
        birth = v[6:14]
        try:
            datetime.strptime(birth, "%Y%m%d")
        except ValueError:
            return False, f"身份证号出生日期无效: {birth}"
        return True, ""

    @staticmethod
    def verify_name_vs_idcard(receiver_name: str, id_card: str) -> Tuple[bool, str]:
        """P3: 校验收件人姓名 vs 身份证持证人姓名一致"""
        if not receiver_name or not id_card:
            return True, ""  # 无数据可校验，放行
        if not HAS_IDCARD_DB:
            return True, ""
        try:
            holder_name = idcard_db.get_name_by_number(id_card)
        except Exception:
            return True, ""
        if holder_name is None:
            return True, ""  # 缓存无记录，放行
        if receiver_name.strip() != holder_name.strip():
            return False, f"⚠️ 收件人姓名「{receiver_name}」与身份证持证人「{holder_name}」不一致"
        return True, ""


validator = IDCardValidator()


# ==================== 奶粉拆单 ====================

# 奶粉关键词（与PM_PRODUCTS中的奶粉SKU匹配）
MILK_POWDER_KEYWORDS = ["奶粉", "德爱", "爱他美", "喜宝", "BEBA", "至尊", "牛栏", "白金", "蓝罐"]


def is_milk_powder(product_name: str) -> bool:
    """判断商品是否是奶粉"""
    name_lower = product_name.lower()
    return any(kw in name_lower for kw in MILK_POWDER_KEYWORDS)


def split_milk_powder_order(order: dict) -> List[dict]:
    """奶粉拆单：每2罐一单"""
    milk_items = [it for it in order.get("items", []) if is_milk_powder(it.get("name", ""))]
    other_items = [it for it in order.get("items", []) if not is_milk_powder(it.get("name", ""))]

    if not milk_items:
        return [order]  # 没有奶粉，不拆

    split_orders = []
    base_so_id = order.get("so_id", "")

    # 非奶粉商品作为一个订单
    if other_items:
        base_order = dict(order)
        base_order["items"] = other_items
        split_orders.append(base_order)

    # 每个奶粉商品独立拆单
    sub_idx = 0
    for item in milk_items:
        qty = int(item.get("qty", 1))
        split_count = (qty + 1) // 2  # 每2罐1单，向上取整
        logger.info(f"[拆单] {item['name']} x{qty} → {split_count}单")
        for i in range(split_count):
            sub_idx += 1
            sub = dict(order)
            sub["so_id"] = f"{base_so_id}-{sub_idx}" if base_so_id else ""
            item_qty = 2 if (i * 2 + 2) <= qty else (qty - i * 2)
            sub["items"] = [dict(item, qty=item_qty)]
            split_orders.append(sub)

    return split_orders if split_orders else [order]


# ==================== 订单预览 ====================

def build_preview_message(order: dict) -> str:
    """生成订单预览消息"""
    lines = []
    lines.append("📋 **订单预览**")
    lines.append(f"单号: {order.get('so_id', '待生成')}")
    lines.append(f"收件人: {order.get('receiver_name', '')}")
    lines.append(f"电话: {order.get('receiver_phone', '')}")
    lines.append(f"地址: {order.get('receiver_state', '')} {order.get('receiver_city', '')} {order.get('receiver_district', '')} {order.get('receiver_address', '')}")
    id_card = order.get("id_card_number", "") or order.get("id_card", "")
    if id_card:
        lines.append(f"身份证: {id_card[:6]}****{id_card[-4:]}")
    lines.append(f"商品:")
    for item in order.get("items", []):
        lines.append(f"  • {item.get('name', '')} x{item.get('qty', 1)}  SKU: {item.get('sku_id', '')}")
    if order.get("buyer_message"):
        lines.append(f"备注: {order['buyer_message']}")
    lines.append("")
    lines.append("✅ 回复「确认」或「推送」正式推单")
    return "\n".join(lines)


# ==================== 主推单函数 ====================

def push_order(order: dict, shop_key: str = None, auto_push: bool = True) -> dict:
    """
    主推单函数（增强版）

    Args:
        order: 订单字典
        shop_key: 店铺KEY
        auto_push: True=直接推, False=仅预览返回
    """
    # ── 确定店铺 ──
    if shop_key and shop_key in SHOPS:
        shop_cfg = SHOPS[shop_key]
        shop_id = shop_cfg["id"]
        shop_name = shop_cfg["name"]
        need_idcard = shop_cfg.get("need_idcard", True)
        buyer_id = order.get("buyer_id") or shop_cfg.get("buyer_id", DEFAULT_BUYER_ID)
    else:
        shop_cfg = SHOPS.get(DEFAULT_SHOP_KEY, {})
        shop_id = shop_cfg.get("id", DEFAULT_SHOP_ID)
        shop_name = shop_cfg.get("name", DEFAULT_SHOP_NAME)
        need_idcard = shop_cfg.get("need_idcard", True)
        buyer_id = order.get("buyer_id") or shop_cfg.get("buyer_id", DEFAULT_BUYER_ID)

    order["buyer_id"] = buyer_id

    # ── 1. 姓名匹配数据库 → 自动填充身份证 ──
    receiver_name = order.get("receiver_name", "").strip()
    id_card = order.get("id_card_number", "").strip() or order.get("id_card", "").strip()
    if not id_card and receiver_name and HAS_IDCARD_DB:
        try:
            matches = idcard_db.check_local_by_name(receiver_name)
            if matches:
                id_card = matches[0]["id_card_number"]
                order["id_card_number"] = id_card
                logger.info(f"[身份证] 自动匹配: {receiver_name} → {id_card[:6]}****{id_card[-4:]}")
        except Exception:
            pass

    # ── 2. 身份证格式校验 ──
    if need_idcard and id_card:
        valid, err_msg = validator.validate_format(id_card)
        if not valid:
            return {"success": False, "code": -3, "msg": f"身份证格式错误: {err_msg}"}

    # ── 3. P3姓名一致性校验 ──
    if need_idcard and id_card and receiver_name:
        ok, err_msg = validator.verify_name_vs_idcard(receiver_name, id_card)
        if not ok:
            return {"success": False, "code": -4, "name_mismatch": True, "msg": err_msg}

    # ── 4. 身份证前置拦截 ──
    if need_idcard and not id_card:
        return {"success": False, "code": -2,
                "msg": "缺少收件人身份证号，该店铺跨境订单必须提供",
                "shop_name": shop_name}

    # ── 5. 奶粉拆单 ──
    orders_to_push = split_milk_powder_order(order)

    # ── 6. 构建JST订单 ──
    jst_orders = []
    for sub_order in orders_to_push:
        jst = _jst_client.build_jst_order(sub_order, shop_id)
        jst_orders.append(jst)

    # ── 7. 空SKU检查 ──
    for jst_order in jst_orders:
        empty_skus = [it for it in jst_order.get("items", []) if not it.get("sku_id", "").strip()]
        if empty_skus:
            names = [it.get("name", "?") for it in empty_skus]
            return {"success": False, "code": -1,
                    "msg": f"商品编码为空: {', '.join(names)}",
                    "shop_name": shop_name, "so_id": jst_order["so_id"]}

    # ── 预览模式 ──
    if not auto_push:
        return {
            "success": True,
            "preview": True,
            "orders": orders_to_push,
            "jst_orders": jst_orders,
            "shop_name": shop_name,
        }

    # ── 8. 防重复推 ──
    from push_records import is_duplicate
    for o in orders_to_push:
        so_id = o.get("so_id", "")
        if so_id and is_duplicate(so_id):
            logger.warning(f"[防重推] 订单已推送过: {so_id}")
            return {"success": False, "code": -5, "msg": f"订单 {so_id} 已推送过，请勿重复推送"}

    # ── 9. 推送 ──
    result = _jst_client.call_api("orders.upload", jst_orders)

    response = {
        "success": result.get("code") == 0,
        "code": result.get("code"),
        "msg": result.get("msg", ""),
        "shop_name": shop_name,
        "so_id": jst_orders[0]["so_id"] if jst_orders else "",
        "o_id": result.get("data", {}).get("o_id", ""),
        "raw": result,
    }

    # ── 10. 推单后处理 ──
    if response["success"]:
        # 保存身份证到本地
        if receiver_name and id_card and HAS_IDCARD_DB:
            try:
                idcard_db.save_to_local(receiver_name, id_card, verified=False)
            except Exception:
                pass
        # 保存推单记录
        try:
            from push_records import save_push_record
            save_push_record(order, response)
        except Exception as e:
            logger.warning(f"[记录] 保存失败: {e}")
        # 自动查物流
        try:
            _auto_fetch_logistics(order, response)
        except Exception as e:
            logger.warning(f"[物流] 查询异常: {e}")

    return response


def push_orders_batch(orders: List[dict], shop_key: str = None) -> dict:
    """批量推单"""
    results = []
    for order in orders:
        result = push_order(order, shop_key)
        results.append(result)
    success_count = sum(1 for r in results if r.get("success"))
    return {
        "success": True,
        "msg": f"批量推送完成: {success_count}/{len(orders)} 成功",
        "results": results,
    }


def _auto_fetch_logistics(order: dict, response: dict):
    """推单成功后自动查物流"""
    import heuste_client
    so_id = response.get("so_id", "")
    if not so_id:
        return
    # 方案A: 精准匹配
    order_info = heuste_client.search_by_merchant_sn(so_id)
    if order_info:
        tracking_no = order_info.get("tracking_no", "")
        domestic_no = order_info.get("domestic_no", "")
        logistics_state = order_info.get("state", "")
        response["tracking_no"] = tracking_no
        response["domestic_no"] = domestic_no
        response["logistics_state"] = logistics_state
        try:
            from push_records import update_tracking
            update_tracking(so_id, tracking_no, domestic_no, logistics_state)
        except Exception:
            pass
        logger.info(f"[物流] 精准匹配: {so_id} → {tracking_no}")
        return
    # 方案B: 6h窗口模糊匹配
    from datetime import datetime, timedelta
    push_time = datetime.now()
    logistics = heuste_client.search_orders_by_receiver(
        order.get("receiver_name", ""),
        order.get("receiver_phone", ""),
    )
    if logistics:
        window_start = push_time - timedelta(hours=6)
        filtered = []
        for l in logistics:
            created_str = l.get("created", "")
            if created_str:
                try:
                    created_dt = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")
                    if window_start <= created_dt <= push_time + timedelta(hours=6):
                        filtered.append(l)
                except ValueError:
                    filtered.append(l)
        if filtered:
            filtered.sort(key=lambda x: x.get("created", ""), reverse=True)
            latest = filtered[0]
            response["tracking_no"] = latest.get("tracking_no", "")
            response["domestic_no"] = latest.get("domestic_no", "")
            response["logistics_state"] = latest.get("state", "")
            logger.info(f"[物流] 6h窗口: {so_id} → {latest.get('tracking_no','')}")


# ==================== 辅助函数 ====================

def get_shop_list() -> list:
    """返回店铺列表"""
    return [{"key": k, **v} for k, v in SHOPS.items()]


def check_jst_connection() -> dict:
    """检查聚水潭连接"""
    try:
        result = _jst_client.call_api("shops.query", [{}])
        if result.get("code") == 0:
            return {"success": True, "msg": "连接正常"}
        return {"success": False, "msg": result.get("msg", "连接失败")}
    except Exception as e:
        return {"success": False, "msg": str(e)}
