"""直邮管家 — 字段解析工具函数
数量/手机/地址/姓名的提取函数（无 push_engine 依赖）
"""
import re
import logging

logger = logging.getLogger("pm-parser")

# ===== 数量汉字映射 =====
CN_NUM = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _parse_qty(text: str) -> (int, str):
    """从文本开头提取数量

    "两罐爱他美" → (2, "爱他美")
    "3罐雀巢" → (3, "雀巢")
    "2*2罐爱他美" → (4, "爱他美")
    "2×2罐爱他美" → (4, "爱他美")
    "2罐*2" → (4, "爱他美")
    """
    # 支持 "2*2盒" / "2×2盒" / "2盒*2" / "2盒×2"
    m = re.match(r"(\d+)\s*[*×]\s*(\d+)\s*([罐盒瓶袋箱条包套件个])(.*)", text)
    if m:
        qty = int(m.group(1)) * int(m.group(2))
        rest = m.group(4)
        return qty, rest
    m = re.match(r"(\d+)\s*([罐盒瓶袋箱条包套件个])\s*[*×]\s*(\d+)(.*)", text)
    if m:
        qty = int(m.group(1)) * int(m.group(3))
        rest = m.group(4)
        return qty, rest
    # 支持 "名称×数量罐" 格式（如"小红x4罐" "爱他美×2盒"）
    m = re.match(r"(.+?)[x×*](\d+)([罐盒瓶袋箱条包套件个])(.*)", text)
    if m:
        name = m.group(1).strip()
        qty = int(m.group(2))
        rest = m.group(4)
        return qty, name + rest
    # 支持 "名称*数量" 格式（如"小白*2" "德爱白金pre*3"）
    m = re.match(r"(.+?)\s*[*×]\s*(\d+)$", text)
    if m:
        name = m.group(1).strip()
        qty = int(m.group(2))
        return qty, name
    # 标准格式
    m = re.match(r"(\d+|[一二两三四五六七八九十]+)([罐盒瓶袋箱条包套件个])", text)
    if m:
        qty_str = m.group(1)
        if qty_str.isdigit():
            qty = int(qty_str)
        else:
            qty = CN_NUM.get(qty_str, 1)
        rest = text[m.end():]
        return qty, rest
    # 支持 "数量*名称" 格式（如"2*小白" "3*德爱白金pre"）
    m = re.match(r"(\d+)\s*[*×]\s*(.+)$", text)
    if m:
        qty = int(m.group(1))
        rest = m.group(2).strip()
        return qty, rest
    # 支持 "数量名称" 连写格式（如"2小白" "3德爱白金pre"）
    m = re.match(r"(\d+)([\u4e00-\u9fa5].*)$", text)
    if m:
        qty = int(m.group(1))
        rest = m.group(2)
        return qty, rest
    # 支持 "名称+数量[单位]" 格式（如"抗氧化8个" "辅酶4" "小红2盒"）
    m = re.match(r"([\u4e00-\u9fa5]{2,})\s*(\d+)\s*([个罐盒瓶袋箱条包套件])?$", text)
    if m:
        return int(m.group(2)), m.group(1)
    # 支持 SKU+数量 格式（如"0702037XB*2"）
    m = re.match(r"([A-Za-z0-9\-]{5,})\s*[*×]\s*(\d+)$", text)
    if m:
        return int(m.group(2)), m.group(1)
    return 1, text


def _parse_phone(text: str) -> (str, str):
    """提取手机号 (1开头的11位数字)"""
    m = re.search(r"1[3-9]\d{9}", text)
    if m:
        phone = m.group(0)
        rest = text[:m.start()] + " " + text[m.end():]
        rest = re.sub(r'[ \t]+', ' ', rest).strip()
        return phone, rest
    return "", text


# ===== 省份列表 =====
_PROVINCES = [
    "北京", "天津", "上海", "重庆",
    "新疆", "西藏", "内蒙古", "广西", "宁夏",
    "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南", "广东", "海南",
    "四川", "贵州", "云南", "陕西", "甘肃",
    "青海", "台湾",
]

