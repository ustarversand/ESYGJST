#!/usr/bin/env python3
"""批量扫描在途国际单号 → 对比国内单号状态 → 写入 anomaly_comparison.json"""
import json, os, sys, time, hashlib, urllib.request, urllib.parse
from datetime import datetime
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
KD100_KEY = "tufqlXgA2928"
KD100_CUSTOMER = "E26E983AE77169477938606B043C5494"

STATE_MAP = {0:"在途",1:"揽收",2:"疑难",3:"签收",4:"退签",5:"派件",6:"退回",7:"清关",8:"拒签"}

# ─── API 查询 ──────────────────────────────────────────────────────────────

def _kuaidi100_enterprise(biz_no: str, com: str) -> dict | None:
    """企业版API查询"""
    try:
        param = json.dumps({'com': com, 'num': biz_no, 'resultv2': '4'})
        raw = param + KD100_KEY + KD100_CUSTOMER
        sign = hashlib.md5(raw.encode()).hexdigest().upper()
        data = urllib.parse.urlencode({'customer': KD100_CUSTOMER, 'sign': sign, 'param': param}).encode()
        req = urllib.request.Request('https://poll.kuaidi100.com/poll/query.do', data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
        if result.get('returnCode'):
            return None
        state = int(result.get('state', 0))
        return {
            'status': STATE_MAP.get(state, f"状态{state}"),
            'state_code': state,
            'events': len(result.get('data', [])),
            'latest_time': (result.get('data', [{}])[0] or {}).get('time', ''),
            'latest_desc': ((result.get('data', [{}])[0] or {}).get('context', ''))[:80],
            'source': f'kuaidi100_enterprise({com})',
        }
    except Exception as e:
        return None

def _kuaidi100_public_sf(biz_no: str) -> dict | None:
    """公共API查询SF（5s超时）"""
    try:
        url = f"https://www.kuaidi100.com/query?type=shunfeng&postid={biz_no}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        if data.get("status") != "200":
            return None
        state = int(data.get("state", 0))
        if state >= 300:
            status_name = "签收"
        else:
            status_name = STATE_MAP.get(state, f"状态{state}")
        items = data.get("data", [])
        events = [i for i in items if i.get("context", "") != "查无结果"] if isinstance(items, list) else []
        return {
            'status': status_name,
            'state_code': state,
            'events': len(events),
            'latest_time': (events[0] if events else {}).get('time', ''),
            'latest_desc': ((events[0] if events else {}).get('context', ''))[:80],
            'source': 'kuaidi100_public(sf)',
        }
    except Exception:
        return None

def query_intl(tracking_no: str) -> dict | None:
    """查询国际单号 → 企业版 auto"""
    # DEU → auto
    for com in ['auto', 'sf', 'youzhenggj']:
        r = _kuaidi100_enterprise(tracking_no, com)
        if r:
            return r
    return None

def query_domestic(ext_no: str, phone: str = '') -> dict | None:
    """查询国内单号 → JD/SF均走企业版，SF传手机号后4位"""
    if not ext_no:
        return None
    prefix = ext_no[:2].upper()
    if prefix == 'JD':
        return _kuaidi100_enterprise(ext_no, 'jd')
    elif prefix == 'SF':
        phone_val = phone[-4:] if phone and len(phone) >= 4 else ''
        param_dict = {'com': 'sf', 'num': ext_no, 'resultv2': '4'}
        if phone_val:
            param_dict['phone'] = phone_val
        try:
            param = json.dumps(param_dict)
            raw = param + KD100_KEY + KD100_CUSTOMER
            sign = hashlib.md5(raw.encode()).hexdigest().upper()
            data = urllib.parse.urlencode({'customer': KD100_CUSTOMER, 'sign': sign, 'param': param}).encode()
            req = urllib.request.Request('https://poll.kuaidi100.com/poll/query.do', data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'})
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read())
            if result.get('returnCode'):
                return None
            state = int(result.get('state', 0))
            if state >= 300:
                status_name = "签收"
            elif state >= 1000:
                status_name = "在途"
            else:
                status_name = STATE_MAP.get(state, f"状态{state}")
            items = result.get('data', [])
            return {
                'status': status_name, 'state_code': state,
                'events': len(items),
                'latest_time': (items[0] if items else {}).get('time', ''),
                'latest_desc': ((items[0] if items else {}).get('context', ''))[:80],
                'source': 'kuaidi100_enterprise(sf)',
            }
        except Exception:
            return None
    return None

# ─── 对比分析 ──────────────────────────────────────────────────────────────

def compare(intl: dict, dom: dict) -> str:
    """对比分析 → ok / warning / severe"""
    is_intl = intl.get('status', '')
    ds = dom.get('status', '')
    if is_intl == ds:
        return 'ok'
    if is_intl in ('在途', '派件', '清关', '揽收') and ds == '签收':
        return 'severe'
    if is_intl != ds:
        return 'warning'
    return 'ok'

# ─── 主流程 ────────────────────────────────────────────────────────────────

def scan_month(month: str, dry_run: bool = False, fix: bool = False):
    """扫描指定月份的在途单号"""
    orders_file = os.path.join(DATA_DIR, f'{month}_orders.json')
    tracking_file = os.path.join(DATA_DIR, f'{month}_tracking_results.json')
    output_file = os.path.join(DATA_DIR, f'anomaly_comparison_{month}.json')
    
    if not os.path.exists(tracking_file):
        print(f"❌ {tracking_file} not found")
        return
    
    with open(tracking_file, 'r') as f:
        tracking = json.load(f)
    
    print(f"📦 {month}: {len(tracking)} entries in cache")
    
    # 找出需要扫描的单号 + 加载手机号
    targets = []
    # 构建手机号字典
    phone_map = {}
    orders_file_path = os.path.join(DATA_DIR, f'{month}_orders.json')
    if os.path.exists(orders_file_path):
        with open(orders_file_path, 'r') as f:
            orders_data = json.load(f)
        for o in orders_data.get('items', []):
            gw = o.get('globalWayBillSN', '')
            tel = o.get('consigneeTel', '')
            if gw and tel:
                phone_map[gw] = tel
    
    for tn, entry in tracking.items():
        if not isinstance(entry, dict):
            continue
        t = entry.get('tracking', {})
        if not isinstance(t, dict):
            continue
        ext = t.get('extTrackNoCn', '')
        status = t.get('currentStatus', '')
        if not ext:
            continue
        # 只扫描非签收/非撤销的
        if status in ('签收', '已签收', '已撤销', '运单已经创建'):
            continue
        targets.append({
            'intl_tn': tn,
            'dom_tn': ext,
            'cached_status': status,
            'order_sn': entry.get('order', {}).get('sn', '') if isinstance(entry.get('order'), dict) else '',
        })
    
    print(f"🎯 {len(targets)} targets (non-签收 with domestic counterpart)")
    
    if dry_run:
        for t in targets[:10]:
            print(f"  {t['order_sn']:20s} {t['intl_tn'][:25]} → {t['dom_tn']} [{t['cached_status']}]")
        return
    
    # 批量查询
    results = []
    sf_count = 0
    severe_new = []
    
    for i, t in enumerate(targets):
        intl_tn = t['intl_tn']
        dom_tn = t['dom_tn']
        
        # 查询国际（企业版无频率限制）
        intl_result = query_intl(intl_tn)
        if not intl_result:
            intl_result = {'status': t['cached_status'], 'state_code': -1, 'events': 0,
                          'latest_time': '', 'latest_desc': '', 'source': 'cache'}
        
        # 查询国内
        dom_result = query_domestic(dom_tn, phone_map.get(intl_tn, ''))
        if not dom_result:
            continue
        
        match = compare(intl_result, dom_result)
        
        record = {
            'order_sn': t['order_sn'],
            'intl_tracking': intl_tn,
            'dom_tracking': dom_tn,
            'intl': intl_result,
            'dom': dom_result,
            'match': match,
            'scanned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        # 时间差计算
        it = intl_result.get('latest_time', '')
        dt = dom_result.get('latest_time', '')
        if it and dt:
            try:
                t1 = datetime.strptime(it[:19], '%Y-%m-%d %H:%M:%S')
                t2 = datetime.strptime(dt[:19], '%Y-%m-%d %H:%M:%S')
                record['time_diff_hours'] = round(abs((t1 - t2).total_seconds()) / 3600, 1)
            except:
                pass
        
        results.append(record)
        
        tag = '🔴' if match == 'severe' else ('🟡' if match == 'warning' else '🟢')
        print(f"  {tag} [{i+1}/{len(targets)}] {intl_tn[:20]} {intl_result['status']} vs {dom_result['status']} ({match})")
        
        if match == 'severe':
            severe_new.append(record)
        
        # 增量保存每20条
        if (i + 1) % 20 == 0:
            with open(output_file, 'w') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"  💾 saved {len(results)}/{len(targets)}")
    
    # 写结果
    with open(output_file, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # 统计
    counts = defaultdict(int)
    for r in results:
        counts[r['match']] += 1
    
    print(f"\n✅ {month} scan done: {len(results)} compared")
    print(f"   🟢 ok: {counts['ok']}  🟡 warning: {counts['warning']}  🔴 severe: {counts['severe']}")
    
    if severe_new:
        print(f"\n🚨 {len(severe_new)} SEVERE anomalies:")
        for r in severe_new:
            print(f"   {r['order_sn']} {r['intl_tracking'][:25]} → {r['dom_tracking']}")
    
    # ─── Fix mode: 自动修正国内已签收的订单状态 ──────────────────────────
    if fix and severe_new:
        fixed_count = 0
        skipped_recent = 0
        for r in severe_new:
            intl_tn = r['intl_tracking']
            time_diff = r.get('time_diff_hours', 0)
            # 时间差<2h 且国内刚签收 → 可能是国际未同步，记录但跳过
            if time_diff < 2:
                skipped_recent += 1
                continue
            if intl_tn in tracking and isinstance(tracking[intl_tn], dict):
                track_data = tracking[intl_tn].get('tracking', {})
                if isinstance(track_data, dict):
                    dom_time = r['dom'].get('latest_time', '')[:16]
                    track_data['currentStatus'] = '签收(国内确认)'
                    track_data['latestDesc'] = f'[国内{dom_time}确认签收] {r["dom"].get("latest_desc", "")}'
                    track_data['latestTime'] = r['dom'].get('latest_time', '')
                    track_data['_fix_source'] = 'auto-fix-by-scan'
                    fixed_count += 1
        
        if fixed_count > 0:
            with open(tracking_file, 'w') as f:
                json.dump(tracking, f, ensure_ascii=False, indent=2)
            print(f"\n🔧 FIXED: {fixed_count} orders updated to 签收(国内确认) in {tracking_file}")
        if skipped_recent > 0:
            print(f"⏭  SKIPPED: {skipped_recent} severe cases with time_diff<2h (may be fresh sync)")
        if fixed_count == 0 and skipped_recent == 0:
            print(f"\n⚠️  No fixes applied")
    
    return results, severe_new

if __name__ == '__main__':
    month = sys.argv[1] if len(sys.argv) > 1 else 'april'
    dry_run = '--dry' in sys.argv
    fix = '--fix' in sys.argv
    scan_month(month, dry_run=dry_run, fix=fix)
