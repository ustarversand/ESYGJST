#!/usr/bin/env python3
"""修复被截断的 april_tracking_results.json"""
import json, re

path = '/opt/data/workspace/heute_express/data/april_tracking_results.json'
with open(path) as f:
    raw = f.read()

# Method 1: find last complete entry by "queried_at" pattern
matches = [m.start() for m in re.finditer(r'"queried_at": "[^"]+"}', raw)]
if matches:
    last_end = matches[-1]
    entry_end = last_end + len('"queried_at": "2026-05-15T12:10:07"}')
    valid = raw[:entry_end] + '}'
    try:
        data = json.loads(valid)
        with open(path, 'w') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
        print(f'✅ 修复成功! {len(data)} 条记录')
        exit(0)
    except json.JSONDecodeError as e:
        print(f'方法1失败: {e}')

# Method 2: find last complete key
all_keys = list(re.finditer(r'"DEUHYD\d+EU"', raw))
if len(all_keys) >= 2:
    second_last_start = all_keys[-2].start()
    valid2 = raw[:second_last_start].rstrip(',') + '}'
    try:
        data = json.loads(valid2)
        with open(path, 'w') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
        print(f'✅ 修复成功(方法2)! {len(data)} 条记录')
        exit(0)
    except json.JSONDecodeError as e:
        print(f'方法2失败: {e}')

print('❌ 所有修复方法失败，删除后从头开始')
import os
os.remove(path)
print('文件已删除')