# 省市区命名补全字典
_NORM_CITY = {"北京": "北京市", "上海": "上海市", "天津": "天津市", "重庆": "重庆市",
              "北京市": "北京市", "上海市": "上海市", "天津市": "天津市", "重庆市": "重庆市"}
_NORM_PROV = {**{"北京": "北京市", "上海": "上海市", "天津": "天津市", "重庆": "重庆市"},
              "河北": "河北省", "山西": "山西省", "辽宁": "辽宁省", "吉林": "吉林省",
              "黑龙江": "黑龙江省", "江苏": "江苏省", "浙江": "浙江省", "安徽": "安徽省",
              "福建": "福建省", "江西": "江西省", "山东": "山东省", "河南": "河南省",
              "湖北": "湖北省", "湖南": "湖南省", "广东": "广东省", "海南": "海南省",
              "四川": "四川省", "贵州": "贵州省", "云南": "云南省", "陕西": "陕西省",
              "甘肃": "甘肃省", "青海": "青海省", "台湾": "台湾省",
              "内蒙古": "内蒙古自治区", "广西": "广西壮族自治区",
              "西藏": "西藏自治区", "宁夏": "宁夏回族自治区", "新疆": "新疆维吾尔自治区",
              "香港": "香港特别行政区", "澳门": "澳门特别行政区"}

# 常见备注词（用于从地址末尾剥离）
_REMARK_WORDS = (
    '请发顺丰', '发顺丰', '尽快发货', '加急', '勿放驿站',
    '放门口', '放快递柜', '放驿站', '不要放驿站', '勿放',
    '电联', '不要打电话', '送到前电话', '急件'
)

# 物流公司关键词（过滤用）
_LOGISTICS_KW = (
    '顺丰', '中通', '圆通', '韵达', '申通', '极兔',
    '京东', '德邦', 'EMS', '邮政', '菜鸟', 'DHL', 'FedEx', 'UPS', 'TNT'
)

# 标签词（过滤用）
_LABEL_WORDS = {
    '收件人', '收货人', '姓名', '手机', '电话', '地址',
    '身份证号', '身份证', '所在地区', '详细地址',
    '直邮', '空运', '海运'
}

# 地址关键词（用于截断地址中的商品信息）
_ADDR_KW_PAT = r'(号|弄|巷|路|道|街|楼|室|村)'


