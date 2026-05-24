"""直邮管家 — 身份证处理 — 上传认证 + OCR识别（调idcard-ocr-v2容器）"""
import os
import json
import time
import logging
import requests
from werkzeug.utils import secure_filename

logger = logging.getLogger("pm-idcard")

# ===== 认证系统API配置 =====
IDCARD_API = {
    "info_url": "http://ccs.ustarvs.com/api/certificate/info",
    "upload_url": "http://ccs.ustarvs.com/api/certificate/update",
    "app_key": os.getenv("IDCARD_APP_KEY", "base64:Wfxt/ngwZJ9KcAfpiZgPk3XH2f+f0ocyPFuDJRe3mgM="),
}

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads", "idcard")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _generate_sign(params: dict) -> str:
    """HMAC-SHA1签名（与PHP服务端一致）"""
    import hashlib
    import hmac
    import base64 as b64
    sign_key = IDCARD_API["app_key"].encode("utf-8")
    sorted_params = sorted(params.items(), key=lambda x: x[0])
    param_parts = []
    for key, value in sorted_params:
        if value is None or value == "" or key == "sign":
            continue
        param_parts.append(f"{key.strip()}={str(value).strip()}&")
    param_string = "".join(param_parts)
    if param_string.endswith("&"):
        param_string = param_string[:-1]
    sha1_hash = hmac.new(sign_key, param_string.encode("utf-8"), hashlib.sha1).digest()
    return b64.b64encode(sha1_hash).decode("utf-8")


def check_idcard(name: str, id_number: str) -> dict:
    """查询身份证是否已在认证系统"""
    try:
        data = {"id_card_name": name, "id_card_number": id_number}
        sign = _generate_sign(data)
        data["sign"] = sign
        resp = requests.post(IDCARD_API["info_url"], data=data, timeout=30)
        result = resp.json()
        if result.get("code") == 0 or result.get("code") == 200:
            return {"exists": True, "data": result.get("data")}
        return {"exists": False, "data": None}
    except Exception as e:
        logger.error(f"身份证查询失败: {e}")
        return {"exists": False, "data": None, "error": str(e)}


def upload_idcard(name: str, id_number: str, front_path: str, reverse_path: str) -> dict:
    """上传身份证正反面到认证系统（仅传文件名，无需传文件内容）"""
    import urllib.request, urllib.parse
    try:
        front_filename = os.path.basename(front_path)
        reverse_filename = os.path.basename(reverse_path)
        sign_params = {
            "id_card_name": name,
            "id_card_number": id_number,
            "id_card_front": front_filename,
            "id_card_reverse": reverse_filename,
        }
        sign = _generate_sign(sign_params)
        data = {
            "id_card_name": name,
            "id_card_number": id_number,
            "id_card_front": front_filename,
            "id_card_reverse": reverse_filename,
            "sign": sign,
        }
        logger.info(f"[upload] 签名param={sign_params} sign={sign}")
        encoded_data = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(IDCARD_API["upload_url"], data=encoded_data)
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        logger.info(f"[upload] 响应 body={result}")
        if result.get("code") == 0 or result.get("code") == 200:
            return {"success": True, "data": result.get("data")}
        return {"success": False, "msg": result.get("msg", "上传失败")}
    except Exception as e:
        logger.error(f"身份证上传失败: {e}")
        return {"success": False, "msg": str(e)}


def save_uploaded_file(file_storage) -> str:
    """保存上传的图片文件到本地"""
    filename = f"{int(time.time()*1000)}_{secure_filename(file_storage.filename or 'idcard.jpg')}"
    path = os.path.join(UPLOAD_DIR, filename)
    file_storage.save(path)
    return path


def auto_process_image(file_path: str, is_front: bool = True) -> str:
    """自动旋转/裁剪身份证图片"""
    try:
        from 身份证上传.auto_orient import auto_orient_idcard
        return auto_orient_idcard(file_path, is_front=is_front, crop_background=False)
    except Exception as e:
        logger.warning(f"图片自动处理跳过: {e}")
        return file_path


# ===== 内置RapidOCR引擎 =====
_ocr_engine = None


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
        logger.info("RapidOCR 引擎初始化完成")
    return _ocr_engine


