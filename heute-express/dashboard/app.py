#!/usr/bin/env python3
"""货易达物流看板 — FastAPI 后端（SQLite 版）"""
import json, os, sys, time, csv, hashlib, urllib.request, urllib.parse, uvicorn, subprocess, shutil, ssl, threading, re, sqlite3

# 从NAS绑定挂载加载修补后的代码（容器重建后自动恢复，patch目录持久化在NAS上）
_PATCH_DIR = '/app/data/patch'
if os.path.isdir(_PATCH_DIR):
    for _src, _dst in [
        (f'{_PATCH_DIR}/app.py',    '/app/dashboard/app.py'),
        (f'{_PATCH_DIR}/heute_db.py', '/app/heute_db.py'),
        (f'{_PATCH_DIR}/index.html',  '/app/dashboard/templates/index.html'),
    ]:
        if os.path.exists(_src):
            try:
                shutil.copy2(_src, _dst)
            except Exception:
                pass

from datetime import datetime, timedelta
from collections import Counter, defaultdict
from fastapi import FastAPI, Query, HTTPException, Request, Body
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from heute_db import (
    init_db, DB,
    get_orders, get_order_count, get_senders,
    get_tracking, get_tracking_status_dist,
    get_tracking_by_no, search_tracking,
    get_anomalies, get_anomaly_counts, count_anomalies_by_sender,
    get_month_overview, upsert_tracking, bulk_upsert_orders,
    store_apollo_order, get_apollo_orders, get_apollo_order_count, delete_apollo_order,
    create_after_sales, get_after_sales, update_after_sales, delete_after_sales, get_after_sales_stats,
    search_after_sales,
    lookup_order_by_tracking,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, '..', 'data')
PROGRESS_FILE = os.path.join(DATA_DIR, '.track_progress.json')

# 批量轨迹查询互斥锁
_batch_lock = threading.Lock()
_batch_in_progress = False

def write_progress(phase='idle', current=0, total=100, message='', done=False):
    """写进度文件供前端轮询"""
    try:
        data = {
            'running': not done,
            'phase': phase,
            'current': current,
            'total': total,
            'percent': round(current / total * 100, 1) if total > 0 else 0,
            'message': message,
            'done': done,
        }
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass

# DB初始化（首次启动建表）
init_db()

# ─── 月份映射 ─────────────────────────────────────────────────────────────
MONTH_FILES = {
    'april': {'surcharge': 'april_2026_weight_surcharge.csv'},
    'may':   {'surcharge': 'may_2026_weight_surcharge.csv'},
}
def _month_path(month: str, key: str) -> str:
    files = MONTH_FILES.get(month, MONTH_FILES['may'])
    return os.path.join(DATA_DIR, files[key])

