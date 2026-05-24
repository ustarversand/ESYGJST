"""直邮管家 — 乔妈价格匹配工具

用法:
    from price_match import match_order_prices, diff_report

    # 匹配单个订单
    result = match_order_prices(items, shop_key="乔妈")
    # 输出差异报告
    print(diff_report(result))
"""
import os
import json
import re
import logging

logger = logging.getLogger("price-match")

_PRICES_CACHE = None


def _load_prices() -> dict:
    global _PRICES_CACHE
    if _PRICES_CACHE is not None:
        return _PRICES_CACHE
    path = os.path.join(os.path.dirname(__file__), "data", "qiaoma_prices.json")
    if not os.path.exists(path):
        logger.warning(f"价格表不存在: {path}")
        _PRICES_CACHE = {"price_list": {}, "aliases": {}}
        return _PRICES_CACHE
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _PRICES_CACHE = data
    return data


def _normalize_name(name: str) -> str | None:
    """将订单中的商品名标准化为标准产品名"""
    if not name:
        return None
    name = name.strip()

    prices = _load_prices()
    price_list = prices.get("price_list", {})
    aliases = prices.get("aliases", {})

    # 1. 直接匹配
    if name in price_list:
        return name

    # 2. 别名匹配
    if name in aliases:
        return aliases[name]

    # 3. 包含匹配（订单里可能是"三合一*2"或"三合一 550"等形式）
    for std_name, variants in prices.get("variants", {}).items():
        for v in variants:
            if v in name:
                return std_name

    # 4. 正则提取核心中文名
    for std_name in price_list:
        # 去除数字/符号/备注后的商品名
        clean = re.sub(r"[×*xX\d\+\-\.\s\(\)（）【】\[\]]", "", name)
        if std_name in clean:
            return std_name

    return None


def match_order_prices(items: list, shop_key: str = "乔妈") -> dict:
    """
    匹配订单商品与价格表

    items: [{"name": "三合一", "price": 550, "qty": 2}, ...]
    shop_key: 店铺key，默认乔妈

    返回:
    {
        "matched": [{"name": ..., "std_name": ..., "price": ..., "ref_price": ..., "match": bool, "diff": ...}, ...],
        "unmatched": [...],
        "total_diff": ...,
        "total_items": ...,
        "matched_count": ...,
    }
    """
    prices = _load_prices()
    price_list = prices.get("price_list", {})

    matched = []
    unmatched = []
    total_diff = 0.0

    for item in items:
        name = item.get("name", "") or item.get("product_name", "")
        order_price = float(item.get("price", 0))

        std_name = _normalize_name(name)
        if std_name and std_name in price_list:
            ref_price = price_list[std_name]
            diff = order_price - ref_price
            total_diff += diff
            matched.append({
                "name": name,
                "std_name": std_name,
                "price": order_price,
                "ref_price": ref_price,
                "diff": round(diff, 2),
                "match": abs(diff) < 0.01,
                "qty": item.get("qty", 1),
            })
        else:
            unmatched.append({
                "name": name,
                "price": order_price,
                "qty": item.get("qty", 1),
                "reason": "未匹配到价格表",
            })

    return {
        "matched": matched,
        "unmatched": unmatched,
        "total_diff": round(total_diff, 2),
        "total_items": len(items),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
    }


def diff_report(result: dict) -> str:
    """生成差异报告文本"""
    lines = []
    lines.append("═══ 乔妈价格匹配报告 ═══")
    lines.append(f"总商品项: {result['total_items']}")
    lines.append(f"匹配成功: {result['matched_count']}")
    lines.append(f"未匹配: {result['unmatched_count']}")
    lines.append(f"总价差: ¥{result['total_diff']:.2f}")
    lines.append("")

    if result["matched"]:
        lines.append("【已匹配】")
        for m in result["matched"]:
            flag = "✅" if m["match"] else "⚠️"
            diff_str = f"(差¥{m['diff']:+.2f})" if not m["match"] else ""
            lines.append(f"  {flag} {m['name']} → {m['std_name']}")
            lines.append(f"     订单价: ¥{m['price']:.2f} 参考价: ¥{m['ref_price']:.2f} {diff_str}")
        lines.append("")

    if result["unmatched"]:
        lines.append("【未匹配】")
        for u in result["unmatched"]:
            lines.append(f"  ❌ {u['name']} ¥{u['price']:.2f} — {u.get('reason', '未知')}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # 测试
    test_items = [
        {"name": "三合一", "price": 550.0, "qty": 1},
        {"name": "小红盒", "price": 150.0, "qty": 2},
        {"name": "抗氧化", "price": 225.0, "qty": 1},
        {"name": "叶黄素", "price": 170.0, "qty": 1},
        {"name": "鱼油", "price": 170.0, "qty": 3},
        {"name": "三合一", "price": 500.0, "qty": 1},  # 故意价格不对
        {"name": "未知商品", "price": 999.0, "qty": 1},  # 无匹配
    ]
    result = match_order_prices(test_items)
    print(diff_report(result))
