#!/usr/bin/env python3
"""批量查询货易达物流轨迹 — 持久版本（不放 /tmp）"""
import json, os, sys, time
from datetime import datetime

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from heute_sdk import track_package

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
ORDERS_FILE = os.path.join(DATA_DIR, 'april_orders.json')
RESULT_FILE = os.path.join(DATA_DIR, 'april_tracking_results.json')

def load_orders():
    items = []
    if os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE) as f:
            raw = json.load(f)
        items = raw.get('items', raw if isinstance(raw, list) else [])
    return items

def load_results():
    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE) as f:
            return json.load(f)
    return {}

def save_results(results):
    with open(RESULT_FILE, 'w') as f:
        json.dump(results, f, ensure_ascii=False, default=str)

def main():
    print("✅ 批量轨迹查询启动", flush=True)
    sys.stdout.flush()
    orders = load_orders()
    results = load_results()
    
    tracked_gws = set(results.keys())
    
    # Also retry previously failed ones
    failed_gws = set()
    for gw, r in results.items():
        t = r.get('tracking', {})
        if isinstance(t, dict) and 'error' in t:
            failed_gws.add(gw)
    
    # Determine which need re-query: not in results, or errored, or not yet delivered
    def needs_refresh(gw):
        r = results.get(gw, {})
        t = r.get('tracking', {})
        if not isinstance(t, dict):
            return True
        if 'error' in t:
            return True
        status = t.get('currentStatus', '')
        return status not in ('已签收', '已撤销')

    untracked = []
    for o in orders:
        gw = (o.get('globalWayBillSN') or '').strip()
        if gw and (gw not in tracked_gws or needs_refresh(gw)):
            untracked.append(o)
    
    total = len(untracked)
    retry_count = len(failed_gws & set(r.get('order',{}).get('sn','') for r in results.values()))
    print(f"[{datetime.now().isoformat()[:19]}] 待查询: {total} / {len(orders)} (含重试 {len(failed_gws)})")
    
    if total == 0:
        print("所有订单已查询完毕！")
        return
    
    by_sender = {}
    for o in untracked:
        sender = o.get('senderName', '未知')
        by_sender.setdefault(sender, []).append(o)
    
    # Per-sender rate limiting
    sender_last_time = {}
    success = 0
    fail = 0
    skip = 0
    
    for i, o in enumerate(untracked):
        gw = o['globalWayBillSN']
        sender = o.get('senderName', '未知')
        consignee = o.get('consigneeName', '?')
        state = o.get('state')
        
        # Skip state -6 (已撤销) — no point querying cancelled orders
        if state == -6:
            results[gw] = {
                'order': {
                    'sn': o.get('sn',''),
                    'consignee': consignee,
                    'state': state,
                    'lineName': o.get('lineName',''),
                    'created': (o.get('creationTime','')[:10]),
                },
                'tracking': {'currentStatus': '已撤销', 'trackingDetails': [], 'logisticsCompany': ''},
                'queried_at': datetime.now().isoformat()[:19],
            }
            skip += 1
            status = '⏭️'
            if (success + fail + skip) % 50 == 0:
                save_results(results)
                sys.stdout.flush()
            print(f"[{i+1}/{total}] {status} {gw} | {consignee} (已撤销)")
            continue
        
        # Rate limit: max 1 per 1.5s per sender
        last = sender_last_time.get(sender, 0)
        elapsed = time.time() - last
        if elapsed < 1.5:
            time.sleep(1.5 - elapsed)
        sender_last_time[sender] = time.time()
        
        try:
            tracking_result = track_package(gw, max_attempts=5)
            results[gw] = {
                'order': {
                    'sn': o.get('sn',''),
                    'consignee': consignee,
                    'state': o.get('state'),
                    'lineName': o.get('lineName',''),
                    'created': (o.get('creationTime','')[:10]),
                },
                'tracking': tracking_result,
                'queried_at': datetime.now().isoformat()[:19],
            }
            
            if 'error' in tracking_result:
                fail += 1
                status = '❌'
            else:
                success += 1
                status = '✅'
            
            # Save every 10
            if (success + fail) % 10 == 0:
                save_results(results)
                # Also save status file for dashboard
                _save_state_summary(results)
                sys.stdout.flush()
            
            print(f"[{i+1}/{total}] {status} {gw} | {consignee}")
            
        except Exception as e:
            results[gw] = {
                'order': {
                    'sn': o.get('sn',''),
                    'consignee': consignee,
                    'state': o.get('state'),
                    'senderName': sender,
                },
                'tracking': {'error': str(e)},
                'queried_at': datetime.now().isoformat()[:19],
            }
            fail += 1
            print(f"[{i+1}/{total}] ⚠️ {gw} | EXCEPTION: {e}")
    
    # Final save
    save_results(results)
    _save_state_summary(results)
    
    elapsed = time.time() - (sender_last_time.get(list(sender_last_time.keys())[0]) if sender_last_time else 0)
    print(f"\n{'='*40}")
    print(f"批量查询完成!")
    print(f"  成功: {success}")
    print(f"  失败: {fail}")
    print(f"  跳过(已撤销): {skip}")
    print(f"  总计已查: {len(results)} / {len(orders)}")
    print(f"{'='*40}")

def _save_state_summary(results):
    """更新状态汇总文件，让 dashboard 可以热加载"""
    from collections import Counter
    status_counter = Counter()
    for gw, r in results.items():
        t = r.get('tracking', {})
        if 'currentStatus' in t:
            status_counter[t['currentStatus']] += 1
        elif 'error' in t:
            status_counter['查询失败'] += 1
        else:
            status_counter['未知'] += 1
    
    summary_path = os.path.join(DATA_DIR, 'april_tracking_by_state.json')
    with open(summary_path, 'w') as f:
        json.dump(dict(status_counter.most_common()), f, ensure_ascii=False)

if __name__ == '__main__':
    main()