app = FastAPI(title='货易达物流看板 (SQLite)', version='2.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
app.add_middleware(SessionMiddleware, secret_key='heute-dashboard-session-secret-2026', max_age=86400)

# ─── 用户系统 ─────────────────────────────────────────────────────────────
USERS_PATH = os.path.join(DATA_DIR, 'users.json')

def load_users() -> dict:
    if os.path.exists(USERS_PATH):
        try:
            with open(USERS_PATH, encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users: dict):
    with open(USERS_PATH, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def sync_users():
    users = load_users()
    changed = False
    for s in get_senders():
        if s not in users:
            users[s] = {"password": "123456", "created": datetime.now().isoformat(),
                         "status": "active", "last_login": None}
            changed = True
    if 'admin' not in users:
        users['admin'] = {"password": "123456", "role": "admin", "created": datetime.now().isoformat(),
                          "status": "active", "last_login": None}
        changed = True
    if changed:
        save_users(users)

def get_sender_from_session(request: Request) -> str | None:
    """获取当前用户，未登录返回None"""
    role = request.session.get('role', '')
    if role == 'admin':
        return None  # admin可以看到所有订单
    return request.session.get('sender', None)

sync_users()

# ─── 辅助 ─────────────────────────────────────────────────────────────────
def format_state(s):
    return {0:'已作废',1:'待支付',2:'待入库',3:'国际运输',4:'国内配送',5:'签收'}.get(s, f'状态{s}')

# ─── 财务数据（不变，仍读CSV）─────────────────────────────────────────────
FINANCE_CACHE = {}
def load_finance(month: str = 'may'):
    global FINANCE_CACHE
    cache_key = f'finance_{month}'
    if cache_key in FINANCE_CACHE:
        return FINANCE_CACHE[cache_key]
    path = _month_path(month, 'surcharge')
    if not os.path.exists(path):
        FINANCE_CACHE[cache_key] = {'total': 0, 'count': 0, 'daily': [], 'by_order': []}
        return FINANCE_CACHE[cache_key]
    import csv
    daily = defaultdict(lambda: {'count': 0, 'amount': 0.0})
    total_amount, total_count = 0.0, 0
    with open(path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            d = row['时间'][:10]
            amt = float(row['金额(元)'])
            daily[d]['count'] += 1
            daily[d]['amount'] += amt
            total_amount += amt
            total_count += 1
    by_order = defaultdict(lambda: {'count': 0, 'amount': 0.0})
    with open(path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            oid = row['订单号']
            by_order[oid]['count'] += 1
            by_order[oid]['amount'] += float(row['金额(元)'])
    FINANCE_CACHE[cache_key] = {
        'total_count': total_count,
        'total_amount': round(total_amount, 2),
        'daily': [{'date': d, 'count': v['count'], 'amount': round(v['amount'], 2)}
                   for d, v in sorted(daily.items())],
        'by_order': [{'order_sn': oid, 'count': v['count'], 'amount': round(v['amount'], 2)}
                      for oid, v in sorted(by_order.items(), key=lambda x: x[1]['amount'])],
    }
    return FINANCE_CACHE[cache_key]

def filter_finance_by_sender(finance: dict, month: str, sender: str | None) -> dict:
    if not sender:
        return finance
    orders = get_orders(month)
    sender_sns = {o['sn'] for o in orders if o.get('sender_name', '') == sender}
    import csv
    daily = defaultdict(lambda: {'count': 0, 'amount': 0.0})
    total_amount, total_count = 0.0, 0
    path = _month_path(month, 'surcharge')
    if not os.path.exists(path):
        return {'total_count': 0, 'total_amount': 0, 'daily': [], 'by_order': []}
    with open(path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if row['订单号'] in sender_sns:
                d = row['时间'][:10]
                amt = float(row['金额(元)'])
                daily[d]['count'] += 1
                daily[d]['amount'] += amt
                total_amount += amt
                total_count += 1
    return {
        'total_count': total_count,
        'total_amount': round(total_amount, 2),
        'daily': [{'date': d, 'count': v['count'], 'amount': round(v['amount'], 2)}
                   for d, v in sorted(daily.items())],
        'by_order': [],
    }

# ─── 认证 ─────────────────────────────────────────────────────────────────
@app.post('/api/auth/login')
def auth_login(request: Request, data: dict):
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        raise HTTPException(400, '缺少用户名或密码')
    users = load_users()
    user = users.get(username)
    if not user or user.get('password') != password:
        raise HTTPException(401, '用户名或密码错误')
    if user.get('status') != 'active':
        raise HTTPException(403, '账户已被停用')
    role = user.get('role', 'sender')
    request.session['sender'] = username if role == 'sender' else None
    request.session['role'] = role
    request.session['username'] = username
    user['last_login'] = datetime.now().isoformat()
    save_users(users)
    return {'ok': True, 'user': username, 'role': role}

@app.get('/api/auth/me')
def auth_me(request: Request):
    return {
        'logged_in': bool(request.session.get('role')),
        'username': request.session.get('username', ''),
        'role': request.session.get('role', ''),
        'sender': request.session.get('sender', ''),
    }

@app.post('/api/auth/logout')
def auth_logout(request: Request):
    request.session.clear()
    return {'ok': True}

@app.get('/api/senders')
def api_senders():
    return {'senders': get_senders()}

# ─── 管理员 ───────────────────────────────────────────────────────────────
@app.get('/api/admin/senders')
def admin_senders(request: Request):
    if request.session.get('role') != 'admin':
        raise HTTPException(403, '仅管理员可访问')
    users = load_users()
    from collections import defaultdict
    agg = defaultdict(lambda: {'total_orders': 0, 'tracked': 0, 'signed': 0, 'severe': 0})
    for m in ('april', 'may'):
        orders = get_orders(m)
        for o in orders:
            name = o.get('sender_name', '')
            if not name:
                continue
            a = agg[name]
            a['total_orders'] += 1
            gw = o.get('global_waybill_sn', '')
            if gw:
                t = get_tracking_by_no(gw, m)
                if t:
                    a['tracked'] += 1
                    cur = t.get('tracking', {}).get('currentStatus', '')
                    if '签收' in cur or '国内确认' in cur:
                        a['signed'] += 1
        a_counts = get_anomaly_counts(m)
        for name in agg:
            agg[name]['severe'] += count_anomalies_by_sender(name, m)
    result = []
    for name in sorted(get_senders()):
        a = agg[name]
        u = users.get(name, {})
        result.append({
            'name': name,
            'total_orders': a['total_orders'],
            'tracked': a['tracked'],
            'signed': a['signed'],
            'severe': a['severe'],
            'status': u.get('status', 'active'),
            'last_login': u.get('last_login', ''),
            'created': u.get('created', ''),
        })
    return result

@app.patch('/api/admin/senders/{name}')
def admin_update_sender(request: Request, name: str, data: dict):
    if request.session.get('role') != 'admin':
        raise HTTPException(403, '仅管理员可访问')
    users = load_users()
    if name not in users:
        raise HTTPException(404, f'用户 {name} 不存在')
    if name == 'admin':
        raise HTTPException(400, '不能修改admin账户')
    if 'status' in data:
        users[name]['status'] = data['status']
    if 'password' in data and data['password']:
        users[name]['password'] = data['password']
    save_users(users)
    return {'ok': True, 'user': name, 'status': users[name]['status']}

@app.post('/api/admin/senders/{name}/token')
def admin_generate_token(request: Request, name: str):
    if request.session.get('role') != 'admin':
        raise HTTPException(403, '仅管理员可访问')
    users = load_users()
    if name not in users:
        raise HTTPException(404, f'用户 {name} 不存在')
    if name == 'admin':
        raise HTTPException(400, '不能为admin生成token')
    import secrets
    token = secrets.token_urlsafe(32)
    tokens_path = os.path.join(DATA_DIR, 'tokens.json')
    tokens = {}
    if os.path.exists(tokens_path):
        try:
            with open(tokens_path) as f:
                tokens = json.load(f)
        except:
            pass
    tokens[token] = {'sender': name, 'created': datetime.now().isoformat()}
    with open(tokens_path, 'w') as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)
    return {'ok': True, 'token': token,
            'url': f"http://9fiyahtfp3uvhf4p.myfritz.net:8890/?token={token}"}

# ─── 快递100企业版开关（物流轨迹异常对比）─────────────────────────────────
KUAIDI100_TOGGLE_PATH = os.path.join(DATA_DIR, 'kuaidi100_toggle.json')

def load_kuaidi100_toggle() -> dict:
    default = {'enabled': False, 'updated_at': ''}
    if os.path.exists(KUAIDI100_TOGGLE_PATH):
        try:
            with open(KUAIDI100_TOGGLE_PATH) as f:
                return json.load(f)
        except:
            pass
    return default

def save_kuaidi100_toggle(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(KUAIDI100_TOGGLE_PATH, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.get('/api/admin/kuaidi100-toggle')
def get_kuaidi100_toggle(request: Request):
    if request.session.get('role') != 'admin':
        raise HTTPException(403, '仅管理员可访问')
    return load_kuaidi100_toggle()

@app.post('/api/admin/kuaidi100-toggle')
def set_kuaidi100_toggle(request: Request, data: dict):
    if request.session.get('role') != 'admin':
        raise HTTPException(403, '仅管理员可访问')
    enabled = data.get('enabled', False)
    if not isinstance(enabled, bool):
        raise HTTPException(400, 'enabled 必须为布尔值')
    toggle = {
        'enabled': enabled,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    save_kuaidi100_toggle(toggle)
    return toggle


# ─── Apollo 订单回调 ──────────────────────────────────────────────────────────

@app.post('/api/apollo/callback')
async def apollo_callback(request: Request):
    """接收 Apollo 数字清关平台的订单推送"""
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse(
            {'success': False, 'code': '400', 'message': f'无效的JSON: {e}'},
            status_code=400
        )
    
    tc_order_id = body.get('tcOrderId', '')
    if not tc_order_id:
        return JSONResponse(
            {'success': False, 'code': '400', 'message': '缺少 tcOrderId'},
            status_code=400
        )
    
    print(f'[Apollo Callback] 收到订单: {tc_order_id}')
    try:
        order_id = store_apollo_order(body)
        print(f'[Apollo Callback] 已存储 #{order_id}')
        return {'success': True, 'code': '200', 'message': '成功', 'data': str(order_id)}
    except Exception as e:
        print(f'[Apollo Callback] 存储失败: {e}')
        return JSONResponse(
            {'success': False, 'code': '500', 'message': f'存储失败: {e}'},
            status_code=500
        )


@app.get('/api/apollo/orders')
def list_apollo_orders(page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
                       month: str = None):
    """查询 Apollo 推送订单列表"""
    offset = (page - 1) * size
    orders = get_apollo_orders(limit=size, offset=offset, month=month)
    total = get_apollo_order_count(month=month)
    for o in orders:
        try:
            o['sku_list'] = json.loads(o.pop('sku_json', '[]'))
        except:
            o['sku_list'] = []
        try:
            o['raw'] = json.loads(o.pop('raw_json', '{}'))
        except:
            o['raw'] = {}
    return {'data': orders, 'total': total, 'page': page, 'size': size}


@app.get('/api/apollo/count')
def apollo_order_count(month: str = None):
    return {'total': get_apollo_order_count(month=month)}


@app.delete('/api/apollo/orders/{order_id}')
def remove_apollo_order(order_id: int):
    if delete_apollo_order(order_id):
        return {'success': True, 'message': '已删除'}
    raise HTTPException(status_code=404, detail='订单不存在')


# ─── 前端 SPA ──────────────────────────────────────────────────────────────
@app.get('/api/auth/token-login')
def token_login(request: Request, token: str = Query('')):
    if not token:
        return {'ok': False, 'error': '缺少token'}
    tokens_path = os.path.join(DATA_DIR, 'tokens.json')
    if not os.path.exists(tokens_path):
        return {'ok': False, 'error': 'Token无效'}
    try:
        with open(tokens_path) as f:
            tokens = json.load(f)
    except:
        return {'ok': False, 'error': 'Token无效'}
    token_data = tokens.get(token)
    if not token_data:
        return {'ok': False, 'error': 'Token无效或已过期'}
    sender = token_data.get('sender', '')
    users = load_users()
    if sender not in users or users[sender].get('status') != 'active':
        return {'ok': False, 'error': '账户不可用'}
    request.session['sender'] = sender
    request.session['role'] = 'sender'
    request.session['username'] = sender
    users[sender]['last_login'] = datetime.now().isoformat()
    save_users(users)
    return {'ok': True, 'user': sender, 'role': 'sender'}

# ─── API ──────────────────────────────────────────────────────────────────

@app.get('/api/stats')
def get_stats(request: Request, month: str = Query('may', pattern='^(april|may)$')):
    sender = get_sender_from_session(request)
    orders = get_orders(month, sender)

    state_dist = Counter()
    line_dist = Counter()
    sender_dist = Counter()
    weekly = Counter()
    now = datetime.now()
    cancelled = []
    abnormal = []

    for o in orders:
        s = o.get('state')
        state_dist[format_state(s)] += 1
        line_dist[o.get('line_name', '未知')] += 1
        sender_dist[o.get('sender_name', '未知')] += 1
        created = (o.get('creation_time') or '')[:10]
        if created:
            try:
                w = datetime.strptime(created, '%Y-%m-%d').isocalendar()[1]
                weekly[f'W{w}'] += 1
            except:
                pass
        gw = o.get('global_waybill_sn', '')
        sn_val = o.get('sn', '')
        if s == -6:
            cancelled.append({'sn': sn_val, 'consignee': o.get('consignee_name',''),
                              'state': '已撤销', 'created': created,
                              'sender': o.get('sender_name',''), 'tracking': gw})
        elif s == 2 and created:
            try:
                dt = datetime.strptime(created, '%Y-%m-%d')
                if (now - dt).days > 7:
                    abnormal.append({'sn': sn_val, 'consignee': o.get('consignee_name',''),
                                     'state': '待入库>7天', 'created': created,
                                     'sender': o.get('sender_name',''), 'tracking': gw})
            except:
                pass

    # 状态分布从DB查
    track_status = get_tracking_status_dist(month, sender)
    tracked = sum(track_status.values())
    # 排除撤销单（state=-6），它们不应算入待查
    cancelled_gws = [c["tracking"] for c in cancelled if c["tracking"]]
    if cancelled_gws:
        from heute_db import DB
        with DB() as db:
            ph = ",".join("?" for _ in cancelled_gws)
            r = db.execute(f"SELECT COUNT(DISTINCT tracking_no) FROM tracking WHERE month=? AND tracking_no IN ({ph})", [month] + cancelled_gws).fetchone()
            cancelled_tracked = r[0] if r else 0
    else:
        cancelled_tracked = 0
    active_count = len(orders) - len(cancelled)
    # 额外排除已签收(state=5)订单，它们不应算入待查
    signed_count = sum(1 for o in orders if o.get('state') == 5)
    active_count -= signed_count
    active_tracked = tracked - cancelled_tracked
    untracked = max(0, active_count - active_tracked)
    # ⭐ 加上手动标记的已撤销（从tracking表标记的）
    manual_cancelled = track_status.get('已撤销', 0)

    # 双轨签收统计
    signed_total = track_status.get('已签收', 0) + track_status.get('签收(国内确认)', 0)
    signed_international = track_status.get('已签收', 0)
    signed_domestic_only = track_status.get('签收(国内确认)', 0)
    # 严重异常数
    severe_count = 0
    try:
        ac = get_anomaly_counts(month, sender=sender)
        severe_count = ac.get('severe', 0)
    except:
        pass

    return {
        'total_orders': len(orders),
        'tracked': tracked,
        'untracked': untracked,
        'cancelled_count': len(cancelled) + manual_cancelled,
        'cancelled_orders': cancelled[:50],
        'abnormal_count': len(abnormal),
        'abnormal_orders': abnormal[:50],
        'state_distribution': dict(state_dist.most_common()),
        'tracking_status': track_status,
        'signed_total': signed_total,
        'signed_international': signed_international,
        'signed_domestic_only': signed_domestic_only,
        'severe_anomalies': severe_count,
        'line_distribution': dict(line_dist.most_common(10)),
        'sender_distribution': dict(sender_dist.most_common(10)),
        'weekly_orders': dict(sorted(weekly.items())),
    }

@app.get('/api/orders/recent')
def get_recent_orders(request: Request, limit: int = Query(50, le=200),
                      month: str = Query('may', pattern='^(april|may)$')):
    sender = get_sender_from_session(request)
    orders = get_orders(month, sender)
    recent = sorted(orders, key=lambda o: o.get('creation_time','') or '', reverse=True)[:limit]
    return [{
        'sn': o['sn'],
        'consignee': o.get('consignee_name',''),
        'state': format_state(o.get('state')),
        'state_code': o.get('state'),
        'line': o.get('line_name',''),
        'sender': o.get('sender_name',''),
        'weight': f"{((o.get('weight') or 0)/1000):.1f}kg",
        'created': (o.get('creation_time','')[:19]).replace('T',' '),
        'tracking_no': o.get('global_waybill_sn',''),
        'domestic_no': o.get('temp_line_sn',''),
    } for o in recent]


@app.get('/api/orders/untracked')
def get_untracked_orders(request: Request, month: str = Query('may', pattern='^(april|may)$')):
    """返回有单号但无tracking记录的订单"""
    sender = get_sender_from_session(request)
    db_path = os.path.join(DATA_DIR, 'heute.db')
    
    try:
        db = sqlite3.connect(db_path)
        if sender:
            rows = db.execute("""
                SELECT o.sn, o.consignee_name, o.sender_name, o.state, 
                       o.global_waybill_sn, o.temp_line_sn, o.creation_time, o.line_name
                FROM orders o
                LEFT JOIN tracking t ON o.global_waybill_sn = t.tracking_no AND t.month = ?
                WHERE o.month = ? AND o.state NOT IN (5, -6)
                  AND t.tracking_no IS NULL
                  AND o.sender_name = ?
                ORDER BY o.creation_time DESC
            """, (month, month, sender)).fetchall()
        else:
            rows = db.execute("""
                SELECT o.sn, o.consignee_name, o.sender_name, o.state, 
                       o.global_waybill_sn, o.temp_line_sn, o.creation_time, o.line_name
                FROM orders o
                LEFT JOIN tracking t ON o.global_waybill_sn = t.tracking_no AND t.month = ?
                WHERE o.month = ? AND o.state NOT IN (5, -6)
                  AND t.tracking_no IS NULL
                ORDER BY o.creation_time DESC
            """, (month, month)).fetchall()
        db.close()
    except Exception as e:
        raise HTTPException(500, f'查询失败: {e}')
    
    return [{
        'sn': r[0],
        'consignee': r[1],
        'sender': r[2],
        'state': format_state(r[3]),
        'state_code': r[3],
        'tracking_no': r[4] or '',
        'domestic_no': r[5] or '',
        'created': (r[6] or '')[:19].replace('T', ' ') if r[6] else '',
        'line': r[7] or '',
    } for r in rows]

# --- 轨迹相关API已移除 (2025-05-23) ---
@app.get('/api/anomalies')
def get_anomalies_endpoint(request: Request, month: str = Query('april', pattern='^(april|may)$'),
                           match_filter: Optional[str] = Query(None, pattern='^(severe|warning|ok)$')):
    sender = get_sender_from_session(request)
    anomalies = get_anomalies(month, match_filter=match_filter, sender=sender)
    counts = Counter(a.get('match') for a in anomalies)
    return {
        'total': len(anomalies),
        'severe': counts.get('severe', 0),
        'warning': counts.get('warning', 0),
        'ok': counts.get('ok', 0),
        'scanned_at': anomalies[0].get('scanned_at', '') if anomalies else '',
        'items': anomalies,
    }

# ─── 轨迹 API ────────────────────────────────────────────────────────────

@app.get('/api/tracking/results')
def get_tracking_results(request: Request, page: int = Query(1, ge=1),
                          per_page: int = Query(50, le=200),
                          status_filter: Optional[str] = None,
                          month: str = Query('may', pattern='^(april|may)$')):
    sender = get_sender_from_session(request)
    if sender:
        # For sender: paginate manually since SQL filters by sender
        sender_gws = {o['global_waybill_sn'] for o in get_orders(month, sender)}
        items, total = get_tracking(month, status_filter, 1, 999999)
        items = [i for i in items if i.get('tracking', {}).get('tracking_no', '') in sender_gws]
        total = len(items)
        start = (page - 1) * per_page
        items = items[start:start + per_page]
    else:
        items, total = get_tracking(month, status_filter, page, per_page)

    result_items = []
    for i in items:
        t = i.get('tracking', {})
        cur = t.get('currentStatus', t.get('current_status', '未知'))
        latest_desc = t.get('latestDesc', t.get('latest_desc', ''))
        details = t.get('trackingDetails', [])
        first_detail = details[0] if details else {}
        
        # 提取位置：优先用轨迹详情里的currentSiteName，否则从latest_desc解析【...】或"国际运单已生成{城市}"
        location = first_detail.get('currentSiteName', '')
        if not location and latest_desc:
            # pattern 1: 【城市名】
            m = re.search(r'【(.+?)】', latest_desc)
            if m:
                location = m.group(1)
            else:
                # pattern 2: 国际运单已生成{城市}顺丰/京东/中通:
                m = re.search(r'已生成(.{2,6}?)(?:顺丰|京东|中通|韵达|圆通|申通|EMS|邮政):', latest_desc)
                if m:
                    location = m.group(1)
        
        result_items.append({
            'tracking_no': t.get('tracking_no', ''),
            'order_sn': t.get('order', {}).get('sn', ''),
            'consignee': t.get('order', {}).get('consignee', ''),
            'status': _better_status_name(cur, latest_desc),
            'company': '',
            'location': location,  # 当前位置
            'domestic_no': t.get('ext_track_no_cn', ''),
            'detail_count': len(details),
            'details': details,  # 完整的轨迹详情，用于弹窗
            'queried_at': t.get('queried_at', ''),
        })

    return {'items': result_items, 'total': total, 'page': page, 'per_page': per_page}


@app.get('/api/tracking/query-live')
def api_tracking_live_query(tracking_no: str = Query(...)):
    """实时查单号轨迹(货易达track API) — 返回完整状态+城市+国内单号+物流公司"""
    tn = tracking_no.strip()
    if not tn:
        return {'found': False, 'error': '请输入运单号'}
    token = _track_api_login()
    if not token:
        return {'found': False, 'error': 'Track API登录失败'}
    try:
        url = f'{_TRACK_API_URL}/tracking?trackingNo={urllib.parse.quote(tn)}&page=1&pageSize=1'
        cmd = ['curl', '-s', '--max-time', '15', '-H', f'Authorization: Bearer {token}', url]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
        records = data.get('data', {}).get('records', []) or data.get('records', [])
        if not records:
            return {'found': False, 'error': 'Track API未找到此单号'}
        rec = records[0]
        raw_status = rec.get('platformTrackingStatusName', '')
        raw_text = rec.get('platformTrackingStatusText', '')
        return {
            'found': True,
            'tracking_no': rec.get('trackingNo', tn),
            'domestic_no': rec.get('extTrackNoCn', ''),
            'status_name': _better_status_name(raw_status, raw_text),
            'status_text': rec.get('platformTrackingStatusText', ''),
            'status_time': rec.get('platformTrackingStatusTime', ''),
            'from_city': rec.get('fromCity', ''),
            'to_city': rec.get('toCity', ''),
            'logistics_company': rec.get('cnLogisticsCompany', ''),
            'weight': rec.get('weight', ''),
            'created_at': rec.get('createdAt', ''),
            'updated_at': rec.get('updatedAt', ''),
            'platform': rec.get('ecommercePlatform', ''),
            'batch_id': rec.get('batchId', ''),
            'flag_ie': rec.get('flagIe', ''),
            'warehouse_id': rec.get('warehouseId', ''),
        }
    except subprocess.TimeoutExpired:
        return {'found': False, 'error': '查询超时'}
    except json.JSONDecodeError:
        return {'found': False, 'error': 'API返回异常'}
    except Exception as e:
        return {'found': False, 'error': f'查询失败: {str(e)}'}


@app.get('/api/tracking/search')
def search_tracking_api(request: Request, q: str = Query('', min_length=3),
                         month: str = Query('may', pattern='^(april|may)$')):
    sender = get_sender_from_session(request)
    if sender:
        results = search_tracking(q, month)
        sender_gws = {o['global_waybill_sn'] for o in get_orders(month, sender)}
        results = [r for r in results
                   if r.get('tracking', {}).get('tracking_no', '') in sender_gws]
    else:
        results = search_tracking(q, month)
    return [{
        'order_sn': r.get('tracking', {}).get('order', {}).get('sn', ''),
        'consignee': r.get('tracking', {}).get('order', {}).get('consignee_name', ''),
        'state': '',
        'line': '',
        'tracking_no': r.get('tracking', {}).get('tracking_no', ''),
        'domestic_no': r.get('tracking', {}).get('ext_track_no_cn', ''),
        'tracking_status': _better_status_name(
            r.get('tracking', {}).get('currentStatus', r.get('tracking', {}).get('current_status', '未查询')),
            r.get('tracking', {}).get('latestDesc', r.get('tracking', {}).get('latest_desc', ''))
        ),
        'created': '',
    } for r in results[:100]]


@app.get('/api/tracking/{tracking_no}')
def query_tracking(tracking_no: str, month: str = Query(None, pattern='^(april|may)$')):
    # 先查本地数据库
    if month:
        result = get_tracking_by_no(tracking_no, month)
        if result:
            return _with_kuaidi100_status(result)
    else:
        for m in ('may', 'april'):
            result = get_tracking_by_no(tracking_no, m)
            if result:
                return _with_kuaidi100_status(result)
    # 本地没有 → 实时查快递100（国际单号、国内单号都能查）
    toggle = load_kuaidi100_toggle()
    if toggle.get('enabled', False):
        live = _live_kuaidi100(tracking_no)
    else:
        live = None
    if live:
        return {'tracking': {
            'tracking_no': tracking_no,
            'currentStatus': _better_status_name(live.get('currentStatus',''), live.get('latestDesc','')),
            'latestDesc': live['latestDesc'],
            'latestTime': live['latestTime'],
            'trackingDetails': live['trackingDetails'],
            '_source': live['_source'],
        }}
    raise HTTPException(404, f'未找到 {tracking_no} 的轨迹')


@app.post('/api/tracking/{tracking_no}/status')
def set_tracking_status(tracking_no: str, data: dict = Body(...)):
    """手动标记运单状态"""
    month = data.get('month', 'may')
    status = data.get('status', '')
    if not status:
        raise HTTPException(400, '缺少 status 参数')
    
    valid_statuses = {'已签收','已撤销','待出库','国际运输','清关中','国内配送','已作废','问题件'}
    if status not in valid_statuses:
        raise HTTPException(400, f'无效状态: {status}，可选: {", ".join(sorted(valid_statuses))}')
    
    db_path = os.path.join(DATA_DIR, 'heute.db')
    try:
        db = sqlite3.connect(db_path)
        db.execute("UPDATE tracking SET current_status=?, queried_at=? WHERE tracking_no=? AND month=?", 
                   (status, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), tracking_no, month))
        db.commit()
        db.close()
    except Exception as e:
        raise HTTPException(500, f'数据库更新失败: {e}')
    
    from heute_db import get_tracking_count_by_status
    stats = get_tracking_count_by_status(month)
    return {'ok': True, 'tracking_no': tracking_no, 'status': status, 'stats': stats}


@app.post('/api/tracking/{tracking_no}/refresh')
def refresh_tracking(tracking_no: str, month: str = Query('may', pattern='^(april|may)$')):
    """手动刷新单条轨迹：调货易达实时查 + 更新DB + 返回新数据"""
    from heute_api import HeuteAPI
    api = HeuteAPI()
    try:
        result = api.track.query(tracking_no)
    except Exception as e:
        raise HTTPException(502, f'货易达查询失败: {e}')
    
    if not result or not result.get('trackingNo'):
        raise HTTPException(404, f'货易达未返回轨迹: {tracking_no}')
    
    # 查订单号
    order_sn = ''
    db_path_refresh = os.path.join(DATA_DIR, 'heute.db')
    try:
        db = sqlite3.connect(db_path_refresh)
        row = db.execute("SELECT sn FROM orders WHERE global_waybill_sn=?", (tracking_no,)).fetchone()
        if row:
            order_sn = row[0]
        db.close()
    except Exception:
        pass
    
    # 写入DB
    try:
        db = sqlite3.connect(db_path_refresh)
        upsert_tracking(db, tracking_no, month, result, order_info={'sn': order_sn})
        db.commit()
        db.close()
    except Exception as e:
        pass  # 不影响返回结果
    
    return _with_kuaidi100_status({
        'tracking_no': tracking_no,
        'month': month,
        'current_status': result.get('currentStatus', ''),
        'latest_desc': result.get('latestDesc', ''),
        'latest_time': result.get('latestTime', ''),
        'tracking_json': json.dumps(result.get('trackingDetails', []), ensure_ascii=False),
        'queried_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })

# ─── 一键更新进度查询 ──────────────────────────────────────────────────
@app.get('/api/tracking/query-untracked/progress')
def get_track_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {'running': False, 'phase': 'idle', 'percent': 0, 'message': '无进行中的任务', 'done': True}
    with open(PROGRESS_FILE) as f:
        data = json.loads(f.read())
    # 合并互斥锁状态
    data['batch_busy'] = _batch_in_progress
    return data

@app.get('/api/tracking/query-untracked/status')
def get_track_status():
    """快速获取批量查询状态（互斥锁）"""
    return {'busy': _batch_in_progress}

# ─── 一键更新：从货易达查询所有订单状态 ─────────────────────────────────
@app.post('/api/tracking/query-untracked')
def query_untracked_tracking(request: Request, month: str = Query('may', pattern='^(april|may)$')):
    """
    一键更新：查询所有未签收订单的状态
    - 只从货易达物流官网查询
    - 跳过已签收的订单(state=5)
    - 互斥锁，防止重复点击
    """
    global _batch_in_progress
    with _batch_lock:
        if _batch_in_progress:
            raise HTTPException(429, '已有批量查询任务在运行，请等待完成后再试')
        _batch_in_progress = True

    try:
        sender = get_sender_from_session(request)
        if sender is None:
            pass
        elif sender == '':
            raise HTTPException(401, '请重新登录或刷新页面')
        else:
            pass

        write_progress('syncing', 0, 100, f'正在同步{month}月订单…')
        DB_PATH = os.path.join(DATA_DIR, 'heute.db')

        # 加载货易达统一API（自动登录，无需Token文件管理）
        from heute_api import HeuteAPI
        api = HeuteAPI()

        # ── 第1步：从货易达官网同步最新订单明细（拉前3页 ≈ 384单，最新订单）──
        try:
            fresh_orders = []
            for p in range(1, 4):
                write_progress('syncing', p, 3, f'正在同步订单…第{p}/3页')
                data = api.order.list(page=p, page_size=128)
                if data and data.get('items'):
                    fresh_orders.extend(data['items'])
                else:
                    break
            if fresh_orders:
                april_orders = [o for o in fresh_orders if (o.get('creationTime') or '').startswith(('2026-04', '2026-4'))]
                may_orders = [o for o in fresh_orders if (o.get('creationTime') or '').startswith(('2026-05', '2026-5'))]
                if april_orders:
                    bulk_upsert_orders(april_orders, month='april')
                if may_orders:
                    bulk_upsert_orders(may_orders, month='may')
        except Exception as e:
            pass

        # ── 第2步：获取本地（已同步最新）的订单 ──
        orders = get_orders(month, sender)

        if not orders:
            write_progress('done', 100, 100, '没有订单需要更新', done=True)
            return {'ok': True, 'message': '没有订单', 'updated': 0}

        # 过滤掉已签收的订单，只保留需要更新的
        write_progress('preparing', 0, 1, '正在筛选待查询运单…')
        to_update = []
        for o in orders:
            sn = o.get('sn', '')
            state = o.get('state')
            gw = o.get('global_waybill_sn', '')
            # 跳过已签收的订单(state=5)和已作废的(state=-6)
            if sn and state not in (5, -6, '5', '-6'):
                to_update.append({
                    'sn': sn, 
                    'gw': gw, 
                    'current_state': state,
                    'ext_no': o.get('temp_line_sn', '')
                })

        if not to_update:
            write_progress('done', 100, 100, '所有订单都已签收', done=True)
            return {'ok': True, 'message': '所有订单都已签收', 'updated': 0}

        # ⭐ 额外过滤：跳过 tracking 表中已标记"已签收"的运单（避免重复查询）
        try:
            db_check = sqlite3.connect(DB_PATH)
            signed_gws = set()
            for row in db_check.execute(
                "SELECT tracking_no FROM tracking WHERE month=? AND (current_status LIKE '%签收%' OR current_status LIKE '%完成%')",
                (month,)
            ):
                signed_gws.add(row[0])
            db_check.close()
            before = len(to_update)
            to_update = [item for item in to_update if item.get('gw') not in signed_gws]
            skipped = before - len(to_update)
            if skipped:
                write_progress('preparing', 0, 1, f'跳过已签收 {skipped} 条，待查询 {len(to_update)} 条')
        except Exception:
            pass  # 不影响主流程

        if not to_update:
            write_progress('done', 100, 100, '所有运单轨迹已签收，无需更新', done=True)
            return {'ok': True, 'message': '所有运单轨迹已签收', 'updated': 0}

        write_progress('tracking', 0, len(to_update), f'准备查询 {len(to_update)} 条轨迹…')

        CHUNK_SIZE = 300
        THREADS = 8

        # ── 第3步：后台线程批量轨迹查询 ──
        def _do_batch_track(to_update_list, month_name):
            global _batch_in_progress
            try:
                from heute_api import HeuteAPI
                tracker = HeuteAPI()
                total = len(to_update_list)

                gw_items = [(item['sn'], item['gw']) for item in to_update_list if item.get('gw')]
                gw_list = [gw for _, gw in gw_items]
                sn_map = {gw: sn for sn, gw in gw_items}

                if not gw_list:
                    write_progress('done', 0, 0, '没有需要查询的国际单号', done=True)
                    return

                db = sqlite3.connect(DB_PATH)
                upserted = 0
                chunk_count = (len(gw_list) + CHUNK_SIZE - 1) // CHUNK_SIZE

                for chunk_idx in range(chunk_count):
                    start = chunk_idx * CHUNK_SIZE
                    chunk = gw_list[start:start + CHUNK_SIZE]
                    chunk_sn_map = {gw: sn_map[gw] for gw in chunk if gw in sn_map}
                    chunk_offset = start

                    ok_count = 0
                    fail_count = 0
                    def _progress(done_in_chunk, total_in_chunk, ok, fail):
                        nonlocal ok_count, fail_count
                        ok_count = ok
                        fail_count = fail
                        total_done = chunk_offset + done_in_chunk
                        write_progress('tracking', total_done, len(gw_list),
                            f'轨迹查询 {total_done}/{len(gw_list)} (成功{ok+upserted}, 失败{fail})')

                    results = tracker.track.batch_query(chunk, threads=THREADS, progress_cb=_progress)

                    for gw, result in results.items():
                        if result and result.get('trackingNo'):
                            try:
                                upsert_tracking(
                                    db, gw, month_name, result,
                                    order_info={'sn': chunk_sn_map.get(gw, '')}
                                )
                                upserted += 1
                            except Exception:
                                pass
                    db.commit()

                db.close()
                write_progress('done', len(gw_list), len(gw_list),
                    f'更新完成: 查询{len(gw_list)}条, 入库{upserted}条, 失败{len(gw_list)-upserted}条',
                    done=True)
            finally:
                with _batch_lock:
                    _batch_in_progress = False

        t = threading.Thread(target=_do_batch_track, args=(to_update, month), daemon=True)
        t.start()
        return {
            'ok': True,
            'message': f'已启动后台批量更新{month}月轨迹（共{len(to_update)}条未更新），完成后自动写入数据库，请稍后刷新查看',
            'month': month,
            'total': len(to_update),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        # 如果在前台阶段抛出异常，释放锁（后台线程有自己独立的finally）
        pass

# ─── 快递100企业版API ─────────────────────────────────────────────────────
KD100_KEY = "tufqlXgA2928"
KD100_CUSTOMER = "E26E983AE77169477938606B043C5494"

def _live_kuaidi100(biz_no: str) -> Optional[dict]:
    if not biz_no:
        return None
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
                'https://poll.kuaidi100.com/poll/query.do', data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'})
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read())
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

def _query_domestic(ext_no: str, phone: str = '') -> Optional[dict]:
    if not ext_no:
        return None
    prefix = ext_no[:2].upper() if len(ext_no) >= 2 else ''
    if prefix == 'JD':
        return _live_kuaidi100(ext_no)
    elif prefix == 'SF':
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
    # SQLite字段 → 前端期望的camelCase映射（无论快递100启用与否都要做）
    tracking["currentStatus"] = tracking.get("current_status", "")
    tracking["latestDesc"] = tracking.get("latest_desc", "")
    tracking["latestTime"] = tracking.get("latest_time", "")
    toggle = load_kuaidi100_toggle()
    if not toggle.get('enabled', False):
        return result
    biz_no = tracking.get("tracking_no", "") or order.get("tempLineSN", "") or tracking.get("ext_track_no_cn", "")
    if not biz_no:
        return result
    kd = _live_kuaidi100(biz_no)
    if not kd:
        time.sleep(1)
        kd = _live_kuaidi100(biz_no)
    if not kd:
        return result
    tracking["currentStatus"] = kd.get("currentStatus", tracking.get("current_status", ""))
    tracking["_source"] = kd.get("_source", "kuaidi100_enterprise")
    tracking["latestDesc"] = kd.get("latestDesc", "")
    tracking["latestTime"] = kd.get("latestTime", "")
    if kd.get("trackingDetails"):
        tracking["trackingDetails"] = kd["trackingDetails"]
    ext_no = tracking.get("ext_track_no_cn", "")
    if ext_no and ext_no != biz_no:
        phone = ''
        order_sn = order.get('sn', '')
        if order_sn:
            for m in ('april', 'may'):
                o_list = get_orders(m)
                for o in o_list:
                    if o.get('sn') == order_sn:
                        phone = o.get('consignee_tel', '')
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
            intl_status = tracking.get("currentStatus", "")
            dom_status = dom_summary["currentStatus"]
            SEVERE_INTL = {'在途', '派件', '清关', '揽收', '其他', '离开', '到达', '未知', ''}
            if intl_status == dom_status:
                dom_summary["match"] = "ok"
            elif dom_status == "签收" and intl_status in SEVERE_INTL:
                dom_summary["match"] = "severe"
            elif intl_status != dom_status:
                dom_summary["match"] = "warning"
            else:
                dom_summary["match"] = "ok"
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
            if dom_summary.get("match") == "severe":
                diff = dom_summary.get("timeDiffHours", 0)
                if diff > 6:
                    dom_time_short = dom_time[:16] if dom_time else ""
                    tracking["currentStatus"] = "签收(国内确认)"
                    tracking["latestDesc"] = f"[国内{dom_time_short}确认签收] {dom_summary.get('latestDesc', '')}"
                    tracking["latestTime"] = dom_time
                    dom_summary["autoCorrected"] = True
            tracking["domesticComparison"] = dom_summary
    # 改善状态名：笼统的"其他"→提取城市名
    cur = tracking.get("currentStatus", tracking.get("current_status", ""))
    desc = tracking.get("latestDesc", tracking.get("latest_desc", ""))
    if cur and desc:
        better = _better_status_name(cur, desc)
        if better != cur:
            tracking["currentStatus"] = better
    return result


# ─── 财务 API ────────────────────────────────────────────────────────────

@app.get('/api/finance')
def get_finance(request: Request, month: str = Query('may', pattern='^(april|may)$')):
    sender = get_sender_from_session(request)
    return filter_finance_by_sender(load_finance(month), month, sender)

@app.post('/api/finance/refresh')
def refresh_finance(request: Request, month: str = Query('may', pattern='^(april|may)$')):
    """重新拉取称重补款数据，更新CSV"""
    from heute_api import HeuteAPI, FinanceClient
    sender = get_sender_from_session(request)
    if sender is not None and sender == '':
        raise HTTPException(401, '请重新登录')
    
    # 确定月份范围
    if month == 'april':
        start, end, prefix = '2026-04-01', datetime.now().strftime('%Y-%m-%d'), '2026-04'
    else:
        start, end, prefix = '2026-05-01', datetime.now().strftime('%Y-%m-%d'), '2026-05'
    
    try:
        api = HeuteAPI()
        api.order.login()
        items = api.finance.fetch_money_logs(start, end)
        csv_path = os.path.join(DATA_DIR, f'{month}_2026_weight_surcharge.csv')
        month_items = FinanceClient.generate_surcharge_csv(items, csv_path, prefix)
        
        # 清除缓存
        FINANCE_CACHE.pop(f'finance_{month}', None)
        
        total_money = sum(i.get('moneyChanged', 0) for i in month_items) / 100
        return {
            'ok': True,
            'count': len(month_items),
            'total': round(total_money, 2),
            'message': f'更新完成: {len(month_items)}条, 总额{total_money:.2f}元'
        }
    except Exception as e:
        raise HTTPException(500, f'财务数据更新失败: {e}')

@app.get('/api/finance/daily-detail')
def get_finance_daily_detail(
    request: Request,
    date: str = Query(None),
    month: str = Query('may', pattern='^(april|may)$')
):
    """今日 vs 昨日对比 + 每笔明细"""
    sender = get_sender_from_session(request)
    today_str = date or datetime.now().strftime('%Y-%m-%d')
    today_dt = datetime.strptime(today_str, '%Y-%m-%d')
    yesterday_str = (today_dt - timedelta(days=1)).strftime('%Y-%m-%d')

    cache = load_product_cache()
    path = _month_path(month, 'surcharge')
    if not os.path.exists(path):
        return {'today': None, 'yesterday': None}

    orders = get_orders(month)
    sender_sns = set()
    if sender:
        for o in orders:
            if o.get('sender_name', '') == sender and o.get('sn'):
                sender_sns.add(o['sn'])

    today_rows, yesterday_rows = [], []
    with open(path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            oid = row['订单号']
            if sender and oid not in sender_sns:
                continue
            d = row['时间'][:10]
            if d == today_str:
                today_rows.append(row)
            elif d == yesterday_str:
                yesterday_rows.append(row)

    def build(rows):
        if not rows:
            return {'date': '', 'amount': 0, 'count': 0, 'records': []}
        total = sum(float(r['金额(元)']) for r in rows)
        items = []
        for r in sorted(rows, key=lambda x: x['订单号']):
            oid = r['订单号']
            pinfo = cache.get(oid, {})
            name = '未知产品'
            if isinstance(pinfo, dict):
                names = pinfo.get('product_names', [])
                if names:
                    name = names[0]
                else:
                    prods = pinfo.get('products', [])
                    if prods and isinstance(prods, list):
                        name = (prods[0].get('name', '') or '未知产品')
            items.append({
                'time': r['时间'][11:19],
                'order_sn': oid,
                'amount': float(r['金额(元)']),
                'product': name,
            })
        return {'amount': round(total, 2), 'count': len(rows), 'records': items}

    return {
        'today': {'date': today_str, **build(today_rows)},
        'yesterday': {'date': yesterday_str, **build(yesterday_rows)},
    }

PRODUCT_CACHE_PATH = os.path.join(DATA_DIR, 'product_cache.json')

def load_product_cache():
    if os.path.exists(PRODUCT_CACHE_PATH):
        try:
            with open(PRODUCT_CACHE_PATH) as f:
                return json.load(f)
        except:
            return {}
    return {}

@app.get('/api/finance/by-product')
def get_finance_by_product(request: Request, month: str = Query('may', pattern='^(april|may)$')):
    sender = get_sender_from_session(request)
    cache = load_product_cache()
    surcharge_path = _month_path(month, 'surcharge')
    if not os.path.exists(surcharge_path):
        return {'products': [], 'cached': len(cache), 'total_orders': 0}
    orders = get_orders(month)
    sender_sns = set()
    if sender:
        for o in orders:
            if o.get('sender_name', '') == sender:
                sn = o.get('sn', '')
                if sn:
                    sender_sns.add(sn)
    import csv
    by_product = defaultdict(lambda: {'count': 0, 'amount': 0.0,
        'orders': defaultdict(lambda: {'count': 0, 'amount': 0.0, 'records': []})})
    total_records = 0
    with open(surcharge_path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            oid = row['订单号']
            if sender and oid not in sender_sns:
                continue
            amt = float(row['金额(元)'])
            total_records += 1
            product_info = cache.get(oid, {})
            name = '未知产品'
            if isinstance(product_info, dict):
                names = product_info.get('product_names', [])
                if names:
                    name = names[0]
                else:
                    prods = product_info.get('products', [])
                    if prods and isinstance(prods, list):
                        name = prods[0].get('name', '') or '未知产品'
            if '待加载' in name:
                name = '待加载...'
            by_product[name]['count'] += 1
            by_product[name]['amount'] += amt
            by_product[name]['orders'][oid]['count'] += 1
            by_product[name]['orders'][oid]['amount'] += amt
    products = []
    for name, data in sorted(by_product.items(), key=lambda x: -x[1]['amount']):
        order_list = [{'order_sn': oid, 'count': v['count'], 'amount': round(v['amount'], 2)}
                       for oid, v in data['orders'].items()]
        products.append({
            'name': name,
            'count': data['count'],
            'amount': round(data['amount'], 2),
            'orders': order_list,
        })
    pending = total_records - sum(len(data['orders']) for data in by_product.values())
    return {'products': products, 'cached': len(cache), 'total_orders': total_records,
            'pending': max(0, pending)}

@app.get('/api/finance/overweight')
def get_overweight(request: Request, month: str = Query('may', pattern='^(april|may)$')):
    """产品超重分析"""
    cache = load_product_cache()
    surcharge_path = _month_path(month, 'surcharge')
    if not os.path.exists(surcharge_path):
        return {'products': []}
    orders = get_orders(month)
    order_weight = {}
    for o in orders:
        order_weight[o['sn']] = o.get('weight', 0)
    import csv
    product_data = defaultdict(lambda: {'order_count': set(), 'surcharge_count': 0, 'surcharge_amount': 0.0, 'total_weight': 0.0})
    with open(surcharge_path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            oid = row['订单号']
            amt = float(row['金额(元)'])
            product_info = cache.get(oid, {})
            name = '未知产品'
            if isinstance(product_info, dict):
                names = product_info.get('product_names', [])
                if names:
                    name = names[0]
                else:
                    prods = product_info.get('products', [])
                    if prods and isinstance(prods, list):
                        name = prods[0].get('name', '') or '未知产品'
            if '待加载' in name:
                name = '待加载...'
            product_data[name]['order_count'].add(oid)
            product_data[name]['surcharge_count'] += 1
            product_data[name]['surcharge_amount'] += amt
            product_data[name]['total_weight'] += order_weight.get(oid, 0)
    products = []
    for name, data in sorted(product_data.items(), key=lambda x: -x[1]['surcharge_amount']):
        n = len(data['order_count'])
        avg_weight = round(data['total_weight'] / n / 1000, 2) if n > 0 else 0
        products.append({
            'name': name,
            'order_count': n,
            'surcharge_count': data['surcharge_count'],
            'surcharge_amount': round(data['surcharge_amount'], 2),
            'avg_weight_kg': avg_weight,
            'surcharge_rate': round(data['surcharge_count'] / n * 100, 1) if n > 0 else 0,
            'suggestion': '建议拆分' if avg_weight > 2.0 else ('关注' if avg_weight > 1.5 else '正常'),
        })
    return {'products': products}

@app.get('/api/overweight/orders')
def get_overweight_orders(request: Request, month: str = Query('may', pattern='^(april|may)$'),
                           page: int = Query(1, ge=1), per_page: int = Query(50, le=200)):
    """包裹重量明细（含产品名/收件人/线路/补款统计）"""
    surcharge_path = _month_path(month, 'surcharge')
    if not os.path.exists(surcharge_path):
        return {'items': [], 'total': 0}
    import csv
    from collections import defaultdict
    # 按订单号分组补款记录
    by_order = defaultdict(lambda: {'count': 0, 'amount': 0.0, 'records': []})
    with open(surcharge_path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            oid = row['订单号']
            amt = float(row['金额(元)'])
            by_order[oid]['count'] += 1
            by_order[oid]['amount'] += amt
            by_order[oid]['records'].append({
                'time': row['时间'], 'amount': amt, 'desc': row.get('描述', '')
            })
    # 获取订单数据和产品缓存
    orders = get_orders(month)
    orders_by_sn = {o.get('sn', ''): o for o in orders if o.get('sn')}
    cache = load_product_cache()
    sender = get_sender_from_session(request)
    items = []
    for oid, odata in by_order.items():
        if sender:
            order = orders_by_sn.get(oid, {})
            if order.get('sender_name', '') != sender:
                continue
        product_name = ''
        if oid in cache:
            entry = cache[oid]
            if isinstance(entry, dict):
                names = entry.get('product_names', [])
                if names:
                    product_name = names[0]
                else:
                    prods = entry.get('products', [])
                    if prods and isinstance(prods, list):
                        product_name = prods[0].get('name', '')
        if not product_name and oid in orders_by_sn:
            # 从订单的 products 列表取第一个
            prods = orders_by_sn[oid].get('products', [])
            if prods and isinstance(prods, list):
                product_name = prods[0].get('goods_name', '')
        order = orders_by_sn.get(oid, {})
        weight_g = order.get('weight', 0) or 0
        items.append({
            'order_sn': oid,
            'product_name': product_name,
            'weight_g': weight_g,
            'weight_kg': round(weight_g / 1000, 1) if weight_g else 0,
            'consignee': order.get('consignee_name', ''),
            'line': order.get('line_name', ''),
            'sender': order.get('sender_name', ''),
            'state_name': order.get('state_name', ''),
            'created': order.get('created', ''),
            'surcharge_count': odata['count'],
            'total_surcharge': round(odata['amount'], 2),
            'has_surcharge': True,
            'surcharges': odata['records'],
        })
    # 有补款的排前，同组按重量降序
    items.sort(key=lambda x: (0 if x['has_surcharge'] else 1, -(x['weight_g'] or 0)))
    total = len(items)
    start = (page - 1) * per_page
    return {'items': items[start:start + per_page], 'total': total}

@app.get('/api/order/{sn}')
def get_order_detail(sn: str, month: str = Query('may', pattern='^(april|may)$')):
    """获取订单详情（含产品明细）"""
    orders = get_orders(month)
    order = None
    for o in orders:
        if o.get('sn') == sn:
            order = o
            break
    if not order:
        raise HTTPException(404, f'订单 {sn} 未找到')
    detail = {}
    try:
        from heute_api import HeuteAPI
        api = HeuteAPI()
        detail = api.order.detail(sn)
        # 货易达API直接返回订单数据（无data包装）
        if not detail.get('error') and detail.get('sn'):
            pass  # detail 已可用
    except Exception:
        pass
    result = {
        'sn': order.get('sn'),
        'state': order.get('state'),
        'state_name': format_state(order.get('state')),
        'line_name': order.get('line_name', ''),
        'weight': order.get('weight', 0),
        'weight_kg': f"{(order.get('weight') or 0)/1000:.1f}",
        'created': (order.get('creation_time','')[:19]).replace('T',' '),
        'sender_name': order.get('sender_name',''),
        'sender_tel': order.get('sender_tel',''),
        'consignee_name': order.get('consignee_name',''),
        'consignee_tel': order.get('consignee_tel',''),
        'consignee_id': order.get('consignee_id',''),
        'consignee_province': order.get('consignee_province',''),
        'consignee_city': order.get('consignee_city',''),
        'consignee_county': order.get('consignee_county',''),
        'consignee_address': order.get('consignee_address',''),
        'global_waybill': order.get('global_waybill_sn',''),
        'temp_line_sn': order.get('temp_line_sn',''),
        'merchant_order_sn': order.get('merchant_order_sn',''),
        'platform_sn': order.get('platform_sn',''),
        'id_card_status': order.get('id_card_info_status', -1),
        'money_estimate': (order.get('money_estimate') or 0) / 100,
        'money_final': (order.get('money_final') or 0) / 100,
        'fee_ship': (order.get('fee_ship') or 0) / 100,
        'fee_customs': (order.get('fee_customs') or 0) / 100,
        'fee_insurance': (order.get('fee_insurance') or 0) / 100,
    }
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

# ─── After-Sales API ──────────────────────────────────────────────────────

# 货易达track API 凭证（实时回退用）
_TRACK_API_URL = 'https://track.heute-express.com/api'
_TRACK_TOKEN_FILE = '/tmp/heute_dashboard_track_token.json'


def _better_status_name(status_name: str, status_text: str) -> str:
    """物流状态归一化映射：把API原始状态+描述合并为5个清晰阶段"""
    
    # ✅ 1. 已签收
    if status_name in ('已签收', '签收(国内确认)', '签收'):
        return '✅ 已签收'
    
    # 2. 根据状态名和描述综合判断
    desc = (status_text or '').lower()
    
    # 🛃 清关
    if status_name == '清关中' or '清关' in desc or '海关' in desc or '口岸' in desc:
        return '🛃 清关中'
    
    # 📦 待出库 — 运单已创建但未实际发出
    if status_name == '运单已经创建':
        return '📦 待出库'
    
    # ✈️ 国际运输 — 关键词：机场、航班、起飞、国际
    if '机场' in desc or '航班' in desc or '起飞' in desc or '国际' in desc:
        return '✈️ 国际运输'
    
    # 🚚 国内配送 — 关键词：派送、配送、派件、快递员、丰巢、投递
    if any(kw in desc for kw in ('派送', '配送', '派件', '快递员', '丰巢', '投递', '送达', '签收人')):
        return '🚚 国内配送'
    
    # 🔄 从【】提取城市名作为位置提示
    if status_text:
        import re
        m = re.search(r'【(.+?)】', status_text)
        if m:
            loc = m.group(1)
            if '电话' in loc or '手机' in loc or re.search(r'\d{11}', loc):
                return status_name or '未知'
            return loc
    
    return status_name or '未知'


def _track_api_login():
    """登录 track API，返回 Bearer Token"""
    now = time.time()
    if os.path.exists(_TRACK_TOKEN_FILE):
        try:
            with open(_TRACK_TOKEN_FILE) as f:
                cached = json.load(f)
            if cached.get('expires_at', 0) > now + 120:
                return cached['token']
        except Exception:
            pass
    try:
        cmd = [
            'curl', '-s', '--max-time', '15',
            '-X', 'POST',
            '-H', 'Content-Type: application/json',
            '-d', '{"username":"admin","password":"Hyd@6ytg19"}',
            'https://track.heute-express.com/api/auth/login',
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
        token = data.get('data', {}).get('accessToken', '')
        if token:
            expires_in = data.get('data', {}).get('expiresIn', 3600)
            with open(_TRACK_TOKEN_FILE, 'w') as f:
                json.dump({'token': token, 'expires_at': now + expires_in}, f)
            return token
    except Exception:
        pass
    return ''


def _track_api_query(tracking_no: str) -> dict:
    """实时查询track API，返回 {trackingNo, extTrackNoCn, currentStatus, latestDesc}"""
    token = _track_api_login()
    if not token:
        return {}
    try:
        url = f'{_TRACK_API_URL}/tracking?trackingNo={urllib.parse.quote(tracking_no)}&page=1&pageSize=1'
        cmd = ['curl', '-s', '--max-time', '15', '-H', f'Authorization: Bearer {token}', url]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
        records = data.get('data', {}).get('records', [])
        if not records:
            records = data.get('records', [])
        if records:
            rec = records[0]
            return {
                'tracking_no': rec.get('trackingNo', ''),
                'domestic_no': rec.get('extTrackNoCn', ''),
                'status_name': rec.get('platformTrackingStatusName', ''),
                'status_text': rec.get('platformTrackingStatusText', ''),
            }
    except Exception:
        pass
    return {}


# ─── 共享匹配函数 ────────────────────────────────────────────────────────────

def _resolve_tracking_match(tn: str) -> Optional[dict]:
    """共享匹配函数：本地SQL查找 + track API实时回退，返回值同 lookup_order_by_tracking 格式，含 track_api 标记"""
    tn = tn.strip()
    if not tn:
        return None
    # 1. 本地SQL查询（orders 表，国际/国内双索引，毫秒级）
    match = lookup_order_by_tracking(tn)
    if match:
        return match
    # 2. 本地查不到 → 实时调track API验证（仅国际单号有效）
    track = _track_api_query(tn)
    if track:
        return {
            'gw': track.get('tracking_no', ''),
            'ts': track.get('domestic_no', ''),
            'sender': '',
            'sn': '',
            'track_api': True,
        }
    return None


@app.get('/api/after-sales/lookup-tracking')
def api_lookup_tracking(tracking_no: str = Query(...)):
    """实时查找运单号对应的国际单号/寄件人等信息（本地SQL + track API实时回退）"""
    match = _resolve_tracking_match(tracking_no)
    if match:
        result = {
            'matched': True,
            'intl_tracking_no': match['gw'],
            'domestic_tracking_no': match['ts'],
            'sender_name': match['sender'],
            'order_sn': match['sn'],
        }
        if match.get('track_api'):
            result['track_api'] = True
        return result
    return {'matched': False}


@app.post('/api/after-sales')
def api_create_after_sales(data: dict = Body(...)):
    """创建售后记录，自动匹配寄件人 + 单号交叉补全"""
    try:
        tn = (data.get('tracking_no') or '').strip()
        # 安全清洗：防止前端传 'undefined' 字符串
        for key in ('order_sn', 'sender_name', 'intl_tracking_no', 'domestic_tracking_no', 'contact_info'):
            if data.get(key) in (None, '', 'undefined', 'null'):
                data.pop(key, None)
        if tn and (not data.get('sender_name') or not data.get('intl_tracking_no')
                   or not data.get('domestic_tracking_no') or not data.get('order_sn')):
            match = _resolve_tracking_match(tn)
            if match:
                if not data.get('sender_name'):
                    data['sender_name'] = match['sender']
                if not data.get('order_sn'):
                    data['order_sn'] = match['sn']
                # 输入的是国际号 → 补国内号
                if match['gw'] and match['gw'] == tn:
                    if not data.get('domestic_tracking_no') and match['ts']:
                        data['domestic_tracking_no'] = match['ts']
                    if not data.get('intl_tracking_no'):
                        data['intl_tracking_no'] = match['gw']
                # 输入的是国内号 → 补国际号
                elif match['ts'] == tn:
                    if not data.get('intl_tracking_no'):
                        data['intl_tracking_no'] = match['gw']
                    if not data.get('domestic_tracking_no'):
                        data['domestic_tracking_no'] = match['ts']
                # 查询到了但输入既不是国际也不是国内（track API回退场景）
                else:
                    if not data.get('intl_tracking_no') and match['gw']:
                        data['intl_tracking_no'] = match['gw']
                    if not data.get('domestic_tracking_no') and match['ts']:
                        data['domestic_tracking_no'] = match['ts']
            # 不匹配时直接存原始值，不做启发式判断

        aid = create_after_sales(data)
        return {'ok': True, 'id': aid}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get('/api/after-sales')
def api_get_after_sales(request: Request,
                         month: str = Query('may', pattern='^(april|may|all)$'),
                         status: Optional[str] = None,
                         sender: Optional[str] = None,
                         q: Optional[str] = None,
                         page: int = Query(1, ge=1),
                         per_page: int = Query(50, le=200)):
    """查询售后记录（自动按登录寄件人隔离），支持 q= 搜索"""
    # 搜索模式 → 不用分页和月份过滤，直接搜全部
    if q and q.strip():
        logged_sender = get_sender_from_session(request)
        items, total = search_after_sales(q.strip(), page=page, per_page=per_page, sender=logged_sender)
        return {'items': items, 'total': total, 'page': page, 'per_page': per_page, 'search_mode': True}
    # 寄件人登录 → 只看自己的
    logged_sender = get_sender_from_session(request)
    if logged_sender:
        sender = logged_sender
    items, total = get_after_sales(month, status, sender, page, per_page)
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}

@app.get('/api/after-sales/stats')
def api_after_sales_stats(request: Request, month: str = Query('may', pattern='^(april|may|all)$')):
    """售后统计（自动按登录寄件人隔离）"""
    sender = get_sender_from_session(request)
    if sender:
        items, _ = get_after_sales(month, sender=sender, page=1, per_page=99999)
        by_status = {}
        by_type = {}
        for item in items:
            s = item.get('status', '')
            t = item.get('issue_type', '')
            by_status[s] = by_status.get(s, 0) + 1
            if t:
                by_type[t] = by_type.get(t, 0) + 1
        return {'total': len(items), 'by_status': by_status, 'by_type': by_type}
    return get_after_sales_stats(month)

@app.patch('/api/after-sales/{after_id}')
def api_update_after_sales(request: Request, after_id: int, data: dict):
    """更新售后记录（寄件人只能改自己的）"""
    # 非管理员只允许改自己的记录
    sender = get_sender_from_session(request)
    if sender:
        items, _ = get_after_sales('all', sender=sender, page=1, per_page=99999)
        own_ids = {i['id'] for i in items}
        if after_id not in own_ids:
            raise HTTPException(403, '只能操作自己的售后记录')
    ok = update_after_sales(after_id, data)
    if not ok:
        raise HTTPException(404, '售后记录不存在或未更新')
    return {'ok': True}

@app.delete('/api/after-sales/{after_id}')
def api_delete_after_sales(request: Request, after_id: int):
    """删除售后记录（寄件人只能删自己的）"""
    sender = get_sender_from_session(request)
    if sender:
        items, _ = get_after_sales('all', sender=sender, page=1, per_page=99999)
        own_ids = {i['id'] for i in items}
        if after_id not in own_ids:
            raise HTTPException(403, '只能操作自己的售后记录')
    ok = delete_after_sales(after_id)
    if not ok:
        raise HTTPException(404, '售后记录不存在')
    return {'ok': True}

# ─── 系统API ──────────────────────────────────────────────────────────────
@app.get('/api')
def api_root():
    return {'name': '货易达物流看板 API (SQLite)', 'version': '2.0', 'endpoints': [
        '/api/stats', '/api/orders/recent', '/api/tracking/results',
        '/api/tracking/{no}', '/api/tracking/search?q=', '/api/order/{sn}'
    ]}

# ─── 前端 SPA ──────────────────────────────────────────────────────────────
@app.get('/', response_class=HTMLResponse)
def index():
    path = os.path.join(BASE_DIR, 'templates', 'index.html')
    if os.path.exists(path):
        from fastapi.responses import HTMLResponse
        with open(path, encoding='utf-8') as f:
            content = f.read()
        return HTMLResponse(content=content, headers={'Cache-Control': 'no-cache, no-store, must-revalidate'})
    return HTMLResponse('<h1>404 Not Found</h1>', status_code=404)

@app.get('/favicon.ico')
def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)  # 无图标，静默

# ─── 启动 ──────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import socket
    host = '0.0.0.0'
    port = int(os.environ.get('DASHBOARD_PORT', '8892'))
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = '127.0.0.1'
    print(f'📊 货易达物流看板 (SQLite)')
    print(f'   Local:   http://127.0.0.1:{port}')
    print(f'   Network: http://{local_ip}:{port}')
    print(f'   Docs:    http://{local_ip}:{port}/docs')
    # 快速验证
    from heute_db import get_month_overview
    for m in ('april', 'may'):
        s = get_month_overview(m)
        print(f'   {m}: {s["orders"]}单, {s["tracked"]}轨迹, {s["signed"]}签收')
    print()
    uvicorn.run(app, host=host, port=port)
