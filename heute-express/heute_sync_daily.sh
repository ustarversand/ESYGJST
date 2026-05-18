#!/bin/bash
# 货易达每日自动同步脚本
# 用法: ./heute_sync_daily.sh [--full]
#   --full: 拉取全部历史数据（首次运行用）
#   (默认): 拉取最近3天数据

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/data"
mkdir -p "$OUTPUT_DIR"

# 日期
TODAY=$(date +%Y-%m-%d)
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)
THREE_DAYS_AGO=$(date -d "3 days ago" +%Y-%m-%d)

if [ "$1" = "--full" ]; then
    START="2025-01-01"
    END="$TODAY"
    SUFFIX="full"
    echo "🔄 全量同步 (直到 $TODAY)"
else
    START="$THREE_DAYS_AGO"
    END="$TODAY"
    SUFFIX="${START}_${END}"
    echo "🔄 增量同步 ($START ~ $END)"
fi

# 导出 CSV
CSV_OUT="${OUTPUT_DIR}/heute_orders_${SUFFIX}.csv"
cd "$SCRIPT_DIR" && python3 heute_cli.py export --start "$START" --end "$END" -o "$CSV_OUT"

# 同时保存一份 JSON
JSON_OUT="${OUTPUT_DIR}/heute_orders_${SUFFIX}.json"
python3 -c "
import json, sys
from heute_sdk import HeuteClient

client = HeuteClient.login('USTAR', 'Hilden11031980!')
orders = client.fetch_all_orders('$START', '$END')

with open('$JSON_OUT', 'w', encoding='utf-8') as f:
    json.dump({'date': '$TODAY', 'count': len(orders), 'items': orders}, f, ensure_ascii=False)

# 统计摘要
total_weight = sum((o.get('weight') or 0) for o in orders)
print(f'📦 共 {len(orders)} 条订单')
print(f'⚖️  总重量: {total_weight/1000:.1f} kg')
stat = {}
for o in orders:
    s = o.get('state')
    if s not in stat: stat[s] = 0
    stat[s] += 1
print('📊 按状态:')
state_names = {0:'已作废',1:'待支付',2:'待入库',3:'国际运输',4:'国内配送',5:'签收'}
for s in sorted(stat.keys()):
    name = state_names.get(s, f'状态{s}')
    print(f'    {name}: {stat[s]}')
"

echo "✅ 同步完成"
echo "   CSV: $CSV_OUT"
echo "   JSON: $JSON_OUT"
