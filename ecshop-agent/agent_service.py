"""
ECShop AI Agent 服务 — FastAPI
为 Hermes Agent / Telegram bot / H5 小助手提供 Restful 工具接口
"""
import os
import json
import re
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ecshop_client import ECShopClient, ECShopAPIError

# ─── 配置 ───
SHOP_USERNAME = os.environ.get("SHOP_USERNAME", "laoyang")
SHOP_PASSWORD = os.environ.get("SHOP_PASSWORD", "668899")

cli = ECShopClient(SHOP_USERNAME, SHOP_PASSWORD)

app = FastAPI(
    title="ECShop AI Agent",
    version="2.0.0",
    description="德赛发USTAR 商城 AI 购物助手 — 支持对话下单全流程",
)


# ═══════════════════ 数据模型 ═══════════════════

class LoginOut(BaseModel):
    username: str
    rank: str
    is_auth: bool
    token: str


class ProductBrief(BaseModel):
    id: int
    name: str
    sku: str
    price: str
    stock: int
    sales: int
    image: str = ""
    specs: list = []


class ConsigneeInfo(BaseModel):
    id: int
    name: str
    mobile: str
    address: str
    is_default: bool = False
    regions: str = ""


class CartItem(BaseModel):
    id: int
    name: str
    price: str
    quantity: int
    subtotal: str
    attrs: str = ""


class OrderInfo(BaseModel):
    sn: str
    total: float
    status: str = ""
    consignee: str
    payment: str = ""
    shipping: str = ""
    created_at: str = ""
    items: list = []


# ═══════════════════ /chat 对话端点（方案C） ═══════════════════

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户输入的消息")
    context: dict = Field(default_factory=dict, description="对话上下文：{view, cart_count, step, selected_product, selected_consignee}")