# 身份证OCR识别skip词（水印/非姓名）
_SKIP_NAMES = {"仅供", "用", "姓名", "仅供酒", "仅供海", "海天清关使用", "使用",
               "关使", "保供海", "无其他", "其他无用", "仅淘宝", "仅供海关清关使用",
               "仅供海关", "清关使用", "海关清关", "仅此", "仅淘宝清关所用",
               "淘宝清关", "其他无用", "只供清关", "清关专用", "供海关",
               "关使用", "请关使用", "天使用", "更用", "夫清关使", "无其他用途",
               "仅限清关使用", "清关用", "仅供洁", "仅供用"}


def _best_name_from_raw(raw_texts: list, ocr_name: str) -> str:
    """从OCR原始文本中提取最合理的姓名"""
    import re
    candidates = []

    if ocr_name and 2 <= len(ocr_name) <= 4 and ocr_name not in _SKIP_NAMES:
        if all('\u4e00' <= c <= '\u9fff' for c in ocr_name):
            return ocr_name

    skip_chars = "姓名性别男女民族出生住址公民身份号码有效期地址省市县区镇村路街号栋楼单元室"
    label_names = []

    for i, txt in enumerate(raw_texts):
        t = txt.strip()
        if t == "姓名":
            if i + 1 < len(raw_texts):
                nxt = raw_texts[i + 1].strip()
                if 2 <= len(nxt) <= 4 and all('\u4e00' <= c <= '\u9fff' for c in nxt):
                    if nxt not in _SKIP_NAMES:
                        candidates.append(nxt)
                        label_names.append(nxt)
            if i > 0:
                prv = raw_texts[i - 1].strip()
                if 2 <= len(prv) <= 4 and all('\u4e00' <= c <= '\u9fff' for c in prv):
                    if prv not in _SKIP_NAMES:
                        candidates.append(prv)
                        label_names.append(prv)

    words = []
    for txt in raw_texts:
        t = txt.strip()
        if 2 <= len(t) <= 4 and all('\u4e00' <= c <= '\u9fff' for c in t):
            if t not in _SKIP_NAMES and not any(c in t for c in skip_chars):
                words.append(t)

    fragments = set()
    for w1 in words:
        for w2 in words:
            if w1 != w2 and w1 in w2:
                fragments.add(w1)
    for t in words:
        if t not in fragments and t not in _SKIP_NAMES:
            candidates.append(t)

    seen = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    label_candidates = [c for c in unique if c in label_names]
    if label_candidates:
        raw_name = label_candidates[0]
        if raw_name.startswith("名") and len(raw_name) > 2:
            raw_name = raw_name[1:]
        if raw_name and len(raw_name) >= 2:
            return raw_name
        return label_candidates[0]
    three_char = [c for c in unique if len(c) == 3]
    if three_char:
        # 优先选不含水印常见字（关/使/用/海/清）的3字名
        watermark_chars = {"关", "使", "用", "海", "清", "仅", "供"}
        clean = [c for c in three_char if not any(ch in watermark_chars for ch in c)]
        if clean:
            return clean[0]
        return three_char[0]
    two_char = [c for c in unique if len(c) == 2]
    if two_char:
        return two_char[0]

    return ocr_name


def _extract_id_number(texts: list) -> str:
    """从OCR文本中提取18位身份证号"""
    import re
    for text in texts:
        matches = re.findall(r'\d{17}[\dXx]', text)
        for match in matches:
            if len(match) == 18 and match[:17].isdigit():
                return match
    return ""


def _preprocess_for_ocr(img) -> tuple:
    """对身份证图片做增强预处理：对比度增强+锐化（PIL），比对测试已验证有效
    返回(是否做了增强, 增强后的BGR图)
    """
    import cv2
    from PIL import Image, ImageEnhance
    try:
        # OpenCV BGR → PIL RGB
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        # 对比度增强×2 + 锐化×2（手动测试验证过的最佳参数）
        enhancer = ImageEnhance.Contrast(pil_img)
        enhanced = enhancer.enhance(2.0)
        sharpener = ImageEnhance.Sharpness(enhanced)
        sharp = sharpener.enhance(2.0)
        # PIL → OpenCV BGR
        import numpy as np
        enhanced_bgr = cv2.cvtColor(np.array(sharp), cv2.COLOR_RGB2BGR)
        logger.info("[OCR] 已应用PIL增强预处理 (contrast×2, sharpness×2)")
        return True, enhanced_bgr
    except Exception as e:
        logger.warning(f"[OCR] PIL预处理失败，使用原图: {e}")
        return False, img


