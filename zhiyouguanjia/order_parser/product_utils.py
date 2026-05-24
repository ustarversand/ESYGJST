"""直邮管家 — 产品名扫描工具函数
已知产品名匹配、连写商品拆分、SKU自动补全等
"""
import re
import logging
from push_engine import fuzzy_match_sku, PM_PRODUCTS

logger = logging.getLogger("pm-parser")

# 预缓存：按长度降序的产品名列表（全局，避免重复排序）
_SORTED_PRODUCT_NAMES = sorted(PM_PRODUCTS.keys(), key=len, reverse=True)

# 品牌前缀列表（用于生成别名）
_BRAND_PREFIXES = ["PM Fitline", "PM", "Fitline"]

# 构建已知产品名集合（含子串，用于过滤姓名/备注中的商品名）
_KNOWN_PRODUCT_NAMES = set(k.lower() for k in PM_PRODUCTS.keys())
_KNOWN_PRODUCT_PARTS = set()
for kn in _KNOWN_PRODUCT_NAMES:
    for i in range(len(kn) - 1):
        for j in range(i + 2, min(i + 5, len(kn) + 1)):
            _KNOWN_PRODUCT_PARTS.add(kn[i:j])


def is_known_product_name(name: str) -> bool:
    """判断文本是否是已知商品名"""
    return name.lower() in _KNOWN_PRODUCT_NAMES or name.lower() in _KNOWN_PRODUCT_PARTS


def apply_sku_to_items(items: list):
    """批量自动匹配SKU"""
    for item in items:
        if not item.get("sku_id"):
            item["sku_id"] = fuzzy_match_sku(item["name"])


# ─── 产品名中的+号保护 ─────────────────────────────────

_plus_placeholders = {}


def protect_plus(text: str) -> str:
    """将产品名中的+替换为占位符，避免被分隔符切割"""
    global _plus_placeholders
    _plus_placeholders = {}
    for pname in sorted(PM_PRODUCTS.keys(), key=len, reverse=True):
        if '+' in pname and pname in text:
            ph = f"__PLUS_{len(_plus_placeholders)}__"
            _plus_placeholders[ph] = pname
            text = text.replace(pname, ph)
    return text


def unprotect_plus(text: str) -> str:
    """将占位符恢复为原产品名"""
    for ph, pname in _plus_placeholders.items():
        text = text.replace(ph, pname)
    return text


# ─── 地址尾部商品提取 ─────────────────────────────────


def extract_products_from_address_tail(address_text: str) -> (list, str):
    """从地址字符串末尾扫描已知商品名+数量，返回(items, cleaned_address)

    如 "...小溪村1-29号 柠檬小红3罐" → ([{name, qty}], "...小溪村1-29号")
    """
    items = []
    scan_addr = address_text
    while scan_addr:
        best_match = None
        best_pos = -1
        best_end = -1
        best_len = 0
        for kn in _SORTED_PRODUCT_NAMES:
            idx = scan_addr.rfind(kn)
            if idx >= 0:
                after = scan_addr[idx + len(kn):]
                m_num = re.match(r'[xX×*]?\s*(\d+)', after)
                if m_num:
                    match_end = idx + len(kn) + (after.index(m_num.group(0)) + len(m_num.group(0)))
                    if best_pos < 0 or (idx < best_pos and idx + len(kn) <= best_pos) or (idx >= best_end):
                        if idx > best_pos:
                            best_pos = idx
                            best_end = match_end
                            best_len = len(kn)
                            best_match = {
                                "name": kn,
                                "qty": int(m_num.group(1)),
                                "sku_id": fuzzy_match_sku(kn),
                            }
        if best_match:
            items.insert(0, best_match)
            scan_addr = scan_addr[:best_pos] + scan_addr[best_end:]
        else:
            break
    if items:
        address_text = scan_addr.strip()
    return items, address_text


# ─── 连写商品拆分（如"小红8辅酶8"）────────────────────


def scan_concat_products(text: str, reverse: bool = False) -> list:
    """贪心扫描 name+digits+name+digits 连写格式"""
    found = []
    pos = len(text) - 1 if reverse else 0
    step = -1 if reverse else 1
    while 0 <= pos < len(text):
        best_match = None
        best_len = 0
        for kn in _SORTED_PRODUCT_NAMES:
            if reverse:
                end = pos + 1
                start = end - len(kn)
                if start < 0:
                    continue
                if text[start:end] == kn:
                    before = text[:start]
                    m_num = re.search(r"(\d+)$", before) if before else None
                    if m_num:
                        if len(kn) > best_len:
                            best_match = (kn, int(m_num.group(1)), start - m_num.end())
                            best_len = len(kn)
            else:
                if text[pos:pos + len(kn)] == kn:
                    after = text[pos + len(kn):]
                    m_num = re.match(r"(\d+)", after)
                    if m_num:
                        if len(kn) > best_len:
                            best_match = (kn, int(m_num.group(1)), pos + len(kn) + m_num.end())
                            best_len = len(kn)
        if best_match:
            kn_name, kn_qty, next_pos = best_match
            found.append({"name": kn_name, "qty": kn_qty})
            pos = next_pos
        else:
            break
    return found


# ─── 从rest_lines解析商品（标签格式中未匹配标签的行）───


def parse_items_from_text(text: str) -> list:
    """从自由文本解析商品列表（用逗号/加号分割，每段parse_qty）"""
    items = []
    segments = [s for s in re.split(r'[，,+＋]', text) if s.strip()]
    from order_parser.fields import _parse_qty
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        qty, prod = _parse_qty(seg)
        if prod and (qty > 1 or fuzzy_match_sku(prod)):
            items.append({
                "name": prod,
                "qty": qty,
                "sku_id": fuzzy_match_sku(prod),
            })
    return items
