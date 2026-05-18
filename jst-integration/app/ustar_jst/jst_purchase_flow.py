#!/usr/bin/env python3
"""
聚水潭采购入库完整流程
用法: python jst_purchase_flow.py <sku_code> <qty> [supplier_id]
基于 jst_api_lib.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.jst_client import JSTClient

def sign(params, app_secret):
    sorted_str = ''.join(f'{k}{params[k]}' for k in sorted(params.keys()))
    return hashlib.md5((app_secret + sorted_str).encode('utf-8')).hexdigest().lower()

def api_call(path, biz_data, config):
    params = {
        'app_key': config['app_key'],
        'access_token': config['token'],
        'timestamp': str(int(time.time())),
        'charset': 'utf-8',
        'version': '2',
        'biz': json.dumps(biz_data, ensure_ascii=False, separators=(',',':'))
    }
    params['sign'] = sign(params, config['app_secret'])
    r = requests.post(f"{config['base_url']}{path}", data=params, timeout=30)
    result = r.json()
    if result.get('code') != 0:
        raise Exception(f"API错误 {path}: {result.get('msg')} (code={result.get('code')})")
    return result

def main(sku_code, qty, supplier_id=12557285, warehouse_id=13659696):
    # 配置
    config = {
        'app_key': 'd561deb348274f1ba3505ec4578870fd',
        'app_secret': os.environ.get("JST_APP_SECRET", "84ad2c023b9b49378b1161ea569e383c"),
        'token': 'cfda23ff97664494bc6fc5ab46f8ea48',
        'base_url': 'https://openapi.jushuitan.com'
    }
    
    timestamp = int(time.time())
    ext_purchase = f"CG{timestamp}"
    ext_booking = f"YY{timestamp}"
    
    print(f"[1/4] 创建采购单: {ext_purchase}")
    biz = {
        'external_id': ext_purchase,
        'supplier_id': supplier_id,
        'items': [{
            'sku_code': sku_code,
            'sku_id': sku_code,
            'qty': qty
        }]
    }
    result = api_call('/open/jushuitan/purchase/upload', biz, config)
    po_id = result['data']['data']['po_id']
    print(f"  -> po_id={po_id}")
    
    print(f"[2/4] 预约入库: {ext_booking}")
    biz = {
        'po_id': po_id,
        'supplier_id': supplier_id,
        'external_id': ext_booking,
        'warehouse_id': warehouse_id,
        'planned_date': time.strftime('%Y-%m-%d', time.localtime(time.time() + 86400)),
        'items': [{
            'sku_code': sku_code,
            'sku_id': sku_code,
            'external_id': f"{ext_booking}_1",
            'qty': qty
        }]
    }
    result = api_call('/open/jushuitan/appointmentin/upload', biz, config)
    booking_id = result['data']['data']['po_id']
    print(f"  -> booking_id={booking_id}")
    
    print(f"[3/4] 确认采购单 (option=1)")
    biz = {'po_ids': [po_id], 'option': 1}
    result = api_call('/open/jushuitan/purchase/change/status', biz, config)
    print(f"  -> {result['data']['result'][0]['status']}")
    
    print(f"[4/4] 完成入库 (option=4)")
    biz = {'po_ids': [po_id], 'option': 4}
    result = api_call('/open/jushuitan/purchase/change/status', biz, config)
    print(f"  -> {result['data']['result'][0]['status']}")
    
    print(f"\n✅ 入库完成! po_id={po_id}, sku={sku_code}, qty={qty}")
    return {'po_id': po_id, 'external_id': ext_purchase}

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    sku = sys.argv[1]
    qty = int(sys.argv[2])
    sup = int(sys.argv[3]) if len(sys.argv) > 3 else 12557285
    main(sku, qty, sup)