def ocr_idcard(image_path: str) -> dict:
    """OCR识别身份证文字（内置RapidOCR）。
    多角度 + 并行加速：0°原图+增强同时跑，不行再并行试其他角度。
    返回: {"success": True, "name": "张梦露", "id_number": "330..."}
    """
    import cv2
    import numpy as np
    import concurrent.futures
    try:
        engine = _get_ocr_engine()
        img = cv2.imread(image_path)
        if img is None:
            return {"success": False, "msg": "无法读取图片"}

        # 缩放大图加速OCR（最大宽800）
        h, w = img.shape[:2]
        if w > 800:
            scale = 800 / w
            img = cv2.resize(img, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_AREA)

        def _ocr(img_cv, label):
            result, elapse = engine(img_cv)
            if not result:
                return None, []
            texts = [line[1] for line in result]
            return result, texts

        def _check_result(texts):
            name = _best_name_from_raw(texts, "")
            id_no = _extract_id_number(texts)
            if name and id_no:
                return name, id_no
            return None, None

        # ── 0° 原图 ──
        r0, t0 = _ocr(img, "0°")
        n, i = _check_result(t0) if r0 else (None, None)
        if n and i:
            logger.info(f"[OCR] ✓ 0° 成功: 姓名={n}")
            return {"success": True, "name": n, "id_number": i}

        # ── 0° 增强（单次，不套_try_one） ──
        _, enhanced = _preprocess_for_ocr(img)
        r1, t1 = _ocr(enhanced, "0°增强")
        n, i = _check_result(t1) if r1 else (None, None)
        if n and i:
            logger.info(f"[OCR] ✓ 0°增强 成功: 姓名={n}")
            return {"success": True, "name": n, "id_number": i}

        # ── 其他角度并行（每个角度先原图后增强） ──
        def _try_angle(img_cv, label):
            r, t = _ocr(img_cv, label)
            n, i = _check_result(t) if r else (None, None)
            if n and i:
                return n, i
            _, en = _preprocess_for_ocr(img_cv)
            r2, t2 = _ocr(en, f"{label}+增强")
            n2, i2 = _check_result(t2) if r2 else (None, None)
            if n2 and i2:
                return n2, i2
            return None, None

        angles = [
            (cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE), "90°"),
            (cv2.rotate(img, cv2.ROTATE_180), "180°"),
            (cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE), "270°"),
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(_try_angle, a, l): l for a, l in angles}
            for f in concurrent.futures.as_completed(futs):
                n, i = f.result()
                if n and i:
                    return {"success": True, "name": n, "id_number": i}

        return {"success": False, "msg": "未识别到完整信息"}
    except Exception as e:
        logger.error(f"[OCR] 识别异常: {e}")
        return {"success": False, "msg": f"OCR识别失败: {e}"}


def smart_process(name: str, id_number: str, front_path: str, reverse_path: str) -> dict:
    """智能处理：查认证→自动处理图片→上传→缓存"""
    # 1. 先查认证系统
    check = check_idcard(name, id_number)
    logger.info(f"[smart_process] check_idcard: exists={check.get('exists')}")
    if check.get("exists"):
        return {"success": True, "skipped": True, "msg": "身份证已认证", "data": check.get("data")}

    # 2. 自动处理图片
    front_path = auto_process_image(front_path, is_front=True)
    reverse_path = auto_process_image(reverse_path, is_front=False)

    # 3. 上传
    result = upload_idcard(name, id_number, front_path, reverse_path)

    # 4. 缓存到本地
    if result.get("success"):
        try:
            from 身份证上传.idcard_cache_db import save_to_local
            save_to_local(name, id_number, True)
        except Exception:
            pass

    return result
