#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
入库重量同步脚本 v3
- 批量从 USTARVS 管理后台拉已出库订单的入库重量，覆盖 actual_weight_g
- 更新 billed_weight_g = actual_weight_g（计费重量）
- 月度差异报告
"""
import sys, os, json, sqlite3, subprocess, time
from datetime import datetime, timedelta
from typing import Optional, List, Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "heute_express.db")
LOGIN_URL = "https://www.heute-express.com/Prod/api/app/token/login"
ORDER_PAGE_URL = "https://www.heute-express.com/Prod/api/app/order/page"
STATE_MAP = {1:"待付款",2:"待入库",3:"已入库",4:"运输中",5:"已出库",6:"已签收"}

# 线路分组
def line_group(name: str) -> str:
    if not name:
        return "未知"
    if "奶粉" in name: return "奶粉专线"
    if "菲莱套" in name: return "菲莱套装"
    if "莱菲套" in name: return "莱菲套线"
    if "菲莱" in name: return "菲莱专线"
    if "杂货" in name: return "杂货专线"
    return name

def login() -> Optional[str]:
    p = {"userNameOrEmailAddress":"USTARVS","password":"668899","name":"USTARVS"}
    r = subprocess.run(["curl","-s","-X","POST",LOGIN_URL,
        "-H","Content-Type: application/json","-d",json.dumps(p)],
        capture_output=True,text=True,timeout=15)
    d = json.loads(r.stdout)
    return d.get("token") or None

def fetch_page(token: str, page: int = 1, page_size: int = 100) -> List[Dict]:
    """拉一页数据"""
    p = {"pageIndex": page, "pageSize": page_size}
    r = subprocess.run(["curl","-s","-X","POST",ORDER_PAGE_URL,
        "-H","Content-Type: application/json",
        "-H",f"Authorization: Bearer {token}",
        "-d",json.dumps(p)], capture_output=True,text=True,timeout=30)
    try:
        data = json.loads(r.stdout)
        return data.get("items", [])
    except:
        return []

def total_pages(token: str, page_size: int = 100) -> int:
    """获取总页数"""
    p = {"pageIndex": 1, "pageSize": page_size}
    r = subprocess.run(["curl","-s","-X","POST",ORDER_PAGE_URL,
        "-H","Content-Type: application/json",
        "-H",f"Authorization: Bearer {token}",
        "-d",json.dumps(p)], capture_output=True,text=True,timeout=30)
    try:
        data = json.loads(r.stdout)
        return data.get("totalPages", 50) or 50
    except:
        return 50

def sync_bulk(token: str, max_pages: int = None, force: bool = False):
    """
    批量拉取已出库订单，更新入库重量 & 计费重量
    force=True: 覆盖所有已同步的（全量刷新）
    force=False: 只补缺 actual_weight_g 的
    """
    if max_pages is None:
        max_pages = total_pages(token)
        print(f"  共 {max_pages} 页")
    
    conn = sqlite3.connect(DB_PATH)
    updated = skipped_no_weight = skipped_no_match = 0
    
    for page in range(1, max_pages + 1):
        items = fetch_page(token, page, 100)
        if not items:
            print(f"  第{page}页无数据，停止")
            break
        
        for item in items:
            sn = item.get("sn", "")
            weight = item.get("weightInStore")
            
            if weight is None or weight == 0:
                skipped_no_weight += 1
                continue
            
            cur = conn.execute("SELECT 1 FROM orders WHERE order_no=?", (sn,))
            if not cur.fetchone():
                skipped_no_match += 1
                continue
            
            if force:
                # 全量刷新：始终更新
                conn.execute("""
                    UPDATE orders SET 
                        actual_weight_g = ?,
                        billed_weight_g = ?,
                        updated_at = ?
                    WHERE order_no = ?
                """, (weight, weight, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sn))
                updated += 1
            else:
                # 增量补充：只更新还没填的
                existing = conn.execute("SELECT actual_weight_g FROM orders WHERE order_no=?", (sn,)).fetchone()
                if existing and existing[0] is None:
                    conn.execute("""
                        UPDATE orders SET 
                            actual_weight_g = ?,
                            billed_weight_g = ?,
                            updated_at = ?
                        WHERE order_no = ?
                    """, (weight, weight, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sn))
                    updated += 1
        
        conn.commit()
        if page % 50 == 0 or page == max_pages:
            print(f"  第{page}/{max_pages}页: 更新{updated}单 (无重量{skipped_no_weight}, 无匹配{skipped_no_match})")
        time.sleep(0.3)
    
    conn.close()
    print(f"\n✅ 批量同步完成: 更新{updated}单, 跳过(无重量){skipped_no_weight}, 无匹配{skipped_no_match}")
    return updated

def update_billed():
    """将 billed_weight_g 统一设为 actual_weight_g（计费重量 = 仓库实称）"""
    conn = sqlite3.connect(DB_PATH)
    empty = conn.execute("SELECT COUNT(*) FROM orders WHERE actual_weight_g IS NOT NULL AND actual_weight_g > 0 AND (billed_weight_g IS NULL OR billed_weight_g = 0)").fetchone()[0]
    if empty == 0:
        total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        filled = conn.execute("SELECT COUNT(*) FROM orders WHERE billed_weight_g IS NOT NULL AND billed_weight_g > 0").fetchone()[0]
        print(f"billed_weight_g 全部已填: {filled}/{total}")
        conn.close()
        return
    
    conn.execute("""
        UPDATE orders 
        SET billed_weight_g = actual_weight_g,
            updated_at = ?
        WHERE actual_weight_g IS NOT NULL 
          AND actual_weight_g > 0 
          AND (billed_weight_g IS NULL OR billed_weight_g = 0)
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
    conn.commit()
    cnt = conn.execute("SELECT changes()").fetchone()[0]
    total_filled = conn.execute("SELECT COUNT(*) FROM orders WHERE billed_weight_g IS NOT NULL AND billed_weight_g > 0").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    conn.close()
    print(f"✅ billed_weight_g 已更新{cnt}单，累计{total_filled}/{total}")

