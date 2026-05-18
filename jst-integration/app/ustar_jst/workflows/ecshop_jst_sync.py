#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ECShop 订单同步到聚水潭 v3.0 - 含商品映射
"""
import os
import sys
import json
import time
import logging
import hashlib
import datetime
import subprocess
from typing import List, Dict, Optional, Tuple

# 聚水潭配置
JST_CONFIG = {
    "app_key": "d561deb348274f1ba3505ec4578870fd",
    "app_secret": "84ad2c023b9b49378b1161ea569e383c",
    "token": "cfda23ff97664494bc6fc5ab46f8ea48",
    "api_url": "https://open.erp321.com/api/open/query.aspx",
    "shop_id": 20941412,
    "shop_name": "智能体AI店铺"
}

# 需要身份证的店铺
SHOPS_REQUIRING_IDCARD = [20941412]

# ==================== 商品SKU映射表 ====================
# 奶粉商品
MILK_POWDER_KEYWORDS = ["奶粉", "奶粉pre", "奶粉1段", "奶粉2段", "奶粉3段", "奶粉1+", "奶粉2+",
                    "德爱", "爱他美", "喜宝", "BEBA", "至尊", "牛栏", "白金", "Aptamil"]

MILK_POWDER_SKU = {
    "德爱白金pre": {"sku": "4056631003435BJP", "price": 195},
    "德爱白金1段": {"sku": "4056631003459BJ1", "price": 195},
    "德爱白金2段": {"sku": "4056631003473BJ2", "price": 195},
    "德爱白金3段": {"sku": "4056631003491BJ3", "price": 195},
    "至尊pre": {"sku": "7613287226631ZZPR", "price": 195},
    "至尊1+": {"sku": "7613287296085ZZ1+", "price": 145},
    "至尊1段": {"sku": "7613036456418ZZ1", "price": 195},
    "至尊2段": {"sku": "7613287226679ZZ2", "price": 195},
    "至尊3段": {"sku": "7613287226699ZZ3", "price": 195},
    "蓝罐pre": {"sku": "4056631001202BLP", "price": 145},
    "蓝罐1段": {"sku": "4056631003411BL1", "price": 145},
    "蓝罐2段": {"sku": "4056631003439BL2", "price": 145},
    "蓝罐3段": {"sku": "4056631003457BL3", "price": 145},
}

# 保健品商品
PRODUCT_SKU_MAP = {
    # FitLine系列
    "基础三合一套装": "1SFCC97001079SHY",
    "基础二合一套装": "1SFCC9700731EHY",
    "Optimal-Set": "1SFCC97001079SHY",
    "基础套装": "1SFCC97001079SHY",
    
    # 德国保健品
    "乐活": "0705044LHTK",
    "乐活Generation": "0705044LHTK",
    "Generation50+": "0705044LHTK",
    "福贵套餐": "0705044LHTK",
    
    "叶黄素": "0712020YHS",
    "异黄酮": "0712021YHT",
    "氨基酸": "0704022AJS",
    "小粉": "0709048XF",
    "大白": "0705018DB",
    "复合大白": "0705012FHDB",
    "小红": "0708023XH",
    "小白": "0702037XB",
    "桃子小红": "0708065XHTZ",
    "肽美": "0709028TM",
    "排毒饮": "0702069PDY",
    
    # 马膏系列
    "马膏": "0715030MG",
    "Krauterhof": "0715030MG",
    "草本庄园": "0715030MG",
    
    # 铁元
    "铁元": "0716030TY",
    "Floradix": "0716030TY",
    "红盒装": "0716030TY",
    
    # 美白祛斑
    "美白": "0717030MB",
    "祛斑": "0717030MB",
    "Allcura": "0717030MB",
    
    # 益生菌
    "幽门": "0718030YM",
    "pylocura": "0718030YM",
    
    # 通鼻
    "通鼻": "0719030TB",
    "Babix": "0719030TB",
    "Inhalat": "0719030TB",
    
    # 维蕾德
    "感冒颗粒": "0720030GM",
    "Infludor": "0720030GM",
    "WELEDA": "0720030GM",
    
    # 防蚊虫
    "防蚊": "0721030FQ",
    "S-quito": "0721030FQ",
    "驱蚊": "0721030FQ",
    
    # 止痒
    "止痒": "0722030ZA",
    
    # 补铁剂
    "补铁剂": "0723030TS",
    "Ferrum": "0723030TS",
    "婴幼儿补铁": "0723030TS",
    
    # VD/钙片
    "钙片": "0724030VD",
    "VD500": "0724030VD",
    "zymafluor": "0724030VD",
    
    # 小熊糖
    "小熊糖": "0725030XZ",
    "Das gesund": "0725030XZ",
}

# 默认价格映射
SKU_PRICE_MAP = {
    "4056631003435BJP": 195,
    "4056631003459BJ1": 195,
    "4056631003473BJ2": 195,
    "7613287296085ZZ1+": 145,
    "7613287226631ZZPR": 195,
    "7613036456418ZZ1": 195,
    "7613287226679ZZ2": 195,
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def get_sku(goods_name: str) -> Tuple[str, float]:
    """
    获取商品SKU编码和价格
    
    Args:
        goods_name: 商品名称
        
    Returns:
        (sku_id, price) 元组
    """
    if not goods_name:
        return "", 0
    
    name_lower = goods_name.lower().strip()
    
    # 1. 精确匹配PRODUCT_SKU_MAP
    for key, sku in PRODUCT_SKU_MAP.items():
        if key.lower() == name_lower:
            price = SKU_PRICE_MAP.get(sku, 0)
            logger.info(f"精确匹配: {goods_name} -> {sku}")
            return sku, price
    
    # 2. 模糊匹配PRODUCT_SKU_MAP
    for key, sku in PRODUCT_SKU_MAP.items():
        if key.lower() in name_lower or name_lower in key.lower():
            price = SKU_PRICE_MAP.get(sku, 0)
            logger.info(f"模糊匹配: {goods_name} -> {sku}")
            return sku, price
    
    # 3. 奶粉精确匹配
    for milk_key, milk_info in MILK_POWDER_SKU.items():
        if milk_key in name_lower:
            logger.info(f"奶粉匹配: {goods_name} -> {milk_info['sku']}")
            return milk_info['sku'], milk_info['price']
    
    # 4. 奶粉关键词匹配
    for keyword in MILK_POWDER_KEYWORDS:
        if keyword.lower() in name_lower:
            # 尝试匹配段位
            if "pre" in name_lower or "0-3" in name_lower:
                for mk, mi in MILK_POWDER_SKU.items():
                    if "pre" in mk.lower():
                        return mi['sku'], mi['price']
            elif "1段" in name_lower or "3-6" in name_lower or "1+" in name_lower:
                for mk, mi in MILK_POWDER_SKU.items():
                    if "1段" in mk or "1+" in mk:
                        return mi['sku'], mi['price']
            elif "2段" in name_lower or "7-9" in name_lower or "2+" in name_lower:
                for mk, mi in MILK_POWDER_SKU.items():
                    if "2段" in mk or "2+" in mk:
                        return mi['sku'], mi['price']
            elif "3段" in name_lower or "10-12" in name_lower or "3+" in name_lower:
                for mk, mi in MILK_POWDER_SKU.items():
                    if "3段" in mk or "3+" in mk:
                        return mi['sku'], mi['price']
            # 默认返回第一个匹配的奶粉
            return list(MILK_POWDER_SKU.values())[0]['sku'], 195
    
    # 5. 未找到警告，返回商品名前20位作为SKU
    logger.warning(f"未找到商品SKU: {goods_name}")
    return goods_name[:20], 0


def mysql_query(sql):
    """执行MySQL查询"""
    # 用单引号包围SQL，简单的shell转义
    sql_clean = sql.replace("'", "\\'")
    cmd = f"docker exec hermes-agent-ecshop mysql -u root -pEcshop@2026! ecshop_renzheng --default-character-set=utf8mb4 -e '{sql_clean}'"
    
    result = subprocess.run(
        ['sshpass', '-p', 'Hilden11031980', 'ssh', '-o', 'StrictHostKeyChecking=no', 'ustar@192.168.178.26', cmd],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        logger.error(f"SQL错误: {result.stderr}")
        return []
    
    lines = [l for l in result.stdout.strip().split('\n') if l]
    if len(lines) < 2:
        return []
    
    headers = lines[0].split('\t')
    rows = []
    for line in lines[1:]:
        values = line.split('\t')
        if len(values) == len(headers):
            rows.append(dict(zip(headers, values)))
    return rows


def mysql_exec(sql):
    """执行MySQL更新"""
    sql = sql.replace("'", "'\\''")
    cmd = f'docker exec hermes-agent-ecshop mysql -u root -pEcshop@2026! ecshop_renzheng -e "{sql}"'
    ssh_cmd = f'sshpass -p "Hilden11031980" ssh -o StrictHostKeyChecking=no ustar@192.168.178.26 "{cmd}"'
    
    result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=30)
    return result.returncode == 0


def get_unsync_orders(limit=10):
    """获取未同步的已支付订单"""
    sql = "SELECT order_id, order_sn, user_id, consignee, mobile, province, city, district, address, goods_amount, shipping_fee, order_amount, pay_status, order_status, shipping_status, add_time FROM ecs_order_info WHERE pay_status = 2 AND order_status IN (0,1) AND sync_jstan = 0 ORDER BY add_time DESC LIMIT " + str(limit)
    return mysql_query(sql)


def get_order_items(order_id):
    """获取订单商品"""
    sql = """
        SELECT og.goods_id, g.goods_sn, og.goods_name, 
               og.goods_number, og.goods_price
        FROM ecs_order_goods og
        LEFT JOIN ecs_goods g ON og.goods_id = g.goods_id
        WHERE og.order_id = {}
    """.format(order_id)
    return mysql_query(sql)


def get_user_idcard(user_id):
    """获取用户实名信息"""
    sql = """
        SELECT realname, id_number
        FROM ecs_user_realname
        WHERE user_id = {}
        ORDER BY create_time DESC
        LIMIT 1
    """.format(user_id)
    rows = mysql_query(sql)
    if rows:
        return rows[0].get('realname', ''), rows[0].get('id_number', '')
    return '', ''


def get_region_name(region_id):
    """获取地区名称"""
    if not region_id:
        return ""
    sql = "SELECT region_name FROM ecs_region WHERE region_id = {}".format(region_id)
    rows = mysql_query(sql)
    if rows:
        return rows[0].get('region_name', '')
    return ""


def mark_synced(order_id):
    """标记订单已同步"""
    sql = "UPDATE ecs_order_info SET sync_jstan = 1 WHERE order_id = {}".format(order_id)
    return mysql_exec(sql)


def generate_sign(method, params):
    """生成API签名"""
    app_key = JST_CONFIG["app_key"]
    app_secret = JST_CONFIG["app_secret"]
    param_str = "".join(str(k) + str(v) for k, v in sorted(params.items()))
    sign_str = method + app_key + param_str + app_secret
    return hashlib.md5(sign_str.encode('utf-8')).hexdigest().lower()


def push_order(order_data):
    """推送订单到聚水潭"""
    import requests
    
    method = "orders.upload"
    ts = str(int(time.time()))
    params = {"token": JST_CONFIG["token"], "ts": ts}
    sign = generate_sign(method, params)
    
    url = f"{JST_CONFIG['api_url']}?method={method}&partnerid={JST_CONFIG['app_key']}&token={JST_CONFIG['token']}&ts={ts}&sign={sign}"
    
    items = []
    for item in order_data.get('items', []):
        goods_name = item.get('goods_name', '')
        
        # 获取SKU和价格
        sku, price = get_sku(goods_name)
        
        # 如果订单有价格，用订单价格
        order_price = float(item.get('goods_price', 0))
        if order_price > 0:
            price = order_price
        
        items.append({
            "sku_id": sku,
            "shop_sku_id": sku,
            "amount": price * int(item.get('goods_number', 1)),
            "base_price": price,
            "qty": int(item.get('goods_number', 1)),
            "name": goods_name,
            "outer_oi_id": "{}_{}".format(order_data['order_sn'], item.get('goods_id', ''))
        })
    
    total = float(order_data.get('goods_amount', 0))
    freight = float(order_data.get('shipping_fee', 0))
    province = order_data.get('province', '')[:20]
    city = order_data.get('city', '')[:20]
    district = order_data.get('district', '')[:20]
    
    jst_data = [{
        "shop_id": JST_CONFIG["shop_id"],
        "so_id": order_data['order_sn'],
        "order_date": datetime.datetime.fromtimestamp(int(order_data.get('add_time', 0))).strftime("%Y-%m-%d %H:%M:%S"),
        "shop_status": "WAIT_SELLER_SEND_GOODS",
        "shop_buyer_id": "U{}".format(order_data['user_id']),
        "receiver_name": order_data.get('consignee', ''),
        "receiver_mobile": order_data.get('mobile', ''),
        "receiver_state": province,
        "receiver_city": city,
        "receiver_district": district,
        "receiver_address": "{}{}{}{}".format(province, city, district, order_data.get('address', '')),
        "receiver_country": "CN",
        "pay_amount": total,
        "freight": freight,
        "items": items
    }]
    
    # 添加身份证（如果需要）
    if order_data.get('id_card'):
        jst_data[0]["card"] = {
            "name": order_data.get('id_name', order_data.get('consignee', '')),
            "id_no": order_data.get('id_card', ''),
            "outer_oi_id": f"{order_data['order_sn']}_card"
        }
    
    try:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        response = requests.post(url, data=json.dumps(jst_data, ensure_ascii=False).encode('utf-8'), headers=headers, timeout=30)
        result = response.json()
        logger.info("推送结果: code={}, msg={}".format(result.get('code'), result.get('msg')))
        return result
    except Exception as e:
        logger.error("推送异常: {}".format(e))
        return {"code": -1, "msg": str(e)}


def sync_orders(limit=10):
    """同步订单"""
    logger.info("开始同步任务 (最多 {} 个订单)".format(limit))
    
    # 获取未同步订单
    orders = get_unsync_orders(limit)
    
    if not orders:
        logger.info("没有待同步订单")
        return {"success": True, "msg": "没有待同步订单", "synced_count": 0}
    
    logger.info("找到 {} 个待同步订单".format(len(orders)))
    
    success_count = 0
    fail_count = 0
    results = []
    
    for order in orders:
        try:
            order_id = int(order.get('order_id', 0))
            order_sn = order.get('order_sn', '')
            logger.info("同步订单: {}".format(order_sn))
            
            # 获取商品
            items = get_order_items(order_id)
            if not items:
                logger.warning("订单 {} 无商品".format(order_sn))
                fail_count += 1
                results.append({"order_sn": order_sn, "success": False, "msg": "无商品"})
                continue
            
            order['items'] = items
            
            # 获取实名信息
            id_name, id_card = get_user_idcard(order['user_id'])
            order['id_name'] = id_name
            order['id_card'] = id_card
            
            # 推送
            result = push_order(order)
            
            if result.get('code') == 0:
                mark_synced(order_id)
                success_count += 1
                logger.info("订单 {} 同步成功".format(order_sn))
                results.append({"order_sn": order_sn, "success": True, "msg": "成功"})
            else:
                fail_count += 1
                logger.error("订单 {} 同步失败: {}".format(order_sn, result.get('msg')))
                results.append({"order_sn": order_sn, "success": False, "msg": result.get('msg', '失败')})
        except Exception as e:
            logger.error("同步异常: {}".format(e))
            fail_count += 1
            results.append({"order_sn": order.get('order_sn', ''), "success": False, "msg": str(e)})
    
    logger.info("同步完成: 成功 {}, 失败 {}".format(success_count, fail_count))
    return {
        "success": True,
        "msg": "成功 {}, 失败 {}".format(success_count, fail_count),
        "synced_count": success_count,
        "fail_count": fail_count,
        "results": results
    }


def test_sku_mapping():
    """测试SKU映射"""
    test_names = [
        "德国直邮 爱他美Aptamil 白金新版 婴儿奶粉 2段 （7-9个月 ）800g",
        "乐活 Generation 50+ 福贵套餐 50+ 现货",
        "德国直邮 Krauterhof 草本庄园 马膏热 500ml",
        "德国直邮 法国波尔多小拉菲 干红葡萄酒2016 12.5° 750ml 原木箱6支",
    ]
    
    print("\n=== SKU映射测试 ===")
    for name in test_names:
        sku, price = get_sku(name)
        print(f"{name[:40]}... -> {sku} (€{price})")


def main():
    # 测试映射
    test_sku_mapping()
    
    # 同步订单
    result = sync_orders(limit=10)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()