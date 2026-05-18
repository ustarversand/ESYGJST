#!/usr/bin/env python3
"""
🚀 混合模式批量轨迹查询（方案3）
Step 1: 线程池并发查当前状态（8线程）
Step 2: 只在途的补 logistics-tracking 时间线

比原脚本快 7-8x
"""
import json, os, sys, time, subprocess
from datetime import datetime
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
LOG_FILE = '/tmp/batch_track_hybrid.log'
TOKEN_FILE = '/tmp/heute_track_token.json'
BASE_API = 'https://track.heute-express.com/api'

MONTH_FILES = {
    'april': {'orders': 'april_orders.json', 'tracking': 'april_tracking_results.json'},
    'may':   {'orders': 'may_orders.json',   'tracking': 'may_tracking_results.json'},
}

def log(msg):
    ts = datetime.now().isoformat()[:19]
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def login():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            cached = json.load(f)
        if cached.get('expires_at', 0) > time.time() + 300:
            return cached['token']
    cmd = '''curl -s "https://track.heute-express.com/api/auth/login" -X POST -H "Content-Type: application/json" -d '{"username":"admin","password":"Hyd@6ytg19"}' '''
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    result = json.loads(r.stdout)
    token = result['data']['accessToken']
    expires_in = result['data'].get('expiresIn', 7200)
    with open(TOKEN_FILE, 'w') as f:
        json.dump({'token': token, 'expires_at': time.time() + expires_in}, f)
    return token

def curl_get(url, token):
    cmd = f'curl -s --connect-timeout 10 --max-time 15 "{url}" -H "Authorization: Bearer {token}"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
    try:
        return json.loads(r.stdout)
    except:
        return {}

def query_current_status(token, gw):
    """查当前状态"""
    url = f"{BASE_API}/tracking?trackingNo={gw}&page=1&pageSize=1"
    data = curl_get(url, token)
    records = data.get('data', {}).get('records', [])
    if not records:
        return None
    r = records[0]
    return {
        'trackingNo': r.get('trackingNo', ''),
        'extTrackNoCn': r.get('extTrackNoCn', ''),
        'logisticsCompany': r.get('cnLogisticsCompany', ''),
        'currentStatus': r.get('platformTrackingStatusName', ''),
        'latestDesc': r.get('platformTrackingStatusText', '')[:200],
        'latestTime': r.get('platformTrackingStatusTime', ''),
        'subscriptionSource': r.get('subscriptionSource', ''),
        'isSubscribed': r.get('isSubscribed', 0),
        'trackingDetails': [],  # 待Step 2补
    }

def query_timeline(token, gw):
    """查时间线"""
    url = f"{BASE_API}/logistics-tracking?trackingNo={gw}&page=1&pageSize=50"
    data = curl_get(url, token)
    records = data.get('data', {}).get('records', [])
    details = []
    for t in records:
        details.append({
            'trackingTime': t.get('trackingTime', ''),
            'trackingDesc': t.get('trackingDesc', ''),
            'statusName': t.get('platformTrackingStatusName', ''),
            'currentSiteName': t.get('currentSiteName', ''),
            'nextSiteName': t.get('nextSiteName', ''),
            'address': t.get('address', ''),
            'contact': t.get('contact', ''),
            'contactPhone': t.get('contactPhone', ''),
            'signerName': t.get('signerName', ''),
            'signerTypeDesc': t.get('signerTypeDesc', ''),
        })
    return details

def load_orders_and_existing(month):
    orders_file = os.path.join(DATA_DIR, MONTH_FILES[month]['orders'])
    tracking_file = os.path.join(DATA_DIR, MONTH_FILES[month]['tracking'])

    with open(orders_file) as f:
        raw = json.load(f)
    orders = raw.get('items', raw if isinstance(raw, list) else [])

    existing = {}
    if os.path.exists(tracking_file) and os.path.getsize(tracking_file) > 0:
        with open(tracking_file, 'rb') as f:
            existing = json.loads(f.read().decode('utf-8', errors='replace'))

    # 筛选待查
    pending = []
    stats = {'total': 0, 'skip_delivered': 0, 'skip_cancelled': 0, 'to_query': 0}
    for o in orders:
        gw = (o.get('globalWayBillSN') or '').strip()
        if not gw:
            continue
        if o.get('state') == -6:
            stats['skip_cancelled'] += 1
            continue
        stats['total'] += 1
        if gw in existing:
            t = existing[gw].get('tracking', {})
            if isinstance(t, dict) and t.get('currentStatus') in ('已签收', '已撤销'):
                stats['skip_delivered'] += 1
                continue
        pending.append(o)
        stats['to_query'] += 1
    return orders, pending, existing, stats