def compare_bulk(limit: int = 100):
    """对比 申报(weight_g) vs 入库(actual_weight_g)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    cur = conn.execute("""
        SELECT order_no, weight_g, actual_weight_g, billed_weight_g,
               (actual_weight_g - weight_g) as diff_g,
               ROUND((actual_weight_g - weight_g) * 100.0 / NULLIF(weight_g, 0), 1) as diff_pct,
               sender, line_name, created_at, status
        FROM orders
        WHERE actual_weight_g IS NOT NULL AND weight_g IS NOT NULL
          AND actual_weight_g != weight_g
          AND actual_weight_g > 0 AND weight_g > 0
        ORDER BY ABS(actual_weight_g - weight_g) DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    
    if not rows:
        print("❌ 没有差异数据")
        conn.close()
        return
    
    total_declared = sum(r["weight_g"] for r in rows)
    total_actual = sum(r["actual_weight_g"] for r in rows)
    total_diff = total_actual - total_declared
    
    print(f"\n{'='*100}")
    print(f"📊 申报重量(weight_g) vs 入库重量(actual_weight_g) - TOP {len(rows)}")
    print(f"{'='*100}")
    print(f"{'#':3s} {'订单号':18s} {'寄件人':16s} {'线路':15s} {'申报':7s} {'入库':7s} {'差异(g)':8s} {'差异%':7s}")
    print(f"{'-'*90}")
    
    for i, r in enumerate(rows, 1):
        d = r["weight_g"]
        a = r["actual_weight_g"]
        diff = r["diff_g"]
        pct = r["diff_pct"]
        marker = "🔴" if abs(pct or 0) > 15 else "🟡" if abs(pct or 0) > 5 else "🟢"
        print(f"{marker} {i:2d} {r['order_no']:18s} {(r['sender'] or '?'):16s} {(r['line_name'] or '?'):15s} {d:>5d}g {a:>5d}g {diff:+6d}g {pct:+5.1f}%")
    
    print(f"{'-'*90}")
    print(f"{'合计':42s} {total_declared:>5d}g {total_actual:>5d}g {total_diff:+6d}g {total_diff/total_declared*100:+5.1f}%")
    
    # 按线路统计
    print(f"\n{'='*60}")
    print(f"📊 按线路统计")
    print(f"{'='*60}")
    cur2 = conn.execute("""
        SELECT 
            CASE 
                WHEN line_name LIKE '%奶粉%' THEN '奶粉专线'
                WHEN line_name LIKE '%菲莱套装%' THEN '菲莱套装'
                WHEN line_name LIKE '%莱菲套%' THEN '莱菲套线'
                WHEN line_name LIKE '%菲莱%' THEN '菲莱专线'
                WHEN line_name LIKE '%杂货%' THEN '杂货专线'
                ELSE line_name
            END as line_group,
            COUNT(*) as cnt,
            SUM(actual_weight_g - weight_g) as total_diff_g,
            ROUND(AVG(actual_weight_g - weight_g), 1) as avg_diff_g,
            ROUND(AVG((actual_weight_g - weight_g) * 100.0 / NULLIF(weight_g, 0)), 1) as avg_diff_pct
        FROM orders
        WHERE actual_weight_g IS NOT NULL AND weight_g IS NOT NULL
          AND actual_weight_g != weight_g
          AND actual_weight_g > 0 AND weight_g > 0
        GROUP BY line_group
        ORDER BY total_diff_g DESC
    """)
    print(f"{'线路':16s} {'单数':8s} {'总差(g)':12s} {'均差(g)':10s} {'均差%':8s}")
    for r in cur2.fetchall():
        print(f"{r[0]:16s} {r[1]:6d}单 {r[2]:+8d}g {r[3]:+6.0f}g {r[4]:+5.1f}%")
    
    conn.close()

