#!/usr/bin/env python3
"""Login to Heute and get order detail"""
import json, sys
sys.path.insert(0, '/opt/data/workspace/heute_express')
from heute_sdk import HeuteClient

client = HeuteClient.login(username='USTAR', password='Hilden11031980!', save=True)
print('✅ 登录成功')

detail = client.get_order_detail('2604291216254691')
print(json.dumps(detail, ensure_ascii=False, indent=2, default=str))
