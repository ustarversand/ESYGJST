"""直邮管家 — 货易达主站 API 客户端

直接调用 www.heute-express.com API，支持：
- 按商家订单号(merchantOrderSN)精确查询
- 自动 Token 管理（从共享文件读取或用密码登录）
"""
import json
import time
import os
import ssl
import urllib.request
import urllib.error
import logging

logger = logging.getLogger("heuste-sdk")

BASE_URL = "https://www.heute-express.com"
API_PREFIX = "/Prod/api/app"
LOGIN_URL = f"{BASE_URL}{API_PREFIX}/token/login"
ORDER_LIST_URL = f"{BASE_URL}{API_PREFIX}/member-order/get-member-order-list"

# 货易达轨迹查询系统 (track.heute-express.com)
TRACK_BASE_URL = "https://track.heute-express.com"
TRACK_LOGIN_URL = f"{TRACK_BASE_URL}/api/auth/login"
TRACK_QUERY_URL = f"{TRACK_BASE_URL}/api/tracking"

# USTAR 货易达登录凭据（优先用环境变量）
HEUTE_USERNAME = os.getenv("HEUTE_USERNAME", "USTAR")
HEUTE_PASSWORD = os.getenv("HEUTE_PASSWORD", "Hilden11031980!")

# 轨迹管理系统登录凭据（优先用环境变量）
TRACK_USERNAME = os.getenv("TRACK_USERNAME", "admin")
TRACK_PASSWORD = os.getenv("TRACK_PASSWORD", "Hyd@6ytg19")

# Token 缓存文件路径（容器内）
_TOKEN_FILE = os.path.join(os.path.dirname(__file__), "data", ".heute_token")
_TRACK_TOKEN_FILE = os.path.join(os.path.dirname(__file__), "data", ".track_token")


def _http_post(url: str, data: dict, headers: dict = None, timeout: int = 15) -> dict:
    """POST JSON 请求"""
    if headers is None:
        headers = {}
    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning(f"[货易达] HTTP {e.code}: {body[:200]}")
        raise
    except Exception as e:
        logger.warning(f"[货易达] 请求失败: {e}")
        raise


def login() -> str:
    """登录货易达，返回 Bearer Token"""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/login",
    }
    data = {"name": HEUTE_USERNAME, "password": HEUTE_PASSWORD}
    result = _http_post(LOGIN_URL, data, headers, timeout=15)
    token = result.get("token")
    if not token:
        raise Exception(f"登录失败: {json.dumps(result, ensure_ascii=False)[:200]}")
    # 缓存 token
    try:
        os.makedirs(os.path.dirname(_TOKEN_FILE), exist_ok=True)
        with open(_TOKEN_FILE, "w") as f:
            f.write(token)
    except Exception:
        pass
    logger.info("[货易达] 登录成功")
    return token


def get_token() -> str:
    """获取有效 Token（从缓存或重新登录）"""
    # 尝试从缓存文件读取
    if os.path.exists(_TOKEN_FILE):
        try:
            with open(_TOKEN_FILE) as f:
                token = f.read().strip()
            if token:
                return token
        except Exception:
            pass
    # 重新登录
    return login()


def search_by_merchant_sn(sn: str) -> dict:
    """按商家订单号(merchantOrderSN)精确查询货易达订单

    Returns:
        {"found": bool, "order": {...}} or {"found": False}
    """
    try:
        token = get_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Referer": f"{BASE_URL}/members/order-list",
            "Origin": BASE_URL,
        }
        payload = {
            "pageIndex": 1,
            "pageSize": 10,
            "merchantOrderSN": sn.strip(),
        }
        result = _http_post(ORDER_LIST_URL, payload, headers, timeout=15)
        items = result.get("items", [])
        if items:
            o = items[0]
            return {
                "found": True,
                "sn": o.get("sn", ""),
                "merchant_sn": o.get("merchantOrderSN", ""),
                "consignee": o.get("consigneeName", ""),
                "tracking_no": o.get("globalWayBillSN", ""),
                "domestic_no": o.get("tempLineSN", ""),
                "state_code": o.get("state", 0),
                "state": _format_state(o.get("state", 0)),
                "line": o.get("lineName", ""),
                "sender": o.get("senderName", ""),
                "weight": o.get("weight", ""),
                "created": o.get("creationTime", ""),
            }
        return {"found": False, "sn": sn}
    except Exception as e:
        logger.warning(f"[货易达] merchant_sn查询失败: {e}")
        return {"found": False, "sn": sn, "error": str(e)}


