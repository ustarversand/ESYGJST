#!/usr/bin/env python3
"""
货易达 - 批量下载全部订单列表数据
API: POST /Prod/api/app/member-order/get-member-order-list
分页: pageSize=100, 每页最多128条
输出: orders_list.json (所有订单的列表数据)
"""

import json
import time
import urllib.request
import ssl
import os

BASE_URL = "https://www.heute-express.com"

# 从浏览器拦截到的有效 Bearer Token (过期: 2026-05-22)
BEARER_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJhdWQiOiJKRFQuRXhwcmVzc1N1ZGEiLCJpc3MiOiJKRFQuRXhwcmVzc1N1ZGEi"
    "LCJuYW1laWQiOiI3ZDM5NjNiYi0xMmZkLTQzNDAtYjMxYi01NWQzOWM3MWNiNjAi"
    "LCJnaXZlbl9uYW1lIjoieWFuZyIsInVuaXF1ZV9uYW1lIjoiVVNUQVIiLCJlbWFp"
    "bCI6InVzdGFydmVyc2FuZEBnbWFpbC5jb20iLCJ0ZW5hbnRpZCI6IiIsIk1lbWJl"
    "cklkIjoiMTIiLCJuYmYiOjE3Nzg4MzY3NjMsImV4cCI6MTc3OTQ0MTU2MywiaWF0"
    "IjoxNzc4ODM2NzYzfQ"
    ".deSKYxngTlmiI6KLNQvfpm_MJXgORXGgaABaMSWHAP8"
)

LIST_API = BASE_URL + "/Prod/api/app/member-order/get-member-order-list"
DETAIL_API = BASE_URL + "/Prod/api/app/member-order/get-member-order-for-view"
OUTPUT_DIR = "/opt/data/workspace/heute_express"

PAGE_SIZE = 100
START_TIME = "2026-04-01"
END_TIME = "2026-05-15"

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {BEARER_TOKEN}",
}

ctx = ssl.create_default_context()


def post_json(url, data):
    """POST JSON and return parsed response"""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_orders():
    """Download all orders in paginated batches"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    all_orders = []
    page = 1
    total = None
    consecutive_errors = 0
    max_errors = 10

    print(f"Starting download...")
    
    while True:
        try:
            payload = {
                "pageIndex": page,
                "pageSize": PAGE_SIZE,
                "startTime": START_TIME,
                "endTime": END_TIME,
            }
            data = post_json(LIST_API, payload)
            
            items = data.get("items", [])
            if total is None:
                total = data.get("totalCount", 0)
                print(f"Total orders: {total}")
            
            all_orders.extend(items)
            
            # Progress
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            pct = len(all_orders) / total * 100 if total else 0
            print(f"  Page {page}/{total_pages} - {len(all_orders)}/{total} ({pct:.1f}%)")
            
            # Check if done
            if len(all_orders) >= total or len(items) < PAGE_SIZE:
                break
            
            page += 1
            consecutive_errors = 0
            
            # Rate limit
            time.sleep(0.3)
            
        except Exception as e:
            consecutive_errors += 1
            print(f"  ERROR page {page}: {e}")
            if consecutive_errors >= max_errors:
                print(f"Too many errors ({consecutive_errors}), stopping")
                break
            time.sleep(2)
    
    # Save
    output_path = os.path.join(OUTPUT_DIR, "orders_list.json")
    output = {
        "totalCount": total,
        "fetchedCount": len(all_orders),
        "startTime": START_TIME,
        "endTime": END_TIME,
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "items": all_orders,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\nDone! Saved {len(all_orders)} orders to {output_path}")
    return all_orders


if __name__ == "__main__":
    orders = fetch_all_orders()