def monthly_report(months: int = 3):
    """
    月度运费差异分析报告
    按月份+线路 统计申报vs实称的差异，估算运费多付金额
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    print(f"\n{'='*80}")
    print(f"📊 月度运费差异分析报告 (最近{months}个月)")
    print(f"{'='*80}")
    
    # 1. 按月+线路统计
    cur = conn.execute("""
        SELECT 
            strftime('%Y-%m', created_at) as month,
            CASE 
                WHEN line_name LIKE '%奶粉%' THEN '奶粉专线'
                WHEN line_name LIKE '%菲莱套装%' THEN '菲莱套装'
                WHEN line_name LIKE '%莱菲套%' THEN '莱菲套线'
                WHEN line_name LIKE '%菲莱%' THEN '菲莱专线'
                WHEN line_name LIKE '%杂货%' THEN '杂货专线'
                ELSE line_name
            END as line_group,
            COUNT(*) as cnt,
            SUM(weight_g) as total_declared_g,
            SUM(actual_weight_g) as total_actual_g,
            ROUND(AVG(actual_weight_g - weight_g), 1) as avg_diff_g,
            ROUND(AVG((actual_weight_g - weight_g) * 100.0 / NULLIF(weight_g, 0)), 1) as avg_diff_pct
        FROM orders
        WHERE actual_weight_g IS NOT NULL AND weight_g IS NOT NULL
          AND actual_weight_g > 0 AND weight_g > 0
          AND actual_weight_g != weight_g
          AND created_at >= date('now', ?)
        GROUP BY month, line_group
        ORDER BY month DESC, total_actual_g - total_declared_g DESC
    """, (f'-{months} months',))
    
    rows = cur.fetchall()
    if not rows:
        print("❌ 近3个月无差异数据")
        conn.close()
        return
    
    print(f"{'月份':10s} {'线路':10s} {'单数':5s} {'申报(kg)':10s} {'实称(kg)':10s} {'多报(kg)':10s} {'均差(g)':8s} {'均差%':6s}")
    print(f"{'-'*72}")
    
    grand_cnt = grand_declared = grand_actual = grand_diff = 0
    for r in rows:
        extra_kg = (r["total_actual_g"] - r["total_declared_g"]) / 1000
        print(f"{r['month']:10s} {r['line_group']:10s} {r['cnt']:5d} {r['total_declared_g']/1000:>8.1f} {r['total_actual_g']/1000:>8.1f} {extra_kg:>8.1f} {r['avg_diff_g']:>+6.1f}g {r['avg_diff_pct']:>+5.1f}%")
        grand_cnt += r["cnt"]
        grand_declared += r["total_declared_g"]
        grand_actual += r["total_actual_g"]
    
    grand_extra_kg = (grand_actual - grand_declared) / 1000
    print(f"{'-'*72}")
    print(f"{'合计':21s} {grand_cnt:5d} {grand_declared/1000:>8.1f} {grand_actual/1000:>8.1f} {grand_extra_kg:>8.1f}")
    
    # 2. 估算多付运费
    print(f"\n{'='*80}")
    print(f"💰 运费多付估算")
    print(f"{'='*80}")
    print(f"按照奶粉专线 ~€6/kg, 菲莱专线 ~€5/kg 估算")
    print()
    
    for r in rows:
        extra_kg = (r["total_actual_g"] - r["total_declared_g"]) / 1000
        if extra_kg <= 0: continue
        rate = 6 if "奶粉" in r["line_group"] else 5
        est_cost = extra_kg * rate
        # 按首重+续重计算更精确的估算
        # 按平均每单超重计算
        avg_extra_g = r["avg_diff_g"]
        if avg_extra_g <= 0: continue
        print(f"  {r['month']} | {r['line_group']:10s} | {r['cnt']}单 | 均超{avg_extra_g:.0f}g/单 | 累计多付 ~€{est_cost:.0f}")
    
    # 3. 寄件人维度统计（超重最多的寄件人）
    print(f"\n{'='*80}")
    print(f"🔍 超重最多的寄件人 (Top 10)")
    print(f"{'='*80}")
    cur2 = conn.execute("""
        SELECT sender, COUNT(*) as cnt,
               SUM(actual_weight_g - weight_g) as total_extra_g,
               ROUND(AVG(actual_weight_g - weight_g), 1) as avg_extra_g,
               ROUND(AVG((actual_weight_g - weight_g) * 100.0 / NULLIF(weight_g, 0)), 1) as avg_extra_pct
        FROM orders
        WHERE actual_weight_g IS NOT NULL AND weight_g IS NOT NULL
          AND actual_weight_g > 0 AND weight_g > 0
          AND actual_weight_g != weight_g
          AND created_at >= date('now', ?)
        GROUP BY sender
        HAVING total_extra_g > 0
        ORDER BY total_extra_g DESC
        LIMIT 10
    """, (f'-{months} months',))
    
    print(f"{'寄件人':16s} {'单数':5s} {'累计超重(kg)':14s} {'均超(g)':8s} {'均超%':7s}")
    print(f"{'-'*52}")
    for r in cur2.fetchall():
        print(f"{(r['sender'] or '?'):16s} {r['cnt']:5d} {r['total_extra_g']/1000:>9.1f}kg {r['avg_extra_g']:>+6.1f}g {r['avg_extra_pct']:>+5.1f}%")
    
    # 4. 改善建议
    print(f"\n{'='*80}")
    print(f"💡 改善建议")
    print(f"{'='*80}")
    print("""