def _extract_address(text: str) -> (dict, str):
    """从文本中提取地址，返回 (address_info, text_without_address)
    address_info = {state, city, district, address}
    """
    # 找省/直辖市关键词
    prov_idx = -1
    matched_prov = ""
    for prov in _PROVINCES:
        idx = text.find(prov)
        if idx >= 0:
            if prov_idx == -1 or idx < prov_idx:
                prov_idx = idx
                matched_prov = prov

    if prov_idx < 0:
        return {"state": "", "city": "", "district": "", "address": ""}, text

    # 从省开始到结尾是地址部分
    addr_part = text[prov_idx:].strip()

    # 地址前面的部分是 收件人 + 备注
    name_part = text[:prov_idx].strip()

    # 解析地址
    state = matched_prov
    rest_addr = addr_part[len(matched_prov):].strip()

    # 去掉开头的"省"字（如"浙江省"→"省台州市"）
    rest_addr = re.sub(r'^省', '', rest_addr).strip()

    # 直辖市处理：北京/上海/天津/重庆 后面紧接"市"字
    if state in ("北京", "上海", "天津", "重庆") and rest_addr.startswith("市"):
        state += "市"
        rest_addr = rest_addr[1:].strip()

    # 找市
    city = ""
    city_match = re.match(r"([^市县区]+市)", rest_addr)
    if city_match:
        city = city_match.group(1)
        rest_addr = rest_addr[city_match.end():].strip()

    # 找区/县/县级市
    district = ""
    dist_match = re.match(r"([^区县市]+[区县])", rest_addr)
    if dist_match:
        district = dist_match.group(1)
        rest_addr = rest_addr[dist_match.end():].strip()
    else:
        dist_match2 = re.match(r"([^市县]+[市])", rest_addr)
        if dist_match2:
            district = dist_match2.group(1)
            rest_addr = rest_addr[dist_match2.end():].strip()

    address = rest_addr.strip()

    # JioNLP 地址解析兜底（覆盖正则不足：直辖市区县、不规则写法）
    try:
        import jionlp as jio
        _jl = jio.parse_location(addr_part)
        if _jl.get('province') and _jl.get('county') and (not district or not city):
            _js, _jc, _jd = _jl['province'], (_jl.get('city', '') or ''), _jl['county']
            state, city, district = _js, _jc, _jd
            _rest = addr_part
            for _seg in [_js, _jc, _jd]:
                if not _seg:
                    continue
                _idx = _rest.find(_seg)
                if _idx < 0:
                    _short = re.sub(r'(省|市|自治区|特别行政区)$', '', _seg)
                    if _short != _seg:
                        _idx = _rest.find(_short)
                        if _idx >= 0:
                            _rest = _rest[_idx + len(_short):].strip()
                            continue
                if _idx >= 0:
                    _rest = _rest[_idx + len(_seg):].strip()
            address = _rest.strip()
    except Exception:
        pass

    # 分离地址和备注/商品/收件人信息
    msg_from_addr = ""

    # 策略1: 按换行截断
    if chr(10) in address:
        lines = address.split(chr(10))
        first_line = lines[0].strip()
        rest = chr(10).join(lines[1:]).strip()
        if first_line and rest and re.search(r'\d', first_line):
            address = first_line
            msg_from_addr = rest

    # 策略2: 最后一个地址关键词后找截断点
    if not msg_from_addr:
        last_kw_pos = -1
        for m in re.finditer(_ADDR_KW_PAT, address):
            last_kw_pos = m.end()
        if last_kw_pos > 0:
            tail = address[last_kw_pos:].strip()
            if tail:
                cut_in_tail = -1
                nl_pos = tail.find('\n')
                if nl_pos >= 0:
                    cut_in_tail = nl_pos
                elif '。' in tail:
                    cut_in_tail = tail.index('。')
                elif re.search(r'[，,]\s*[\u4e00-\u9fa5]', tail):
                    cm = re.search(r'[，,]\s*[\u4e00-\u9fa5]', tail)
                    cut_in_tail = cm.start()
                if cut_in_tail >= 0:
                    address = address[:last_kw_pos + cut_in_tail].strip()
                    msg_from_addr = tail[cut_in_tail:].strip()

    # 策略5: 从地址末尾剥离常见备注词
    if not msg_from_addr:
        for rw in _REMARK_WORDS:
            if address.endswith(rw) or address.endswith(' ' + rw):
                address = address[:-(len(rw) + 1)].strip() if address.endswith(' ' + rw) else address[:-len(rw)].strip()
                msg_from_addr = rw
                break

    # 策略6: 从地址末尾提取身份证号（18位数字）
    id_match = re.search(r'\b(\d{17}[\dXx])\b', msg_from_addr or "")
    if not id_match:
        id_match = re.search(r'(\d{17}[\dXx])\s*$', address)
        if id_match:
            msg_from_addr = (msg_from_addr or '') + ' ' + id_match.group(1)
            address = address[:id_match.start()].strip()

    # 省市区命名补全
    state = _NORM_PROV.get(state, state)
    if state in _NORM_CITY and not city:
        city = _NORM_CITY[state]

    return {
        "state": state,
        "city": city,
        "district": district,
        "address": address,
    }, msg_from_addr


def _extract_name(text: str) -> (str, str):
    """提取收件人姓名（通常2-4个汉字）"""
    text = text.strip()
    if not text:
        return "", ""
    text = re.sub(r'^[：:\s,，]+', '', text).strip()
    m = re.match(r"([\u4e00-\u9fa5]{2,4})", text)
    if m:
        name = m.group(1)
        rest = text[m.end():].strip()
        return name, rest
    return "", text
