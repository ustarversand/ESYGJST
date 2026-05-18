#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一告警引导模块
====================

启动时调用 bootstrap_alerts()，自动把 JST 和 ECShop 的告警钩子
全部接入 Telegram（也可以扩展飞书/邮件等）。

用法（在 cronjob 或程序入口调用一次）：
    from core.alert_bootstrap import bootstrap_alerts
    bootstrap_alerts()

环境变量：
    TELEGRAM_BOT_TOKEN — Telegram Bot Token（默认使用 @LLHMbot）
    HERMES_TELEGRAM_CHAT_ID — 告警推送目标用户 ID（默认 5573662232）
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

# ─────────────── 配置 ───────────────

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8713145628:AAHvpiAwEMX6-myAvw9mRJKZ0uXgHiJyUkw",  # @LLHMbot（绿联Hermes1号）
)
HERMES_TELEGRAM_CHAT_ID = os.environ.get(
    "HERMES_TELEGRAM_CHAT_ID",
    "5573662232",  # 德国 Jansen
)

# ─────────────── Telegram 发送 ───────────────

def _telegram_send(text: str, parse_mode: str = "Markdown") -> bool:
    """发送 Telegram 消息，返回成功/失败"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.warning("[AlertBootstrap] 未配置 TELEGRAM_BOT_TOKEN，跳过告警")
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": HERMES_TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
        result = r.json()
        if result.get("ok"):
            return True
        logger.error(f"[AlertBootstrap] Telegram发送失败: {result.get('description')}")
        return False
    except Exception as e:
        logger.error(f"[AlertBootstrap] Telegram异常: {e}")
        return False


# ─────────────── JST 告警处理器 ───────────────

def _jst_alert_handler(title: str, context: dict):
    """处理 JST API 失败告警（注册到 JSTAlertHook）"""
    import json

    # 截断过长内容
    ctx_str = json.dumps(context, ensure_ascii=False, indent=2)
    if len(ctx_str) > 1500:
        ctx_str = ctx_str[:1500] + "\n... (truncated)"

    # 格式化消息
    msg = (
        f"🔴 *JST API 告警*\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"*{title}*\n"
        f"```\n{ctx_str}\n```"
    )
    _telegram_send(msg)


# ─────────────── ECShop 告警处理器 ───────────────

def _ecshop_alert_handler(title: str, exc: Exception):
    """处理 ECShop API 失败告警（注册到 ECShopAlertHook）"""
    import traceback

    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tb_str = "".join(tb)
    if len(tb_str) > 1500:
        tb_str = tb_str[:1500] + "\n... (truncated)"

    msg = (
        f"🟠 *ECShop API 告警*\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"*{title}*\n"
        f"```\n{type(exc).__name__}: {exc}\n```\n"
        f"```\n{tb_str[-800:]}\n```"
    )
    _telegram_send(msg)


# ─────────────── 引导函数 ───────────────

_alerts_bootstrapped = False


def bootstrap_alerts():
    """
    初始化所有告警钩子（只执行一次）

    调用后：
      - JST API 失败 → Telegram
      - ECShop API 失败 → Telegram
    """
    global _alerts_bootstrapped
    if _alerts_bootstrapped:
        logger.debug("[AlertBootstrap] 已初始化，跳过")
        return

    # ── JST 告警 ──
    try:
        # 相对导入，从 core 包内部访问 jst_client
        from .jst_client import alert_hook as _jst_hook

        # 避免重复注册
        if _jst_alert_handler not in _jst_hook._handlers:
            _jst_hook.register(_jst_alert_handler)
            logger.info(f"[AlertBootstrap] JST alert_hook 已注册 Telegram → {HERMES_TELEGRAM_CHAT_ID}")
        else:
            logger.info("[AlertBootstrap] JST alert_hook 已存在，跳过")
    except Exception as e:
        logger.error(f"[AlertBootstrap] JST alert_hook 注册失败: {e}")

    # ── ECShop 告警 ──
    try:
        import sys
        import os.path as osp

        # ECShop client 在上层目录，动态加载
        ecshop_path = osp.join(osp.dirname(osp.dirname(osp.abspath(__file__))), "ECShop", "agent")
        if ecshop_path not in sys.path:
            sys.path.insert(0, ecshop_path)

        from ecshop_client import _ecshop_alert_hook

        if _ecshop_alert_handler not in _ecshop_alert_hook._handlers:
            _ecshop_alert_hook.register(_ecshop_alert_handler)
            logger.info(f"[AlertBootstrap] ECShop alert_hook 已注册 Telegram → {HERMES_TELEGRAM_CHAT_ID}")
        else:
            logger.info("[AlertBootstrap] ECShop alert_hook 已存在，跳过")
    except Exception as e:
        logger.warning(f"[AlertBootstrap] ECShop alert_hook 注册失败（可能 ECShop 未部署）: {e}")

    _alerts_bootstrapped = True
    logger.info("[AlertBootstrap] 告警引导完成")


# ─────────────── 快捷测试 ───────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    print("=== 告警引导测试 ===")
    bootstrap_alerts()

    # 模拟触发一次 JST 告警
    print("\n发送测试告警...")
    from .jst_client import alert_hook
    alert_hook.alert("🧪 测试：JST API 失败 [test_order_query]", {
        "result": {"code": -1, "msg": "network timeout"},
        "retries": 3,
    })
    print("✅ 测试告警已发送（检查 Telegram）")
