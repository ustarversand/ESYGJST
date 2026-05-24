"""直邮管家 — Web 服务
"""
import os
import json
import logging
import tempfile
from datetime import datetime
from flask import Flask, request, jsonify, render_template, session, g

# ===== 应用初始化 =====
from config import HOST, PORT, DEBUG, SHOPS, USERS
from push_engine import push_order, push_orders_batch, get_shop_list, check_jst_connection, search_products
from excel_parser import parse_excel
from order_parser import parse_order_text
import push_records
import heuste_client
import idcard_handler

# ===== 认证模块 =====
from auth import auth_bp, login_required

# ===== 店铺智能路由规则 =====
SHOP_ROUTING = {
    "武姐": "武姐",
    "韦峥": "韦峥",
    "夏总": "夏总WX",
    "天海": "夏总天海易购",
    "沐浴阳光": "沐浴阳光PDD",
    "PDD": "沐浴阳光PDD",
    "甘总": "甘总-付总",
    "付总": "甘总-付总",
    "乔妈": "乔妈",
    "路久": "A路久",
    "德聚": "德聚小罗",
    "小罗": "德聚小罗",
    "阿美": "阿美奶粉",
    "沐浴阳光JD": "沐浴阳光JD",
    "京东": "沐浴阳光JD",
    "Asweety": "Asweety",
    "高总": "A高总",
    "智能体": "智能体AI店铺",
}
DEFAULT_SHOP_KEY = "AUSTARWX"


def resolve_shop(sender_name: str = "", buyer_message: str = "", excel_shop: str = "") -> str:
    if excel_shop and excel_shop in SHOPS:
        return excel_shop
    text = f"{sender_name or ''} {buyer_message or ''}".lower()
    for keyword, shop in SHOP_ROUTING.items():
        if keyword.lower() in text:
            logger.info(f"[路由] 关键词'{keyword}' → {shop}")
            return shop
    return DEFAULT_SHOP_KEY


# ===== 日志 =====
from logging.handlers import RotatingFileHandler
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler("zygj.log", maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'),
    ]
)
logger = logging.getLogger("zygj-web")

# ===== Flask =====
app = Flask(__name__)
# 持久化 secret_key 到文件，避免重启后用户需重新登录
SECRET_KEY_FILE = os.path.join(os.path.dirname(__file__), ".secret_key")
if os.path.exists(SECRET_KEY_FILE):
    with open(SECRET_KEY_FILE, "r") as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.urandom(24).hex()
    with open(SECRET_KEY_FILE, "w") as f:
        f.write(app.secret_key)
app.register_blueprint(auth_bp)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_user_visible_shops() -> list:
    """获取当前用户可见的店铺列表"""
    user = session.get("user", {})
    shop_key = user.get("shop_key")
    if shop_key:
        if shop_key in SHOPS:
            return [shop_key]
        return []
    return list(SHOPS.keys())


# ==================== 首页 ====================

@app.route("/")
@login_required
def index():
    visible_keys = get_user_visible_shops()
    shops = [s for s in get_shop_list() if s["key"] in visible_keys]
    user_info = session.get("user", {})
    return render_template("index.html", shops=shops, now=datetime.now().strftime("%Y-%m-%d %H:%M"),
                           current_user=user_info)


# ==================== API: 推单 ====================

