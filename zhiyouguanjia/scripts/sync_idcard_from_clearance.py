"""从清关资料看板同步身份证数据到直邮管家"""
import sqlite3
import logging
import re
import sys
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync-idcard")

# 清关看板数据库（Hermes 容器侧路径）
SRC_DB = "/opt/data/workspace/customs-clearance-dashboard/data/customs_clearance.db"
# 直邮管家数据库
DST_DB = "/opt/data/workspace/zhiyouguanjia/身份证上传/idcard_cache.db"


def is_valid_id_card(name: str, id_number: str) -> bool:
    """过滤无效/测试数据"""
    # 姓名至少2个汉字
    if not name or len(name) < 2:
        return False
    # 姓名不能含数字
    if re.search(r'\d', name):
        return False
    # 过滤测试名
    _test_names = {'test', '测试', 'testd', 'terst', 'gaok', 'w3441', 'test1', 'test2'}
    if name.lower().strip() in _test_names:
        return False
    # 身份证号15或18位
    if not re.match(r'^\d{15,17}[\dXx]?$', id_number):
        return False
    # 身份证号不能全是相同数字（测试数据特征）
    if len(set(id_number)) <= 2:
        return False
    return True


def sync():
    if not os.path.exists(SRC_DB):
        logger.error(f"源数据库不存在: {SRC_DB}")
        return False
    if not os.path.exists(DST_DB):
        logger.warning(f"目标数据库不存在，将创建: {DST_DB}")
        os.makedirs(os.path.dirname(DST_DB), exist_ok=True)

    # 读源数据
    src = sqlite3.connect(SRC_DB)
    src.row_factory = sqlite3.Row
    rows = src.execute(
        "SELECT id_card_name, id_card_number FROM idcard_verification "
        "WHERE id_card_name != '' AND length(id_card_number) >= 15 "
        "ORDER BY id_card_name"
    ).fetchall()
    src.close()
    logger.info(f"从清关看板读取 {len(rows)} 条记录")

    # 打开目标库
    dst = sqlite3.connect(DST_DB)
    
    # 先统计已有记录
    existing = set()
    cur = dst.execute("SELECT id_card_number FROM idcard_cache")
    for row in cur:
        existing.add(row[0])
    logger.info(f"直邮管家已有 {len(existing)} 条身份证记录")

    # 批量导入
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    added = 0
    skipped = 0
    filtered = 0

    dst.execute("BEGIN TRANSACTION")
    for row in rows:
        name = row["id_card_name"].strip()
        id_number = row["id_card_number"].strip()

        if not is_valid_id_card(name, id_number):
            filtered += 1
            continue

        if id_number in existing:
            skipped += 1
            continue

        dst.execute(
            "INSERT OR IGNORE INTO idcard_cache (id_card_number, id_card_name, is_authenticated, checked_at) "
            "VALUES (?, ?, 1, ?)",
            (id_number, name, now)
        )
        added += 1

    dst.execute("COMMIT")
    dst.close()

    logger.info(f"同步完成: 新增 {added}, 跳过已有 {skipped}, 过滤无效 {filtered}")
    return True


if __name__ == "__main__":
    success = sync()
    sys.exit(0 if success else 1)
