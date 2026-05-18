#!/usr/bin/env python3
"""
货易达每日同步脚本 — 高效版本（直接SDK，无CLI开销）
===================================================
用法:
  python3 heute_sync.py                   # 同步昨天
  python3 heute_sync.py --days 3          # 同步最近3天
  python3 heute_sync.py --full            # 全量同步
  python3 heute_sync.py --start 2026-01-01 --end 2026-05-15  # 自定义范围
"""

import sys
import os
import json
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from heute_sdk import HeuteClient, ORDER_STATES

# 配置
USERNAME = "USTAR"
PASSWORD = "Hilden11031980!"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def parse_args():
    args = sys.argv[1:]
    if "--full" in args:
        return "2025-01-01", datetime.now().strftime("%Y-%m-%d")
    
    start = end = None
    for i, a in enumerate(args):
        if a == "--start" and i+1 < len(args):
            start = args[i+1]
        elif a == "--end" and i+1 < len(args):
            end = args[i+1]
    
    if start and end:
        return start, end
    
    days = 1
    for i, a in enumerate(args):
        if a == "--days" and i+1 < len(args):
            days = int(args[i+1])
            break
    
    today = datetime.now()
    end = today.strftime("%Y-%m-%d")
    start = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    return start, end


def collect_summary(orders):
    """生成统计摘要"""
    weight = sum((o.get("weight") or 0) for o in orders)
    states = {}
    for o in orders:
        s = o.get("state")
        states[s] = states.get(s, 0) + 1
    
    lines = {}
    for o in orders:
        l = o.get("lineName", "未知")
        lines[l] = lines.get(l, 0) + 1
    
    return {
        "total": len(orders),
        "weight_kg": round(weight / 1000, 1),
        "states": {ORDER_STATES.get(k, f"状态{k}"): v for k, v in sorted(states.items())},
        "lines": dict(sorted(lines.items(), key=lambda x: -x[1])[:10]),
    }


def main():
    start, end = parse_args()
    print(f"🔄 货易达同步: {start} ~ {end}", flush=True)
    
    # 自动登录
    client = HeuteClient.login(USERNAME, PASSWORD)
    info = HeuteClient.decode_token(client.token)
    print(f"🔑 登录成功 (过期: {info.get('exp_date','?')})", flush=True)
    
    # 拉取
    def progress(fetched, total, page):
        print(f"\r📦 第{page}页: {fetched}条", end="", flush=True)
    
    orders = client.fetch_all_orders(start, end, progress_cb=progress)
    print(f"\n✅ 共 {len(orders)} 条", flush=True)
    
    # 保存 JSON
    suffix = f"{start}_{end}"
    json_path = os.path.join(OUTPUT_DIR, f"heute_orders_{suffix}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "start": start,
            "end": end,
            "fetched_at": datetime.now().isoformat(),
            "count": len(orders),
            "items": orders,
        }, f, ensure_ascii=False)
    
    # 保存 CSV
    csv_path = os.path.join(OUTPUT_DIR, f"heute_orders_{suffix}.csv")
    client.orders_to_csv(orders, csv_path)
    
    # 摘要
    summary = collect_summary(orders)
    print(f"📁 已保存:")
    print(f"   JSON: {json_path}")
    print(f"   CSV:  {csv_path}")
    print(f"📊 统计: {summary['total']}单, {summary['weight_kg']}kg")
    print(f"   状态: {summary['states']}")
    
    # 为 Hermes cron 格式化摘要
    return summary


if __name__ == "__main__":
    try:
        summary = main()
        # 输出 Markdown 摘要（Hermes cron 会作为消息发送）
        print(f"\n---")
        print(f"**货易达同步完成** | {summary['total']}单")
        print(f"- 📦 总重: {summary['weight_kg']}kg")
        for k, v in summary['states'].items():
            print(f"- {k}: {v}")
    except Exception as e:
        print(f"\n❌ 同步失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
