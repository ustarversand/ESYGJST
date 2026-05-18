#!/usr/bin/env python3
"""预获取称重补款订单的产品名称，缓存到 product_cache.json"""
import json, sys, time, csv, os
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient

MONTH = sys.argv[1] if len(sys.argv) > 1 else 'april'
CACHE_FILE = '/opt/data/workspace/heute_express/data/product_cache.json'
SURCHARGE_CSV = f'/tmp/heute_docker/data/{MONTH}_2026_weight_surcharge.csv'
BATCH_SIZE = 10
MAX_ORDERS = 0  # 0 = all

# 加载已有缓存
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f:
        cache = json.load(f)
else:
    cache = {}

# 收集所有需要查询的订单号
if not os.path.exists(SURCHARGE_CSV):
    print(f"❌ CSV not found: {SURCHARGE_CSV}")
    sys.exit(1)

with open(SURCHARGE_CSV, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    order_ids = set(row['订单号'] for row in reader)

# 过滤已缓存的
pending = sorted([oid for oid in order_ids if oid not in cache])
if MAX_ORDERS > 0:
    pending = pending[:MAX_ORDERS]

total = len(pending)
print(f"📅 Month: {MONTH}")
print(f"📦 总计: {len(order_ids)} 个唯一订单")
print(f"✅ 已缓存: {len(order_ids) - total} 个")
print(f"⏳ 待获取: {total} 个")

if total == 0:
    print("🎉 全部已缓存，无需获取")
    sys.exit(0)

# 登录
client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)

fetched = 0
errors = 0

for i in range(0, total, BATCH_SIZE):
    batch = pending[i:i+BATCH_SIZE]
    for oid in batch:
        try:
            detail = client.get_order_detail(oid)
            products = detail.get('orderDetails', [])
            names = [p.get('goodsName', '') for p in products if p.get('goodsName')]
            cache[oid] = {
                'products': [{
                    'name': p.get('goodsName', ''),
                    'name_en': p.get('goodsNameForeign', ''),
                    'brand': p.get('goodsBrand', ''),
                    'ean': p.get('ean', ''),
                    'num': p.get('num', 0),
                    'price': p.get('price', 0),
                } for p in products],
                'product_names': names,
                'product_summary': ' + '.join(names) if names else '未知',
            }
            fetched += 1
        except Exception as e:
            cache[oid] = {'products': [], 'product_names': [], 'product_summary': f'获取失败: {str(e)[:50]}'}
            errors += 1
            print(f"  ❌ {oid}: {str(e)[:60]}")
    
    # 每批保存
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    
    pct = min(100, (i + BATCH_SIZE) / total * 100)
    print(f"  📊 {min(i+BATCH_SIZE, total)}/{total} ({pct:.0f}%) | 成功{fetched} | 失败{errors}")
    
    if i + BATCH_SIZE < total:
        time.sleep(0.5)

print(f"\n✅ 完成! 共获取 {fetched} 个订单, 失败 {errors} 个")
print(f"💾 缓存文件: {CACHE_FILE}")