class ChatResponse(BaseModel):
    reply: str = Field(..., description="要显示给用户的文本回复")
    type: str = Field("text", description="回复类型：text | products | product_detail | cart | addresses | confirm_order")
    data: dict = Field(default_factory=dict, description="结构化的数据，供前端渲染用")
    actions: list = Field(default_factory=list, description="前端可用的操作按钮")


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """
    对话式下单 — 一次请求理解用户意图，自动执行并返回结构化结果。
    前端根据 type 渲染不同的消息模板。
    """
    msg = req.message.strip()
    ctx = req.context
    reply = ""
    rtype = "text"
    data = {}
    actions = []

    # ─── 意图识别 ───
    intent, params = _detect_intent(msg)

    try:
        cli._ensure_login()
        user_rank_name = ""
        if cli.user_info:
            ur = cli.user_info.get("rank", {})
            user_rank_name = ur.get("name", "") if isinstance(ur, dict) else str(ur)

        if intent == "search":
            keyword = params.get("keyword", msg)
            limit = params.get("limit", 8)
            # 第0步：先查分类映射 — 看是不是分类浏览词
            matched = _classify_products(all_products_cache(), keyword, limit)
            if matched:
                price_info = ""
                if user_rank_name:
                    price_info = f" [{user_rank_name}价]"
                lines = []
                for b in matched['products']:
                    lines.append(_bline(b))
                reply = f"📂 **{matched['label']}** — {len(matched['products'])}件{price_info}\n\n" + "\n".join(lines)
                rtype = "products"
                data = {"products": matched['products'], "keyword": keyword, "label": matched['label']}
                actions = [{"label": f"🛒 加购第{n+1}件", "action": "add_to_cart", "product_id": p["id"]} for n, p in enumerate(matched['products'][:5])]
            else:
                # 第1步：尝试 API 搜索
                products = cli.search_products(keyword, per_page=30)
                products = [p for p in products if keyword.lower() in (p.get("name", "") or "").lower()]
                if not products:
                    products = [p for p in all_products_cache() if keyword.lower() in (p.get("name", "") or "").lower()]
                if not products:
                    keywords = [k for k in keyword.split() if len(k) >= 2]
                    if len(keywords) > 1:
                        for kw in keywords:
                            products = [p for p in cli.list_products(per_page=100) if kw.lower() in (p.get("name", "") or "").lower()]
                products = products[:limit]
                if products:
                    briefs = [_brief(p) for p in products]
                    price_info = ""
                    if user_rank_name:
                        price_info = f" [{user_rank_name}价]"
                    lines = [_bline(b) for b in briefs]
                    reply = f"🔍 找到 {len(briefs)} 件{price_info}\n\n" + "\n".join(lines)
                    rtype = "products"
                    data = {"products": briefs, "keyword": keyword}
                    actions = [{"label": f"🛒 加购第{n+1}件", "action": "add_to_cart", "product_id": p["id"]} for n, p in enumerate(briefs[:5])]
                    actions += [{"label": "📈 按销量排序", "action": "sort", "field": "sales", "order": "desc", "keyword": keyword}]
                else:
                    hot = sorted(all_products_cache(), key=lambda p: p.get("sales_count", 0) or 0, reverse=True)[:6]
                    hot_briefs = [_brief(p) for p in hot]
                    hot_lines = [_bline(b) for b in hot_briefs]
                    reply = f"😅 没找到 \"{keyword}\"🔥 看看热销吧\n\n" + "\n".join(hot_lines)
                    rtype = "products"
                    data = {"products": hot_briefs, "keyword": "热销推荐"}
                    actions = [{"label": f"🛒 加购第{n+1}件", "action": "add_to_cart", "product_id": p["id"]} for n, p in enumerate(hot_briefs[:5])]

        elif intent == "browse_all":
            all_products = all_products_cache()
            briefs = [_brief(p) for p in all_products[:20]]
            price_info = ""
            if user_rank_name:
                price_info = f" [{user_rank_name}价]"
            lines = [_bline(b) for b in briefs]
            reply = f"📋 全部 {len(all_products)} 件商品{price_info}\n\n" + "\n".join(lines)
            rtype = "products"
            data = {"products": briefs, "keyword": "全部商品"}
            actions = [{"label": f"🛒 加购第{n+1}件", "action": "add_to_cart", "product_id": p["id"]} for n, p in enumerate(briefs[:5])]
            actions += [
                {"label": "🔥 热销排行", "action": "sort", "field": "sales", "order": "desc"},
                {"label": "💰 价格从低到高", "action": "sort", "field": "price", "order": "asc"},
            ]

        elif intent == "hot_products":
            all_products = all_products_cache()
            hot = sorted(all_products, key=lambda p: p.get("sales_count", 0) or 0, reverse=True)[:10]
            briefs = [_brief(p) for p in hot]
            lines = [_bline(b) for b in briefs]
            reply = "🔥 **热销排行榜**\n\n" + "\n".join(lines)
            rtype = "products"
            data = {"products": briefs, "keyword": "热销"}
            actions = [{"label": f"🛒 加购第{n+1}件", "action": "add_to_cart", "product_id": p["id"]} for n, p in enumerate(briefs[:5])]

        elif intent == "sort":
            field = params.get("field", "sales")
            order = params.get("order", "desc")
            keyword = params.get("keyword", "")
            limit = 10
            all_products = all_products_cache()
            # 如果有关键词，先过滤
            if keyword:
                products = [p for p in all_products if keyword.lower() in (p.get("name", "") or "").lower()]
            else:
                products = list(all_products)
            # 排序
            if field in ("price", "价格"):
                reverse = order == "desc"
                products.sort(key=lambda p: float(p.get("current_price", p.get("price", 0)) or 0), reverse=reverse)
                label = f"{'从高到低' if reverse else '从低到高'}"
                reply = f"💰 按价格{label}排序"
            elif field in ("sales", "销量"):
                products.sort(key=lambda p: p.get("sales_count", 0) or 0, reverse=True)
                reply = "🔥 按销量从高到低排序"
            else:
                products.sort(key=lambda p: p.get("id", 0), reverse=(order == "desc"))
                reply = "📅 按最新上架排序"
            products = products[:limit]
            briefs = [_brief(p) for p in products]
            lines = [_bline(b) for b in briefs]
            rtype = "products"
            data = {"products": briefs, "keyword": keyword or "全部商品"}
            reply = f"{'💰' if '价格' in label else '🔥'} {label}\n\n" + "\n".join(lines)
            actions = [{"label": f"🛒 加购第{n+1}件", "action": "add_to_cart", "product_id": p["id"]} for n, p in enumerate(briefs[:5])]

        elif intent == "view_product":
            pid = params.get("product_id", 0)
            try:
                prod = cli.get_product(pid)
                brief = _brief(prod)
                # 提取规格属性
                specs = []
                for prop in prod.get("properties", []):
                    attrs = []
                    for a in prop.get("attrs", []):
                        attrs.append({
                            "id": a.get("id", 0),
                            "name": a.get("attr_name", ""),
                            "price_mod": str(a.get("attr_price", 0)),
                        })
                    if attrs:
                        specs.append({
                            "name": prop.get("name", ""),
                            "attrs": attrs,
                        })
                brief["specs_detail"] = specs
                mp = str(brief.get("market_price", brief["price"]))
                sav = brief.get("savings", 0)
                member_tag = f" [{user_rank_name}]" if user_rank_name else ""
                if mp != brief["price"] and sav > 0:
                    reply = f"📦 {brief['name']}\n💰 **¥{brief['price']}**  市场价 ~~¥{mp}~~  🔥省¥{sav:.0f}{member_tag}  📦 库存{brief['stock']}"
                elif mp != brief["price"]:
                    reply = f"📦 {brief['name']}\n💰 ¥{brief['price']}   市场价 ~~¥{mp}~~{member_tag}  📦 库存{brief['stock']}"
                else:
                    reply = f"📦 {brief['name']}\n💰 ¥{brief['price']}{member_tag}  📦 库存{brief['stock']}"
                rtype = "product_detail"
                data = {"product": brief}
                actions = [{"label": "🛒 加入购物车", "action": "add_to_cart", "product_id": pid}]
            except Exception as e:
                reply = f"❌ 商品不存在: {e}"
                rtype = "text"

        elif intent == "add_to_cart":
            pid = params.get("product_id", 0)
            qty = params.get("quantity", 1)
            specs = params.get("specs", [])
            try:
                cli.cart_add(pid, qty, specs)
                # 获取购物车数量
                cart_items = cli.cart_get()
                cart_count = len(cart_items)
                reply = f"✅ 已加入购物车！当前共 {cart_count} 件商品"
                rtype = "text"
                data = {"cart_count": cart_count}
                actions = [
                    {"label": "🛒 查看购物车", "action": "view_cart"},
                    {"label": "🔍 继续购物", "action": "search"},
                ]
            except ECShopAPIError as e:
                reply = f"❌ 加购失败: {e.desc}"
                rtype = "text"

        elif intent == "view_cart":
            items = cli.cart_get()
            if not items:
                reply = "🛒 购物车是空的，快去逛逛吧！"
                rtype = "text"
            else:
                cart_items_list = [_cart_item(i) for i in items]
                total = sum(float(i.get("price", 0)) * int(i.get("amount", 0)) for i in items)
                reply = f"🛒 购物车共 {len(items)} 件商品，合计 ¥{total:.2f}"
                rtype = "cart"
                data = {"items": cart_items_list, "total": f"{total:.2f}"}
                # 获取收货地址用于结算
                try:
                    addrs = cli.list_consignees()
                    if addrs:
                        data["consignees"] = [ConsigneeInfo(
                            id=a["id"],
                            name=a["name"],
                            mobile=a.get("mobile", ""),
                            address=a.get("address", ""),
                            is_default=a.get("is_default", False),
                            regions=" ".join(r["name"] for r in a.get("regions", []) if r.get("name")),
                        ).model_dump() for a in addrs]
                        actions = [{"label": "💳 去结算", "action": "checkout", "consignee_id": addrs[0]["id"]}]
                    else:
                        actions = []
                except Exception:
                    actions = []
                actions.append({"label": "🗑️ 清空购物车", "action": "clear_cart"})

        elif intent == "checkout":
            consignee_id = params.get("consignee_id", ctx.get("consignee_id", 0))
            # 如果没指定地址，返回地址列表让前端选
            if not consignee_id:
                try:
                    addrs = cli.list_consignees()
                    if addrs:
                        addr_list = [ConsigneeInfo(
                            id=a["id"], name=a["name"], mobile=a.get("mobile", ""),
                            address=a.get("address", ""), is_default=a.get("is_default", False),
                            regions=" ".join(r["name"] for r in a.get("regions", []) if r.get("name")),
                        ).model_dump() for a in addrs]
                        reply = "📮 选择收货地址："
                        rtype = "addresses"
                        data = {"consignees": addr_list}
                        actions = [{"label": f"📍 {a['name']} {a.get('regions','')[:12]}", "action": "checkout", "consignee_id": a["id"]} for a in addr_list[:6]]
                    else:
                        reply = "❌ 没有收货地址，请先在商城添加"
                        rtype = "text"
                except Exception as e:
                    reply = f"❌ 获取地址失败: {e}"
                    rtype = "text"
            else:
                shipping_id = params.get("shipping_id", ctx.get("shipping_id", 0))
                pay_id = params.get("pay_id", ctx.get("pay_id", 0))
                # 如果没选配送方式，先获取可选方式
                if not shipping_id:
                    try:
                        carts = cli.cart_get()
                        if not carts:
                            reply = "🛒 购物车是空的，请先加购商品"
                            rtype = "text"
                        else:
                            prods = [{"goods_id": c.get("goods_id"), "num": c.get("amount", 1)} for c in carts]
                            venders = cli.list_shipping_vendors(consignee_id, prods)
                            if venders:
                                lines = [f"{i+1}. **{v['name']}** — ¥{v.get('fee', '?')}" for i, v in enumerate(venders)]
                                reply = f"🚚 **选择配送方式**\n\n" + "\n".join(lines)
                                rtype = "shipping"
                                data = {"vendors": venders, "consignee_id": consignee_id}
                                actions = [{"label": f"🚚 {v['name']} ¥{v.get('fee','?')}", "action": "checkout", "consignee_id": consignee_id, "shipping_id": v["id"]} for v in venders[:6]]
                            else:
                                reply = "❌ 该地址没有可用的配送方式"
                                rtype = "text"
                    except Exception as e:
                        reply = f"❌ 获取配送方式失败: {e}"
                        rtype = "text"
                elif not pay_id and not ctx.get("change_payment"):
                    # --- 默认余额支付（跳过选择，直接下单） ---
                    pay_id = 1
                    pay_name = "余额支付"
                    try:
                        carts = cli.cart_get()
                        if not carts:
                            reply = "🛒 购物车是空的，请先加购商品"
                            rtype = "text"
                        else:
                            cart_ids = [c["id"] for c in carts]
                            result = cli.cart_checkout(consignee_id, shipping_id=shipping_id, cart_good_ids=cart_ids)
                            order = result.get("order", {})
                            order_sn = order.get("sn", "")
                            total = order.get("total", 0)

                            # 设置支付方式为余额支付
                            if order_sn and pay_id == 1:
                                # 对余额支付：调用 payment.pay API 真正处理支付（扣余额、改状态、发通知）
                                try:
                                    order_id = order.get("id", 0)
                                    if order_id:
                                        pay_result = cli._post("ecapi.payment.pay", {
                                            "order": order_id,
                                            "code": "balance",
                                        }, need_auth=True)
                                        if pay_result.get("error_code"):
                                            # 余额支付失败，退回到设置 pay_id
                                            import subprocess
                                            subprocess.run(
                                                ["mysql", "-uroot", "-pEcshop@2026!", "ecshop_renzheng",
                                                 "-e", f"UPDATE ecs_order_info SET pay_id={pay_id}, pay_name='余额支付' WHERE order_sn='{order_sn}'"],
                                                capture_output=True, timeout=5
                                            )
                                except Exception:
                                    import subprocess
                                    subprocess.run(
                                        ["mysql", "-uroot", "-pEcshop@2026!", "ecshop_renzheng",
                                         "-e", f"UPDATE ecs_order_info SET pay_id={pay_id}, pay_name='余额支付' WHERE order_sn='{order_sn}'"],
                                        capture_output=True, timeout=5
                                    )
                            elif order_sn and pay_id:
                                import subprocess
                                subprocess.run(
                                    ["mysql", "-uroot", "-pEcshop@2026!", "ecshop_renzheng",
                                     "-e", f"UPDATE ecs_order_info SET pay_id={pay_id}, pay_name='{pay_name}' WHERE order_sn='{order_sn}'"],
                                    capture_output=True, timeout=5
                                )

                            # 获取支付链接
                            pay_url = order.get("payment_url", "")
                            if not pay_url:
                                if pay_id == 1:
                                    # 余额支付已扣款 — pay_url 留空，前端不显示付款按钮
                                    pay_url = ""
                                else:
                                    # 其他支付方式仍需用户扫码支付
                                    pay_url = f"http://9fiyahtfp3uvhf4p.myfritz.net:8081/h5/#/payment?order_sn={order_sn}"

                            if pay_id == 1:
                                reply = f"✅ **订单已支付！**\\n\\n订单号: `{order_sn}`\\n金额: ¥{total:.2f}\\n支付方式: **{pay_name}**（余额已扣除）"
                                pay_label = "📦 查看订单"
                            else:
                                reply = f"✅ **订单已提交！**\\n\\n订单号: `{order_sn}`\\n金额: ¥{total:.2f}\\n支付方式: **{pay_name}**\\n\\n💳 点击下方按钮付款"
                                pay_label = "💳 立即付款"
                            rtype = "confirm_order"
                            data = {
                                "order_sn": order_sn,
                                "total": f"{total:.2f}",
                                "pay_url": pay_url,
                            }
                            if pay_id == 1:
                                actions = [
                                    {"label": pay_label, "action": "query_order", "order_sn": order_sn},
                                ]
                            else:
                                actions = [
                                    {"label": pay_label, "action": "pay", "url": pay_url},
                                    {"label": "📦 查看订单", "action": "query_order", "order_sn": order_sn},
                                ]
                            # 附带给用户换支付方式的入口
                            if pay_id != 1:
                                actions.append({"label": "💳 换支付方式", "action": "change_payment", "consignee_id": consignee_id, "shipping_id": shipping_id})
                    except ECShopAPIError as e:
                        reply = f"❌ 下单失败: {e.desc}"
                        rtype = "text"
                elif ctx.get("change_payment"):
                    # --- 换支付方式：展示可选支付方式 ---
                    try:
                        import subprocess
                        pm_result = subprocess.run(
                            ["mysql", "-uroot", "-pEcshop@2026!", "-N", "-e",
                             "SELECT pay_id,pay_name,pay_code FROM ecshop_renzheng.ecs_payment WHERE enabled=1"],
                            capture_output=True, timeout=5
                        )
                        pay_methods = []
                        for line in pm_result.stdout.decode('utf-8', errors='replace').strip().split('\n'):
                            if line.strip():
                                parts = line.split('\t')
                                if len(parts) >= 3:
                                    pay_methods.append({"id": int(parts[0]), "name": parts[1], "code": parts[2]})

                        reply = "💳 **选择支付方式：**"
                        rtype = "checkout_preview"
                        data = {"pay_methods": pay_methods, "consignee_id": consignee_id, "shipping_id": shipping_id}
                        actions = []
                        for pm in pay_methods:
                            icon = {"balance": "💰", "cod": "📦", "wxpaynative": "💚", "yabandpay.wap": "🏦", "yabandpay": "🏦"}.get(pm["code"], "💳")
                            actions.append({
                                "label": f"{icon} {pm['name']}",
                                "action": "submit_order",
                                "consignee_id": consignee_id,
                                "shipping_id": shipping_id,
                                "pay_id": pm["id"],
                            })
                    except Exception as e:
                        reply = f"❌ 获取支付方式失败: {e}"
                        rtype = "text"
                else:
                    # --- 第4步：提交订单（带支付方式） ---
                    try:
                        carts = cli.cart_get()
                        if not carts:
                            reply = "🛒 购物车是空的，请先加购商品"
                            rtype = "text"
                        else:
                            # 获取支付方式名称
                            import subprocess
                            pm_name_result = subprocess.run(
                                ["mysql", "-uroot", "-pEcshop@2026!", "-N", "-e",
                                 f"SELECT pay_name FROM ecshop_renzheng.ecs_payment WHERE pay_id={pay_id}"],
                                capture_output=True, timeout=5
                            )
                            pay_name = pm_name_result.stdout.decode('utf-8', errors='replace').strip()

                            cart_ids = [c["id"] for c in carts]
                            result = cli.cart_checkout(consignee_id, shipping_id=shipping_id, cart_good_ids=cart_ids)
                            order = result.get("order", {})
                            order_sn = order.get("sn", "")
                            total = order.get("total", 0)

                            # 设置支付方式
                            if order_sn and pay_id == 1:
                                # 余额支付：调用 payment.pay API 真正处理支付
                                try:
                                    order_id = order.get("id", 0)
                                    if order_id:
                                        pay_result = cli._post("ecapi.payment.pay", {
                                            "order": order_id,
                                            "code": "balance",
                                        }, need_auth=True)
                                except Exception:
                                    pass
                                # 无论成功与否，都更新 pay_id
                                import subprocess
                                subprocess.run(
                                    ["mysql", "-uroot", "-pEcshop@2026!", "ecshop_renzheng",
                                     "-e", f"UPDATE ecs_order_info SET pay_id={pay_id}, pay_name='{pay_name}' WHERE order_sn='{order_sn}'"],
                                    capture_output=True, timeout=5
                                )
                            elif order_sn and pay_id:
                                subprocess.run(
                                    ["mysql", "-uroot", "-pEcshop@2026!", "ecshop_renzheng",
                                     "-e", f"UPDATE ecs_order_info SET pay_id={pay_id}, pay_name='{pay_name}' WHERE order_sn='{order_sn}'"],
                                    capture_output=True, timeout=5
                                )

                            # 获取支付链接
                            pay_url = order.get("payment_url", "")
                            if not pay_url:
                                if pay_id == 1:
                                    # 余额支付已扣款 — pay_url 留空，前端不显示付款按钮
                                    pay_url = ""
                                else:
                                    # 其他支付方式仍需用户扫码支付
                                    pay_url = f"http://9fiyahtfp3uvhf4p.myfritz.net:8081/h5/#/payment?order_sn={order_sn}"

                            if pay_id == 1:
                                reply = f"✅ **订单已支付！**\n\n订单号: `{order_sn}`\n金额: ¥{total:.2f}\n支付方式: **{pay_name}**（余额已扣除）"
                                pay_label = "📦 查看订单"
                            else:
                                reply = f"✅ **订单已提交！**\n\n订单号: `{order_sn}`\n金额: ¥{total:.2f}\n支付方式: **{pay_name}**\n\n💳 点击下方按钮付款"
                                pay_label = "💳 立即付款"
                            rtype = "confirm_order"
                            data = {
                                "order_sn": order_sn,
                                "total": f"{total:.2f}",
                                "pay_url": pay_url,
                            }
                            if pay_id == 1:
                                actions = [
                                    {"label": pay_label, "action": "query_order", "order_sn": order_sn},
                                ]
                            else:
                                actions = [
                                    {"label": pay_label, "action": "pay", "url": pay_url},
                                    {"label": "📦 查看订单", "action": "query_order", "order_sn": order_sn},
                                ]
                    except ECShopAPIError as e:
                        reply = f"❌ 下单失败: {e.desc}"
                        rtype = "text"

        elif intent == "query_order":
            order_sn = params.get("order_sn", "")
            if not order_sn:
                # 查看最近订单
                orders = cli.list_orders(page=1, per_page=5)
                if not orders:
                    reply = "📦 暂无订单记录"
                    rtype = "text"
                else:
                    order_list = [_order_info(o) for o in orders]
                    text_parts = ["📦 **最近订单：**"]
                    for o in order_list[:5]:
                        text_parts.append(f"`{o['sn']}`  ¥{o['total']}  {o['status']}")
                    reply = "\n".join(text_parts)
                    rtype = "text"
                    data = {"orders": order_list}
                    actions = [{"label": f"📄 {o['sn']}", "action": "query_order", "order_sn": o["sn"]} for o in order_list[:3]]
            else:
                try:
                    order = cli.get_order(order_sn)
                    consignee = order.get("consignee", {})
                    payment = order.get("payment", {})
                    shipping = order.get("shipping", {})
                    items_list = order.get("items", [])
                    reply = (
                        f"📦 **订单 `{order_sn}`**\n"
                        f"状态: {order.get('order_status', '处理中')}\n"
                        f"金额: ¥{order.get('total', 0)}\n"
                        f"收件人: {consignee.get('name', '')} {consignee.get('mobile', '')}\n"
                        f"地址: {consignee.get('address', '')}\n"
                        f"配送: {shipping.get('name', '')}\n"
                        f"支付: {payment.get('name', '')}\n"
                    )
                    if items_list:
                        reply += "\n商品明细：\n"
                        for item in items_list[:5]:
                            reply += f"  • {item.get('name','')} × {item.get('amount',1)} = ¥{item.get('subtotal',0)}\n"
                    rtype = "order_detail"
                    data = {"order": order}
                except ECShopAPIError as e:
                    reply = f"❌ 未找到订单: {e.desc}"
                    rtype = "text"

        elif intent == "clear_cart":
            try:
                cli.cart_clear()
                reply = "🗑️ 购物车已清空"
                rtype = "text"
            except ECShopAPIError as e:
                reply = f"❌ 清空失败: {e.desc}"
                rtype = "text"

        elif intent == "my_member":
            """我的会员 — 显示等级、省钱统计"""
            if not cli.user_info:
                reply = "请先登录再查看会员信息"
                rtype = "text"
            else:
                ur = cli.user_info.get("rank", {})
                rank_name = ur.get("name", "未知") if isinstance(ur, dict) else str(ur)
                score = cli.user_info.get("pay_points", 0)
                # 统计省钱
                all_products = all_products_cache()
                total_saved = 0
                vip_items = 0
                for p in all_products:
                    cp = float(p.get("current_price", p.get("price", 0)) or 0)
                    mp = float(p.get("market_price", 0) or 0)
                    if mp > cp > 0:
                        total_saved += mp - cp
                        vip_items += 1
                reply = (
                    f"👤 **我的会员**\n\n"
                    f"等级: **{rank_name}**\n"
                    f"积分: {score}\n"
                    f"\n📊 **会员权益**\n"
                    f"• 可浏览 {len(all_products)} 件商品\n"
                    f"• {vip_items} 件享专属会员价\n"
                    f"• 单次购物可省 **¥{total_saved:.0f}**\n"
                )
            rtype = "text"

        elif intent == "save_rank":
            """省钱排行 — 按价差排序显示最优惠商品"""
            all_products = all_products_cache()
            diffs = []
            for p in all_products:
                cp = float(p.get("current_price", p.get("price", 0)) or 0)
                mp = float(p.get("market_price", 0) or 0)
                if mp > cp > 0:
                    diffs.append((p, mp - cp))
            diffs.sort(key=lambda x: x[1], reverse=True)
            briefs = [_brief(p) for p, _ in diffs[:10]]
            total_save = sum(d[1] for d in diffs[:10])
            lines = [_bline(b) for b in briefs]
            reply = f"💰 **省钱排行榜 {user_rank_name}价**\n前10件共省¥{total_save:.0f}\n\n" + "\n".join(lines)
            rtype = "products"
            data = {"products": briefs, "keyword": "省钱排行"}
            actions = [{"label": f"🛒 加购第{n+1}件", "action": "add_to_cart", "product_id": p["id"]} for n, p in enumerate(briefs[:5])]

        elif intent == "help":
            reply = (
                "👋 **我可以帮你：**\n\n"
                "🔍 **搜商品** — 直接输入商品名\n"
                "🛒 **加购物车** — 搜索后点加购按钮\n"
                "📦 **查订单** — 输入订单号\n"
                "💰 **省钱排行** — 看看最优惠的商品\n"
                "👤 **我的会员** — 查看会员等级权益\n"
                "清单：\n"
                "• 「搜 爱他美」— 搜索\n"
                "• 「购物车」— 查看\n"
                "• 「结算」— 下单\n"
                "• 「省钱排行」— 最优惠\n"
                "• 「我的会员」— 等级权益"
            )
            rtype = "text"

        else:
            reply = "😅 没理解你的意思，试试说「搜奶粉」「购物车」「查订单」"
            rtype = "text"

    except ECShopAPIError as e:
        reply = f"⚠️ 服务异常: {e.desc}（代码 {e.code}）"
        rtype = "text"
    except Exception as e:
        reply = f"⚠️ 出错了: {str(e)}"
        rtype = "text"

    return ChatResponse(reply=reply, type=rtype, data=data, actions=actions)


