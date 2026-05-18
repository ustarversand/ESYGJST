#!/usr/bin/env python3
"""Query Heute financial transaction logs (账务明细)"""
import json, sys, ssl, urllib.request, urllib.error, time
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient

client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)
headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + client.token,
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Origin': 'https://www.heute-express.com',
}
ctx = ssl.create_default_context()
base = 'https://www.heute-express.com'

# First try: get money logs from April 1st 
url = base + '/Prod/api/app/member-center/get-member-money-logs'
payload = {
    "startTime": "2026-04-01",
    "endTime": "2026-05-15",
    "type": "",
    "orderSn": "",
    "pageIndex": 1,
    "pageSize": 50
}
body = json.dumps(payload).encode()
req = urllib.request.Request(url, data=body, headers=headers, method='POST')
with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
    data = json.loads(resp.read())

print('Code:', data.get('code'))
print('Message:', data.get('message'))
dd = data.get('data', {})
print('Total count:', dd.get('totalCount'))
print('Items:', len(dd.get('items', [])))
print()

if dd.get('items'):
    for item in dd['items']:
        print('  ' + str(item.get('creationTime',''))[:19] + 
              ' | ' + str(item.get('typeStr','')) +
              ' | ' + str(item.get('amount','')) +
              ' | ' + str(item.get('balance','')) +
              ' | ' + str(item.get('orderSn','')) +
              ' | ' + str(item.get('remark',''))[:60])
    
    # Show all keys from first item
    print('\nAll keys in item:')
    print(list(dd['items'][0].keys()))
    print('\nFull first item:')
    print(json.dumps(dd['items'][0], ensure_ascii=False, indent=2))
