#!/usr/bin/env python3
"""Get financial logs for April 2026 only"""
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
    payload = {"pageIndex":page, "pageSize":200, "startTime":"2026-04-01", "endTime":"2026-05-15", "type":type_val, "orderSn":None}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read())

# Just get totals for April, not all records
for t, name in [(-2, '称重补款'), (-1, '预收款')]:
    data = query_page(1, t)
    total = data.get('totalCount', 0)
    items = data.get('items', [])
    
    # Get first page sum
    page_sum = sum(i.get('moneyChanged', 0) for i in items) / 100
    print(f'{name}: {total} 条记录, 第一页金额: {page_sum:.2f} 元')

# Get detailed sample - first 20 称重补款 records
print('\n=== 称重补款（2026年4月，前20条）===')
data = query_page(1, -2)
total = data.get('totalCount', 0)
items = data.get('items', [])
print(f'共 {total} 条')

for item in items[:20]:
    t = item.get('creationTime','')[:10]
    oid = item.get('orderSN','')
    amt = item.get('moneyChanged', 0) / 100
    desc = item.get('description','')
    print(f'  {t} | {oid} | {amt:+.2f}元 | {desc[:50]}')

# Also get 预收款 sample
print('\n=== 预收款（2026年4月，前10条）===')
data = query_page(1, -1)
total_pre = data.get('totalCount', 0)
items = data.get('items', [])
print(f'共 {total_pre} 条')

for item in items[:10]:
    t = item.get('creationTime','')[:10]
    oid = item.get('orderSN','')
    amt = item.get('moneyChanged', 0) / 100
    desc = item.get('description','')
    print(f'  {t} | {oid} | {amt:+.2f}元 | {desc[:50]}')
