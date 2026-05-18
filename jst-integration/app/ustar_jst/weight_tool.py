#!/usr/bin/env python3
"""
📦 重量管理工具
==============
用途：打包时录入自报重量，对比货易达实际称重，监控成本泄漏

用法:
  python3 weight_tool.py record <订单号> <重量(克)>   # 记录自报重量
  python3 weight_tool.py check <订单号>               # 查看订单重量对比
  python3 weight_tool.py compare <订单号> [<货易达重量>]  # 录入+自动比对
  python3 weight_tool.py batch <运单号前缀>             # 批量查看对比
  python3 weight_tool.py report                       # 重量差异报告
  python3 weight_tool.py diff <阈值百分比>              # 列出差异超过 N% 的订单

示例:
  python3 weight_tool.py record 2605141515510856 980      # 自报980g
  python3 weight_tool.py check DEUHYD600224353231EU       # 查询单号
  python3 weight_tool.py diff 30                           # 查看差异>30%的订单
"""

import sqlite3
import sys
from datetime import datetime

DB = '/opt/data/workspace/ustar-deploy/app/ustar_jst/workflows/heute_express.db'

def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def fmt_w(g):
    if g is None or g == 0:
        return "N/A"
    if g >= 1000:
        return f"{g/1000:.2f}kg"
    return f"{g}g"

def find_order(conn, query):
    """Find order by order_no, tracking_no, or biz_no"""
    for col in ['order_no', 'tracking_no', 'biz_no']:
        cur = conn.execute(f"SELECT * FROM orders WHERE {col}=?", (query,))
        row = cur.fetchone()
        if row:
            return row
    # Try partial match
    cur = conn.execute(
        "SELECT * FROM orders WHERE order_no LIKE ? OR tracking_no LIKE ? OR biz_no LIKE ? LIMIT 1",
        (f'%{query}%', f'%{query}%', f'%{query}%')
    )
    return cur.fetchone()

def cmd_record(args):
    """Record declared weight for an order"""
    if len(args) < 2:
        print("用法: python3 weight_tool.py record <订单号/运单号> <重量(克)>")
        return
    
    query = args[0]
    weight = int(args[1])
    
    conn = connect()
    order = find_order(conn, query)
    if not order:
        print(f"❌ 未找到订单: {query}")
        conn.close()
        return
    
    conn.execute("UPDATE orders SET declared_weight_g=? WHERE order_no=?",
                 (weight, order['order_no']))
    conn.commit()
    
    # Compare with actual_weight_g
    actual = order['actual_weight_g']
    if actual and actual > 0:
        diff = actual - weight
        diff_pct = diff / weight * 100
        cost_per_kg = 0  # user should fill this in
        cost_leak = abs(diff) * cost_per_kg / 1000
        
        print(f"✅ 已记录自报重量")
        print(f"   订单: {order['order_no']}")
        print(f"   收件人: {order['receiver_name']}")
        print(f"   线路: {order['line_name']}")
        print(f"   📝 自报: {fmt_w(weight)}")
        print(f"   🔄 货易达: {fmt_w(actual)}")
        print(f"   📊 差异: {diff:+d}g ({diff_pct:+.1f}%)")
        if abs(diff_pct) > 20:
            print(f"   ⚠️ 差异超过20%，建议排查!")
    else:
        print(f"✅ 已记录自报重量: {fmt_w(weight)}")
        print(f"   订单: {order['order_no']} (货易达重量暂无)")
        print(f"   等货易达回传重量后自动比对")
    
    conn.close()