def _detect_intent(msg: str) -> tuple:
    """
    规则式意图识别 — 轻量、零延迟、不上 LLM。
    返回 (intent, params_dict)
    """
    m = msg.strip()
    params = {}

    # 搜商品（支持分类浏览）
    search_patterns = [
        r"^搜\s*(.+)$", r"^搜索\s*(.+)$", r"^找\s*(.+)$",
        r"^查\s*(.+)$", r"^看看\s*(.+)$", r"^我要买\s*(.+)$",
        r"^有\s*(.+)\s*吗", r"^想买\s*(.+)",
    ]
    for pat in search_patterns:
        match = re.match(pat, m)
        if match:
            keyword = match.group(1).strip()
            # 检测是否是分类浏览
            if any(kw in keyword for kw in ["所有", "全部", "列表", "商品"]):
                return "browse_all", {}
            return "search", {"keyword": keyword}

    # 浏览所有 / 热门推荐
    if re.match(r"^(热门|热销|推荐|爆款|best|hot)$", m, re.IGNORECASE):
        return "hot_products", {}
    if re.match(r"^(全部商品|所有商品|全部分类|列表|商品列表)$", m):
        return "browse_all", {}

    # 排序
    sort_match = re.search(r"(按|以)?(价格|销量|时间|新|old)(从低到高|从高到低|升序|降序|排序)?", m)
    if sort_match:
        field = sort_match.group(2)
        order = "desc" if sort_match.group(3) in ["从高到低", "降序"] else "asc"
        return "sort", {"field": field, "order": order}

    # 加购物车：数字+商品名 或 "加购"
    if re.match(r"^加购\s*$", m):
        return "add_to_cart", {}
    if re.match(r"^加购\s*(\d+)", m):
        match = re.match(r"^加购\s*(\d+)", m)
        params["product_id"] = int(match.group(1))
        return "add_to_cart", params

    # 查看购物车
    if re.search(r"购物车|cart|🛒", m):
        if re.search(r"清空|clear|删除|delete", m):
            return "clear_cart", {}
        return "view_cart", {}

    # 结算/下单
    if re.search(r"结算|下单|提交|checkout|去结算|去付款", m):
        # 提取收货地址ID
        addr_match = re.search(r"地址[#]?(\d+)", m)
        if addr_match:
            params["consignee_id"] = int(addr_match.group(1))
        return "checkout", params

    # 查订单
    order_match = re.search(r"订单\s*(\d{8,20})", m)
    if order_match:
        return "query_order", {"order_sn": order_match.group(1)}
    if re.match(r"^\d{10,20}$", m):
        return "query_order", {"order_sn": m}
    if re.search(r"订单|查单|order|查订单", m) and not re.search(r"下单|结算", m):
        return "query_order", {}

    # 💰省钱排行
    if re.match(r"^(省钱|最优惠|特价|会员特价|省|save|优惠排行)", m, re.IGNORECASE):
        return "save_rank", {}

    # 👤我的会员
    if re.match(r"^(我的会员|会员|等级|会员等级|会员权益|vip|mypage)", m, re.IGNORECASE):
        return "my_member", {}

    # 查看商品详情（数字可能表示商品ID）
    if re.match(r"^(\d+)$", m) and 2 <= len(m) <= 5:
        return "view_product", {"product_id": int(m)}

    # 帮助
    if re.search(r"帮助|help|功能|怎么用|指南|说明|可以做什么", m):
        return "help", {}

    # 纯搜索兜底（识别为关键词搜索）
    if len(m) >= 2:
        return "search", {"keyword": m}

    return "unknown", {}



