#!/usr/bin/env python3
"""Get financial logs from April 1st"""
import json, sys, ssl, urllib.request, urllib.error
from collections import Counter
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient

client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)
headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + client.token,
    'User-Agent': 'Mozilla/5.0',
}
ctx = ssl.create_default_context()
url = 'https://www.heute-express.com/Prod/api/app/member-center/get-member-money-logs'

def query_page(page, start, end, type_val=None):
    payload = {"pageIndex":page, "pageSize":100, "startTime":start, "endTime":end, "type":type_val, "orderSn":None}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read())

# First, discover all type values available
print("=== 类型探索(不加时间筛选) ===")
# Get a sample of records to see type values
data = query_page(1, '', '', None)
items = data.get('items', [])
type_counter = Counter()
for item in items:
    type_counter[item.get('type')] += 1
    type_counter[item.get('description', '')[:20]] += 0  # just for catalog

print("type values found:", dict(type_counter.most_common(10)))
print()

# Now query specifically 称重补款 with date range
# The type value for 称重补款... let me check what type values exist in recent records
# Let me try to find it without date filter first
print("\n=== 最近10条记录 ===")
for item in items:
    t = item.get('creationTime','')[:10]
    desc = item.get('description','')
    amt = item.get('moneyChanged',0) / 100
    print(f"  {t} | type={item.get('type')} | {amt:+.2f} | {desc[:50]}")

# Try query with date range: April 2026
print("\n=== 2026年4月 账务明细 ===")
data = query_page(1, '2026-04-01', '2026-05-15', None)
total = data.get('totalCount', 0)
print(f"总记录: {total}")
items = data.get('items', [])

# Count types
type_dist = Counter()
for item in items:
    type_dist[item.get('type')] += 1
print("类型分布:")
for t, c in type_dist.most_common(10):
    samples = [i for i in items if i.get('type') == t][:2]
    desc = [s.get('description','')[:40] for s in samples]
    print(f"  type={t}: {c}条 - 例如: {desc}")
