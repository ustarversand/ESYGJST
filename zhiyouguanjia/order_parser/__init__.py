"""直邮管家 — 一段话订单解析器
把自然语言订单文本解析为结构化字段

支持格式：
- 标签格式：收件人: / 手机: / 所在地区: / 详细地址:
- 自由文本："两罐爱他美白金pre直邮 ：13750639232 张梦露 浙江省..."
"""
import re
import logging
from push_engine import fuzzy_match_sku, PM_PRODUCTS

from order_parser.fields import (
    _parse_qty, _parse_phone, _extract_address, _extract_name,
    _LOGISTICS_KW, _LABEL_WORDS,
)
from order_parser.product_utils import (
    _SORTED_PRODUCT_NAMES, is_known_product_name, apply_sku_to_items,
    protect_plus, unprotect_plus,
    extract_products_from_address_tail, scan_concat_products,
    parse_items_from_text, _KNOWN_PRODUCT_NAMES, _KNOWN_PRODUCT_PARTS,
)

logger = logging.getLogger("pm-parser")


def parse_order_text(raw_text: str) -> dict:
    """解析一段话订单文本

    Returns:
        {"success": bool, "items": [{name, qty, sku_id}], "phone": str,
         "receiver_name": str, "state": str, "city": str,
         "district": str, "address": str, "buyer_message": str,
         "id_card_number": str, "is_direct_mail": bool}
    """
    text = raw_text.strip()
    if not text:
        return {"success": False, "msg": "文本不能为空"}

    logger.info(f"[解析] 原文: {text}")

    # ===== 预处理：单"收件人"标签剥除 =====
    _has_name_label = '收件人' in raw_text or '收货人' in raw_text or '姓名' in raw_text
    _has_phone_label = '手机' in raw_text or '电话' in raw_text
    _has_region_label = '所在地区' in raw_text
    _has_addr_label = '详细地址' in raw_text or re.search(r'(?<!所在地区)地址\s*[：:]', raw_text) is not None
    _label_count = sum([_has_name_label, _has_phone_label, _has_region_label, _has_addr_label])
    if _label_count < 3:
        text_stripped = re.sub(r'^(?:收件人|收货人|姓名)\s*[：:]?\s*', '', raw_text.strip())
        if text_stripped != raw_text.strip():
            logger.info(f"[解析] 剥除收件人标签: {text_stripped[:60]}...")
            text = text_stripped
        else:
            text = raw_text.strip()
    else:
        text = raw_text.strip()

    # ===== 检测标签格式 =====
    has_name_label = '收件人' in text or '收货人' in text or '姓名' in text
    has_phone_label = '手机' in text or '电话' in text
    has_region_label = '所在地区' in text
    has_addr_label = ('详细地址' in text or
                      re.search(r'(?<!所在地区)地址\s*[：:]', text) is not None)
    label_count = sum([has_name_label, has_phone_label, has_region_label, has_addr_label])

    if label_count >= 3:
        return _parse_label_format(text)

    # ===== 以下是自由文本解析逻辑 =====
    return _parse_free_text(text)