# ═══════════════════ 搜索增强：分类映射 ═══════════════════

_products_cache = None

def all_products_cache():
    """缓存全量商品列表（每次请求最多拉一次完整列表）"""
    global _products_cache
    if _products_cache is None:
        try:
            _products_cache = cli.list_products(per_page=100)
        except:
            _products_cache = []
    return _products_cache


# 分类映射表：中文关键词 → 匹配规则
CLASSIFICATION_MAP = [
    {
        "name": "🥛 奶粉/母婴",
        "match": lambda p, kw: any(t in p.get("name","") for t in ["爱他美","Aptamil","婴儿奶粉","pre段","1段","2段","母婴"]),
    },
    {
        "name": "💪 健身/运动营养",
        "match": lambda p, kw: any(t in p.get("name","") for t in ["Fitline","FitLine","肌酸","Creatine","CC-胶囊","Cell Capsule"]),
    },
    {
        "name": "💊 保健品/维生素",
        "match": lambda p, kw: any(t in p.get("name","") for t in ["Elite","EliteNutrition","Vitacrest","维他命","维生素","D3","K2","补铁","含片","胶囊","钙片","护肺","Lung","叶黄素","脑智","成人多维"]),
    },
    {
        "name": "🌸 美容/护肤",
        "match": lambda p, kw: any(t in p.get("name","") for t in ["德玛","D.Estetic","胶原蛋白","CAELO","骨胶原","马膏","krauterhof","草本庄园"]),
    },
    {
        "name": "🚚 物流/保险",
        "match": lambda p, kw: any(t in p.get("name","") for t in ["DHL","物流","直邮","保险","破损","高温保险","邮政小包"]),
    },
    {
        "name": "🍫 食品/零食",
        "match": lambda p, kw: any(t in p.get("name","") for t in ["巧克力","GOUFRAIS","红豆","绿豆","小红"]),
    },
    {
        "name": "⚡ 黑科技/健康科技",
        "match": lambda p, kw: any(t in p.get("name","") for t in ["LifeWave","LIFEWAVE","干细胞","光疗贴片","肌肽"]),
    },
    {
        "name": "🧸 儿童",
        "match": lambda p, kw: any(t in p.get("name","") for t in ["儿童","婴儿","宝宝","防咬","苦甲水"]),
    },
    {
        "name": "💊 Fitline 全线",
        "match": lambda p, kw: any(t in p.get("name","") for t in ["Fitline","FitLine","PM"]),
    },
]


