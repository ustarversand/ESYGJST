#!/usr/bin/env python3
"""ECShop v2 API Mock — 模拟 duesselpharm.com 的 ECShop API 响应格式"""
import json
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

PORT = 8082

# ─── 模拟数据 ───
MOCK_PRODUCTS = [
    {"id": 1, "name": "德国直邮 爱他美Aptamil 白金新版 婴儿奶粉 pre段 800g",
     "sku": "APT-PRE", "price": "248", "market_price": "268",
     "stock": 56, "sales": 1280, "image": "", "brief": "德国直邮, 800g罐装",
     "category_id": 1, "brand": "Aptamil"},
    {"id": 2, "name": "德国直邮 爱他美Aptamil 白金新版 婴儿奶粉 1段 800g",
     "sku": "APT-1", "price": "248", "market_price": "268",
     "stock": 42, "sales": 2350, "image": "", "brief": "德国直邮, 800g罐装",
     "category_id": 1, "brand": "Aptamil"},
    {"id": 3, "name": "德国直邮 爱他美Aptamil 白金新版 婴儿奶粉 2段 800g",
     "sku": "APT-2", "price": "248", "market_price": "268",
     "stock": 38, "sales": 1890, "image": "", "brief": "德国直邮, 800g罐装",
     "category_id": 1, "brand": "Aptamil"},
    {"id": 4, "name": "PM Fitline Restorate 小白 42g",
     "sku": "PM-WHITE", "price": "580", "market_price": "620",
     "stock": 20, "sales": 356, "image": "", "brief": "细胞营养素",
     "category_id": 2, "brand": "PM Fitline"},
    {"id": 5, "name": "PM Fitline Actvize 小红 42g",
     "sku": "PM-RED", "price": "580", "market_price": "620",
     "stock": 15, "sales": 412, "image": "", "brief": "细胞营养素",
     "category_id": 2, "brand": "PM Fitline"},
    {"id": 6, "name": "PM Fitline Basics 大白 91g",
     "sku": "PM-BIG", "price": "680", "market_price": "720",
     "stock": 12, "sales": 289, "image": "", "brief": "基础营养包",
     "category_id": 2, "brand": "PM Fitline"},
    {"id": 7, "name": "雀巢BEBA至尊 pre段 800g",
     "sku": "BEBA-PRE", "price": "195", "market_price": "218",
     "stock": 88, "sales": 670, "image": "", "brief": "雀巢高端",
     "category_id": 1, "brand": "BEBA"},
    {"id": 8, "name": "雀巢BEBA至尊 1段 800g",
     "sku": "BEBA-1", "price": "195", "market_price": "218",
     "stock": 72, "sales": 890, "image": "", "brief": "雀巢高端",
     "category_id": 1, "brand": "BEBA"},
    {"id": 9, "name": "雀巢BEBA至尊 2段 800g",
     "sku": "BEBA-2", "price": "195", "market_price": "218",
     "stock": 65, "sales": 750, "image": "", "brief": "雀巢高端",
     "category_id": 1, "brand": "BEBA"},
    {"id": 10, "name": "Hipp 喜宝有机奶粉 pre段 600g",
     "sku": "HIPP-PRE", "price": "168", "market_price": "188",
     "stock": 34, "sales": 430, "image": "", "brief": "德国有机",
     "category_id": 1, "brand": "Hipp"},
    {"id": 11, "name": "德玛 D.Esteti 鱼子酱精华 30ml",
     "sku": "DE-CAVIAR", "price": "1280", "market_price": "1580",
     "stock": 8, "sales": 95, "image": "", "brief": "抗衰精华",
     "category_id": 3, "brand": "D.Esteti"},
    {"id": 12, "name": "Fitline Cell Capsules CC-胶囊 90粒",
     "sku": "PM-CC", "price": "860", "market_price": "920",
     "stock": 22, "sales": 310, "image": "", "brief": "细胞胶囊",
     "category_id": 2, "brand": "PM Fitline"},
]