def _parse_label_format(text: str) -> dict:
    """标签格式解析（收件人: / 手机: / 所在地区: / 详细地址:）"""
    logger.info(f"[解析] 检测到标签格式，共{count_labels(text)}个标签")
    lines = text.strip().split('\n')
    fields = {}
    rest_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = re.match(r'(收件人|收货人|姓名)\s*[：:]\s*(.+)', line, re.IGNORECASE)
        if m:
            fields['name'] = m.group(2).strip()
            continue
        m = re.match(r'(手机号码|手机号|电话|手机)\s*[：:]\s*(1[3-9]\d{9})', line, re.IGNORECASE)
        if m:
            fields['phone'] = m.group(2).strip()
            continue
        m = re.match(r'(所在地区)\s*[：:]\s*(.+)', line, re.IGNORECASE)
        if m:
            fields['region'] = m.group(2).strip()
            continue
        m = re.match(r'(详细地址|地址)\s*[：:]?\s*(.+)', line, re.IGNORECASE)
        if m:
            fields['address'] = m.group(2).strip()
            continue
        m = re.match(r'(身份证号|身份证)\s*[：:]?\s*(.+)', line, re.IGNORECASE)
        if m:
            fields['id_card'] = m.group(2).strip()
            continue
        rest_lines.append(line)

    if not (fields.get('phone') and (fields.get('name') or fields.get('address') or fields.get('region'))):
        return {"success": False, "msg": "标签格式不完整"}

    # 解析所在地区（省市区）
    state, city, district = "", "", ""
    region = fields.get('region', '')
    address_text = fields.get('address', '')
    from order_parser.fields import _PROVINCES, _NORM_PROV, _NORM_CITY

    if region:
        for prov in _PROVINCES:
            if region.startswith(prov):
                state = prov
                rest = region[len(prov):].lstrip('省')
                m_city = re.match(r'([^市区县]+[市])', rest)
                if m_city:
                    city = m_city.group(1)
                    rest = rest[m_city.end():]
                m_dist = re.match(r'([^区县]+[区县])', rest)
                if m_dist:
                    district = m_dist.group(1)
                break
    elif address_text:
        _addr_info, _ = _extract_address(address_text)
        state, city, district = _addr_info["state"], _addr_info["city"], _addr_info["district"]
        if _addr_info["address"]:
            address_text = _addr_info["address"]

    # 从地址尾部分离商品信息（括号内内容）
    items = []
    items_text = ""
    m_bracket = re.search(r'[（(](.+?)[）)]$', address_text)
    if m_bracket:
        items_text = m_bracket.group(1)
        address_text = address_text[:m_bracket.start()].strip()
    else:
        # 无括号时，从右向左扫描已知商品名
        products, address_text = extract_products_from_address_tail(address_text)
        items.extend(products)

    if any(item.get("name") for item in items):
        items_text = " ".join(f"{i['name']}{i['qty']}" for i in items)

    # 是否直邮
    is_direct_mail = "直邮" in address_text or "直邮" in items_text

    # 解析商品
    if not items and items_text:
        items = _parse_items_from_label(items_text)

    # 如果地址尾部没解析到商品，尝试从 rest_lines 解析
    if not items and rest_lines:
        rest_text = " ".join(rest_lines)
        logger.info(f"[解析] 从 rest_lines 解析商品: {rest_text[:80]}")
        items = parse_items_from_text(rest_text)

    apply_sku_to_items(items)

    result = {
        "success": True,
        "items": items,
        "phone": fields.get('phone', ''),
        "receiver_name": fields.get('name', ''),
        "is_direct_mail": is_direct_mail,
        "buyer_message": "",
        "id_card_number": fields.get('id_card', ''),
        "state": state,
        "city": city,
        "district": district,
        "address": address_text,
    }
    logger.info(f"[解析] 标签格式结果: {result}")
    return result