1️⃣ 奶粉专线: 申报1600g→实际平均2153g(+553g)，建议申报统一调整为2200g
2️⃣ JYTB(菲莱专线): 全部报1000g但轻重不一(180~1980g)，建议按实际产品分重量申报
3️⃣ lebenswelle1: 奶粉每单均超500g+，建议包装后先称重再申报
4️⃣ 菲莱套装: 均超127g(+6.8%)，可以忽略或适当上调
""")
    
    conn.close()

def main():
    print(f"🚀 入库重量批量同步 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    token = login()
    if not token:
        print("❌ 登录失败")
        return
    sync_bulk(token)
    update_billed()
    compare_bulk(limit=30)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", default="sync", 
                       choices=["sync","compare","billed","report","all"])
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--force", action="store_true", 
                       help="全量刷新(覆盖已有actual_weight)")
    args = parser.parse_args()
    
    if args.action == "compare":
        compare_bulk(limit=args.limit)
    elif args.action == "billed":
        update_billed()
    elif args.action == "report":
        monthly_report(months=args.months)
    elif args.action == "sync":
        main()
    elif args.action == "all":
        token = login()
        if token:
            sync_bulk(token, force=args.force)
            update_billed()
        compare_bulk(limit=args.limit)
        monthly_report(months=args.months)
