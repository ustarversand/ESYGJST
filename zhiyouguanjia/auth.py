"""直邮管家 — 用户认证模块"""
import os
import hashlib
import logging
from functools import wraps
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, g

from config import USERS, SHOPS

logger = logging.getLogger("zygj-auth")

auth_bp = Blueprint("auth", __name__)


# ===== 辅助函数 =====

def _hash_password(password: str) -> str:
    """SHA256 哈希密码"""
    return hashlib.sha256(password.encode()).hexdigest()


def _verify_password(password: str, stored: dict) -> bool:
    """验证密码（支持明文和哈希）"""
    stored_pw = stored.get("password", "")
    # 支持明文密码
    return password == stored_pw or _hash_password(password) == stored_pw


def login_required(f):
    """登录保护装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"success": False, "msg": "未登录"}), 401
            return redirect(url_for("auth.login_page"))
        g.current_user = session["user"]
        return f(*args, **kwargs)
    return decorated


def get_user_shop_keys() -> list:
    """获取当前用户可见的店铺key列表"""
    user = session.get("user", {})
    shop_key = user.get("shop_key")
    if shop_key:
        # 绑定店铺 → 只看这一个
        if shop_key in SHOPS:
            return [shop_key]
        return []
    # 管理员看全部
    return list(SHOPS.keys())


# ===== 路由 =====

@auth_bp.route("/login", methods=["GET"])
def login_page():
    """登录页面"""
    if "user" in session:
        return redirect(url_for("index"))
    return render_template("login.html")


@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    """登录API"""
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"success": False, "msg": "请提供用户名和密码"}), 400

    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"success": False, "msg": "用户名和密码不能为空"}), 400

    user_info = USERS.get(username)
    if not user_info or not _verify_password(password, user_info):
        return jsonify({"success": False, "msg": "用户名或密码错误"}), 401

    # 登录成功
    session["user"] = {
        "username": username,
        "shop_key": user_info.get("shop_key"),
    }
    session.permanent = True

    shop_key = user_info.get("shop_key")
    shop_info = SHOPS.get(shop_key) if shop_key else None

    logger.info(f"[登录] {username} {'→ ' + shop_key if shop_key else '(管理员)'}")

    return jsonify({
        "success": True,
        "user": {
            "username": username,
            "shop_key": shop_key,
            "shop_name": shop_info["name"] if shop_info else None,
            "shop_id": shop_info["id"] if shop_info else None,
            "is_admin": shop_key is None,
        },
    })


@auth_bp.route("/api/logout", methods=["POST"])
def api_logout():
    """登出"""
    session.clear()
    return jsonify({"success": True})


@auth_bp.route("/api/me", methods=["GET"])
def api_me():
    """获取当前用户信息"""
    if "user" not in session:
        return jsonify({"authenticated": False}), 200

    user = session["user"]
    shop_key = user.get("shop_key")
    shop_info = SHOPS.get(shop_key) if shop_key else None

    return jsonify({
        "authenticated": True,
        "user": {
            "username": user["username"],
            "shop_key": shop_key,
            "shop_name": shop_info["name"] if shop_info else None,
            "shop_id": shop_info["id"] if shop_info else None,
            "is_admin": shop_key is None,
        },
    })
