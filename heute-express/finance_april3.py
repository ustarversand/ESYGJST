#!/usr/bin/env python3
"""Get 称重补款 records for April - with token refresh"""
import json, sys, ssl, urllib.request, urllib.error, time, os
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient

client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)
print(f'Token refreshed: {client.token[:20]}...')

headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + client.token,
    'User-Agent': 'Mozilla/5.0',
    'Origin': 'https://www.heute-express.com',
    'Referer': 'https://www.heute-express.com/members/member-money-log',
}
url = 'https://www.heute-express.com/Prod/api/app/member-center/get-member-money-logs'
ctx = ssl.create_default_context()

def query_page(page, type_val):
    payload = {"pageIndex":page, "pageSize":200, "startTime":"2026-04-01", "endTime":"2026-05-15", "type":type_val, "orderSn":None}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read())

# 称重补款 - type=-2
print("\n=== 称重补款 (type=-2) ===")
data = query_page(1, -2)
total = data.get('totalCount', 0)
print(f"总条数: {total}")

all_items = list(data.get('items', []))
page = 1
while len(all_items) < total:
    page += 1
    data = query_page(page, -2)
    all_items.extend(data.get('items', []))
    print(f"  进度: {len(all_items)}/{total}")
    time.sleep(0.3)

# Group by orderSN
from collections import defaultdict
by_order = defaultdict(list)
for item in all_items:
    by_order[item.get('orderSN', '')].append(item)

print(f"\n共有 {len(by_order)} 个订单有称重补款")
total_amt = 0
for oid, items in sorted(by_order.items()):
    amt = sum(i.get('moneyChanged', 0) for i in items) / 100
    total_amt += amt
    date = items[0].get('creationTime','')[:10]
    desc = items[0].get('description','')
    print(f"  {date} | {oid} | {amt:+.2f}元 | {desc[:50]}")

print(f"\n称重补款总额: {total_amt:.2f} 元")

# Also get预收款 summary
print("\n=== 预收款 (type=-1) ===")
data = query_page(1, -1)
total_pre = data.get('totalCount', 0)
print(f"总条数: {total_pre}")

all_pre = list(data.get('items', []))
page = 1
while len(all_pre) < total_pre:
    page += 1
    data = query_page(page, -1)
    all_pre.extend(data.get('items', []))
    print(f"  进度: {len(all_pre)}/{total_pre}")
    time.sleep(0.3)

pre_amt = sum(i.get('moneyChanged', 0) for i in all_pre) / 100
print(f"\n预收款总额: {pre_amt:.2f} 元 ({len(all_pre)} 笔)")
print(f"余额变化: {pre_amt:.2f} 元 (负数为支出)")
