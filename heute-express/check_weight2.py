#!/usr/bin/env python3
"""Check all fields in order detail for weight-related info"""
import json, sys
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient

client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)

detail = client.get_order_detail('2604291216254691')

# Print all keys with their values
print('=== 所有字段（不含orderDetails） ===')
for k, v in detail.items():
    if k != 'orderDetails':
        print(f'  {k}: {v}')

print('\n=== 产品明细 ===')
for p in detail.get('orderDetails', []):
    print(json.dumps(p, ensure_ascii=False, default=str))

# Also check: is weight in the order list the "declared" or "actual"?
# Let's check a few orders to see if weight changes
print('\n=== 对比多个订单的weight字段 ===')
orders = client.fetch_all_orders('2026-04-01', '2026-04-30', page_size=5)
for o in orders[:3]:
    print(f'  {o["sn"]}: weight={o.get("weight")}g, sender={o.get("senderName")}, state={o.get("state")}')
    # Get detail to check
    try:
        d = client.get_order_detail(o['sn'])
        print(f'    detail: weight={d.get("weight")}g, box={d.get("orderExBoxLength")}x{d.get("orderExBoxWidth")}x{d.get("orderExBoxHeight")}')
    except:
        print('    detail: ERROR')