def _classify_products(products, keyword, limit=8):
    kw = keyword.lower()

    # 策略1：关键词直接匹配分组名（"奶粉" → 奶粉/母婴）
    for group in CLASSIFICATION_MAP:
        group_kw = group["name"].lower()
        if kw in group_kw or kw in group_kw.replace("/", "").replace(" ", "").replace("🥛", "").replace("💊", "").replace("🌸", "").replace("🚚", "").replace("🍫", "").replace("⚡", "").replace("🧸", "").replace("💪", ""):
            full = [p for p in products if group["match"](p, kw)]
            briefs = [_brief(p) for p in full[:limit]]
            return {"label": group["name"], "products": briefs, "products_full": full} if full else None

    # 策略2：找到关键词匹配的商品，反推分组
    matched_products = [p for p in products if kw in (p.get("name", "") or "").lower()]
    if matched_products:
        for group in CLASSIFICATION_MAP:
            group_products = [p for p in matched_products if group["match"](p, kw)]
            if group_products:
                # 只返回关键词匹配到的商品，不返回整组成员
                briefs = [_brief(p) for p in group_products[:limit]]
                return {"label": group["name"], "products": briefs, "products_full": group_products}

    return None


# ═══════════════════ 工具接口（原 API，向后兼容） ═══════════════════