@app.route("/api/push", methods=["POST"])
@login_required
def api_push():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"success": False, "msg": "请求体不能为空"}), 400

    missing = []
    for field in ["receiver_name", "receiver_phone", "receiver_address"]:
        if not data.get(field):
            missing.append(field)
    if missing:
        return jsonify({"success": False, "msg": f"缺少必填字段: {', '.join(missing)}"}), 400

    items = data.get("items", [])
    if not items:
        sku_id = data.get("sku_id", "").strip()
        item_name = data.get("item_name", "").strip()
        qty = int(data.get("qty", 1))
        price = float(data.get("price", 0))
        if sku_id or item_name:
            items.append({
                "sku_id": sku_id,
                "name": item_name or sku_id,
                "qty": qty,
                "price": price,
            })
    else:
        for it in items:
            it.setdefault("sku_id", it.get("sku", ""))
            it.setdefault("name", it.get("item_name", ""))
            it.setdefault("qty", int(it.get("qty", 1)))
            it.setdefault("price", float(it.get("price", 0)))

    if not items:
        return jsonify({"success": False, "msg": "请输入至少一个商品SKU"}), 400

    pay_amount = data.get("pay_amount")
    if not pay_amount or float(pay_amount) <= 0:
        pay_amount = sum(it["qty"] * it["price"] for it in items)

    shop_key = data.get("shop_key") or ""
    # 如果用户绑定了店铺，强制使用绑定店铺
    user = session.get("user", {})
    bound_shop = user.get("shop_key")
    if bound_shop:
        shop_key = bound_shop
    elif shop_key not in SHOPS:
        sender_name = data.get("sender_name", "")
        shop_key = resolve_shop(sender_name, data.get("buyer_message", ""), shop_key)

    logger.info(f"[路由] 手动录入: sender={data.get('sender_name','')} → {shop_key}")

    order = {
        "so_id": data.get("so_id", ""),
        "receiver_name": data["receiver_name"].strip(),
        "receiver_phone": data["receiver_phone"].strip(),
        "receiver_state": data.get("receiver_state", "").strip(),
        "receiver_city": data.get("receiver_city", "").strip(),
        "receiver_district": data.get("receiver_district", "").strip(),
        "receiver_address": data["receiver_address"].strip(),
        "buyer_message": data.get("buyer_message", "").strip(),
        "id_card_number": data.get("id_card_number", "").strip(),
        "pay_amount": float(pay_amount),
        "freight": float(data.get("freight", 0)),
        "items": items,
    }

    logger.info(f"[推单] 手动录入: {order['receiver_name']} / {shop_key}")
    result = push_order(order, shop_key)
    logger.info(f"[推单] 结果: {result}")
    return jsonify(result)


def _group_orders_by_shop(orders_data: list, bound_shop: str, user_shop_key: str) -> dict:
    """按店铺分组订单（去重逻辑，供 api_push_batch 复用）"""
    shop_groups = {}
    for order in orders_data:
        sender = order.pop("sender_name", "")
        excel_shop = order.pop("shop_key", "")

        if bound_shop:
            sk = bound_shop
        elif user_shop_key and user_shop_key in SHOPS:
            sk = user_shop_key
        else:
            sk = resolve_shop(sender, "", excel_shop)
        logger.info(f"[路由] {order.get('receiver_name','')} 寄件人={sender} → {sk}")
        if sk not in shop_groups:
            shop_groups[sk] = []
        shop_groups[sk].append(order)
    return shop_groups


def _build_preview_results(shop_groups: dict) -> list:
    """生成预览结果（供 api_push_batch 复用）"""
    from push_engine import search_products as _sp
    preview_results = []
    for sk, group_orders in shop_groups.items():
        for o in group_orders:
            items = o.get("items", [])
            sku_ids = []
            for it in items:
                pname = it.get("name", "")
                matched = _sp(pname, limit=1) if pname else []
                sku_ids.append({
                    "name": pname,
                    "matched_sku": matched[0].get("sku_id", "") if matched else "",
                    "matched": bool(matched),
                })
            preview_results.append({
                "receiver": o.get("receiver_name", ""),
                "phone": o.get("receiver_phone", ""),
                "address": o.get("receiver_address", ""),
                "shop": sk,
                "items": sku_ids,
                "ready": bool(items and any(it.get("name") for it in items)),
            })
    return preview_results


# ==================== API: 批量推单（Excel上传） ====================

