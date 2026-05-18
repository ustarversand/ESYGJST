"""
USTAR JST Core — 统一导出

优先使用 core.jst_client.JSTClient（新统一 SDK）
旧模块保留用于兼容，逐步迁移。
"""
from .jst_base_client import (
    JSTBaseClient,
    JST_CONFIG as _JST_CONFIG,
    retry_on_failure,
    alert_hook,
    register_telegram_alert,
)
from .jst_client import (
    JSTClient,           # 统一 SDK（整合了所有 API）
    call_jushuitan_api,
    call_jushuitan_api_dict,
    call_new_api,
    generate_sign,
    get_timestamp,
    DEFAULT_SHOP_ID,
    DEFAULT_BUYER_ID,
    alert_hook as jst_alert_hook,
)

# 保留旧导出别名（兼容现有代码）
JST_CONFIG = _JST_CONFIG

from .alert_bootstrap import bootstrap_alerts

__all__ = [
    # 统一 SDK（优先使用）
    "JSTClient",
    "call_jushuitan_api",
    "call_jushuitan_api_dict",
    "call_new_api",
    # 工具
    "JST_CONFIG",
    "JSTBaseClient",
    "retry_on_failure",
    "alert_hook",
    "register_telegram_alert",
    "generate_sign",
    "get_timestamp",
    "DEFAULT_SHOP_ID",
    "DEFAULT_BUYER_ID",
    "bootstrap_alerts",
]