def cmd_check(args):
    """Check weight comparison for an order"""
    if not args:
        print("用法: python3 weight_tool.py check <订单号/运单号>")
        return
    
    conn = connect()
    order = find_order(conn, args[0])
    if not order:
        print(f"❌ 未找到订单: {args[0]}")
        conn.close()
        return
    
    print(f"📋 订单重量详情")
    print(f"   订单号: {order['order_no']}")
    print(f"   运单号: {order['tracking_no']}")
    print(f"   国内单: {order['biz_no']}")
    print(f"   收件人: {order['receiver_name']}")
    print(f"   寄件人: {order['sender']}")
    print(f"   线路: {order['line_name']}")
    print(f"   状态: {order['status']}")
    print()
    
    dw = order['declared_weight_g']
    aw = order['actual_weight_g']
    bw = order['billed_weight_g']
    wg = order['weight_g']
    
    print(f"   📝 自报重量(declared_weight_g):  {fmt_w(dw)}")
    print(f"   ⚖️  货易达重量(actual_weight_g):  {fmt_w(aw)}")
    print(f"   💰 计费重量(billed_weight_g):      {fmt_w(bw)}")
    print(f"   📦 接口原始重量(weight_g):          {fmt_w(wg)}")
    
    if dw and aw and dw > 0 and aw > 0:
        diff = aw - dw
        diff_pct = diff / dw * 100
        print(f"\n   📊 比对结果: 货易达 {'>' if diff > 0 else '<'} 自报")
        print(f"      差异: {diff:+d}g ({diff_pct:+.1f}%)")
        if abs(diff_pct) > 20:
            print(f"      ⚠️ 差异显著!")
        elif abs(diff_pct) > 10:
            print(f"      ⚡ 注意差异")
        else:
            print(f"      ✅ 差异在合理范围")
    
    conn.close()

def cmd_report(args):
    """Generate weight difference report"""
    conn = connect()
    
    print("📊 重量差异综合报告")
    print("=" * 60)
    
    # Stats per sender
    cur = conn.execute("""
        SELECT sender, 
               COUNT(*) as cnt,
               ROUND(AVG(actual_weight_g - declared_weight_g), 0) as avg_diff,
               ROUND(AVG(ABS(actual_weight_g - declared_weight_g) * 100.0 / NULLIF(declared_weight_g, 0)), 1) as avg_diff_pct,
               SUM(CASE WHEN ABS(actual_weight_g - declared_weight_g) * 100.0 / NULLIF(declared_weight_g, 0) > 20 THEN 1 ELSE 0 END) as over_20_pct,
               ROUND(AVG(declared_weight_g), 0) as avg_declared,
               ROUND(AVG(actual_weight_g), 0) as avg_actual
        FROM orders
        WHERE declared_weight_g IS NOT NULL AND declared_weight_g > 0
          AND actual_weight_g IS NOT NULL AND actual_weight_g > 0
        GROUP BY sender
        HAVING cnt >= 10
        ORDER BY avg_diff_pct DESC
    """)
    rows = cur.fetchall()
    
    if not rows:
        print("暂无数据录入——你还未录入过自报重量。")
        print("请先用 record 命令录入: python3 weight_tool.py record <订单号> <重量>")
        conn.close()
        return
    
    total = sum(r['cnt'] for r in rows)
    total_over_20 = sum(r['over_20_pct'] for r in rows)
    
    print(f"\n已录入自报重量: {total} 单")
    print(f"差异>20%的订单: {total_over_20} 单 ({total_over_20/total*100:.1f}%)")
    print()
    
    print(f"{'寄件人':<20} {'单数':<8} {'均自报':<10} {'均实际':<10} {'均差':<10} {'均差%':<8} {'>20%':<8}")
    print("-" * 74)
    for r in rows:
        print(f"{r['sender']:<20} {r['cnt']:<8} {fmt_w(r['avg_declared']):<10} {fmt_w(r['avg_actual']):<10} "
              f"{r['avg_diff']:+d}g{r'':<6} {r['avg_diff_pct']:<8} {r['over_20_pct']:<8}")
    
    # Top discrepancies
    print(f"\n\n🔴 差异最大的20个订单:")
    cur = conn.execute("""
        SELECT order_no, sender, receiver_name, declared_weight_g, actual_weight_g,
               (actual_weight_g - declared_weight_g) as diff,
               ROUND((actual_weight_g - declared_weight_g) * 100.0 / NULLIF(declared_weight_g, 0), 1) as diff_pct
        FROM orders
        WHERE declared_weight_g IS NOT NULL AND declared_weight_g > 0
          AND actual_weight_g IS NOT NULL AND actual_weight_g > 0
        ORDER BY ABS(actual_weight_g - declared_weight_g) DESC
        LIMIT 20
    """)
    print(f"{'订单号':<20} {'寄件人':<15} {'收件人':<10} {'自报':<8} {'实际':<8} {'差异':<8} {'差异%':<8}")
    print("-" * 77)
    for r in cur.fetchall():
        print(f"{r['order_no']:<20} {r['sender']:<15} {r['receiver_name']:<10} "
              f"{fmt_w(r['declared_weight_g']):<8} {fmt_w(r['actual_weight_g']):<8} "
              f"{r['diff']:+d}g{r'':<5} {r['diff_pct']:+.1f}%")
    
    conn.close()

