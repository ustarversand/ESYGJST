#!/usr/bin/env python3
"""Quick financial query for April 2026 - only 1 page each"""
import json, sys, ssl, urllib.request, urllib.error
sys.path.insert(0, '/opt/data/workspace/heute_express')

# Manual login
import heute_sdk
client = heute_sdk.HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)
headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + client.token,
}
url = 'https://www.heute-express.com/Prod/api/app/member-center/get-member-money-logs'
ctx = ssl.create_default_context()

def query(type_val):
    payload = {"pageIndex":1, "pageSize":200, "startTime":"2026-04-01", "endTime":"2026-05-15", "type":type_val, "orderSn":None}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read())

# 称重补款
d = query(-2)
print('S1:' + str(d.get('totalCount', 0)))

# 预收款  
d2 = query(-1)
print('S2:' + str(d2.get('totalCount', 0)))
