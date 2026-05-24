"""直邮管家 — 项目配置
德国直邮营养保健/奶粉/美妆产品，通过聚水潭推单
"""
import os

# ===== 聚水潭 API 配置 =====
_JST_APP_KEY = os.getenv("JST_APP_KEY")
_JST_APP_SECRET = os.getenv("JST_APP_SECRET")
_JST_TOKEN = os.getenv("JST_TOKEN")
if not _JST_APP_KEY or not _JST_APP_SECRET or not _JST_TOKEN:
    raise RuntimeError("请设置 JST_APP_KEY / JST_APP_SECRET / JST_TOKEN 环境变量")
JST_CONFIG = {
    "app_key": _JST_APP_KEY,
    "app_secret": _JST_APP_SECRET,
    "token": _JST_TOKEN,
    "api_url_legacy": "https://open.erp321.com/api/open/query.aspx",
    "api_url_new": "https://openapi.jushuitan.com",
}

# ===== 用户认证 =====
# username: {password, shop_key(不填=管理员看全部)}
USERS = {
    "admin": {"password": "Hilden11031980", "shop_key": None},
    "qiaoma": {"password": "123456", "shop_key": "乔妈"},
}

# ===== 店铺 =====
# 完整店铺列表（从全工作区收集，共15店）
_NEED_IDCARD = True
_DONT_NEED_IDCARD = False
SHOPS = {
    "AUSTARWX":          {"id": "18442196", "name": "AUSTARWX", "need_idcard": _NEED_IDCARD, "platform": "跨境线下平台"},
    "沐浴阳光PDD":       {"id": "18020520", "name": "沐浴阳光PDD", "need_idcard": _DONT_NEED_IDCARD, "platform": "拼多多"},
    "武姐":              {"id": "18283794", "name": "武姐", "need_idcard": _NEED_IDCARD, "platform": "跨境线下平台"},
    "韦峥":              {"id": "18331345", "name": "韦峥", "need_idcard": _NEED_IDCARD, "platform": "跨境线下平台"},
    "夏总WX":            {"id": "18614842", "name": "夏总WX", "need_idcard": _NEED_IDCARD, "platform": "跨境线下平台"},
    "夏总天海易购":      {"id": "16631713", "name": "夏总天海易购", "need_idcard": _NEED_IDCARD, "platform": "跨境线下平台"},
    "甘总-付总":         {"id": "17288013", "name": "甘总-付总", "need_idcard": _DONT_NEED_IDCARD, "platform": "跨境线下平台"},
    "乔妈":              {"id": "16612947", "name": "乔妈", "need_idcard": _DONT_NEED_IDCARD, "platform": "跨境线下平台"},
    "A路久":             {"id": "16896076", "name": "A路久", "need_idcard": _NEED_IDCARD, "platform": "跨境线下平台"},
    "德聚小罗":          {"id": "19437979", "name": "德聚小罗", "need_idcard": _NEED_IDCARD, "platform": "跨境线下平台"},
    "阿美奶粉":          {"id": "18559895", "name": "阿美奶粉", "need_idcard": _NEED_IDCARD, "platform": "跨境线下平台"},
    "沐浴阳光JD":        {"id": "18422496", "name": "沐浴阳光JD", "need_idcard": _DONT_NEED_IDCARD, "platform": "京东"},
    "Asweety":           {"id": "18334864", "name": "Asweety", "need_idcard": _DONT_NEED_IDCARD, "platform": "跨境线下平台"},
    "A高总":             {"id": "16871568", "name": "A高总", "need_idcard": _NEED_IDCARD, "platform": "跨境线下平台"},
    "智能体AI店铺":      {"id": "20941412", "name": "智能体AI店铺", "need_idcard": _NEED_IDCARD, "platform": "跨境线下平台"},
}

DEFAULT_SHOP_KEY = "AUSTARWX"
DEFAULT_SHOP_ID = SHOPS[DEFAULT_SHOP_KEY]["id"]
DEFAULT_SHOP_NAME = DEFAULT_SHOP_KEY
DEFAULT_BUYER_ID = "直邮管家"

# ===== 产品别名→SKU 映射（从 JSON 加载） =====
# 数据文件: data/products.json（修改后无需重启）
import json as _json
_PRODUCTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "products.json")


def _load_products():
    """从 JSON 加载产品数据，文件不存在时保持向后兼容"""
    if not os.path.exists(_PRODUCTS_FILE):
        return {}, {}, {}, {}
    try:
        with open(_PRODUCTS_FILE, "r", encoding="utf-8") as f:
            data = _json.load(f)
        return (
            data.get("milk_powder", {}),
            data.get("pm_fitline", {}),
            data.get("other", {}),
            data.get("qiaoma_prices", {}),
        )
    except Exception:
        return {}, {}, {}, {}


MILK_POWDER_PRODUCTS, PM_FITLINE_PRODUCTS, OTHER_PRODUCTS, QIAOMA_PRICES = _load_products()

# 合并全部产品为一个字典（订单解析用）
PM_PRODUCTS = {}
PM_PRODUCTS.update(MILK_POWDER_PRODUCTS)
PM_PRODUCTS.update(PM_FITLINE_PRODUCTS)
PM_PRODUCTS.update(OTHER_PRODUCTS)

# ===== Flask =====
HOST = "0.0.0.0"
PORT = 8899
DEBUG = False