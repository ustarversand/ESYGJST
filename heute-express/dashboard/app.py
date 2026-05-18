#!/usr/bin/env python3
"""货易达物流看板 — FastAPI 后端"""
import json, os, sys, time, hashlib, urllib.parse, uvicorn
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from heute_sdk import track_package

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, '..', 'data')

# ─── 月份文件映射 ─────────────────────────────────────────────────────────

MONTH_FILES = {
    'april': {
        'orders': 'april_orders.json',
        'tracking': 'april_tracking_results.json',
        'surcharge': 'april_2026_weight_surcharge.csv',
    },
    'may': {
        'orders': 'may_orders.json',
        'tracking': 'may_tracking_results.json',
        'surcharge': 'may_2026_weight_surcharge.csv',
    },
}

def _month_path(month: str, key: str) -> str:
    """Get data file path for given month and key."""
    files = MONTH_FILES.get(month, MONTH_FILES['may'])
    return os.path.join(DATA_DIR, files[key])

app = FastAPI(title='货易达物流看板', version='1.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

# ─── 加载数据 ──────────────────────────────────────────────────────────────

ORDERS_CACHE = {}
TRACKING_CACHE = {}
CACHE_TIME = None

def load_orders(month: str = 'may'):
    global ORDERS_CACHE, CACHE_TIME
    cache_key = f'orders_{month}'
    if cache_key not in ORDERS_CACHE:
        path = _month_path(month, 'orders')
        if os.path.exists(path):
            with open(path) as f:
                raw = json.load(f)
            ORDERS_CACHE[cache_key] = raw.get('items', raw if isinstance(raw, list) else [])
            CACHE_TIME = datetime.now()
    return ORDERS_CACHE.get(cache_key, [])

def load_tracking(month: str = 'may'):
    global TRACKING_CACHE
    cache_key = f'track_{month}'
    if cache_key not in TRACKING_CACHE:
        path = _month_path(month, 'tracking')
        if os.path.exists(path):
            with open(path) as f:
                TRACKING_CACHE[cache_key] = json.load(f)
    return TRACKING_CACHE.get(cache_key, {})

def format_state(s):
    return {0:'已作废',1:'待支付',2:'待入库',3:'国际运输',4:'国内配送',5:'签收'}.get(s, f'状态{s}')

# ─── 财务数据 ─────────────────────────────────────────────────────────────

FINANCE_CACHE = None

def load_finance(month: str = 'may'):
    global FINANCE_CACHE
    cache_key = f'finance_{month}'
    if FINANCE_CACHE and cache_key in FINANCE_CACHE:
        return FINANCE_CACHE[cache_key]
    
    path = _month_path(month, 'surcharge')
    if not os.path.exists(path):
        FINANCE_CACHE[cache_key] = {'total': 0, 'count': 0, 'daily': [], 'by_order': []}
        return FINANCE_CACHE[cache_key]
    
    import csv
    daily = defaultdict(lambda: {'count': 0, 'amount': 0.0})
    total_amount = 0.0
    total_count = 0
    
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row['时间'][:10]
            amt = float(row['金额(元)'])
            daily[d]['count'] += 1
            daily[d]['amount'] += amt
            total_amount += amt
            total_count += 1
    
    # Convert to sorted list for charts
    daily_list = [{'date': d, 'count': v['count'], 'amount': round(v['amount'], 2)}
                  for d, v in sorted(daily.items())]
    
    # Re-read for order-level grouping
    by_order = defaultdict(lambda: {'count': 0, 'amount': 0.0})
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            oid = row['订单号']
            amt = float(row['金额(元)'])
            by_order[oid]['count'] += 1
            by_order[oid]['amount'] += amt
    
    by_order_list = [{'order_sn': oid, 'count': v['count'], 'amount': round(v['amount'], 2)}
                     for oid, v in sorted(by_order.items(), key=lambda x: x[1]['amount'])]
    
    FINANCE_CACHE[cache_key] = {
        'total_count': total_count,
        'total_amount': round(total_amount, 2),
        'daily': daily_list,
        'by_order': by_order_list,
    }
    return FINANCE_CACHE[cache_key]

FINANCE_CACHE = {}  # dict per month

@app.get('/api/finance')
def get_finance(month: str = Query('may', regex='^(april|may)$')):
    return load_finance(month)

# ─── 按产品名汇总 ─────────────────────────────────────────────────────────

PRODUCT_CACHE_PATH = os.path.join(BASE_DIR, '..', 'data', 'product_cache.json')

def load_product_cache():
    if os.path.exists(PRODUCT_CACHE_PATH):
        try:
            with open(PRODUCT_CACHE_PATH) as f:
                return json.load(f)
        except:
            return {}
    return {}

@app.get('/api/finance/by-product')
def get_finance_by_product(month: str = Query('may', regex='^(april|may)$')):
    cache = load_product_cache()
    surcharge_path = _month_path(month, 'surcharge')
    
    if not os.path.exists(surcharge_path):
        return {'products': [], 'cached': len(cache), 'total_orders': 0}
    
    import csv
    # structure: product_name -> {count, amount, orders: {order_sn: {count, amount, records: [{time, amt}]}}}
    by_product = defaultdict(lambda: {'count': 0, 'amount': 0.0, 'orders': defaultdict(lambda: {'count': 0, 'amount': 0.0, 'records': []})})
    total_records = 0
    
    with open(surcharge_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            oid = row['订单号']
            amt = float(row['金额(元)'])
            total_records += 1
            
            product_info = cache.get(oid, {})
            names = product_info.get('product_names', [])
            product_name = ' + '.join(names) if names else '待加载...'
            
            prod = by_product[product_name]
            prod['count'] += 1
            prod['amount'] += amt
            
            oinfo = prod['orders'][oid]
            oinfo['count'] += 1
            oinfo['amount'] += amt
            oinfo['records'].append({
                'time': row['时间'][:19],
                'amt': round(amt, 2),
                'desc': row.get('描述', '')[:60],
            })
    
    product_list = []
    for name, v in sorted(by_product.items(), key=lambda x: x[1]['amount']):
        orders_list = [{
            'order_sn': oid,
            'count': oinfo['count'],
            'amount': round(oinfo['amount'], 2),
            'records': oinfo['records'][-10:],  # last 10 records per order
        } for oid, oinfo in sorted(v['orders'].items(), key=lambda x: x[1]['amount'])]
        
        product_list.append({
            'name': name,
            'count': v['count'],
            'amount': round(v['amount'], 2),
            'order_count': len(v['orders']),
            'orders': orders_list,
        })
    
    return {
        'products': product_list,
        'cached': len(cache),
        'total_orders': total_records,
        'total_cached_orders': sum(1 for oid in set(r['订单号'] for r in csv.DictReader(open(surcharge_path, 'r', encoding='utf-8-sig'))) if oid in cache),
        'pending': sum(1 for oid in set(r['订单号'] for r in csv.DictReader(open(surcharge_path, 'r', encoding='utf-8-sig'))) if oid not in cache),
    }

@app.get('/api/finance/overweight')
def get_overweight_analysis(month: str = Query('april', regex='^(april|may)$')):
    """超重分析：按产品统计补款率+金额+打包建议"""
    cache = load_product_cache()
    surcharge_path = _month_path(month, 'surcharge')
    orders = load_orders(month)
    
    if not os.path.exists(surcharge_path):
        return {'products': [], 'summary': {}}
    
    # 构建: order_sn -> {weight, product_names, surcharges[]}
    order_map = {}
    for o in orders:
        sn = o.get('sn', '')
        order_map[sn] = {
            'weight_g': o.get('weight', 0),
            'weight_kg': (o.get('weight', 0) or 0) / 1000,
            'product_names': cache.get(sn, {}).get('product_names', []),
        }
    
    # 读补款
    import csv
    with open(surcharge_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sn = row['订单号']
            amt = float(row['金额(元)'])
            if sn in order_map:
                order_map[sn].setdefault('surcharges', []).append(amt)
    
    # 按产品聚合
    from collections import defaultdict
    prod = defaultdict(lambda: {'orders': 0, 'surcharged': 0, 'total_surcharge': 0.0,
                                 'weights': [], 'order_sns': []})
    
    for sn, info in order_map.items():
        names = info['product_names']
        name = ' + '.join(names) if names else None
        if not name:
            continue
        
        p = prod[name]
        p['orders'] += 1
        p['order_sns'].append(sn)
        if info['weight_g']:
            p['weights'].append(info['weight_kg'])
        
        surcharges = info.get('surcharges', [])
        if surcharges:
            p['surcharged'] += 1
            p['total_surcharge'] += sum(surcharges)
    
    # 计算指标 + 打包建议
    products = []
    total_orders = 0
    total_surcharge = 0.0
    
    for name, p in prod.items():
        if p['orders'] < 2:
            continue
        rate = p['surcharged'] / p['orders'] * 100 if p['orders'] else 0
        avg_surcharge = p['total_surcharge'] / p['surcharged'] if p['surcharged'] else 0
        avg_weight = sum(p['weights']) / len(p['weights']) if p['weights'] else 0
        
        # 打包建议
        if rate >= 80 and avg_surcharge <= -1.5:
            advice = '🔴 高频高额：优先优化打包，减重或拆单'
        elif rate >= 60:
            advice = '🟡 高频低额：检查填充物，微调包装'
        elif avg_surcharge <= -3:
            advice = '🟠 低频高额：个别订单严重超重，排查'
        elif rate >= 30:
            advice = '🟢 偶发超重：整体包装OK，关注异常'
        else:
            advice = '✅ 包装良好'
        
        products.append({
            'name': name,
            'orders': p['orders'],
            'surcharged': p['surcharged'],
            'rate': round(rate, 1),
            'total_surcharge': round(p['total_surcharge'], 2),
            'avg_surcharge': round(avg_surcharge, 2),
            'avg_weight_kg': round(avg_weight, 2),
            'advice': advice,
        })
        total_orders += p['orders']
        total_surcharge += p['total_surcharge']
    
    products.sort(key=lambda x: -x['total_surcharge'])
    
    return {
        'products': products,
        'summary': {
            'total_products': len(products),
            'total_orders': total_orders,
            'total_surcharge': round(total_surcharge, 2),
            'month': month,
        }
    }

# ─── API ────────────────────────────────────────────────────────────────────

@app.get('/api/stats')
def get_stats(month: str = Query('may', regex='^(april|may)$')):
    orders = load_orders(month)
    tracking = load_tracking(month)
    
    # Order state distribution
    state_dist = Counter()
    line_dist = Counter()
    sender_dist = Counter()
    weekly = Counter()
    
    for o in orders:
        s = o.get('state')
        state_dist[format_state(s)] += 1
        line_dist[o.get('lineName', '未知')] += 1
        sender_dist[o.get('senderName', '未知')] += 1
        created = (o.get('creationTime') or '')[:10]
        if created:
            try:
                w = datetime.fromisoformat(created).isocalendar()[1]
                weekly[f'W{w}'] += 1
            except:
                pass
    
    # Tracking status distribution
    track_status = Counter()
    for gw, r in tracking.items():
        t = r.get('tracking', {})
        if 'currentStatus' in t:
            track_status[t['currentStatus']] += 1
        elif 'error' in t:
            track_status['查询失败'] += 1
        else:
            track_status['未知'] += 1
    
    # Separate: cancelled (state -6) vs truly abnormal
    cancelled = []
    abnormal = []
    now = datetime.now()
    for o in orders:
        s = o.get('state')
        created = o.get('creationTime', '')
        gw = (o.get('globalWayBillSN') or '').strip()
        if s == -6:
            cancelled.append({'sn': o['sn'], 'consignee': o.get('consigneeName',''),
                              'state': '已撤销', 'created': created[:10],
                              'sender': o.get('senderName',''), 'tracking': gw})
        elif s == 2 and created:
            try:
                dt = datetime.fromisoformat(created.replace('Z',''))
                if (now - dt).days > 7:
                    abnormal.append({'sn': o['sn'], 'consignee': o.get('consigneeName',''),
                                     'state': '待入库>7天', 'created': created[:10],
                                     'sender': o.get('senderName',''), 'tracking': gw})
            except:
                pass
        # Check tracking for errors
        if gw in tracking:
            t = tracking[gw].get('tracking', {})
            if 'error' in t and s != -6:
                pass  # will be caught by tracking_status
    
    return {
        'total_orders': len(orders),
        'tracked': len(tracking),
        'untracked': len(orders) - len(tracking),
        'cancelled_count': len(cancelled),
        'cancelled_orders': cancelled[:50],
        'abnormal_count': len(abnormal),
        'abnormal_orders': abnormal[:50],
        'state_distribution': dict(state_dist.most_common()),
        'tracking_status': dict(track_status.most_common()),
        'line_distribution': dict(line_dist.most_common(10)),
        'sender_distribution': dict(sender_dist.most_common(10)),
        'weekly_orders': dict(sorted(weekly.items())),
        'abnormal_count': len(abnormal),
        'abnormal_orders': abnormal[:50],
        'cache_time': CACHE_TIME.isoformat() if CACHE_TIME else None,
    }

@app.get('/api/orders/recent')
def get_recent_orders(limit: int = Query(50, le=200), month: str = Query('may', regex='^(april|may)$')):
    orders = load_orders(month)
    recent = sorted(orders, key=lambda o: o.get('creationTime',''), reverse=True)[:limit]
    return [{
        'sn': o['sn'],
        'consignee': o.get('consigneeName',''),
        'state': format_state(o.get('state')),
        'state_code': o.get('state'),
        'line': o.get('lineName',''),
        'sender': o.get('senderName',''),
        'weight': f"{((o.get('weight') or 0)/1000):.1f}kg",
        'created': (o.get('creationTime','')[:19]).replace('T',' '),
        'tracking_no': o.get('globalWayBillSN',''),
        'domestic_no': o.get('tempLineSN',''),
    } for o in recent]

# ─── 异常对比 API ─────────────────────────────────────────────────────────

def load_anomalies(month: str) -> list:
    """加载异常对比结果"""
    path = os.path.join(DATA_DIR, f'anomaly_comparison_{month}.json')
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return []

@app.get('/api/anomalies')
def get_anomalies(month: str = Query('april', regex='^(april|may)$')):
    """获取异常对比列表"""
    anomalies = load_anomalies(month)
    return {
        'total': len(anomalies),
        'severe': sum(1 for a in anomalies if a.get('match') == 'severe'),
        'warning': sum(1 for a in anomalies if a.get('match') == 'warning'),
        'ok': sum(1 for a in anomalies if a.get('match') == 'ok'),
        'scanned_at': anomalies[0].get('scanned_at', '') if anomalies else '',
        'items': anomalies,
    }

@app.get('/api/tracking/results')
def get_tracking_results(page: int = Query(1, ge=1), per_page: int = Query(50, le=200),
                         status_filter: Optional[str] = None,
                         month: str = Query('may', regex='^(april|may)$')):
    tracking = load_tracking(month)
    items = []
    for gw, r in tracking.items():
        t = r.get('tracking', {})
        cur = t.get('currentStatus', t.get('error', '未知'))
        if status_filter and status_filter != 'all' and cur != status_filter:
            continue
        items.append({
            'tracking_no': gw,
            'order_sn': r.get('order', {}).get('sn',''),
            'consignee': r.get('order', {}).get('consignee',''),
            'status': cur,
            'company': t.get('logisticsCompany',''),
            'domestic_no': t.get('extTrackNoCn',''),
            'detail_count': len(t.get('trackingDetails', [])),
            'queried_at': r.get('queried_at',''),
        })
    
    items.sort(key=lambda x: x.get('queried_at',''), reverse=True)
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    return {'items': items[start:end], 'total': total, 'page': page, 'per_page': per_page}

@app.get('/api/tracking/{tracking_no}')
def query_tracking(tracking_no: str, month: str = Query(None, regex='^(april|may)$')):
    if month:
        tracking = load_tracking(month)
        if tracking_no in tracking:
            result = tracking[tracking_no]
            return _with_kuaidi100_status(result)
        raise HTTPException(404, f'{month}月未找到 {tracking_no}')
    
    for m in ('may', 'april'):
        tracking = load_tracking(m)
        if tracking_no in tracking:
            result = tracking[tracking_no]
            return _with_kuaidi100_status(result)
    
    raise HTTPException(404, f'未找到 {tracking_no} 的轨迹')

# ─── 快递100企业版API ─────────────────────────────────────────────────────
# ✅ 已验证通过 (2026-05-15): auto自动识别heute品牌, 31+事件全链路

KD100_KEY = "tufqlXgA2928"
KD100_CUSTOMER = "E26E983AE77169477938606B043C5494"

def _live_kuaidi100(biz_no: str) -> Optional[dict]:
    """快递100企业版API实时查询轨迹（智能识别：DEU→auto, SF→sf, JD→jd）"""
    if not biz_no:
        return None
    
    # 智能选择快递编码
    prefix = biz_no[:3].upper() if len(biz_no) >= 3 else ''
    if prefix in ('SF1', 'SF0'):
        com_list = ['sf', 'auto']
    elif prefix in ('JDV', 'JDX', 'JDE'):
        com_list = ['jd', 'auto']
    elif prefix in ('DEU', 'HYD'):
        com_list = ['auto', 'sf', 'youzhenggj']
    else:
        com_list = ['auto', 'sf', 'jd', 'youzhenggj']
    
    try:
        for com in com_list:
            param = json.dumps({'com': com, 'num': biz_no, 'resultv2': '4'})
            raw = param + KD100_KEY + KD100_CUSTOMER
            sign = hashlib.md5(raw.encode()).hexdigest().upper()
            data = urllib.parse.urlencode({'customer': KD100_CUSTOMER, 'sign': sign, 'param': param}).encode()
            req = urllib.request.Request(
                'https://poll.kuaidi100.com/poll/query.do',
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read())
            
            # 有returnCode=失败，尝试下一个com
            if result.get('returnCode'):
                continue
            
            items = result.get('data', [])
            state = int(result.get('state', 0))
            STATE_MAP = {0:"在途",1:"揽收",2:"疑难",3:"签收",4:"退签",5:"派件",6:"退回",7:"清关",8:"拒签"}
            state_name = STATE_MAP.get(state, f"状态{state}")
            
            details = []
            for item in items:
                ctx = item.get("context", "")
                if ctx:
                    details.append({
                        "trackingTime": item.get("time", ""),
                        "trackingDesc": ctx,
                        "statusName": "",
                        "address": item.get("location", ""),
                    })
            
            return {
                "currentStatus": state_name,
                "latestDesc": details[0]["trackingDesc"] if details else state_name,
                "latestTime": details[0]["trackingTime"] if details else "",
                "trackingDetails": details,
                "_source": f"kuaidi100_enterprise({com})",
            }
        return None
    except Exception:
        return None

# ─── 国内单号查询（全走企业版，SF需传手机号） ─────────────────────────────

def _query_domestic(ext_no: str, phone: str = '') -> Optional[dict]:
    """查询国内转运单号轨迹。JD/SF均走企业版，SF用phone后4位"""
    if not ext_no:
        return None
    
    prefix = ext_no[:2].upper() if len(ext_no) >= 2 else ''
    
    if prefix == 'JD':
        return _live_kuaidi100(ext_no)
    
    elif prefix == 'SF':
        # SF企业版：必须传手机号后4位
        phone_val = phone[-4:] if phone and len(phone) >= 4 else ''
        try:
            param_dict = {'com': 'sf', 'num': ext_no, 'resultv2': '4'}
            if phone_val:
                param_dict['phone'] = phone_val
            
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
            # SF企业版 state: 1xx/10xx=在途, 3xx=签收
            if state >= 300:
                state_name = "签收"
            elif state >= 1000:
                state_name = "在途"
            else:
                STATE_MAP = {0:"在途",1:"揽收",2:"疑难",3:"签收",4:"退签",5:"派件",6:"退回",7:"清关",8:"拒签"}
                state_name = STATE_MAP.get(state, f"状态{state}")
            
            items = result.get('data', [])
            details = []
            for item in items:
                ctx = item.get("context", "")
                if ctx:
                    details.append({
                        "trackingTime": item.get("time", ""),
                        "trackingDesc": ctx,
                        "statusName": "",
                        "address": item.get("location", ""),
                    })
            
            return {
                "currentStatus": state_name,
                "latestDesc": details[0]["trackingDesc"] if details else state_name,
                "latestTime": details[0]["trackingTime"] if details else "",
                "trackingDetails": details,
                "_source": "kuaidi100_enterprise(sf)",
            }
        except Exception:
            return None
    
    else:
        return None

def _with_kuaidi100_status(result: dict) -> dict:
    """快递100企业版实时刷新 + 国内单号双轨对比"""
    tracking = result.get("tracking", {})
    order = result.get("order", {})
    
    # 优先用主运单号（DEUHYD...），其次国内转运单号
    biz_no = tracking.get("trackingNo", "") or order.get("tempLineSN", "") or tracking.get("extTrackNoCn", "")
    if not biz_no:
        return result
    
    # 1次自动重试
    kd = _live_kuaidi100(biz_no)
    if not kd:
        time.sleep(1)
        kd = _live_kuaidi100(biz_no)
    
    if not kd:
        return result
    
    tracking["currentStatus"] = kd.get("currentStatus", tracking.get("currentStatus", ""))
    tracking["_source"] = kd.get("_source", "kuaidi100_enterprise")
    tracking["latestDesc"] = kd.get("latestDesc", "")
    tracking["latestTime"] = kd.get("latestTime", "")
    
    # 有事件明细 → 完全替换；无事件 → 保留缓存
    if kd.get("trackingDetails"):
        tracking["trackingDetails"] = kd["trackingDetails"]
    
    # ── 国内单号双轨对比 ──
    ext_no = tracking.get("extTrackNoCn", "")
    if ext_no and ext_no != biz_no:
        # 获取收件人手机号（SF查询需要）
        phone = ''
        order_sn = order.get('sn', '')
        if order_sn:
            for m in ('april', 'may'):
                for o in load_orders(m):
                    if o.get('sn') == order_sn:
                        phone = o.get('consigneeTel', '')
                        break
                if phone:
                    break
        
        dom = _query_domestic(ext_no, phone)
        if dom:
            dom_summary = {
                "trackingNo": ext_no,
                "currentStatus": dom.get("currentStatus", ""),
                "latestDesc": dom.get("latestDesc", ""),
                "latestTime": dom.get("latestTime", ""),
                "trackingDetails": dom.get("trackingDetails", []),
                "_source": dom.get("_source", ""),
            }
            # 对比分析
            intl_status = tracking.get("currentStatus", "")
            dom_status = dom_summary["currentStatus"]
            if intl_status == dom_status:
                dom_summary["match"] = "ok"
            elif intl_status in ("在途", "派件", "清关", "揽收") and dom_status == "签收":
                dom_summary["match"] = "severe"  # 🔴 国内已签收但国际未完成
            elif intl_status != dom_status:
                dom_summary["match"] = "warning"  # 🟡 状态不一致
            else:
                dom_summary["match"] = "ok"
            
            # 时间差
            intl_time = tracking.get("latestTime", "")
            dom_time = dom_summary["latestTime"]
            if intl_time and dom_time:
                try:
                    t1 = datetime.strptime(intl_time[:19], "%Y-%m-%d %H:%M:%S")
                    t2 = datetime.strptime(dom_time[:19], "%Y-%m-%d %H:%M:%S")
                    diff_hours = abs((t1 - t2).total_seconds()) / 3600
                    dom_summary["timeDiffHours"] = round(diff_hours, 1)
                except:
                    pass
            
            # ── 自动修正：国内已签收>6h → 覆盖国际状态 ──
            if dom_summary["match"] == "severe":
                diff = dom_summary.get("timeDiffHours", 0)
                if diff > 6:
                    dom_time_short = dom_time[:16] if dom_time else ""
                    tracking["currentStatus"] = f"签收(国内确认)"
                    tracking["latestDesc"] = f"[国内{dom_time_short}确认签收] {dom_summary.get('latestDesc', '')}"
                    tracking["latestTime"] = dom_time
                    dom_summary["autoCorrected"] = True
            
            tracking["domesticComparison"] = dom_summary
    
    return result

@app.get('/api/tracking/search')
def search_tracking(q: str = Query('', min_length=3),
                    month: str = Query('may', regex='^(april|may)$')):
    """搜索运单号或收件人"""
    tracking = load_tracking(month)
    orders = load_orders(month)
    results = []
    q = q.lower()
    
    for o in orders:
        gw = (o.get('globalWayBillSN') or '').lower()
        sn = (o.get('sn') or '').lower()
        name = (o.get('consigneeName') or '').lower()
        if q in gw or q in sn or q in name:
            t = tracking.get(o.get('globalWayBillSN',''), {})
            if isinstance(t, dict):
                track_data = t.get('tracking', {})
            results.append({
                'order_sn': o['sn'],
                'consignee': o.get('consigneeName',''),
                'state': format_state(o.get('state')),
                'line': o.get('lineName',''),
                'tracking_no': o.get('globalWayBillSN',''),
                'domestic_no': o.get('tempLineSN',''),
                'tracking_status': track_data.get('currentStatus', '未查询'),
                'created': (o.get('creationTime','')[:19]).replace('T',' '),
            })
    return results[:100]

@app.get('/api')
def api_root():
    return {'name': '货易达物流看板 API', 'version': '1.0', 'endpoints': [
        '/api/stats', '/api/orders/recent', '/api/tracking/results',
        '/api/tracking/{no}', '/api/tracking/search?q=', '/api/order/{sn}'
    ]}

@app.get('/api/order/{sn}')
def get_order_detail(sn: str, month: str = Query('may', regex='^(april|may)$')):
    """获取订单详情（含下单信息和产品明细）"""
    orders = load_orders(month)
    order = None
    for o in orders:
        if o.get('sn') == sn:
            order = o
            break
    if not order:
        raise HTTPException(404, f'订单 {sn} 未找到')
    
    # Try to get full detail from Heute API
    detail = {}
    try:
        import sys
        import importlib.util
        sdk_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'heute_sdk.py')
        if os.path.exists(sdk_path):
            spec = importlib.util.spec_from_file_location('heute_sdk', sdk_path)
            sdk = importlib.util.module_from_spec(spec)
            sys.modules['heute_sdk'] = sdk
            spec.loader.exec_module(sdk)
            
            token_paths = [
                os.path.join(os.path.dirname(os.path.dirname(__file__)), '.heute_token'),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), 'heute_token.txt'),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', '..', '.heute_token'),
            ]
            token = None
            for p in token_paths:
                if os.path.exists(p):
                    token = open(p).read().strip()
                    break
            if token:
                client = sdk.HeuteClient(token=token)
                detail = client.get_order_detail(sn)
    except Exception as e:
        pass
    
    result = {
        'sn': order.get('sn'),
        'state': order.get('state'),
        'state_name': format_state(order.get('state')),
        'line_name': order.get('lineName', ''),
        'weight': order.get('weight', 0),
        'weight_kg': f"{(order.get('weight') or 0)/1000:.1f}",
        'created': (order.get('creationTime','')[:19]).replace('T',' '),
        'sender_name': order.get('senderName',''),
        'sender_tel': order.get('senderTel',''),
        'consignee_name': order.get('consigneeName',''),
        'consignee_tel': order.get('consigneeTel',''),
        'consignee_id': order.get('consigneeIDNumber',''),
        'consignee_province': order.get('consigneeProvince',''),
        'consignee_city': order.get('consigneeCity',''),
        'consignee_county': order.get('consigneeCounty',''),
        'consignee_address': order.get('consigneeAddress',''),
        'global_waybill': order.get('globalWayBillSN',''),
        'temp_line_sn': order.get('tempLineSN',''),
        'merchant_order_sn': order.get('merchantOrderSN',''),
        'platform_sn': order.get('platformSN',''),
        'id_card_status': order.get('idCardInfoStatus', -1),
        'money_estimate': (order.get('moneyEstimate') or 0) / 100,
        'money_final': (order.get('moneyFinal') or 0) / 100,
        'fee_ship': (order.get('feeShip') or 0) / 100,
        'fee_customs': (order.get('feeCustoms') or 0) / 100,
        'fee_insurance': (order.get('feeInsurance') or 0) / 100,
    }
    
    # If we got full detail from API, merge products
    if detail and not detail.get('error'):
        products = []
        for p in detail.get('orderDetails', []):
            products.append({
                'goods_name': p.get('goodsName',''),
                'goods_name_en': p.get('goodsNameForeign',''),
                'brand': p.get('goodsBrand',''),
                'ean': p.get('ean',''),
                'num': p.get('num', 0),
                'price': (p.get('price') or 0) / 100,
                'price_rmb': (p.get('priceRMB') or 0) / 100,
                'net_weight': p.get('netWeight',''),
                'goods_code': p.get('goodsCode',''),
            })
        result['products'] = products
        result['has_full_detail'] = True
    else:
        result['products'] = []
        result['has_full_detail'] = False
    
    return result

# ─── 前端 SPA ──────────────────────────────────────────────────────────────

@app.get('/', response_class=HTMLResponse)
def index():
    path = os.path.join(BASE_DIR, 'templates', 'index.html')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return f.read()
    return HTMLResponse('<h1>货易达看板</h1><p>前端文件缺失</p>')

# ─── 启动 ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import socket
    host = '0.0.0.0'
    port = int(os.environ.get('DASHBOARD_PORT', '8892'))
    
    # Print local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = '127.0.0.1'
    
    print(f'📊 货易达物流看板')
    print(f'   Local:   http://127.0.0.1:{port}')
    print(f'   Network: http://{local_ip}:{port}')
    print(f'   Docs:    http://{local_ip}:{port}/docs')
    print(f'   Orders cached: {len(load_orders())}')
    print(f'   Tracking cached: {len(load_tracking())}')
    print()
    uvicorn.run(app, host=host, port=port, log_level='info')