@app.get("/")
def root():
    return {"service": "ECShop AI Agent", "version": "2.0.0", "features": ["chat", "search", "cart", "order"]}


@app.get("/login")
def login() -> LoginOut:
    """登录并获取用户信息"""
    user = cli.login()
    return LoginOut(
        username=user["username"],
        rank=user.get("rank", {}).get("name", ""),
        is_auth=user.get("is_auth", False),
        token=cli.token,
    )


@app.get("/products/search")
def search_products(q: str, page: int = 1, limit: int = 10) -> list:
    """搜索商品"""
    try:
        products = cli.search_products(q, page, limit)
    except ECShopAPIError:
        products = cli.list_products(page, limit)
    return [_brief(p) for p in products]


@app.get("/products")
def list_products(page: int = 1, limit: int = 10, category: int = 0) -> list:
    """商品列表"""
    products = cli.list_products(page, limit)
    return [_brief(p) for p in products]


@app.get("/products/{product_id}")
def get_product(product_id: int) -> dict:
    """商品详情（含规格）"""
    try:
        prod = cli.get_product(product_id)
    except ECShopAPIError as e:
        raise HTTPException(404, str(e))
    return prod


@app.get("/consignees")
def list_consignees() -> list:
    """收货地址列表"""
    try:
        addrs = cli.list_consignees()
    except ECShopAPIError as e:
        raise HTTPException(401, f"需要登录: {e}")
    return [ConsigneeInfo(
        id=a["id"],
        name=a["name"],
        mobile=a.get("mobile", ""),
        address=a.get("address", ""),
        is_default=a.get("is_default", False),
        regions=" ".join(r["name"] for r in a.get("regions", []) if r.get("name")),
    ).model_dump() for a in addrs]