MOCK_PRODUCTS_DETAIL = {
    1: {"id": 1, "name": "德国直邮 爱他美Aptamil 白金新版 婴儿奶粉 pre段 800g",
        "sku": "APT-PRE", "price": "248", "market_price": "268",
        "stock": 56, "sales": 1280, "brief": "德国直邮, 800g罐装",
        "description": "爱他美白金版Pre段，适合0-6个月新生儿。添加双重HMO母乳低聚糖，接近母乳配方。德国原装直邮。",
        "images": [], "category_id": 1, "brand": "Aptamil",
        "properties": [
            {"name": "发货规格", "attrs": [
                {"attr_id": 101, "attr_name": "4罐直邮", "price_diff": "0", "stock": 30},
                {"attr_id": 102, "attr_name": "6罐直邮", "price_diff": "0", "stock": 20},
                {"attr_id": 103, "attr_name": "8罐直邮", "price_diff": "10", "stock": 6},
            ]},
            {"name": "保质期", "attrs": [
                {"attr_id": 201, "attr_name": "2027年", "price_diff": "0", "stock": 56},
            ]},
        ]},
    2: {"id": 2, "name": "德国直邮 爱他美Aptamil 白金新版 婴儿奶粉 1段 800g",
        "sku": "APT-1", "price": "248", "market_price": "268",
        "stock": 42, "sales": 2350, "brief": "德国直邮, 800g罐装",
        "description": "爱他美白金版1段，适合6-12个月婴儿。添加GOS/FOS益生元组合，促进肠道健康。德国原装直邮。",
        "images": [], "category_id": 1, "brand": "Aptamil",
        "properties": [
            {"name": "发货规格", "attrs": [
                {"attr_id": 101, "attr_name": "4罐直邮", "price_diff": "0", "stock": 25},
                {"attr_id": 102, "attr_name": "6罐直邮", "price_diff": "0", "stock": 17},
            ]},
        ]},
}

MOCK_CATEGORIES = [
    {"id": 1, "name": "奶粉", "parent_id": 0, "level": 1, "product_count": 7},
    {"id": 2, "name": "Fitline / PM细胞营养素", "parent_id": 0, "level": 1, "product_count": 4},
    {"id": 3, "name": "德玛护肤", "parent_id": 0, "level": 1, "product_count": 1},
]

MOCK_ORDERS = [
    {"order_id": "20260513123456", "sn": "20260513123456", "total": 496.00,
     "status_label": "已发货", "status_code": "shipped",
     "consignee": {"name": "张三", "mobile": "138****1234", "address": "上海市浦东新区XX路100号"},
     "payment": "微信支付", "shipping": "德国DHL直邮",
     "created_at": "2026-05-13 10:30:00",
     "goods": [{"id": 1, "name": "爱他美白金pre段", "price": 248, "qty": 2}]},
    {"order_id": "20260513123457", "sn": "20260513123457", "total": 248.00,
     "status_label": "待发货", "status_code": "pending",
     "consignee": {"name": "李四", "mobile": "139****5678", "address": "北京市朝阳区XX街50号"},
     "payment": "支付宝", "shipping": "德国DHL直邮",
     "created_at": "2026-05-13 11:00:00",
     "goods": [{"id": 2, "name": "爱他美白金1段", "price": 248, "qty": 1}]},
    {"order_id": "20260513123458", "sn": "20260513123458", "total": 1160.00,
     "status_label": "已签收", "status_code": "received",
     "consignee": {"name": "王五", "mobile": "136****9012", "address": "广州市天河区XX路88号"},
     "payment": "银行转账", "shipping": "EMS特快",
     "created_at": "2026-04-28 14:00:00",
     "goods": [{"id": 4, "name": "PM Fitline 小白", "price": 580, "qty": 2}]},
]

MOCK_USER = {
    "id": 1, "username": "laoyang", "nickname": "老杨", "email": "laoyang@example.com",
    "mobile": "138****8888", "rank": "银牌会员", "points": 5200, "balance": "168.00",
    "is_auth": True,
}

MOCK_CONSIGNEES = [
    {"id": 1, "name": "张三", "mobile": "138****1234",
     "address": "上海市浦东新区XX路100号", "is_default": True},
    {"id": 2, "name": "李四", "mobile": "139****5678",
     "address": "北京市朝阳区XX街50号", "is_default": False},
]