@app.route("/api/push/batch", methods=["POST"])
@login_required
def api_push_batch():
    # 检查是否为预览模式
    is_preview = request.form.get("preview", "false").lower() == "true"
    
    if "file" not in request.files:
        return jsonify({"success": False, "msg": "请上传Excel文件"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "msg": "文件名不能为空"}), 400

    suffix = os.path.splitext(file.filename)[1] or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=UPLOAD_DIR) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    user = session.get("user", {})
    bound_shop = user.get("shop_key")

    try:
        user_shop_key = request.form.get("shop_key", "").strip()
        if bound_shop:
            user_shop_key = bound_shop

        orders_data = parse_excel(tmp_path)

        if orders_data:
            sample = orders_data[0]
            keys_detected = list(sample.keys())
            has_sku = bool(sample.get("items") and sample["items"][0].get("sku_id"))
            has_item_name = bool(sample.get("items") and sample["items"][0].get("name"))
            logger.info(f"[Excel] 解析到 {len(orders_data)} 行, 用户选择店铺={user_shop_key!r}, 字段: {keys_detected}, 有SKU={has_sku}, 有商品名={has_item_name}")
            for i, o in enumerate(orders_data[:3]):
                logger.info(f"[Excel] 第{i+1}行: name={o.get('receiver_name')}, items={o.get('items')}")

        if not orders_data:
            return jsonify({"success": False, "msg": "未识别到任何订单数据，请检查Excel格式"}), 400

        empty_items = sum(1 for o in orders_data if not o.get("items"))
        if empty_items == len(orders_data):
            return jsonify({
                "success": False,
                "msg": f"Excel中没有识别到商品列（商品编码/商品名称），已解析{len(orders_data)}行但全无商品明细",
                "total": 0, "success_count": 0, "fail_count": 0, "results": []
            }), 400

        # 按店铺分组（统一逻辑，只做一次）
        shop_groups = _group_orders_by_shop(orders_data, bound_shop, user_shop_key)

        # ===== 预览模式：只解析不推送 =====
        if is_preview:
            preview_results = _build_preview_results(shop_groups)
            return jsonify({
                "success": True,
                "preview": True,
                "total": len(preview_results),
                "results": preview_results,
            })

        # ===== 实际推送 =====
        results = []
        total_success = 0
        total_fail = 0

        for sk, group_orders in shop_groups.items():
            for o in group_orders:
                if not o.get("items"):
                    total_fail += 1
                    results.append({
                        "so_id": o.get("so_id", ""),
                        "receiver": o.get("receiver_name", ""),
                        "shop": SHOPS.get(sk, {}).get("name", sk),
                        "success": False,
                        "msg": "无商品明细，跳过",
                    })
                    continue
                r = push_order(o, sk)
                if r.get("success"):
                    total_success += 1
                else:
                    total_fail += 1
                results.append({
                    "so_id": o.get("so_id", ""),
                    "receiver": o.get("receiver_name", ""),
                    "shop": SHOPS.get(sk, {}).get("name", sk),
                    "success": r.get("success"),
                    "msg": r.get("msg", "未知错误"),
                })

        return jsonify({
            "success": total_fail == 0,
            "total": len(results),
            "success_count": total_success,
            "fail_count": total_fail,
            "results": results,
        })

    except Exception as e:
        logger.exception("[推单] 批量处理异常")
        return jsonify({"success": False, "msg": f"处理异常: {str(e)}"}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ==================== API: 店铺列表 ====================

@app.route("/api/shops", methods=["GET"])
@login_required
def api_shops():
    visible_keys = get_user_visible_shops()
    all_shops = get_shop_list()
    filtered = [s for s in all_shops if s["key"] in visible_keys]
    return jsonify({"shops": filtered})


# ==================== API: 健康检查 ====================

@app.route("/api/health", methods=["GET"])
def api_health():
    jst = check_jst_connection()
    return jsonify({
        "status": "ok" if jst.get("connected") else "degraded",
        "jst_connected": jst.get("connected"),
        "jst_msg": jst.get("msg", ""),
        "shops_count": len(SHOPS),
        "time": datetime.now().isoformat(),
    })


# ==================== API: 一段话解析 ====================

@app.route("/api/parse-order", methods=["POST"])
@login_required
def api_parse_order():
    data = request.get_json(force=True, silent=True)
    if not data or not data.get("text"):
        return jsonify({"success": False, "msg": "请输入订单文本"}), 400
    result = parse_order_text(data["text"])
    if result.get("success") and result.get("receiver_name") and result.get("id_card_number"):
        try:
            from 身份证上传 import idcard_cache_db as idcard_db
            name = result["receiver_name"]
            idn = result["id_card_number"]
            idcard_db.save_to_local(name, idn, verified=False)
        except Exception:
            pass
    return jsonify(result)


# ==================== API: 商品搜索 ====================

@app.route("/api/product-search", methods=["GET"])
@login_required
def api_product_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})
    results = search_products(q, limit=10)
    return jsonify({"results": results})


# ==================== API: 物流查询 ====================

@app.route("/api/query-logistics", methods=["POST"])
@login_required
def api_query_logistics():
    data = request.get_json(force=True, silent=True)
    if not data or not data.get("name"):
        return jsonify({"success": False, "msg": "请提供收件人姓名(name)"}), 400

    name = data["name"].strip()
    phone = data.get("phone", "").strip()
    sender = data.get("sender", "").strip()

    orders = heuste_client.search_orders_by_receiver(name, phone, sender=sender)

    # ===== 数据隔离：已绑定店铺的用户只能看到自己店铺的订单 =====
    # merchant_sn 格式: {shop_id}-{order_ref}（如 "19437979-458278-02"）
    user = session.get("user", {})
    bound_shop = user.get("shop_key")
    if bound_shop:
        from config import SHOPS
        shop_info = SHOPS.get(bound_shop)
        if shop_info:
            shop_id = str(shop_info.get("id", ""))
            prefix = f"{shop_id}-"
            before = len(orders)
            orders = [o for o in orders if o.get("merchant_sn", "").startswith(prefix)]
            logger.info(f"[数据隔离] {bound_shop}({shop_id}) 过滤: {before}→{len(orders)}单")

    # 按创建时间倒序（最新在前）
    orders.sort(key=lambda o: o.get("created", ""), reverse=True)

    return jsonify({
        "success": True,
        "data": orders,
    })