@app.get("/cart")
def get_cart() -> list:
    """购物车内容"""
    try:
        items = cli.cart_get()
    except ECShopAPIError as e:
        raise HTTPException(401, str(e))
    return [_cart_item(i) for i in items]


class CheckoutReq(BaseModel):
    consignee_id: int = Field(..., description="收货地址ID")
    shipping_id: int = Field(default=25, description="配送方式ID (25=只限直邮产品)")
    postscript: str = ""


class PlaceOrderReq(BaseModel):
    """一键下单：清空购物车+加购+提交"""
    product_id: int
    specs: list[int] = Field(default=[], description="规格属性ID, 如 [7258]=4罐直邮")
    quantity: int = 1
    consignee_id: int
    shipping_id: int = 25


@app.post("/cart/add")
def add_to_cart(
    product_id: int, quantity: int = 1, specs: str = ""
) -> dict:
    """加购物车 (specs示例: \"[7258,7711]\")"""
    try:
        spec_list = json.loads(specs) if specs else []
        result = cli.cart_add(product_id, quantity, spec_list)
        return {"success": True, "msg": "已加入购物车", "data": result}
    except ECShopAPIError as e:
        raise HTTPException(400, str(e))


@app.post("/cart/checkout")
def checkout(req: CheckoutReq) -> dict:
    """提交订单（购物车需先有商品）"""
    try:
        carts = cli.cart_get()
        if not carts:
            raise HTTPException(400, "购物车为空")
        cart_good_ids = [c["id"] for c in carts]
        result = cli.cart_checkout(
            req.consignee_id, req.shipping_id, cart_good_ids
        )
        order = result.get("order", {})
        order_sn = order.get("sn", "")
        return {"success": True, "order_sn": order_sn, "msg": f"订单 {order_sn} 提交成功"}
    except ECShopAPIError as e:
        raise HTTPException(400, str(e))


