#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JST 订单状态主动推送模块

触发链（定时轮询）:
  每5分钟 cronjob
    → JST 查询最近发货订单（l_id 有值的）
      → 查今日新增运单（对比上次推送记录）
        → 有新快递号 → 查货易达轨迹
          → 推送 Telegram 给对应用户

用法:
  from workflows.order_status_notifier import OrderStatusNotifier
  notifier = OrderStatusNotifier()
  notifier.run_once()

cronjob 配置（每5分钟）:
  cronjob(action='create', prompt='...', schedule='*/5 * * * *',
          skills=['logistics-tracking'], script='...')
"""

import os
import sys
import sqlite3
import logging
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # .../workflows/
PARENT_DIR = os.path.dirname(BASE_DIR)  # .../ustar_jst/


# ==================== 推送记录（幂等） ====================

def get_db_path():
    return os.path.join(PARENT_DIR, "heute_express.db")


class PushRecordDB:
    """
    记录哪些订单已推送过（避免重复推送）
    表结构:
      order_no TEXT PRIMARY KEY  — 聚水潭 so_id
      jst_o_id TEXT            — 聚水潭内部单号
      tracking_no TEXT          — 物流单号
      pushed_at TEXT            — 推送时间
      status TEXT               — 推送状态
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.path.join(PARENT_DIR, "jst_push_records.db")
        # 初始化告警钩子（JST/ECShop 失败 → Telegram）
        try:
            from core.alert_bootstrap import bootstrap_alerts
            bootstrap_alerts()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"告警引导失败（不影响主流程）: {e}")

    def init(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS pushed_orders (
            order_no TEXT PRIMARY KEY,
            jst_o_id TEXT,
            tracking_no TEXT,
            pushed_at TEXT,
            status TEXT
        )""")
        conn.commit()
        conn.close()

    def is_pushed(self, order_no: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT 1 FROM pushed_orders WHERE order_no=? LIMIT 1", (order_no,)
        )
        exists = cur.fetchone() is not None
        conn.close()
        return exists

    def mark_pushed(self, order_no: str, jst_o_id: str = None, tracking_no: str = None):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT OR REPLACE INTO pushed_orders
               (order_no, jst_o_id, tracking_no, pushed_at, status)
               VALUES (?, ?, ?, ?, ?)""",
            (
                order_no,
                jst_o_id or "",
                tracking_no or "",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "notified",
            ),
        )
        conn.commit()
        conn.close()

    def get_recent(self, hours: int = 24) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            "SELECT * FROM pushed_orders WHERE pushed_at >= ? ORDER BY pushed_at DESC",
            (since,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# ==================== Telegram 推送器 ====================

class TelegramPusher:
    """
    通过 Telegram Bot API 直接推送消息到 Telegram

    使用环境变量:
      TELEGRAM_BOT_TOKEN  — Bot Token（如 123456:ABC-DEF...）
      HERMES_TELEGRAM_CHAT_ID — 默认推送用户 ID（默认 5573662232）
    """

    def __init__(
        self,
        bot_token: str = None,
        default_chat_id: str = None,
    ):
        self.bot_token = bot_token or os.environ.get(
            "TELEGRAM_BOT_TOKEN",
            "8713145628:AAHvpiAwEMX6-myAvw9mRJKZ0uXgHiJyUkw",  # @LLHMbot
        )
        self.default_chat_id = default_chat_id or os.environ.get(
            "HERMES_TELEGRAM_CHAT_ID", "5573662232"
        )
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"

    def _send_raw(self, payload: dict) -> dict:
        """直接调 Telegram Bot API"""
        if not self.bot_token:
            logger.warning("[TelegramPusher] 未配置 TELEGRAM_BOT_TOKEN，跳过发送")
            return {"ok": False, "description": "no token"}

        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.api_base}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception as e:
            logger.error(f"[TelegramPusher] 发送失败: {e}")
            return {"ok": False, "description": str(e)}

    def send(
        self,
        text: str,
        chat_id: str = None,
        parse_mode: str = "Markdown",
    ) -> dict:
        """
        发送文本消息

        Args:
            text:      消息内容（支持 Markdown）
            chat_id:   目标用户 ID（默认发给自己）
            parse_mode: Markdown 或 HTML
        """
        return self._send_raw({
            "chat_id": chat_id or self.default_chat_id,
            "text": text,
            "parse_mode": parse_mode,
        })

    def send_order_update(
        self,
        order: Dict,
        tracking_info: Dict = None,
        chat_id: str = None,
    ) -> Dict:
        """格式化并发送订单状态更新"""
        so_id = order.get("so_id", "")
        receiver = order.get("receiver_name", "未知")
        logistics_company = order.get("logistics_company", "")
        l_id = order.get("l_id", "")   # 国内快递号
        cb_l_id = order.get("cb_l_id", "")  # 国际单号

        lines = [
            "📦 *订单已发货*",
            "━━━━━━━━━━━━━━━━━",
            f"📋 订单号: `{so_id}`",
            f"👤 收件人: {receiver}",
        ]

        if logistics_company:
            lines.append(f"🚚 快递: {logistics_company}")
        if l_id:
            lines.append(f"📮 国内单号: `{l_id}`")
        if cb_l_id:
            lines.append(f"🌍 国际单号: `{cb_l_id}`")

        # 货易达轨迹
        if tracking_info:
            status = tracking_info.get("status", "")
            if status:
                lines.append(f"📍 状态: {status}")
            created = tracking_info.get("created_at", "")
            if created:
                lines.append(f"🕐 时间: {created}")

        lines.append("━━━━━━━━━━━━━━━━━")

        msg = "\n".join(lines)
        result = self.send(msg, chat_id=chat_id)

        if result.get("ok"):
            logger.info(f"[TelegramPusher] 已发送消息给 {chat_id or self.default_chat_id}")
        else:
            logger.error(f"[TelegramPusher] 发送失败: {result.get('description')}")

        return result


