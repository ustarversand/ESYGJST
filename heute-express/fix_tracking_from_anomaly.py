#!/usr/bin/env python3
"""读取 anomaly_comparison_{month}.json → 修正 tracking cache 中的 severe 订单"""
import json, sys, os

DATA_DIR = '/app/data'

def fix_tracking(month: str):
    anomaly_file = os.path.join(DATA_DIR, f'anomaly_comparison_{month}.json')
    tracking_file = os.path.join(DATA_DIR, f'{month}_tracking_results.json')
    
    if not os.path.exists(anomaly_file):
        print(f"❌ {anomaly_file} not found")
        return
    
    with open(anomaly_file, 'r') as f:
        anomalies = json.load(f)
    
    with open(tracking_file, 'r') as f:
        tracking = json.load(f)
    
    fixed = 0
    for a in anomalies:
        if a.get('match') != 'severe':
            continue
        
        intl_tn = a.get('intl_tracking', '')
        dom = a.get('dom', {})
        
        if intl_tn not in tracking:
            continue
        
        td = tracking[intl_tn].get('tracking', {})
        old_status = td.get('currentStatus', '')
        
        # Already fixed
        if '签收' in old_status:
            continue
        
        dom_time = dom.get('latest_time', '')[:16]
        td['currentStatus'] = '签收(国内确认)'
        td['latestDesc'] = f'[国内{dom_time}确认签收] {dom.get("latest_desc", "")}'
        td['latestTime'] = dom.get('latest_time', '')
        td['_fix_source'] = 'auto-fix-from-anomaly-comparison'
        fixed += 1
        print(f"  ✅ {intl_tn[:28]} | {old_status} → 签收(国内确认)")
    
    if fixed > 0:
        with open(tracking_file, 'w') as f:
            json.dump(tracking, f, ensure_ascii=False, indent=2)
        print(f"\n🔧 FIXED: {fixed} orders in {tracking_file}")
    else:
        print("\n✅ No new fixes needed")

if __name__ == '__main__':
    month = sys.argv[1] if len(sys.argv) > 1 else 'april'
    fix_tracking(month)