def cmd_diff(args):
    """List orders where difference exceeds threshold"""
    threshold = int(args[0]) if args else 20
    
    conn = connect()
    cur = conn.execute("""
        SELECT order_no, sender, receiver_name, line_name,
               declared_weight_g, actual_weight_g,
               ROUND((actual_weight_g - declared_weight_g) * 100.0 / NULLIF(declared_weight_g, 0), 1) as diff_pct
        FROM orders
        WHERE declared_weight_g IS NOT NULL AND declared_weight_g > 0
          AND actual_weight_g IS NOT NULL AND actual_weight_g > 0
          AND ABS((actual_weight_g - declared_weight_g) * 100.0 / NULLIF(declared_weight_g, 0)) > ?
        ORDER BY ABS(actual_weight_g - declared_weight_g) DESC
    """, (threshold,))
    rows = cur.fetchall()
    
    if not rows:
        print(f"✅ 没有差异超过{threshold}%的订单")
        conn.close()
        return
    
    print(f"⚠️  发现 {len(rows)} 个差异超过 {threshold}% 的订单:\n")
    print(f"{'订单号':<20} {'寄件人':<15} {'收件人':<10} {'线路':<18} {'自报':<8} {'实际':<8} {'差异%':<8}")
    print("-" * 87)
    for r in rows[:30]:
        print(f"{r['order_no']:<20} {r['sender']:<15} {r['receiver_name']:<10} "
              f"{r['line_name'][:16]:<18} {fmt_w(r['declared_weight_g']):<8} "
              f"{fmt_w(r['actual_weight_g']):<8} {r['diff_pct']:+.1f}%")
    
    if len(rows) > 30:
        print(f"...还有 {len(rows) - 30} 个订单未显示")
    
    conn.close()

def cmd_batch(args):
    """Batch check for a sender or prefix"""
    if not args:
        print("用法: python3 weight_tool.py batch <寄件人名称 或 日期>")
        print("示例: python3 weight_tool.py batch lebenswelle1")
        return
    
    conn = connect()
    query = args[0]
    
    cur = conn.execute("""
        SELECT order_no, sender, receiver_name, declared_weight_g, actual_weight_g,
               (actual_weight_g - declared_weight_g) as diff,
               ROUND((actual_weight_g - declared_weight_g) * 100.0 / NULLIF(declared_weight_g, 0), 1) as diff_pct
        FROM orders
        WHERE (sender LIKE ? OR order_no LIKE ?)
          AND declared_weight_g IS NOT NULL AND declared_weight_g > 0
          AND actual_weight_g IS NOT NULL AND actual_weight_g > 0
        ORDER BY created_at DESC
        LIMIT 30
    """, (f'%{query}%', f'%{query}%'))
    rows = cur.fetchall()
    
    if not rows:
        print(f"未找到匹配订单（或这些订单尚未录入自报重量）")
        conn.close()
        return
    
    print(f"📍 筛选: '{query}' — 共 {len(rows)} 单\n")
    print(f"{'订单号':<20} {'寄件人':<15} {'收件人':<10} {'自报':<8} {'实际':<8} {'差异':<8} {'差异%':<8}")
    print("-" * 77)
    for r in rows:
        print(f"{r['order_no']:<20} {r['sender']:<15} {r['receiver_name']:<10} "
              f"{fmt_w(r['declared_weight_g']):<8} {fmt_w(r['actual_weight_g']):<8} "
              f"{r['diff']:+d}g{r'':<5} {r['diff_pct']:+.1f}%")
    
    conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    
    cmd = sys.argv[1]
    args = sys.argv[2:]
    
    commands = {
        'record': cmd_record,
        'check': cmd_check,
        'report': cmd_report,
        'diff': cmd_diff,
        'batch': cmd_batch,
        'compare': cmd_check,  # alias
    }
    
    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"未知命令: {cmd}")
        print("可用命令: record, check, report, diff, batch")