# ==================== API: 推单记录列表 ====================

@app.route("/api/push-records", methods=["GET"])
@login_required
def api_push_records():
    q = request.args.get("q", "").strip()
    limit = int(request.args.get("limit", 50))
    if q:
        records = push_records.search_records(q, limit)
    else:
        records = push_records.get_all_records(limit)
    
    # ===== 数据隔离：已绑定店铺的用户只能看到自己店铺的记录 =====
    user = session.get("user", {})
    bound_shop = user.get("shop_key")
    if bound_shop:
        from config import SHOPS
        shop_info = SHOPS.get(bound_shop)
        if shop_info:
            shop_id = str(shop_info.get("id", ""))
            prefix = f"{shop_id}-"
            before = len(records)
            records = [r for r in records if str(r.get("shop_id", "")).startswith(prefix) or r.get("shop") == bound_shop]
            logger.info(f"[数据隔离] {bound_shop}({shop_id}) 过滤: {before}→{len(records)}条")
    
    return jsonify({
        "success": True,
        "total": len(records),
        "records": records,
    })


# ==================== API: 身份证 ====================

@app.route("/api/idcard/check", methods=["POST"])
@login_required
def api_idcard_check():
    data = request.get_json(force=True, silent=True)
    name = (data or {}).get("name", "").strip()
    id_number = (data or {}).get("id_number", "").strip()
    if not name or not id_number:
        return jsonify({"success": False, "msg": "请提供姓名和身份证号"}), 400
    result = idcard_handler.check_idcard(name, id_number)
    return jsonify(result)


@app.route("/api/idcard/check-by-name", methods=["POST"])
def api_idcard_check_by_name():
    data = request.get_json(force=True, silent=True)
    name = (data or {}).get("name", "").strip()
    if not name:
        return jsonify({"found": False, "msg": "请提供姓名"}), 400
    try:
        from 身份证上传 import idcard_cache_db
        matches = idcard_cache_db.check_local_by_name(name)
        if matches:
            best = matches[-1] if isinstance(matches, list) else matches
            id_number = best.get("id_card_number", "") if isinstance(best, dict) else str(best)
            return jsonify({"found": True, "id_number": id_number, "name": name})
        return jsonify({"found": False})
    except Exception as e:
        return jsonify({"found": False, "msg": str(e)})


@app.route("/api/idcard/upload", methods=["POST"])
@login_required
def api_idcard_upload():
    name = request.form.get("name", "").strip()
    id_number = request.form.get("id_number", "").strip()
    front_file = request.files.get("front")
    reverse_file = request.files.get("reverse")

    if not name or not id_number:
        return jsonify({"success": False, "msg": "请提供姓名和身份证号"}), 400
    if not front_file:
        return jsonify({"success": False, "msg": "请上传身份证正面照片"}), 400
    if not reverse_file:
        return jsonify({"success": False, "msg": "请上传身份证反面照片"}), 400

    front_path = idcard_handler.save_uploaded_file(front_file)
    reverse_path = idcard_handler.save_uploaded_file(reverse_file)

    result = idcard_handler.smart_process(name, id_number, front_path, reverse_path)

    if result.get("success"):
        ocr_result = idcard_handler.ocr_idcard(front_path)
        if ocr_result.get("success"):
            result["ocr"] = ocr_result

    return jsonify(result)


@app.route("/api/idcard/ocr", methods=["POST"])
@login_required
def api_idcard_ocr():
    file = request.files.get("image")
    if not file:
        return jsonify({"success": False, "msg": "请上传身份证照片"}), 400

    path = idcard_handler.save_uploaded_file(file)
    path = idcard_handler.auto_process_image(path, is_front=True)
    result = idcard_handler.ocr_idcard(path)
    if result.get("success") and result.get("name") and result.get("id_number"):
        try:
            from 身份证上传 import idcard_cache_db as idcard_db
            idcard_db.save_to_local(result["name"], result["id_number"], verified=False)
        except Exception:
            pass
    return jsonify(result)


# ==================== 启动 ====================

if __name__ == "__main__":
    print(f"🚀 直邮管家启动: http://{HOST}:{PORT}")
    print(f"📦 店铺数: {len(SHOPS)}")
    print(f"👥 用户数: {len(USERS)}")
    app.run(host=HOST, port=PORT, debug=DEBUG)