def ok(data, debug_id=None):
    return {"error_code": 0, "error_desc": "", "debug_id": debug_id or str(uuid.uuid4())[:8], **data}

# ─── 请求路由 ───
ROUTES = {}

def route(endpoint):
    def wrapper(fn):
        ROUTES[endpoint] = fn
        return fn
    return wrapper

@route("ecapi.auth.signin")
def handle_login(body):
    return ok({"token": "mock_token_" + uuid.uuid4().hex[:12],
               "user": MOCK_USER})

@route("ecapi.product.list")
def handle_product_list(body):
    page = body.get("page", 1)
    per_page = body.get("per_page", 10)
    start = (page - 1) * per_page
    products = MOCK_PRODUCTS[start:start + per_page]
    return ok({"products": products, "total": len(MOCK_PRODUCTS), "page": page})

@route("ecapi.product.get")
def handle_product_get(body):
    pid = body.get("product")
    if isinstance(pid, dict):
        pid = pid.get("product_id")
    prod = MOCK_PRODUCTS_DETAIL.get(int(pid)) if pid else None
    if not prod:
        prod = next((p for p in MOCK_PRODUCTS if str(p["id"]) == str(pid)), None)
        if prod:
            prod = {**prod, "description": "", "images": [], "properties": []}
    if not prod:
        return {"error_code": 404, "error_desc": "商品不存在", "debug_id": uuid.uuid4().hex[:8]}
    return ok({"product": prod})

@route("ecapi.search.product.list")
def handle_product_search(body):
    keywords = body.get("keywords", "")
    page = body.get("page", 1)
    per_page = body.get("per_page", 10)
    q = keywords.lower()
    results = [p for p in MOCK_PRODUCTS
               if q in p["name"].lower() or q in p["sku"].lower() or q in p["brand"].lower()]
    start = (page - 1) * per_page
    return ok({"products": results[start:start + per_page],
               "total": len(results), "page": page})

@route("ecapi.category.list")
def handle_category_list(body):
    return ok({"categories": MOCK_CATEGORIES})

@route("ecapi.order.list")
def handle_order_list(body):
    page = body.get("page", 1)
    per_page = body.get("per_page", 10)
    start = (page - 1) * per_page
    return ok({"orders": MOCK_ORDERS[start:start + per_page],
               "total": len(MOCK_ORDERS), "page": page})

@route("ecapi.order.get")
def handle_order_get(body):
    oid = body.get("order_id", "")
    order = next((o for o in MOCK_ORDERS if o["sn"] == oid or o["order_id"] == oid), None)
    if not order:
        return {"error_code": 404, "error_desc": "订单不存在", "debug_id": uuid.uuid4().hex[:8]}
    return ok({"order": order})

@route("ecapi.consignee.list")
def handle_consignee_list(body):
    return ok({"consignees": MOCK_CONSIGNEES})


class Handler(BaseHTTPRequestHandler):
    def _respond(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_POST(self):
        path = self.path.strip("/")
        if path.startswith("v2/"):
            path = path[3:]
        body_len = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(body_len) if body_len else b"{}"
        body = json.loads(raw) if raw else {}
        print(f"  ← POST /{path}  body={json.dumps(body, ensure_ascii=False)}")

        if path == "":
            self._respond(200, ok({"service": "ECShop v2 API (Mock)", "version": "2.0"}))
            return

        handler = ROUTES.get(path)
        if handler:
            try:
                result = handler(body)
                self._respond(200, result)
            except Exception as e:
                self._respond(200, {"error_code": 500, "error_desc": str(e), "debug_id": "mock_error"})
        else:
            self._respond(200, {"error_code": 404, "error_desc": f"API {path} 不存在",
                                "debug_id": uuid.uuid4().hex[:8]})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f"[MockECShop] {args[0]} {args[1]} → {args[2]}", flush=True)


if __name__ == "__main__":
    print(f"🚀 ECShop v2 API Mock — {len(MOCK_PRODUCTS)} 商品, {len(MOCK_ORDERS)} 订单")
    print(f"   监听 http://0.0.0.0:{PORT}/v2/")
    print(f"   支持接口:")
    for ep in sorted(ROUTES):
        print(f"     POST /v2/{ep}")
    print()
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
