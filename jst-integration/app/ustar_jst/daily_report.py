#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate daily sales report for JST"""

import sqlite3
import sys

def main():
    conn = sqlite3.connect('/opt/data/workspace/ustar-deploy/app/ustar_jst/orders.db')
    last_date = '2026-05-12'

    # Overall stats
    cursor = conn.execute('''
        SELECT 
            COUNT(*) as total_orders,
            COALESCE(SUM(pay_amount), 0) as total_amount,
            SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) as cancelled
        FROM orders
        WHERE substr(created_time, 1, 10) = ?
    ''', (last_date,))
    total_orders, total_amount, cancelled = cursor.fetchone()
    cancelled_pct = (cancelled / total_orders * 100) if total_orders > 0 else 0

    # Shop distribution
    cursor = conn.execute('''
        SELECT shop_name, COUNT(*) as cnt, COALESCE(SUM(pay_amount), 0) as amt
        FROM orders
        WHERE substr(created_time, 1, 10) = ?
        GROUP BY shop_id
        ORDER BY cnt DESC
    ''', (last_date,))
    shops = cursor.fetchall()

    # Build report
    report = []
    report.append('=== JST Daily Sales Report ===')
    report.append(f'Date: {last_date}')
    report.append(f'Total Orders: {total_orders}')
    report.append(f'Total Amount: {total_amount:,.2f}')
    if cancelled_pct > 10:
        report.append(f'WARNING: Cancelled {cancelled} ({cancelled_pct:.1f}%)')
    else:
        report.append(f'Cancelled: {cancelled}')
    report.append('')
    report.append('--- Shop Distribution ---')
    for shop_name, cnt, amt in shops:
        report.append(f'{shop_name}: {cnt} orders, {amt:,.2f}')
    report.append('')
    report.append(f'(Note: Data from local cache, latest: {last_date})')

    print('\n'.join(report))

if __name__ == '__main__':
    main()