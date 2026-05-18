#!/usr/bin/env python3
"""拉取5月称重补款完整明细"""
import json, sys, time, csv
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient, BASE_URL, _make_headers

client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)

endpoint = '/Prod/api/app/member-center/get-member-money-logs'
url = f"{BASE_URL}{endpoint}"

def query_page(page, type_val, start='2026-05-01', end='2026-05-15'):
    import urllib.request, ssl
    payload = {"pageIndex": page, "pageSize": 200, "startTime": start, "endTime": end, "type": type_val, "orderSn": None}
    body = json.dumps(payload).encode('utf-8')
    headers = _make_headers(client.token)
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read())

data = query_page(1, -2)
total = data.get('totalCount', 0)
print(f"📊 5月称重补款: {total} 条")

all_items = []
page = 1
while True:
    data = query_page(page, -2)
    items = data.get('items', [])
    if not items:
        break
    all_items.extend(items)
    print(f"  第{page}页: {len(items)}条 (累计{len(all_items)})")
    if len(all_items) >= total:
        break
    page += 1
    time.sleep(0.3)

print(f"\n✅ 共 {len(all_items)} 条")

# Save CSV
csv_path = '/opt/data/workspace/heute_express/may_2026_weight_surcharge.csv'
with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['时间', '订单号', '金额(元)', '描述'])
    for item in all_items:
        t = item.get('creationTime', '')[:19]
        oid = item.get('orderSN', '')
        amt = item.get('moneyChanged', 0) / 100
        desc = item.get('description', '')
        w.writerow([t, oid, f'{amt:.2f}', desc])

total_money = sum(i.get('moneyChanged', 0) for i in all_items) / 100
print(f"💰 总额: {total_money:.2f} 元")
print(f"📄 CSV: {csv_path}")

# Daily summary
from collections import defaultdict
daily = defaultdict(lambda: {'count': 0, 'amount': 0.0})
for item in all_items:
    d = item.get('creationTime', '')[:10]
    amt = item.get('moneyChanged', 0) / 100
    daily[d]['count'] += 1
    daily[d]['amount'] += amt

print("\n📅 每日:")
for d in sorted(daily.keys()):
    info = daily[d]
    print(f"  {d}: {info['count']}笔 {info['amount']:.2f}元")
