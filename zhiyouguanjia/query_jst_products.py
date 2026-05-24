#!/usr/bin/env python3
"""查询聚水潭商品数据库 — 直邮管家 SKU 发现"""
import sys, json
sys.path.insert(0, '/opt/data/workspace/ustar-deploy/app/ustar_jst')
from core.jst_client import JSTClient

client = JSTClient()

# 方案1: 新 API sku query (全量)
print("=" * 60)
print("方案1: /open/sku/query (全量)")
print("=" * 60)
all_skus = []
page = 1
while True:
    result = client.call_new('/open/sku/query', {'page_size': 100, 'page_index': page})
    if result.get('code') != 0:
        print(f"  Error @ page {page}: {result.get('msg','')}")
        break
    datas = result.get('data', {}).get('datas', [])
    all_skus.extend(datas)
    print(f"  page={page}, got={len(datas)}, total_so_far={len(all_skus)}")
    if result.get('data', {}).get('has_next') != True:
        break
    page += 1
    if page > 20:  # safety
        break

print(f"\n  Total SKUs: {len(all_skus)}")

# Filter for PM-related products
pm_keywords = ['PM', 'Fitline', 'fitline', 'pm', 'Pm', '小红', '小白', '大白', '肽美', '小粉', '叶黄素']
pm_skus = [s for s in all_skus if any(kw in str(s.get('sku_code','') + s.get('name','') + s.get('i_name','')) for kw in pm_keywords)]

print(f"\n  PM-related: {len(pm_skus)}")
for s in pm_skus:
    print(f"  SKU: {s.get('sku_code',''):25s} | 名称: {s.get('name','') or s.get('i_name',''):30s} | 类别: {s.get('c_name','')}")

# Show some non-PM samples
print("\n\n  Sample non-PM (first 5):")
for s in all_skus[:5]:
    print(f"  SKU: {s.get('sku_code',''):25s} | 名称: {s.get('name','') or s.get('i_name',''):30s} | 类别: {s.get('c_name','')}")

import datetime
now = datetime.datetime.now()

# 方案2: 旧 API sku.query — 宽范围时间
print("\n" + "=" * 60)
print("方案2: sku.query (旧API, 宽时间范围)")
print("=" * 60)
result2 = client.call_jushuitan_api_dict('sku.query', {
    'page_index': 1,
    'page_size': 100,
    'modified_begin': '2024-01-01 00:00:00',
    'modified_end': now.strftime('%Y-%m-%d %H:%M:%S'),
})
print(f"code={result2.get('code')}, total={result2.get('total_count',0)}")
if result2.get('code') == 0:
    skus2 = result2.get('skus', result2.get('datas', []))
    for s in skus2[:20]:
        sid = s.get('sku_id','') if isinstance(s,dict) else s
        nm = s.get('name','') if isinstance(s,dict) else s
        print(f"  {sid:30s} | {nm}")
else:
    print(f"  Error: {result2.get('msg','')}")
    print(json.dumps(result2, ensure_ascii=False)[:500])

# 方案3: /open/mall/item/query — 商城商品
print("\n" + "=" * 60)
print("方案3: /open/mall/item/query")
print("=" * 60)
all_items = []
for pg in range(1, 6):
    result3 = client.call_new('/open/mall/item/query', {'page_size': 20, 'page_index': pg})
    if result3.get('code') == 0:
        items = result3.get('data', {}).get('datas', [])
        all_items.extend(items)
        print(f"  page={pg}, got={len(items)}")
    else:
        print(f"  page={pg} Error: {result3.get('msg','')}")
        break

print(f"\n  Total mall items: {len(all_items)}")
for s in all_items[:20]:
    print(f"  SKU: {s.get('sku_id',''):25s} | 名称: {s.get('i_name','') or s.get('name',''):30s} | 价格: {s.get('sale_price','')}")