def _parse_free_text(text: str) -> dict:
    """自由文本解析"""
    # 提取直邮标记
    is_direct_mail = "直邮" in text

    items = []
    parsed_phone = ""
    parsed_name = ""
    address_info = {}
    parsed_msg = ""
    parsed_id_card = ""

    # 先找电话
    parsed_phone, after_phone = _parse_phone(text)
    if not parsed_phone:
        after_phone = text

    # 提取地址（从省开始）
    address_info, msg_from_addr = _extract_address(after_phone)

    if address_info["state"]:
        logger.info(f"[解析] 地址: {address_info}")
        if msg_from_addr:
            parsed_msg = msg_from_addr
            logger.info(f"[解析] 地址分离备注: {parsed_msg}")

        # 在地址前找姓名
        addr_pos = after_phone.find(address_info["state"])
        if addr_pos < 0:
            _state_short = re.sub(r'(省|市|自治区|特别行政区)$', '', address_info["state"])
            if _state_short != address_info["state"]:
                addr_pos = after_phone.find(_state_short)
        before_addr = after_phone[:addr_pos].strip() if addr_pos >= 0 else ""
        before_addr = re.sub(r'1[3-9]\d{9}', '', before_addr).strip()
        before_addr = re.sub(r'[：:\s]+', ' ', before_addr).strip()

        parts = before_addr.split()
        if parts:
            for p in parts:
                p = p.strip()
                if p in ('收件人', '收货人', '姓名', '发货人', '寄件人'):
                    continue
                if re.match(r'^[\u4e00-\u9fa5]{2,4}$', p) and not re.search(r'\d', p) and not is_known_product_name(p):
                    parsed_name = p
                    break
            if not parsed_name:
                for p in reversed(parts):
                    p = p.strip()
                    if p in ('收件人', '收货人', '姓名', '发货人', '寄件人'):
                        continue
                    if re.search(r'\d', p):
                        continue
                    if not is_known_product_name(p):
                        parsed_name = p
                        break

        if not parsed_name:
            addr_start_idx = after_phone.find(address_info["state"])
            if addr_start_idx < 0:
                _state_short = re.sub(r'(省|市|自治区|特别行政区)$', '', address_info["state"])
                if _state_short != address_info["state"]:
                    addr_start_idx = after_phone.find(_state_short)
            if addr_start_idx >= 0:
                addr_end_idx = (addr_start_idx + len(address_info["state"])
                                + len(address_info.get("city", ""))
                                + len(address_info.get("district", ""))
                                + len(address_info.get("address", "")))
                after_addr_text = after_phone[addr_end_idx:].strip()
                if after_addr_text:
                    m_name = re.search(r'([\u4e00-\u9fa5]{2,4})', after_addr_text)
                    if m_name:
                        candidate = m_name.group(1)
                        if (candidate not in ('收件人', '收货人', '姓名', '发货人', '寄件人')
                                and not is_known_product_name(candidate)):
                            parsed_name = candidate
                            logger.info(f"[解析] 地址后提取姓名: {parsed_name}")

        if not parsed_msg:
            addr_pos2 = after_phone.find(address_info["state"])
            if addr_pos2 >= 0:
                addr_full = after_phone[addr_pos2:]
                addr_full_end = addr_full.find(address_info.get("address", ""))
                if addr_full_end >= 0:
                    msg_start = addr_full_end + len(address_info.get("address", ""))
                    parsed_msg = addr_full[msg_start:].strip()

        parsed_msg = parsed_msg.replace("直邮", "").strip()
        parsed_msg = re.sub(r'\s+', ' ', parsed_msg).strip()
    else:
        # 没有地址，整段作为商品信息
        after_phone
        cand_name, after_name = _extract_name(after_phone)
        if cand_name and is_known_product_name(cand_name):
            parsed_name = ""
        else:
            parsed_name = cand_name

    # 从文本中提取商品
    item_text = text
    if parsed_phone:
        item_text = item_text.replace(parsed_phone, "")
    if address_info.get("state"):
        addr_start = item_text.find(address_info["state"])
        if addr_start < 0:
            _state_short = re.sub(r'(省|市|自治区|特别行政区)$', '', address_info["state"])
            if _state_short != address_info["state"]:
                addr_start = item_text.find(_state_short)
        if addr_start >= 0:
            item_text = item_text[:addr_start]
    if parsed_name:
        item_text = item_text.replace(parsed_name, "")
    item_text = re.sub(r'[：:\s,，直邮]+', ' ', item_text).strip()

    # 保护产品名中的+号
    item_text = protect_plus(item_text)
    item_text = re.sub(r'[+＋]', ' ', item_text).strip()
    item_text = unprotect_plus(item_text)

    # 用空格分割
    item_segments = re.split(r'\s+', item_text)
    _last_item_idx = -1
    for seg in item_segments:
        seg = seg.strip()
        if not seg:
            continue
        m_star = re.match(r'^[*×]\s*(\d+)$', seg)
        if m_star:
            qty = int(m_star.group(1))
            if _last_item_idx >= 0 and len(items) > _last_item_idx:
                items[_last_item_idx]['qty'] = qty
            continue
        m_xqty = re.match(r'^[xX×]\s*(\d+)$', seg)
        if m_xqty:
            qty = int(m_xqty.group(1))
            if _last_item_idx >= 0 and len(items) > _last_item_idx:
                items[_last_item_idx]['qty'] = qty
            continue
        if not re.search(r'[\u4e00-\u9fa5]', seg):
            if not re.match(r'^[A-Za-z0-9\-]{5,}$', seg):
                continue
        if seg in _LABEL_WORDS:
            continue
        if seg in _LOGISTICS_KW:
            continue
        if re.match(r'^[\dXx]{15,}$', seg) or re.match(r'^\d{11}$', seg):
            continue
        if re.match(r'^\d+[罐盒瓶袋箱条包套件]$', seg) and not re.search(r'[\u4e00-\u9fa5]{2,}', seg):
            qty = int(re.match(r'^(\d+)', seg).group(1))
            if _last_item_idx >= 0 and len(items) > _last_item_idx:
                items[_last_item_idx]['qty'] = qty
            continue
        qty, product_name = _parse_qty(seg)
        if product_name:
            product_name = product_name.replace("直邮", "").strip()
            if product_name:
                items.append({"name": product_name, "qty": qty, "sku_id": ""})
                _last_item_idx = len(items) - 1
            if qty == 1 and product_name:
                m_trail = re.search(r'(\d+)$', product_name)
                if m_trail:
                    base_name = product_name[:m_trail.start()]
                    trail_qty = int(m_trail.group(1))
                    if base_name in PM_PRODUCTS:
                        items[-1]['name'] = base_name
                        items[-1]['qty'] = trail_qty

    # 连写商品拆分
    items = _split_concat_items(items)

    # 如果没解析出商品，从全文提取
    if not items:
        qty, after_qty = _parse_qty(text)
        product = after_qty
        if parsed_phone:
            product = product.replace(parsed_phone, "")
        if parsed_name:
            product = product.replace(parsed_name, "")
        if address_info.get("state"):
            a = address_info["state"]
            product = product[:product.find(a)] if a in product else product
        product = re.sub(r'[：:\s,，直邮]+', ' ', product).strip()
        if product:
            _product_words = set(product.split())
            if _product_words - _LABEL_WORDS:
                items.append({"name": product, "qty": qty, "sku_id": ""})

    # 商品名中的数量词提取
    clean_items(items)

    # 自动匹配SKU
    apply_sku_to_items(items)

    # 从地址分离的文本中提取商品
    if parsed_msg:
        items, parsed_msg = _extract_items_from_msg(parsed_msg, parsed_name, items)

    # 从备注中提取身份证号
    if parsed_msg:
        _id_match = re.search(r'\b(\d{17}[\dXx])\b', parsed_msg)
        if _id_match:
            parsed_id_card = _id_match.group(1)
            parsed_msg = parsed_msg.replace(_id_match.group(1), '').strip(' ,，、').strip()

    result = {
        "success": bool(parsed_phone or address_info.get("state") or items),
        "items": items,
        "phone": parsed_phone,
        "receiver_name": parsed_name,
        "is_direct_mail": is_direct_mail,
        "buyer_message": parsed_msg,
        "id_card_number": parsed_id_card,
        **address_info,
    }

    if not result["success"]:
        result["msg"] = "未能解析出有效订单信息"

    logger.info(f"[解析] 结果: {result}")
    return result


