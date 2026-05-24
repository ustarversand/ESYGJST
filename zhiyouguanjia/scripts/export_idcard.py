"""从清关看板同步身份证数据到直邮管家"""
import sqlite3
import json
import sys
import re
from datetime import datetime

def main():
    src_db = "/opt/data/workspace/customs-clearance-dashboard/data/customs_clearance.db"
    
    conn = sqlite3.connect(src_db)
    rows = conn.execute(
        "SELECT id_card_name, id_card_number FROM idcard_verification "
        "WHERE id_card_name != '' AND length(id_card_number) >= 15"
    ).fetchall()
    conn.close()

    # 过滤无效数据
    test_names = {'test','测试','testd','terst','gaok','w3441','test1','test2','测试名','测试姓名','测试底子','我们','看到你','先生','女士','小姐', '李先生','张女士','刘先生','刘总','王先生','陈小姐','李小姐','阿丫\n阿丫'}
    valid = []
    bad = 0
    for name, idn in rows:
        name = name.strip()
        idn = idn.strip()
        if len(name) < 2 or re.search(r'\d', name): bad += 1; continue
        if name.lower() in test_names: bad += 1; continue
        if not re.match(r'^\d{15,17}[\dXx]?$', idn): bad += 1; continue
        if len(set(idn)) <= 2: bad += 1; continue
        valid.append((name, idn))
    
    # 输出为 JSON lines 格式
    print(json.dumps({"count": len(valid), "bad": bad}))
    for name, idn in valid:
        print(json.dumps([name, idn]))

if __name__ == "__main__":
    main()
