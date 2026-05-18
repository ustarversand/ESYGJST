#!/usr/bin/env python3
"""Get 称重补款 records from April 2026"""
import json, sys, ssl, urllib.request, urllib.error, time
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient

client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)
headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + client.token,
}
url = 'https://www.heute-express.com/Prod/api/app/member-center/get-member-money-logs'
ctx = ssl.create_default_context()

def query_page(page, type_val):
    payload = {"pageIndex":page, "pageSize":100, "startTime":"2026-04-01", "endTime":"2026-05-15", "type":type_val, "orderSn":None}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read())

# Get all 称重补款 records for April
print("=== 称重补款 (type=-2) — 2026年4月 ===")
data = query_page(1, -2)
total = data.get('totalCount', 0)
items = data.get('items', [])
print(f"总记录: {total}")

# Collect all pages
all_items = list(items)
page = 1
while len(all_items) < total:
    page += 1
    data = query_page(page, -2)
    all_items.extend(data.get('items', []))
    print(f"  已获取 {len(all_items)}/{total}")
    time.sleep(0.3)

print(f"\n共 {len(all_items)} 条称重补款记录:")
total_amount = 0
for item in all_items:
    amt = item.get('moneyChanged', 0) / 100
    total_amount += amt
    print(f'  {item.get("creationTime","")[:10]} | {item.get("orderSN","")} | {amt:+.2f}元 | {item.get("description","")}')

print(f'\n称重补款总额: {total_amount:.2f} 元')
print(f'预收款(粗略): 请稍后...')

# Get 预收款 summary
print("\n=== 预收款 (type=-1) — 2026年4月 ===")
data = query_page(1, -1)
total_pre = data.get('totalCount', 0)
print(f"总记录: {total_pre}")
all_pre = list(data.get('items', []))
page = 1
while len(all_pre) < total_pre and total_pre > 0:
    page += 1
    data = query_page(page, -1)
    all_pre.extend(data.get('items', []))
    print(f"  已获取 {len(all_pre)}/{total_pre}")
    time.sleep(0.3)

pre_total = sum(i.get('moneyChanged', 0) for i in all_pre) / 100
print(f'\n预收款总额: {pre_total:.2f} 元 (含 {len(all_pre)} 笔)')
