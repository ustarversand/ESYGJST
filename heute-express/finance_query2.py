#!/usr/bin/env python3
"""Query Heute financial logs with proper format"""
import json, sys, ssl, urllib.request, urllib.error
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient

client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)
headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + client.token,
    'User-Agent': 'Mozilla/5.0',
    'Origin': 'https://www.heute-express.com',
    'Referer': 'https://www.heute-express.com/members/member-money-log',
}
ctx = ssl.create_default_context()
base = 'https://www.heute-express.com'
url = base + '/Prod/api/app/member-center/get-member-money-logs'

# Try the parameters the page uses
payload = {"pageIndex":1, "pageSize":10, "startTime":"","endTime":"","type":None,"orderSn":None}
body = json.dumps(payload).encode()
req = urllib.request.Request(url, data=body, headers=headers, method='POST')
try:
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        data = json.loads(resp.read())
        print('Success:', json.dumps(data, ensure_ascii=False)[:500])
except urllib.error.HTTPError as e:
    print('HTTP', e.code)
    print('Response:', e.read().decode()[:500])