# ==================== JST 订单状态查询 ====================

def query_recent_shipped_orders(
    minutes: int = 10, page_size: int = 50
) -> List[Dict]:
    """
    查询最近 N 分钟内发货（有快递单号）的订单
    用的是聚水潭老版 API（legacy）
    """
    # BASE_DIR 是 workflows/，core/ 在 PARENT_DIR 下
    core_path = os.path.join(PARENT_DIR, "core")
    if core_path not in sys.path:
        sys.path.insert(0, PARENT_DIR)
    try:
        from core.jst_client import (
            JST_CONFIG,
            JST_TOKEN,
            generate_sign,
            get_timestamp,
            call_jushuitan_api_dict,
        )
    except ImportError:
        logger.warning("[JSTStatusWatcher] 无法导入 JST API，跳过")
        return []

    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_time = (datetime.now() - timedelta(minutes=minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # 注意：JST 老版 API 用 modified_begin/modified_end，不是 start_time/end_time
    data = {
        "modified_begin": start_time,
        "modified_end": end_time,
        "page_index": 1,
        "page_size": page_size,
    }

    try:
        result = call_jushuitan_api_dict("orders.single.query", data)
        if result.get("code") != 0:
            logger.warning(f"[JSTStatusWatcher] 查询失败: {result.get('msg')}")
            return []

        orders = result.get("orders", [])
        # 筛选有快递单号的（已发货）
        shipped = [
            o
            for o in orders
            if o.get("l_id") or o.get("logistics_company")
        ]
        logger.info(f"[JSTStatusWatcher] 最近{minutes}分钟: 共{len(orders)}单, 已发货{len(shipped)}单")
        return shipped

    except Exception as e:
        logger.error(f"[JSTStatusWatcher] 查询异常: {e}")
        return []


# ==================== 货易达轨迹查询 ====================

def get_heute_tracking(tracking_no: str) -> Optional[Dict]:
    """
    查货易达本地DB轨迹
    """
    if not tracking_no:
        return None

    db_path = get_db_path()
    if not os.path.exists(db_path):
        return None

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM orders WHERE tracking_no=? OR biz_no=? LIMIT 1",
            (tracking_no, tracking_no),
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
    except Exception as e:
        logger.error(f"[HeuteTracking] 查询失败 {tracking_no}: {e}")

    return None


# ==================== 完整通知器 ====================

class OrderStatusNotifier:
    """
    JST 订单状态主动通知器

    流程:
      1. 查 JST 最近发货订单
      2. 对比已推送记录（幂等）
      3. 有新订单 → 查货易达轨迹 → 推送 Telegram
    """

    def __init__(
        self,
        push_record_db: PushRecordDB = None,
        telegram_pusher: TelegramPusher = None,
    ):
        self.record_db = push_record_db or PushRecordDB()
        self.record_db.init()
        self.pusher = telegram_pusher or TelegramPusher()

    def run_once(self, lookback_minutes: int = 10) -> Dict:
        """
        执行一次检查+推送
        """
        logger.info(f"[OrderStatusNotifier] 开始检查 JST 发货订单（回溯{lookback_minutes}分钟）")

        # 1. 查最近发货订单
        orders = query_recent_shipped_orders(minutes=lookback_minutes)

        new_orders = []
        for order in orders:
            so_id = order.get("so_id", "")
            if not so_id:
                continue
            # 幂等过滤
            if self.record_db.is_pushed(so_id):
                continue
            new_orders.append(order)

        logger.info(f"[OrderStatusNotifier] 新发货订单: {len(new_orders)} 单")

        if not new_orders:
            return {"checked": len(orders), "new": 0, "pushed": 0}

        # 2. 逐单推送
        pushed = 0
        for order in new_orders:
            so_id = order.get("so_id", "")
            tracking_no = order.get("l_id") or order.get("cb_l_id", "")

            # 查货易达轨迹
            tracking_info = None
            if tracking_no:
                tracking_info = get_heute_tracking(tracking_no)

            # 推送
            try:
                result = self.pusher.send_order_update(order, tracking_info)
                if result.get("success"):
                    self.record_db.mark_pushed(
                        so_id,
                        jst_o_id=order.get("o_id", ""),
                        tracking_no=tracking_no,
                    )
                    pushed += 1
                    logger.info(f"[OrderStatusNotifier] 已推送: {so_id}")
            except Exception as e:
                logger.error(f"[OrderStatusNotifier] 推送失败 {so_id}: {e}")

        return {
            "checked": len(orders),
            "new": len(new_orders),
            "pushed": pushed,
            "orders": [
                {"so_id": o.get("so_id"), "receiver": o.get("receiver_name")}
                for o in new_orders
            ],
        }


# ==================== CLI 入口 ====================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    print("=== JST 订单状态主动推送 ===\n")

    notifier = OrderStatusNotifier()

    # 立即执行一次
    result = notifier.run_once(lookback_minutes=10)

    print(f"\n📊 结果:")
    print(f"   检查订单: {result['checked']}")
    print(f"   新发货: {result['new']}")
    print(f"   已推送: {result['pushed']}")
    if result.get("orders"):
        print(f"   订单列表:")
        for o in result["orders"]:
            print(f"     - {o['so_id']} / {o['receiver']}")
