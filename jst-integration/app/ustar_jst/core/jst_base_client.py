"""
聚水潭 API 统一基类
JSTBaseClient — 统一签名、重试、错误处理
"""
import os
import time
import json
import logging
import hashlib
import requests
from typing import Dict, List, Any, Optional, Callable
from functools import wraps

logger = logging.getLogger(__name__)

# ==================== 全局配置（环境变量） ====================
JST_CONFIG = {
    "app_key": os.environ.get("JST_APP_KEY", "d561deb348274f1ba3505ec4578870fd"),
    "app_secret": os.environ.get("JST_APP_SECRET", "84ad2c023b9b49378b1161ea569e383c"),
    "token": os.environ.get("JST_TOKEN", "cfda23ff97664494bc6fc5ab46f8ea48"),
    "callback_url": os.environ.get(
        "JST_CALLBACK_URL",
        "https://gateway-cn.jieztech.com/apos.aps/api/JuShuiTanSpi/CallBack",
    ),
    "api_url_legacy": "https://open.erp321.com/api/open/query.aspx",
    "api_url_new": "https://openapi.jushuitan.com",
}

# 默认重试参数
DEFAULT_MAX_RETRIES = int(os.environ.get("JST_MAX_RETRIES", "3"))
DEFAULT_RETRY_DELAY = float(os.environ.get("JST_RETRY_DELAY", "1.0"))
DEFAULT_TIMEOUT = int(os.environ.get("JST_TIMEOUT", "30"))


# ==================== 通用重试装饰器 ====================

def retry_on_failure(
    max_retries: int = None,
    delay: float = None,
    backoff: float = 2.0,
    retriable_codes: set = None,
):
    """
    API 重试装饰器（指数退避）

    Args:
        max_retries:   最大重试次数（默认 3）
        delay:         初始重试间隔秒数（默认 1.0）
        backoff:       退避倍率（默认 2.0，即 1s → 2s → 4s）
        retriable_codes: 可重试的 code 集合（默认 {-1} 表示网络异常）
    """
    max_retries = max_retries if max_retries is not None else DEFAULT_MAX_RETRIES
    delay = delay if delay is not None else DEFAULT_RETRY_DELAY
    retriable_codes = retriable_codes or {-1, 99999}

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_result = None
            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    last_result = result
                    if isinstance(result, dict):
                        code = result.get("code", 0)
                        # code == 0 表示成功
                        if code == 0:
                            return result
                        # 非零 code 检查是否可重试
                        if code in retriable_codes:
                            msg = result.get("msg", "Unknown")
                            logger.warning(
                                f"[{func.__name__}] code={code} {msg} "
                                f"| attempt {attempt + 1}/{max_retries + 1}"
                            )
                            if attempt < max_retries:
                                sleep_time = delay * (backoff ** attempt)
                                time.sleep(sleep_time)
                                continue
                        # 不可重试的 code，直接返回
                        return result
                    return result
                except Exception as e:
                    last_result = {"code": -1, "msg": str(e)}
                    logger.warning(
                        f"[{func.__name__}] exception={e} "
                        f"| attempt {attempt + 1}/{max_retries + 1}"
                    )
                    if attempt < max_retries:
                        time.sleep(delay * (backoff ** attempt))
                        continue
            return last_result or {"code": -1, "msg": "Max retries exceeded"}

        return wrapper

    return decorator


# ==================== 告警钩子 ====================

class JSTAlertHook:
    """API 告警钩子（可扩展接入 Telegram/飞书等）"""

    def __init__(self):
        self._handlers: List[Callable] = []

    def register(self, handler: Callable[[str, Dict], None]):
        """注册告警处理器，签名: (title: str, context: Dict) -> None"""
        self._handlers.append(handler)

    def alert(self, title: str, context: Dict):
        for h in self._handlers:
            try:
                h(title, context)
            except Exception as e:
                logger.error(f"Alert handler error: {e}")

    def alert_api_failure(self, func_name: str, result: Dict, retries: int):
        self.alert(
            f"⚠️ JST API 失败 [{func_name}]",
            {"result": result, "retries": retries},
        )


# 全局告警钩子
alert_hook = JSTAlertHook()


