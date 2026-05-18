# -*- coding: utf-8 -*-
"""
Telegram 订单推送处理器

两种模式：
1. 订单模式：用户发送订单文字 → 解析 → 确认 → 推送
2. 身份证模式：用户在群里发身份证正反面 → 自动识别 → 上传认证

用法:
    handler = TelegramOrderHandler()
    
    # 订单模式
    result = handler.handle_message(user_id, text="订单信息")
    
    # 身份证模式（自动处理群里的图片）
    result = handler.handle_idcard_image(user_id, image_path, chat_type="group")
"""

import os
import re
import logging
from datetime import datetime
from workflows.order_push_flow import OrderPushSystem

# 用户会话（订单模式）
user_sessions = {}

# 身份证待处理队列（群模式：等待配对）
# pending_idcards: {idcard_key: {name, idcard, front_path, back_path, chat_id, ...}}
pending_idcards = {}


def get_session(user_id: str) -> dict:
    """获取用户会话"""
    global user_sessions
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "step": "order",
            "order_info": {},
            "idcard": "",
            "name": "",
            "state": ""
        }
    return user_sessions[user_id]


def clear_session(user_id: str) -> None:
    """清除用户会话"""
    global user_sessions
    if user_id in user_sessions:
        del user_sessions[user_id]


def mask_idcard(idcard: str) -> str:
    """脱敏身份证号"""
    if len(idcard) == 18:
        return f"{idcard[:6]}****{idcard[-4:]}"
    return idcard


def get_idcard_key(idcard: str) -> str:
    """生成身份证唯一键"""
    return idcard[:6] + idcard[-4:] if len(idcard) == 18 else idcard


