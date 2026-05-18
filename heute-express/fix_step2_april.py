#!/usr/bin/env python3
"""补全4月在途运单的时间线 (Step 2 only)"""
import json, os, sys, time, subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
TOKEN_FILE = '/tmp/heute_track_token.json'
LOG_FILE = '/tmp/batch_track_step2.log'

def log(msg):
    ts = datetime.now().isoformat()[:19]
    print(f"[{ts}] {msg}", flush=True)

def login():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            cached = json.load(f)
        if cached.get('expires_at', 0) > time.time() + 300:
            return cached['token']
    r = subprocess.run(
        '''curl -s "https://track.heute-express.com/api/auth/login" -X POST -H "Content-Type: application/json" -d '{"username":"admin","password":"Hyd@6ytg19"}' ''',
        shell=True, capture_output=True, text=True, timeout=15)
    result = json.loads(r.stdout)
    token = result['data']['accessToken']
    expires_in = result['data'].get('expiresIn', 7200)
    with open(TOKEN_FILE, 'w') as f:
        json.dump({'token': token, 'expires_at': time.time() + expires_in}, f)
    return token

def query_timeline(token, gw):
    url = f"https://track.heute-express.com/api/logistics-tracking?trackingNo={gw}&page=1&pageSize=50"
    cmd = f'curl -s --connect-timeout 10 --max-time 15 "{url}" -H "Authorization: Bearer {token}"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
    try:
        data = json.loads(r.stdout)
    except:
        return gw, []
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
    return gw, details

def main():
    log("🚀 Step 2: 补4月在途时间线")
    token = login()

    tracking_file = os.path.join(DATA_DIR, 'april_tracking_results.json')
    with open(tracking_file) as f:
        tracking = json.load(f)

    # 筛选在途且无时间线的
    need_tl = []
    for gw, r in tracking.items():
        t = r.get('tracking', {})
        if isinstance(t, dict):
            s = t.get('currentStatus', '')
            if s not in ('已签收', '已撤销', '', None) and 'error' not in t:
                tl = t.get('trackingDetails', [])
                if not tl:
                    need_tl.append(gw)

    log(f"📊 需补时间线: {len(need_tl)}条")
    if not need_tl:
        log("✅ 无需补")
        return

    # 并发查
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(query_timeline, token, gw): gw for gw in need_tl}
        for future in as_completed(futures):
            gw, tl = future.result()
            if gw in tracking:
                tracking[gw]['tracking']['trackingDetails'] = tl
            done += 1
            if done % 30 == 0:
                log(f"  📊 [{done}/{len(need_tl)}]")
                # 每批保存
                with open(tracking_file, 'w', encoding='utf-8') as f:
                    json.dump(tracking, f, ensure_ascii=False, default=str)

    # 最终保存
    with open(tracking_file, 'w', encoding='utf-8') as f:
        json.dump(tracking, f, ensure_ascii=False, default=str)
    log(f"✅ 完成！{len(need_tl)}条时间线已补全")

if __name__ == '__main__':
    main()