def register_telegram_alert(bot_token: str, chat_id: str):
    """快捷注册 Telegram 告警"""
    import requests as _r

    def _handler(title: str, context: Dict):
        msg = f"{title}\n```\n{json.dumps(context, ensure_ascii=False, indent=2)}\n```"
        try:
            _r.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Telegram alert failed: {e}")

    alert_hook.register(_handler)


# ==================== 基类 ====================

class JSTBaseClient:
    """
    聚水潭 API 统一基类

    子类只需:
    1. 设置 self.config（字典，会自动合并全局配置）
    2. 定义 self._sign(params) 或沿用内置 MD5 签名
    3. 实现 self._build_url(method) 指定 API 地址
    """

    config: Dict[str, str] = {}  # 子类覆盖
    _api_base: str = JST_CONFIG["api_url_legacy"]

    def __init__(self, config: Optional[Dict] = None):
        # 合并：全局默认 → 实例 config（实例优先）
        self.cfg = {**JST_CONFIG, **self.config, **(config or {})}
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json; charset=utf-8"})

    # ─────────────── 签名 ───────────────

    def _sign(self, params: Dict) -> str:
        """
        默认 MD5 签名（可被子类覆盖）
        签名规则: MD5(secret + sorted(k1v1k2v2...))
        """
        sorted_str = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
        raw = self.cfg["app_secret"] + sorted_str
        return hashlib.md5(raw.encode("utf-8")).hexdigest().lower()

    def _sign_new_api(self, params: Dict) -> str:
        """新版 API 签名 (openapi.jushuitan.com)"""
        sorted_str = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
        return hashlib.md5((self.cfg["app_secret"] + sorted_str).encode("utf-8")).hexdigest().lower()

    # ─────────────── 请求 ───────────────

    def _timestamp(self) -> str:
        return str(int(time.time()))

    @retry_on_failure()
    def _post(
        self,
        path_or_url: str,
        method: str,
        biz_data: Any,
        use_new_api: bool = False,
        timeout: int = None,
    ) -> Dict:
        """
        通用 POST 请求（已内置重试装饰器）

        Args:
            path_or_url:  API path 或完整 URL
            method:        接口方法名（用于签名）
            biz_data:      业务数据（dict 或 list）
            use_new_api:   是否走新版 API (openapi.jushuitan.com)
            timeout:       请求超时秒数
        """
        timeout = timeout or DEFAULT_TIMEOUT

        if use_new_api:
            # ── 新版 API ──
            ts = self._timestamp()
            params = {
                "app_key": self.cfg["app_key"],
                "access_token": self.cfg["token"],
                "timestamp": ts,
                "charset": "utf-8",
                "version": "2",
                "biz": json.dumps(biz_data, ensure_ascii=False, separators=(",", ":")),
            }
            params["sign"] = self._sign_new_api(params)
            url = f"{JST_CONFIG['api_url_new']}{path_or_url}"
            resp = self._session.post(url, data=params, timeout=timeout)
        else:
            # ── 旧版 API ──
            ts = self._timestamp()
            sys_params = {"token": self.cfg["token"], "ts": ts}
            sign = self._sign(sys_params)
            url = (
                f"{JST_CONFIG['api_url_legacy']}"
                f"?method={method}&partnerid={self.cfg['app_key']}"
                f"&token={self.cfg['token']}&ts={ts}&sign={sign}"
            )
            resp = self._session.post(
                url,
                data=json.dumps(biz_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                timeout=timeout,
            )

        result = resp.json()
        return result

    def call_legacy(self, method: str, biz_data: Any, timeout: int = None) -> Dict:
        """调用旧版 API（自动判断 list/dict）"""
        return self._post("", method, biz_data, use_new_api=False, timeout=timeout)

    def call_new(self, path: str, biz_data: Any, timeout: int = None) -> Dict:
        """调用新版 API"""
        return self._post(path, "", biz_data, use_new_api=True, timeout=timeout)

    # ─────────────── 便捷方法 ───────────────

    def health_check(self) -> Dict:
        """简单健康检查（查店铺接口）"""
        try:
            return self.call_new("/open/shops/query", {"page_index": 1, "page_size": 1})
        except Exception as e:
            return {"code": -1, "msg": str(e)}