def _format_state(state_code) -> str:
    states = {0: "已作废", 1: "待支付", 2: "待入库", 3: "国际运输",
              4: "顺丰待揽收", 5: "签收"}
    return states.get(state_code, f"未知({state_code})")


# ─── 轨迹查询模块 (track.heute-express.com) ──────────────────────────

def _track_http_get(url: str, headers: dict = None, timeout: int = 15) -> dict:
    """GET JSON 请求（用 urllib，会被 Cloudflare 拦截，备用 curl）"""
    import subprocess
    if headers is None:
        headers = {}
    header_args = []
    for k, v in headers.items():
        header_args.extend(["-H", f"{k}: {v}"])
    cmd = ["curl", "-s", "--max-time", str(timeout)] + header_args + [url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return {}


def track_login() -> str:
    """登录轨迹管理系统，返回 JWT Bearer Token"""
    import subprocess
    payload = json.dumps({"username": TRACK_USERNAME, "password": TRACK_PASSWORD})
    cmd = [
        "curl", "-s", "--max-time", "15",
        "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", payload,
        TRACK_LOGIN_URL,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        data = json.loads(result.stdout)
        token = data.get("data", {}).get("accessToken", "")
        if token:
            # 缓存 token
            try:
                os.makedirs(os.path.dirname(_TRACK_TOKEN_FILE), exist_ok=True)
                with open(_TRACK_TOKEN_FILE, "w") as f:
                    f.write(token)
            except Exception:
                pass
            return token
    except Exception as e:
        logger.warning(f"[轨迹] 登录失败: {e}")
    return ""


def get_track_token() -> str:
    """获取轨迹系统 Token（缓存或新登录）"""
    if os.path.exists(_TRACK_TOKEN_FILE):
        try:
            with open(_TRACK_TOKEN_FILE) as f:
                token = f.read().strip()
            if token:
                return token
        except Exception:
            pass
    return track_login()


def query_tracking(tracking_no: str) -> dict:
    """查询单个国际单号的轨迹信息，返回 {city, status_name, status_text, from_city, to_city}
    
    city 优先规则：
    1. 从 statusText 的 【城市名】 提取当前所在地（最准确）
    2. 已签收 → "签收"
    3. 用 fromCity（始发地，包裹当前所在）
    """
    import re
    token = get_track_token()
    if not token:
        return {}
    url = f"{TRACK_QUERY_URL}?trackingNo={tracking_no}&page=1&pageSize=1"
    headers = {"Authorization": f"Bearer {token}"}
    data = _track_http_get(url, headers)
    records = data.get("data", {}).get("records", [])
    if not records:
        records = data.get("records", [])
    if records:
        r = records[0]
        status_name = r.get("platformTrackingStatusName", "")
        status_text = r.get("platformTrackingStatusText", "")
        from_city = r.get("fromCity", "") or ""
        to_city = r.get("toCity", "") or ""
        
        city = ""
        # 规则1: 从 statusText 提取 【城市名】 (最准确的当前所在地)
        m = re.search(r'【(.+?)】', status_text)
        if m:
            city = m.group(1).strip()
        # 规则2: 已签收
        if "签收" in status_name or "已签" in status_name:
            city = "签收"
        # 规则3: 没有 【】 也没有签收 → 用 fromCity（始发地）
        if not city:
            city = from_city
        
        return {
            "city": city,
            "status_name": status_name,
            "status_text": status_text,
            "from_city": from_city,
            "to_city": to_city,
        }
    return {}


def batch_query_tracking(tracking_nos: list) -> dict:
    """并发查询多个国际单号的轨迹，返回 {tracking_no: {city, status_name, ...}}"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    if not tracking_nos:
        return results
    with ThreadPoolExecutor(max_workers=10) as ex:
        fut_map = {ex.submit(query_tracking, tn): tn for tn in tracking_nos}
        for f in as_completed(fut_map):
            tn = fut_map[f]
            try:
                r = f.result()
                if r:
                    results[tn] = r
            except Exception:
                pass
    return results