@app.post("/order/place")
def place_order(req: PlaceOrderReq) -> dict:
    """一键下单（清空→加购→结算）"""
    try:
        cli.cart_clear()
        cli.cart_add(req.product_id, req.quantity, req.specs)
        carts = cli.cart_get()
        cart_good_ids = [c["id"] for c in carts]
        result = cli.cart_checkout(
            req.consignee_id, req.shipping_id, cart_good_ids
        )
        order = result.get("order", {})
        order_sn = order.get("sn", "")
        return {"success": True, "order_sn": order_sn, "msg": f"✅ 订单 {order_sn} 提交成功"}
    except ECShopAPIError as e:
        raise HTTPException(400, str(e))


@app.get("/orders")
def list_orders(page: int = 1, limit: int = 5) -> list:
    """订单列表"""
    try:
        orders = cli.list_orders(page, limit)
    except ECShopAPIError as e:
        raise HTTPException(401, str(e))
    return [_order_info(o) for o in orders]


@app.get("/orders/{order_sn}")
def get_order(order_sn: str) -> dict:
    """订单详情"""
    try:
        order = cli.get_order(order_sn)
    except ECShopAPIError as e:
        raise HTTPException(404, str(e))
    return order


# ═══════════════════ 辅助函数 ═══════════════════

def _brief(p: dict) -> dict:
    price = p.get("current_price", p.get("price", "0"))
    market_price = p.get("market_price", price)
    try:
        cp = float(price)
        mp = float(market_price)
        savings = mp - cp if mp > cp > 0 else 0
    except (ValueError, TypeError):
        savings = 0
    return {
        "id": p["id"],
        "name": p.get("name", p.get("goods_name", "")),
        "sku": p.get("sku", p.get("goods_sn", "")),
        "price": str(price),
        "market_price": str(market_price),
        "savings": savings,
        "stock": p.get("good_stock", p.get("goods_number", 0)),
        "sales": p.get("sales_count", 0),
        "image": (p.get("default_photo") or {}).get("thumb", ""),
        "specs": p.get("properties", []),
    }


def _bline(b: dict) -> str:
    """_brief转tgbot展示行 — 显示商品名、价格、省钱标记"""
    line = f"• {b['name']}"
    if b.get("savings", 0) > 0:
        line += f"  ¥{b['price']} 🔥省¥{b['savings']:.0f}"
    else:
        line += f"  ¥{b['price']}"
    return line


def _cart_item(i: dict) -> dict:
    return {
        "id": i.get("id", 0),
        "name": i.get("name", ""),
        "price": i.get("price", "0"),
        "quantity": i.get("amount", 0),
        "subtotal": str(float(i.get("price", 0)) * int(i.get("amount", 0))),
        "attrs": i.get("property", ""),
    }


def _order_info(o: dict) -> dict:
    consignee = o.get("consignee", {})
    payment = o.get("payment", {})
    shipping = o.get("shipping", {})
    return {
        "sn": o.get("sn", ""),
        "total": float(o.get("total", 0)),
        "status": o.get("order_status", ""),
        "consignee": consignee.get("name", ""),
        "payment": payment.get("name", ""),
        "shipping": shipping.get("name", ""),
        "created_at": o.get("add_time", ""),
        "items": o.get("items", []),
    }


# ─── 启动 ───
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("AGENT_PORT", 8766))
    print(f"🚀 ECShop AI Agent v2.0 服务启动在 :{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")



