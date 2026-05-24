"""直邮管家 — Excel 订单解析
"""
import re
import openpyxl
import logging
from typing import List, Optional

logger = logging.getLogger("pm-excel")


def parse_excel(filepath: str, sheet_index: int = 0) -> List[dict]:
    """
    解析 Excel 文件中的订单数据

    支持的列名 (中英文均可):
        - 订单号 / so_id / order_id
        - 收件人 / receiver_name / name
        - 电话 / receiver_phone / phone / mobile / 手机号
        - 省 / receiver_state / province / state
        - 市 / receiver_city / city
        - 区 / receiver_district / district / 地区
        - 地址 / receiver_address / address / 详细地址
        - 商品编码 / sku_id / sku
        - 商品名称 / name / product_name / 商品
        - 数量 / qty / quantity / 件数
        - 价格 / price / 单价
        - 备注 / buyer_message / remark / message
        - 身份证号 / id_card_number / idcard / id_no
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.worksheets[sheet_index]

    rows = list(ws.iter_rows(values_only=True))
    if not rows or not rows[0]:
        return []

    # 构建表头映射
    header_map = _build_header_map(rows[0])

    orders = []
    last_real_idx = -1  # 上一个有效订单的索引

    for row in rows[1:]:
        if not any(cell is not None for cell in row):
            continue  # 跳过空行

        order = _row_to_order(row, header_map)

        # 续行检测：so_id=0 且无收件人信息，但有商品 → 合并到上一单
        so_id = order.get("so_id", "")
        has_receiver = bool(order.get("receiver_name"))
        has_items = bool(order.get("items"))
        is_continuation = (so_id == "0" or so_id == "") and not has_receiver and has_items

        if is_continuation and last_real_idx >= 0:
            orders[last_real_idx]["items"].extend(order["items"])
            logger.info(f"[续行] so_id={so_id!r} 合并到第{last_real_idx}单 (so_id={orders[last_real_idx].get('so_id','')})")
        elif has_receiver or has_items:
            orders.append(order)
            if so_id or has_receiver:
                last_real_idx = len(orders) - 1

    wb.close()

    # 去重合并：同so_id的多行合并为一个订单
    orders = _merge_same_so_id(orders)

    return orders


def _merge_same_so_id(orders: list) -> list:
    """合并同so_id的多个订单为一个（去重保留商品明细）"""
    merged = {}
    result = []
    for o in orders:
        so_id = o.get("so_id", "")
        if so_id and so_id != "0":
            if so_id in merged:
                idx = merged[so_id]
                result[idx]["items"].extend(o["items"])
                # 保留非空字段
                for k in ("receiver_name", "receiver_phone", "receiver_state", "receiver_city",
                          "receiver_district", "receiver_address", "id_card_number", "buyer_message"):
                    if o.get(k) and not result[idx].get(k):
                        result[idx][k] = o[k]
                logger.info(f"[去重] so_id={so_id} 合并到已存在的订单")
            else:
                merged[so_id] = len(result)
                result.append(o)
        else:
            result.append(o)
    return result


HEADER_ALIASES = {
    "订单号": "so_id", "so_id": "so_id", "order_id": "so_id", "so id": "so_id", "系统订单号": "so_id", "客户订单号": "so_id",
    "寄件人": "sender_name", "发件人": "sender_name",
    "收件人": "receiver_name", "receiver_name": "receiver_name", "name": "receiver_name", "收货人": "receiver_name",
    "收件人姓名": "receiver_name",
    "收件人地址街道": "receiver_address",
    "电话": "receiver_phone", "receiver_phone": "receiver_phone", "phone": "receiver_phone",
    "手机": "receiver_phone", "mobile": "receiver_phone", "手机号": "receiver_phone", "手机号码": "receiver_phone", "联系电话": "receiver_phone",
    "省": "receiver_state", "receiver_state": "receiver_state", "province": "receiver_state", "state": "receiver_state",
    "市": "receiver_city", "receiver_city": "receiver_city", "city": "receiver_city",
    "区": "receiver_district", "receiver_district": "receiver_district", "district": "receiver_district",
    "地区": "receiver_district",
    "地址": "receiver_address", "receiver_address": "receiver_address", "address": "receiver_address",
    "详细地址": "receiver_address",
    "商品编码": "sku_id", "sku_id": "sku_id", "sku": "sku_id", "编码": "sku_id", "条码": "sku_id", "SKU": "sku_id",
    "商品": "item_name", "商品名称": "item_name", "name": "item_name", "product_name": "item_name", "货品": "item_name", "产品": "item_name", "货物名称": "item_name", "品名": "item_name",
    "数量": "qty", "qty": "qty", "quantity": "qty", "件数": "qty",
    "价格": "price", "price": "price", "单价": "price", "金额": "price", "pay_amount": "pay_amount",
    "备注": "buyer_message", "buyer_message": "buyer_message", "remark": "buyer_message",
    "message": "buyer_message", "留言": "buyer_message", "买家留言": "buyer_message",
    "身份证号": "id_card_number", "id_card_number": "id_card_number", "idcard": "id_card_number",
    "id_no": "id_card_number", "身份证": "id_card_number",
    "店铺": "shop_key", "shop_key": "shop_key", "店铺名称": "shop_key", "shop_name": "shop_key",
}


def _build_header_map(headers: tuple) -> dict:
    """将表头行转为 {字段索引: 标准字段名} 映射"""
    mapping = {}
    logger = logging.getLogger("pm-excel")
    logger.info(f"[解析] 表头行: {headers}")
    for i, header in enumerate(headers):
        if header is None:
            continue
        header_str = str(header).strip().lower()
        # 精确匹配 - 按长度降序，确保最长匹配优先
        if header_str in HEADER_ALIASES:
            mapping[i] = HEADER_ALIASES[header_str]
            logger.info(f"[解析] 列{i} '{header}' → '{HEADER_ALIASES[header_str]}' (精确匹配)")
            continue
        # 按长度降序模糊匹配
        sorted_aliases = sorted(HEADER_ALIASES.items(), key=lambda x: len(x[0]), reverse=True)
        found = False
        for alias, std_name in sorted_aliases:
            if alias in header_str or header_str in alias:
                mapping[i] = std_name
                logger.info(f"[解析] 列{i} '{header}' → '{std_name}' (模糊匹配: '{alias}')")
                found = True
                break
        if not found:
            # 子串匹配 - 也按长度降序
            for alias, std_name in sorted_aliases:
                if len(alias) >= 2 and alias in header_str:
                    mapping[i] = std_name
                    logger.info(f"[解析] 列{i} '{header}' → '{std_name}' (子串匹配: '{alias}')")
                    found = True
                    break
        if not found:
            logger.info(f"[解析] 列{i} '{header}' → 未匹配")
    logger.info(f"[解析] 最终映射: { {i: mapping[i] for i in sorted(mapping.keys())} }")
    return mapping


def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float):
        if val == int(val):
            # ID 卡号等长数字：float 精度不够，用完整字符串读取
            s = str(int(val))
            # 15-18位数字可能是身份证号，尝试从原始单元格读取
            if 15 <= len(s) <= 18:
                logger.warning(f"[解析] 长数字 {len(s)}位 '{s}'，可能精度丢失！请在Excel中将此列格式设为文本")
            return s
        return str(val)
    return str(val).strip()


def _row_to_order(row: tuple, header_map: dict) -> dict:
    """将一行数据转为订单字典"""
    row_data = {}
    for idx, std_name in header_map.items():
        if idx < len(row):
            row_data[std_name] = _safe_str(row[idx])

    order = {
        "so_id": row_data.get("so_id", ""),
        "sender_name": row_data.get("sender_name", ""),
        "receiver_name": row_data.get("receiver_name", ""),
        "receiver_phone": row_data.get("receiver_phone", ""),
        "receiver_state": row_data.get("receiver_state", ""),
        "receiver_city": row_data.get("receiver_city", ""),
        "receiver_district": row_data.get("receiver_district", ""),
        "receiver_address": row_data.get("receiver_address", ""),
        "buyer_message": row_data.get("buyer_message", ""),
        "id_card_number": row_data.get("id_card_number", ""),
        "pay_amount": _parse_number(row_data.get("pay_amount", "0")),
        "shop_key": row_data.get("shop_key", ""),
        "items": [],
    }

    # 商品
    sku_id = row_data.get("sku_id", "")
    item_name = row_data.get("item_name", "")
    qty = _parse_int(row_data.get("qty", "1"))
    price = _parse_number(row_data.get("price", "0"))

    if sku_id or item_name:
        order["items"].append({
            "sku_id": sku_id,
            "name": item_name or sku_id,
            "qty": qty,
            "price": price if price > 0 else 0,
        })

    return order


def _parse_number(val) -> float:
    try:
        return float(re.sub(r'[^\d.]', '', str(val)))
    except (ValueError, TypeError):
        return 0.0


def _parse_int(val) -> int:
    try:
        return int(re.sub(r'[^\d]', '', str(val)))
    except (ValueError, TypeError):
        return 1