def save(month, results):
    tracking_file = os.path.join(DATA_DIR, MONTH_FILES[month]['tracking'])
    with open(tracking_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, default=str)
    cnt = Counter()
    for r in results.values():
        t = r.get('tracking', {})
        if isinstance(t, dict):
            s = t.get('currentStatus', '')
            cnt[s] += 1 if s else 0
            if 'error' in t:
                cnt['查询失败'] += 1
        else:
            cnt['未知'] += 1
    by_state = os.path.join(DATA_DIR, f'{month}_tracking_by_state.json')
    with open(by_state, 'w') as f:
        json.dump(dict(cnt.most_common()), f, ensure_ascii=False)
    log(f"  💾 已保存 {len(results)} 条, 状态: {dict(cnt.most_common(6))}")

def run_month(month):
    log(f"\n{'='*50}")
    log(f"🚀 混合模式 {month}月")
    token = login()
    orders, pending, existing, stats = load_orders_and_existing(month)
    log(f"📊 {month}月: 共{stats['total']}单, 已签收跳过{stats['skip_delivered']}单, 待查{stats['to_query']}单")

    if stats['to_query'] == 0:
        log("✅ 全部完成")
        return

    results = existing.copy()
    total = len(pending)
    start = time.time()
    step1_ok = step1_err = 0

    # ═══════════════════════════════════════
    # Step 1: 并行查当前状态
    # ═══════════════════════════════════════
    log(f"\n⚡ Step 1: 并行查当前状态 ({total}条, 8线程)")

    def do_status(order):
        gw = (order.get('globalWayBillSN') or '').strip()
        try:
            status = query_current_status(token, gw)
            if status:
                return gw, {
                    'order': {
                        'sn': order.get('sn', ''),
                        'consignee': order.get('consigneeName', ''),
                        'state': order.get('state'),
                        'lineName': order.get('lineName', ''),
                        'created': (order.get('creationTime', '') or '')[:10],
                        'senderName': order.get('senderName', ''),
                    },
                    'tracking': status,
                    'queried_at': datetime.now().isoformat()[:19],
                }, True
        except Exception as e:
            pass
        return gw, {
            'order': {'sn': order.get('sn','')},
            'tracking': {'error': '查询失败'},
            'queried_at': datetime.now().isoformat()[:19],
        }, False

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(do_status, o): o for o in pending}
        for i, future in enumerate(as_completed(futures)):
            gw, result, ok = future.result()
            results[gw] = result
            if ok:
                step1_ok += 1
            else:
                step1_err += 1
            done = i + 1
            if done % 100 == 0:
                el = time.time() - start
                rate = done / el if el > 0 else 0
                rem = (total - done) / rate if rate > 0 else 0
                log(f"  📊 [{done}/{total}] ok={step1_ok} err={step1_err} | {rate:.0f}条/秒 | {el:.0f}s耗时 | 预计剩余{rem:.0f}s")

        # 每批保存 + 刷新token
        token = login()

    save(month, results)

    # ═══════════════════════════════════════
    # Step 2: 补时间线（只在途）
    # ═══════════════════════════════════════
    need_tl = []
    for gw, r in results.items():
        t = r.get('tracking', {})
        if isinstance(t, dict) and t.get('currentStatus') not in ('已签收', '已撤销', '', None) and 'error' not in t:
            need_tl.append(gw)

    if need_tl:
        log(f"\n⚡ Step 2: 补时间线 ({len(need_tl)}条在途, 8线程)")
        def do_timeline(gw):
            try:
                tl = query_timeline(token, gw)
                return gw, tl
            except:
                return gw, []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(do_timeline, gw): gw for gw in need_tl}
            for i, future in enumerate(as_completed(futures)):
                gw, tl = future.result()
                if gw in results:
                    results[gw]['tracking']['trackingDetails'] = tl
                if (i + 1) % 50 == 0:
                    log(f"  📊 时间线 [{i+1}/{len(need_tl)}]")
    else:
        log("\n⚡ Step 2: 无在途记录，跳过")

    # 最终保存
    save(month, results)
    el = time.time() - start
    log(f"\n{'='*50}")
    log(f"✅ {month}月完成！")
    log(f"  Step1: {step1_ok}成功 {step1_err}失败")
    log(f"  Step2: {len(need_tl)}条时间线")
    log(f"  总耗时: {el:.0f}秒 ({el/60:.1f}分钟)")

if __name__ == '__main__':
    month = sys.argv[1] if len(sys.argv) > 1 else 'april'
    if month not in ('april', 'may'):
        print("用法: python3 batch_track_hybrid.py [april|may]")
        sys.exit(1)
    run_month(month)