# ===== 内部辅助函数 =====


def count_labels(text: str) -> int:
    return sum([
        '收件人' in text or '收货人' in text or '姓名' in text,
        '手机' in text or '电话' in text,
        '所在地区' in text,
        '详细地址' in text or re.search(r'(?<!所在地区)地址\s*[：:]', text) is not None,
    ])


def _parse_items_from_label(items_text: str) -> list:
    """从标签格式的括号内容中解析商品"""
    items = []
    scan = items_text
    while scan:
        best_match = None
        best_len = 0
        next_pos = 0
        for kn in _SORTED_PRODUCT_NAMES:
            if scan.startswith(kn):
                after = scan[len(kn):]
                m_num = re.match(r'[xX×*]?\s*(\d+)', after)
                if m_num and len(kn) > best_len:
                    best_match = {"name": kn, "qty": int(m_num.group(1))}
                    best_len = len(kn)
                    next_pos = len(kn) + (after.index(m_num.group(0)) + len(m_num.group(0)))

        if best_match:
            items.append(best_match)
            scan = scan[next_pos:]
        else:
            # 没匹配到已知商品 → 通用商品
            m_generic = re.match(r'([\u4e00-\u9fa5]+)(\d+)', scan)
            if m_generic:
                items.append({"name": m_generic.group(1), "qty": int(m_generic.group(2)), "sku_id": ""})
                scan = scan[m_generic.end():]
            else:
                break
    return items


