#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快递100 实时查询 API 封装

接口: POST https://poll.kuaidi100.com/poll/query.do
签名: MD5(param + key + customer)，32位大写
文档: https://api.kuaidi100.com/product/query
"""

import hashlib
import json
import logging
import time
import urllib.request
import urllib.parse
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# ==================== 配置 ====================
KD100_CONFIG = {
    "key": "tufqlXgA2928",
    "customer": "E26E983AE77169477938606B043C5494",
    "secret": "b6d4e8631c6c43259e5304e799bc22cd",  # 备用
    "endpoint": "https://poll.kuaidi100.com/poll/query.do",
    "timeout": 10,
}

# 快递公司编码（快递100官方编码，小写）
COURIER_CODE_MAP = {
    "京东": "jd",
    "京东快递": "jd",
    "顺丰": "sf",
    "顺丰速运": "sf",
    "圆通": "yuantong",
    "中通": "zhongtong",
    "韵达": "yunda",
    "申通": "shentong",
    "ems": "ems",
    "邮政": "youzheng",
    "菜鸟": "cainiao",
    "极兔": "jtexpress",
    "jtexpress": "jtexpress",
    "jd": "jd",
    "sf": "sf",
}

# 快递100状态码 → 中文
STATE_MAP = {
    "0": "在途",
    "1": "揽收",
    "2": "疑难",
    "3": "签收",
    "4": "退签",
    "5": "派件",
    "6": "退回",
    "7": "转单",
    "10": "待清关",
    "11": "清关中",
    "12": "已清关",
    "13": "清关异常",
    "14": "收件人拒签",
}


def get_courier_code(carrier_name: str) -> str:
    """将快递公司名称转为快递100编码"""
    if not carrier_name:
        return ""
    name = carrier_name.lower().strip()
    return COURIER_CODE_MAP.get(carrier_name, name)


def make_sign(param_json: str, key: str, customer: str) -> str:
    """
    生成签名: MD5(param + key + customer)，32位大写
    param_json: JSON 字符串（不含空格）
    """
    return hashlib.md5((param_json + key + customer).encode()).hexdigest().upper()


def query_tracking(
    num: str,
    com: str = None,
    phone: str = "",
    from_city: str = "",
    to_city: str = "",
    resultv2: int = 1,
    show: int = 0,
    order: str = "desc",
) -> Dict[str, Any]:
    """
    查询快递轨迹

    Args:
        num: 运单号（必填）
        com: 快递公司编码（必填，如 'jd', 'sf'，小写）
              如不传会自动识别
        phone: 收/寄件人电话（部分快递必填）
        from_city: 出发城市
        to_city: 目的地城市
        resultv2: 1=返回完整轨迹+标注，0=仅轨迹
        show: 0=JSON（默认）
        order: desc=降序（最新在前），asc=升序

    Returns:
        {
            "result": True/False,
            "status": "200",
            "state": "0",
            "message": "ok",
            "nu": "运单号",
            "com": "jd",
            "data": [
                {"time": "2026-05-14 22:04:58", "context": "...", "location": "..."},
                ...
            ]
        }
    """
    if not num:
        return {"result": False, "message": "运单号不能为空"}

    # 如果没传 com，尝试从单号判断
    if not com:
        com = _auto_detect_courier(num)
        if not com:
            return {"result": False, "message": "无法识别快递公司编码，请手动传入 com 参数"}

    # 构建 param
    param_obj = {
        "com": com.lower(),
        "num": num,
    }
    if phone:
        param_obj["phone"] = phone
    if from_city:
        param_obj["from"] = from_city
    if to_city:
        param_obj["to"] = to_city
    if resultv2:
        param_obj["resultv2"] = resultv2
    if show:
        param_obj["show"] = show
    if order:
        param_obj["order"] = order

    param_json = json.dumps(param_obj, separators=(",", ":"))

    key = KD100_CONFIG["key"]
    customer = KD100_CONFIG["customer"]
    sign = make_sign(param_json, key, customer)

    # 发送请求
    data = urllib.parse.urlencode({
        "customer": customer,
        "sign": sign,
        "param": param_json,
    }).encode()

    req = urllib.request.Request(
        KD100_CONFIG["endpoint"],
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req, timeout=KD100_CONFIG["timeout"]) as r:
            body = r.read().decode("utf-8", errors="ignore")
            result = json.loads(body)
            # 快递100 成功时 status="200"，不在 result 字段
            # 失败时 result=false 或 status!=200
            if str(result.get("status")) == "200" or result.get("data"):
                result["result"] = True
            else:
                result["result"] = False
            return result
    except Exception as e:
        logger.error(f"快递100 API 请求失败: {e}")
        return {"result": False, "message": str(e)}


def _auto_detect_courier(num: str) -> Optional[str]:
    """根据单号自动判断快递公司（简单版，依赖已知编码）"""
    if not num:
        return None
    num_upper = num.upper()
    # 京东
    if num_upper.startswith("JDV") or num_upper.startswith("JD"):
        return "jd"
    # 顺丰
    if num_upper.startswith("SF"):
        return "sf"
    # 圆通
    if num_upper.startswith("YT"):
        return "yuantong"
    # 中通
    if num_upper.startswith("ZZ"):
        return "zhongtong"
    # 韵达
    if num_upper.startswith("YD"):
        return "yunda"
    # 申通
    if num_upper.startswith("ST"):
        return "shentong"
    # 极兔
    if num_upper.startswith("JT"):
        return "jtexpress"
    # EMS
    if num_upper.startswith("EM"):
        return "ems"
    return None


def format_tracking_text(result: Dict) -> str:
    """把 API 响应格式化为可读文本"""
    # 优先用 status 判断成功
    api_status = str(result.get("status", ""))
    has_data = bool(result.get("data"))

    if not has_data and api_status != "200":
        msg = result.get("message", "查询失败")
        # 友好提示
        friendly_msgs = {
            "查询无结果，请隔段时间再查": "⚠️ 单号暂无轨迹，可能尚未揽收或超出查询范围",
            "快递公司参数异常": "⚠️ 快递公司编码错误，请检查",
        }
        for key, friendly in friendly_msgs.items():
            if key in msg:
                return f"❌ {friendly}\n   原因: {msg}"
        return f"❌ 查询失败: {msg}"

    data = result.get("data", [])
    if not data:
        return "📦 暂无轨迹信息"

    state_map = {
        "0": "🚚 在途", "1": "📥 揽收", "2": "❓ 疑难",
        "3": "✅ 签收", "4": "↩️ 退签", "5": "📦 派件",
        "6": "↩️ 退回", "7": "🔄 转单",
        "10": "⏳ 待清关", "11": "🛃 清关中", "12": "✅ 已清关",
        "13": "❌ 清关异常", "14": "🚫 收件人拒签",
    }
    state = result.get("state", "0")
    state_text = state_map.get(state, f"未知({state})")
    nu = result.get("nu", "")
    com = result.get("com", "")

    lines = [f"📦 {nu} ({com}) — {state_text}\n"]
    for item in data:
        t = item.get("time", "")
        ctx = item.get("context", "")
        loc = item.get("location", "")
        loc_part = f" [{loc}]" if loc else ""
        lines.append(f"  {t} {ctx}{loc_part}")
    return "\n".join(lines)


# ==================== 速查函数 ====================

def quick_query(num: str, com: str = None) -> str:
    """
    一句话查快递，返回格式化文本。
    用法示例:
        text = quick_query("JDV027245639679", "jd")
    """
    result = query_tracking(num, com)
    return format_tracking_text(result)
