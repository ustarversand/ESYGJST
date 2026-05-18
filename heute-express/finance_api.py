#!/usr/bin/env python3
"""探索货易达财务API"""
import json, sys, ssl, urllib.request, urllib.error, time
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient

client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)
headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + client.token,
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Origin': 'https://www.heute-express.com',
    'Referer': 'https://www.heute-express.com/',
}

base = 'https://www.heute-express.com'
ctx = ssl.create_default_context()

endpoints = [
    ('/Prod/api/app/finance/balance', {}),
    ('/Prod/api/app/finance/my-bills', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/finance/account-detail', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/finance/get-account-records', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/finance/get-recharge-records', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/finance/get-bill-list', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/finance/get-cost-detail', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/finance/get-weight-supplement', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/finance/get-supplement-list', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/order/get-weight-difference', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/account/get-account-info', {}),
    ('/Prod/api/app/account/get-transaction-list', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/account/transaction-record', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/bill/get-bill-list', {'pageIndex': 1, 'pageSize': 20}),
    ('/Prod/api/app/bill/get-recharge-list', {'pageIndex': 1, 'pageSize': 20}),
]

for ep, payload in endpoints:
    url = base + ep
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read())
            code = data.get('code', data.get('result', '?'))
            dd = data.get('data', {})
            if isinstance(dd, dict):
                keys = list(dd.keys())
                print('EP: ' + ep)
                print('  code=' + str(code) + ' keys=' + str(keys))
                for k, v in dd.items():
                    if isinstance(v, list) and len(v) > 0:
                        print('  ' + k + '[0]: ' + json.dumps(v[0], ensure_ascii=False)[:200])
                    elif not isinstance(v, (list, dict)):
                        print('  ' + k + ': ' + str(v))
            elif isinstance(dd, list):
                print('EP: ' + ep + ' code=' + str(code) + ' count=' + str(len(dd)))
                if dd:
                    print('  [0]: ' + json.dumps(dd[0], ensure_ascii=False)[:200])
            elif dd is None and data.get('items'):
                items = data['items']
                print('EP: ' + ep + ' code=' + str(code) + ' items=' + str(len(items)))
                if items:
                    print('  [0]: ' + json.dumps(items[0], ensure_ascii=False)[:200])
            else:
                print('EP: ' + ep + ' data=None, raw=' + json.dumps(data, ensure_ascii=False)[:150])
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:100]
        print('EP: ' + ep + ' HTTP ' + str(e.code) + ' - ' + body)
    except Exception as e:
        print('EP: ' + ep + ' ' + str(e))
    time.sleep(0.2)