def _split_concat_items(items: list) -> list:
    """拆分连写商品格式（如"小红8辅酶8"）"""
    new_items = []
    for item in items:
        name = item["name"]
        if item["qty"] == 1 and name:
            left = scan_concat_products(name, reverse=False)
            right = scan_concat_products(name, reverse=True)
            concat_found = left if len(left) >= 2 else (right if len(right) >= 2 else [])
            if len(concat_found) < 2:
                seen = set()
                merged = []
                for item_list in (left, right):
                    for cf in item_list:
                        key = (cf["name"], cf["qty"])
                        if key not in seen:
                            seen.add(key)
                            merged.append(cf)
                concat_found = merged
            if len(concat_found) >= 2:
                for cf in concat_found:
                    new_items.append({"name": cf["name"], "qty": cf["qty"], "sku_id": ""})
                continue
        new_items.append(item)
    return new_items if new_items else items


def clean_items(items: list):
    """从商品名中提取尾随数量"""
    for item in items:
        name = item["name"]
        extra_qty, clean_name = _parse_qty(name)
        if extra_qty > 1:
            item["qty"] = item["qty"] * extra_qty
            item["name"] = clean_name
        else:
            # 从名称末尾提取数量格式
            m1 = re.search(r'(.+?)(\d+)\s*[*×]\s*(\d+)([罐盒瓶袋箱条包套件])$', name)
            if m1:
                item["qty"] = item["qty"] * (int(m1.group(2)) * int(m1.group(3)))
                item["name"] = m1.group(1).strip()
            else:
                m2 = re.search(r'(.+?)(\d+)([罐盒瓶袋箱条包套件])$', name)
                if m2:
                    item["qty"] = item["qty"] * int(m2.group(2))
                    item["name"] = m2.group(1).strip()


def _extract_items_from_msg(parsed_msg: str, parsed_name: str, existing_items: list) -> (list, str):
    """从地址分离的文本中提取商品"""
    from order_parser.fields import _parse_qty as _pq
    _msg_clean = parsed_msg.strip()
    if parsed_name and _msg_clean.startswith(parsed_name):
        _msg_clean = _msg_clean[len(parsed_name):].strip().lstrip('。，,、').strip()
    _msg_clean = re.sub(r'^[。，,、.\s]+', '', _msg_clean).strip()

    _product_parts = []
    _msg_parts = []
    for seg in re.split(r'[，,、]', _msg_clean):
        seg = seg.strip()
        if not seg:
            continue
        seg_clean = seg.replace("直邮", "").strip()
        if not seg_clean:
            continue
        qty, prod_name = _pq(seg_clean)
        if qty == 1 and prod_name == seg_clean:
            m3 = re.search(r'(\d+)\s*([罐盒瓶袋箱条包套件])', seg_clean)
            if m3:
                qty = int(m3.group(1))
                prod_name = (seg_clean[:m3.start()] + seg_clean[m3.end():]).replace("直邮", "").strip("，, ").strip()
        if prod_name and (qty > 1 or fuzzy_match_sku(prod_name)):
            _product_parts.append({"name": prod_name, "qty": qty, "sku_id": fuzzy_match_sku(prod_name)})
        else:
            _msg_parts.append(seg)

    existing_items.extend(_product_parts)
    parsed_msg = ", ".join(_msg_parts) if _msg_parts else ""
    return existing_items, parsed_msg
