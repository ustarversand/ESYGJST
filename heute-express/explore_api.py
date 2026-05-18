#!/usr/bin/env python3
"""Explore additional API endpoints on Heute"""
import json, sys, os, ssl, urllib.request, urllib.error
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient

client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)
print(f'Token: {client.token[:20]}...')

# Try potential weight/warehouse endpoints
endpoints = [
    '/Prod/api/app/member-order/get-member-order-for-view',
    '/Prod/api/app/member-order/get-member-order-list',
]
for ep in endpoints:
    url = f'https://www.heute-express.com{ep}'
    body = json.dumps({'sn': '2604291216254691'}).encode()
    ctx = ssl.create_default_context()
    headers = {
        'Content-Type':'application/json',
        'Authorization':f'Bearer {client.token}',
        'User-Agent': 'Mozilla/5.0',
        'Origin': 'https://www.heute-express.com',
        'Referer': 'https://www.heute-express.com/members/order-detail',
    }
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read())
            # Show all keys
            if isinstance(data, dict):
                print(f'\n{ep}: keys={list(data.keys())[:20]}')
                print(f'  {json.dumps(data, ensure_ascii=False)[:300]}')
    except urllib.error.HTTPError as e:
        print(f'{ep}: HTTP {e.code}')