class TelegramOrderHandler:
    """Telegram 订单处理器"""
    
    def __init__(self):
        self.ops = OrderPushSystem()
        self.logger = self.ops.logger
        self.user_sessions = {}
        self.pending_idcards = {}  # 群里的身份证待配对
    
    def get_session(self, user_id: str) -> dict:
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {
                "step": "order",
                "order_info": {},
                "idcard": "",
                "name": "",
                "state": ""
            }
        return self.user_sessions[user_id]
    
    def clear_session(self, user_id: str) -> None:
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
    
    def handle_message(self, user_id: str, text: str = None, images: list = None) -> dict:
        """处理用户消息（订单模式）"""
        session = self.get_session(user_id)
        step = session.get("step", "order")
        
        self.logger.info(f"[Telegram] user={user_id}, step={step}")
        
        # 命令
        if text and text.strip() in ["/start", "/reset", "重置", "取消"]:
            self.clear_session(user_id)
            return {"success": True, "message": "✅ 会话已重置", "next_action": "order"}
        
        # 确认推送
        if text and "确认推送" in text:
            return self._handle_confirm(user_id, session)
        
        # 图片
        if images and len(images) > 0:
            return self._handle_images(user_id, session, images)
        
        # 文本
        return self._handle_text(user_id, session, text)
    
    def handle_idcard_image(self, user_id: str, image_path: str, chat_type: str = "group", chat_id: str = None) -> dict:
        """
        处理群里收到的身份证图片（自动模式）
        
        Args:
            user_id: 发送者ID
            image_path: 图片路径
            chat_type: "group" 或 "private"
            chat_id: 群ID（，如果是群消息）
            
        Returns:
            {"success": True/False, "message": "...", "chat_id": ..., "notify": True/False}
        """
        self.logger.info(f"[IDCard] 处理图片: user={user_id}, chat={chat_id}, type={chat_type}")
        
        # 第1步：OCR识别正面
        self.logger.info("[IDCard] OCR识别...")
        ocr_result = self.ops.idcard_ocr.recognize(image_path)
        
        if not ocr_result.get("success"):
            return {
                "success": False,
                "message": f"❌ 识别失败: {ocr_result.get('message')}",
                "chat_id": chat_id,
                "notify": True  # 需要通知用户重试
            }
        
        name = ocr_result.get("name", "")
        idcard = ocr_result.get("id_card", "")
        
        self.logger.info(f"[IDCard] 识别: {name} / {idcard}")
        
        # 校验格式
        if idcard:
            is_valid, msg = self.ops.validator.validate(idcard)
            if not is_valid:
                return {
                    "success": False,
                    "message": f"❌ 身份证格式错误: {msg}",
                    "chat_id": chat_id,
                    "notify": True
                }
        
        # 检查认证系统
        check_result = self.ops.auth_uploader.check_idcard_exists(name, idcard)
        
        if check_result.get("exists"):
            # 已认证
            self.logger.info(f"[IDCard] 已认证: {idcard}")
            self.ops.auth_uploader.save_to_local_db(name, idcard)
            
            return {
                "success": True,
                "message": f"✅ 认证成功\n📋 {name} / {mask_idcard(idcard)}\n✅ 已认证，可直接用于下单",
                "chat_id": chat_id,
                "notify": True,
                "state": "authenticated",
                "name": name,
                "idcard": idcard
            }
        
        # 未认证，处理正反面配对
        idcard_key = get_idcard_key(idcard)
        
        if chat_type == "group":
            # 群里：需要配对正反面
            if idcard_key not in self.pending_idcards:
                # 第一张图片（可能是正面）
                self.pending_idcards[idcard_key] = {
                    "name": name,
                    "idcard": idcard,
                    "front_path": image_path,
                    "chat_id": chat_id,
                    "step": "front"
                }
                self.logger.info(f"[IDCard] 等待反面配对: {idcard_key}")
                
                return {
                    "success": True,
                    "message": f"📷 已识别正面\n📋 {name} / {mask_idcard(idcard)}\n⚠️ 请上传反面（带国徽）完成认证",
                    "chat_id": chat_id,
                    "notify": True,
                    "wait_reverse": True
                }
            else:
                # 第二张图片（反面）
                pending = self.pending_idcards[idcard_key]
                front_path = pending.get("front_path", "")
                
                # 上传认证
                self.logger.info(f"[IDCard] 上传认证: {idcard}")
                upload_result = self.ops.auth_uploader.upload(
                    id_card_name=name,
                    id_card_number=idcard,
                    front_path=front_path,
                    back_path=image_path
                )
                
                # 清理
                del self.pending_idcards[idcard_key]
                
                if upload_result.get("success"):
                    self.ops.auth_uploader.save_to_local_db(name, idcard)
                    
                    return {
                        "success": True,
                        "message": f"✅ 认证成功！\n📋 {name} / {mask_idcard(idcard)}\n✅ 已认证，可直接用于下单",
                        "chat_id": chat_id,
                        "notify": True,
                        "state": "authenticated",
                        "name": name,
                        "idcard": idcard
                    }
                else:
                    return {
                        "success": False,
                        "message": f"❌ 认证失败: {upload_result.get('message')}",
                        "chat_id": chat_id,
                        "notify": True
                    }
        else:
            # 私聊：直接处理
            return {
                "success": True,
                "message": f"📷 识别成功\n📋 {name} / {mask_idcard(idcard)}\n⚠️ 请上传反面完成认证",
                "chat_id": chat_id,
                "notify": True,
                "state": "front_ok",
                "name": name,
                "idcard": idcard
            }
    
    def handle_idcard_reverse(self, image_path: str, idcard: str, name: str, chat_id: str = None) -> dict:
        """
        处理身份证反面（配对正面后）
        """
        # 获取正面路径
        idcard_key = get_idcard_key(idcard)
        
        if idcard_key in self.pending_idcards:
            pending = self.pending_idcards[idcard_key]
            front_path = pending.get("front_path", "")
        else:
            # 找不到正面，直接失败
            return {
                "success": False,
                "message": "❌ 请先上传正面",
                "chat_id": chat_id,
                "notify": True
            }
        
        # 上传认证
        self.logger.info(f"[IDCard] ���传认证: {idcard}")
        upload_result = self.ops.auth_uploader.upload(
            id_card_name=name,
            id_card_number=idcard,
            front_path=front_path,
            back_path=image_path
        )
        
        # 清理
        if idcard_key in self.pending_idcards:
            del self.pending_idcards[idcard_key]
        
        if upload_result.get("success"):
            self.ops.auth_uploader.save_to_local_db(name, idcard)
            
            return {
                "success": True,
                "message": f"✅ 认证成功！\n📋 {name} / {mask_idcard(idcard)}\n✅ 已认证",
                "chat_id": chat_id,
                "notify": True,
                "state": "authenticated"
            }
        else:
            return {
                "success": False,
                "message": f"❌ 认证失败: {upload_result.get('message')}",
                "chat_id": chat_id,
                "notify": True
            }
    
    def _handle_text(self, user_id: str, session: dict, text: str) -> dict:
        """处理订单文本"""
        # ...同之前的代码...
        step = session.get("step", "order")
        
        if step == "order":
            result = self.ops.parse_order_text(text)
            if not result.get("success"):
                return {"success": False, "message": f"❌ {result.get('msg')}"}
            
            order_info = result.get("order", {})
            requires_idcard = result.get("requires_idcard", False)
            
            if not requires_idcard:
                session["order_info"] = order_info
                session["step"] = "wait_confirm"
                return {"success": True, "message": self._format_order_confirm(order_info), "next_action": "wait_confirm"}
            
            # 检查本地缓存
            receiver_name = order_info.get("收件人") or order_info.get("receiver_name") or ""
            idcard = self.ops.find_idcard_by_name(receiver_name)
            
            if idcard:
                order_info["id_card"] = idcard
                order_info["idcard_name"] = receiver_name
                session["order_info"] = order_info
                session["idcard"] = idcard
                session["name"] = receiver_name
                session["step"] = "wait_confirm"
                return {"success": True, "message": self._format_order_confirm(order_info, True), "next_action": "wait_confirm"}
            
            session["order_info"] = order_info
            session["name"] = receiver_name
            session["step"] = "idcard_front"
            return {"success": True, "message": f"📷 请上传 **{receiver_name}** 的身份证正面", "next_action": "idcard_front"}
        
        elif step == "wait_confirm":
            return self._handle_manual_idcard(user_id, session, text)
        
        return {"success": False, "message": f"⚠️ 当前步骤: {step}"}
    
    def _handle_images(self, user_id: str, session: dict, images: list) -> dict:
        """处理身份证图片"""
        step = session.get("step", "order")
        image_path = images[0]
        
        if step == "idcard_front":
            name = session.get("name", "")
            order_info = session.get("order_info", {})
            
            result = self.ops.process_idcard_image(image_path, name, order_info)
            if not result.get("success"):
                return {"success": False, "message": f"❌ {result.get('msg')}"}
            
            idcard = result.get("id_card")
            state = result.get("state")
            session["idcard"] = idcard
            session["order_info"] = result.get("order", order_info)
            
            if state == "authenticated":
                session["step"] = "wait_confirm"
                return {"success": True, "message": self._format_order_confirm(session["order_info"], True), "next_action": "wait_confirm"}
            else:
                session["step"] = "idcard_back"
                return {"success": True, "message": result.get("msg"), "next_action": "idcard_back"}
        
        elif step == "idcard_back":
            idcard = session.get("idcard", "")
            result = self.ops.process_idcard_back(image_path, idcard)
            if not result.get("success"):
                return {"success": False, "message": f"❌ {result.get('message')}"}
            
            session["order_info"].update(result.get("order", {}))
            session["step"] = "wait_confirm"
            return {"success": True, "message": self._format_order_confirm(session["order_info"], True), "next_action": "wait_confirm"}
        
        return {"success": False, "message": "⚠️ 请先发送订单信息"}
    
    def _handle_manual_idcard(self, user_id: str, session: dict, text: str) -> dict:
        """手动输入身份证"""
        idcard_pattern = r'^[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]$'
        
        text = text.strip()
        if re.match(idcard_pattern, text):
            name = session.get("name", "")
            order_info = session.get("order_info", {})
            
            result = self.ops.process_idcard_manual(name, text, order_info)
            if not result.get("success"):
                return {"success": False, "message": f"❌ {result.get('message')}"}
            
            session["idcard"] = result.get("id_card")
            session["order_info"] = result.get("order", order_info)
            
            if result.get("state") == "authenticated":
                session["step"] = "wait_confirm"
                return {"success": True, "message": self._format_order_confirm(session["order_info"], True), "next_action": "wait_confirm"}
            else:
                session["step"] = "idcard_front"
                return {"success": True, "message": result.get("msg"), "next_action": "idcard_front"}
        
        return {"success": False, "message": "⚠️ 未识别到有效身份证号"}
    
    def _handle_confirm(self, user_id: str, session: dict) -> dict:
        """确认推送"""
        step = session.get("step", "wait_confirm")
        order_info = session.get("order_info", {})
        
        if step != "wait_confirm":
            return {"success": False, "message": "⚠️ 没有待确认的订单"}
        
        result = self.ops.push_order(order_info)
        
        if result.get("success"):
            self.clear_session(user_id)
            return {"success": True, "message": f"✅ 订单推送成功！\n📋 {result.get('order_id')}", "next_action": "done"}
        else:
            return {"success": False, "message": f"❌ 推送失败: {result.get('msg')}"}
    
    def _format_order_confirm(self, order_info: dict, with_idcard: bool = False) -> str:
        name = order_info.get("收件人") or order_info.get("receiver_name") or "N/A"
        mobile = order_info.get("电话") or order_info.get("receiver_mobile") or "N/A"
        address = order_info.get("地址") or order_info.get("receiver_address") or "N/A"
        products = order_info.get("商品") or order_info.get("products") or "N/A"
        idcard = order_info.get("id_card") or ""
        
        msg = f"""📋 订单确认
━━━━━━━━━━━━━━━━━
📌 收件人: {name}
📞 电话: {mobile}
🏠 地址: {address}
📦 商品: {products}
"""
        if with_idcard and idcard:
            msg += f"🪪 身份证: {mask_idcard(idcard)}\n"
        
        msg += """━━━━━━━━━━━━━━━━━
✅ 请回复「确认推送」
❌ 回复「取消」"""
        return msg