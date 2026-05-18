#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店铺配置 — 聚水潭ERP全部107个店铺ID和名称映射
"""

# ===== 完整店铺配置 =====
SHOP_CONFIG = {
    # 跨境线下平台 (81个)
    "AUSTARWX": {"id": "18442196", "name": "AUSTARWX", "platform": "跨境线下平台"},
    "APDD丽水清田1号店": {"id": "15663199", "name": "APDD丽水清田1号店", "platform": "拼多多"},
    "APDD个人店": {"id": "16650930", "name": "APDD个人店", "platform": "拼多多"},
    "AP保健食品2号店": {"id": "17673808", "name": "AP保健食品2号店", "platform": "拼多多"},
    "APDD食品海外3号店": {"id": "17674209", "name": "APDD食品海外3号店", "platform": "拼多多"},
    "A静姐": {"id": "17056031", "name": "A静姐", "platform": "跨境线下平台"},
    "A林总": {"id": "16624745", "name": "A林总", "platform": "跨境线下平台"},
    "A路久": {"id": "16896076", "name": "A路久", "platform": "跨境线下平台"},
    "A牛斯斯": {"id": "16631715", "name": "A牛斯斯", "platform": "跨境线下平台"},
    "A乔妈": {"id": "16612947", "name": "A乔妈", "platform": "跨境线下平台"},
    "A韦峥": {"id": "18331345", "name": "A韦峥", "platform": "跨境线下平台"},
    "A夏总PDD": {"id": "18435161", "name": "A夏总PDD", "platform": "跨境线下平台"},
    "A夏总WX": {"id": "18614842", "name": "A夏总WX", "platform": "跨境线下平台"},
    "A夏总淘分销": {"id": "18247446", "name": "A夏总淘分销", "platform": "跨境线下平台"},
    "A夏总天海易购": {"id": "16631713", "name": "A夏总天海易购", "platform": "跨境线下平台"},
    "A高总": {"id": "16871568", "name": "A高总", "platform": "跨境线下平台"},
    "A安安": {"id": "16631716", "name": "A安安", "platform": "跨境线下平台"},
    "A火山哥2007": {"id": "15671345", "name": "A火山哥2007", "platform": "淘宝天猫"},
    "ADEMA": {"id": "17096973", "name": "ADEMA", "platform": "跨境线下平台"},
    "apos跨境商城": {"id": "16640127", "name": "apos跨境商城", "platform": "跨境线下平台"},
    "Asweety": {"id": "18334864", "name": "Asweety", "platform": "跨境线下平台"},
    "Ausrede003PDD买手店": {"id": "17598710", "name": "Ausrede003PDD买手店", "platform": "拼多多"},
    "Bremen德国奶粉直邮店": {"id": "20399126", "name": "Bremen德国奶粉直邮店", "platform": "拼多多"},
    "Chen": {"id": "16867936", "name": "Chen", "platform": "跨境线下平台"},
    "Crotai": {"id": "16969006", "name": "Crotai", "platform": "跨境线下平台"},
    "DLMY-XUAN": {"id": "17291581", "name": "DLMY-XUAN", "platform": "跨境线下平台"},
    "ecshop跨境商城": {"id": "17292311", "name": "ecshop跨境商城", "platform": "跨境线下平台"},
    "EURMAXI 通用店铺": {"id": "18541488", "name": "EURMAXI 通用店铺", "platform": "跨境线下平台"},
    "Eurmaxi-Dami": {"id": "20754024", "name": "Eurmaxi-Dami", "platform": "跨境线下平台"},
    "Eurmaxi-Maoma": {"id": "18552815", "name": "Eurmaxi-Maoma", "platform": "跨境线下平台"},
    "GMBH": {"id": "18346687", "name": "GMBH", "platform": "跨境线下平台"},
    "GMBH-Fan Qi": {"id": "19987578", "name": "GMBH-Fan Qi", "platform": "跨境线下平台"},
    "GMBH-Renli Li": {"id": "18667907", "name": "GMBH-Renli Li", "platform": "跨境线下平台"},
    "GMBH-Ruanqingna": {"id": "20507480", "name": "GMBH-Ruanqingna", "platform": "跨境线下平台"},
    "King Yik海外专营店": {"id": "20399031", "name": "King Yik海外专营店", "platform": "拼多多"},
    "King Yik母婴海外专营店": {"id": "20537055", "name": "King Yik母婴海外专营店", "platform": "拼多多"},
    "NICK德国TB": {"id": "18441282", "name": "NICK德国TB", "platform": "跨境线下平台"},
    "NICK德国直邮PDD": {"id": "18324536", "name": "NICK德国直邮PDD", "platform": "跨境线下平台"},
    "PDD浩妈DZ": {"id": "17698960", "name": "PDD浩妈DZ", "platform": "跨境线下平台"},
    "Power Protection海外专营店": {"id": "17839273", "name": "Power Protection海外专营店", "platform": "拼多多"},
    "RACHEL": {"id": "16682455", "name": "RACHEL", "platform": "跨境线下平台"},
    "Stan": {"id": "17046612", "name": "Stan", "platform": "跨境线下平台"},
    "timi": {"id": "16899070", "name": "timi", "platform": "跨境线下平台"},
    "timi-LSDP": {"id": "18553655", "name": "timi-LSDP", "platform": "跨境线下平台"},
    "USTAR 异常订单": {"id": "18652730", "name": "USTAR 异常订单", "platform": "跨境线下平台"},
    "阿亮": {"id": "16907649", "name": "阿亮", "platform": "跨境线下平台"},
    "阿美-大米荷兰代购淘宝1号店": {"id": "20552198", "name": "阿美-大米荷兰代购淘宝1号店", "platform": "跨境线下平台"},
    "阿美奶粉-DE Germany": {"id": "18559895", "name": "阿美奶粉-DE Germany", "platform": "跨境线下平台"},
    "阿美奶粉-Liederi Int": {"id": "20285537", "name": "阿美奶粉-Liederi Int", "platform": "跨境线下平台"},
    "阿美奶粉-Maoma": {"id": "20414080", "name": "阿美奶粉-Maoma", "platform": "跨境线下平台"},
    "阿美奶粉-Song": {"id": "20435944", "name": "阿美奶粉-Song", "platform": "跨境线下平台"},
    "阿美奶粉-xiaorong Yang": {"id": "20319211", "name": "阿美奶粉-xiaorong Yang", "platform": "跨境线下平台"},
    "小杨哥1号店": {"id": "18423194", "name": "小杨哥1号店", "platform": "未知"},
    "小杨哥2号店": {"id": "18568889", "name": "小杨哥2号店", "platform": "未知"},
    "小杨哥3号店": {"id": "15474682", "name": "小杨哥3号店", "platform": "未知"},
    "小杨哥4号店": {"id": "17003282", "name": "小杨哥4号店", "platform": "未知"},
    "小杨哥6号店": {"id": "18251252", "name": "小杨哥6号店", "platform": "未知"},
    "甘总-付总": {"id": "17288013", "name": "甘总-付总", "platform": "未知"},
    "沐浴阳光PDD": {"id": "18020520", "name": "沐浴阳光PDD", "platform": "未知"},
    "三月": {"id": "16631712", "name": "三月", "platform": "跨境线下平台"},
    "线下": {"id": "0", "name": "{线下}", "platform": "未知"},
    "武姐": {"id": "18283794", "name": "武姐", "platform": "跨境线下平台"},
    # 淘宝天猫 (4个)
    "比德精质": {"id": "15654933", "name": "比德精质", "platform": "淘宝天猫"},
    "丽水青田hk供货商": {"id": "17578370", "name": "丽水青田hk供货商", "platform": "淘宝天猫"},
    "小苑淘宝店铺9": {"id": "18072170", "name": "小苑淘宝店铺9", "platform": "淘宝天猫"},
    # 天猫供销 (2个)
    "TFX供应商:香港瑞玲商贸供货商6509": {"id": "18194128", "name": "TFX供应商:香港瑞玲商贸供货商6509", "platform": "天猫供销"},
    "供应商:香港瑞玲商贸供货商": {"id": "17520563", "name": "供应商:香港瑞玲商贸供货商", "platform": "天猫供销"},
    # 档口 (1个)
    "档口13659696": {"id": "17758157", "name": "档口13659696", "platform": "档口"},
    # 菜鸟Link面单 (1个)
    "丽水青田菜鸟面单": {"id": "15678757", "name": "丽水青田菜鸟面单", "platform": "菜鸟Link面单"},
    # 口袋微店 (1个)
    "微店": {"id": "15667607", "name": "微店", "platform": "口袋微店"},
}

DEFAULT_SHOP_ID = "20941412"
DEFAULT_SHOP_NAME = "AUSTARWX"

# ===== 常用店铺配置 (简写映射) =====
SHOP_ABBR_MAP = {
    "AUSTARWX": "AUSTARWX",
    "APDD丽水清田1号店": "丽水清田",
    "APDD个人店": "德国丽水清田个人店",
    "AP保健食品2号店": "丽水清田2店",
    "APDD食品海外3号店": "丽水清田3号店",
    "A静姐": "JIngjie",
    "A林总": "Fairy",
    "A路久": "USTAR LJ",
    "A牛斯斯": "NSSZY",
    "A乔妈": "Qiaoma",
    "A韦峥": "A韦峥",
    "A夏总PDD": "A夏总PDD",
    "A夏总WX": "A夏总WX",
    "A夏总淘分销": "A夏总淘分销",
    "A夏总天海易购": "夏总天海",
    "A高总": "USTAR GAO",
    "A安安": "ANAN",
    "A火山哥2007": "德国丽水清田淘宝店",
    "小杨哥1号店": "小杨哥1号",
    "小杨哥2号店": "小杨哥2号",
    "小杨哥3号店": "小杨哥3号",
    "小杨哥4号店": "小杨哥4号",
    "小杨哥6号店": "小杨哥6号",
    "甘总-付总": "甘总-付总",
    "沐浴阳光PDD": "沐浴阳光",
    "三月": "Sanyue",
    "武姐": "武姐",
}


def get_shop_abbr(shop_name: str) -> str:
    """获取店铺名称缩写
    用于退货时填写店铺缩写字段
    """
    return SHOP_ABBR_MAP.get(shop_name, shop_name)


def get_shop_name(shop_id: str) -> str:
    """通过店铺ID获取店铺名称"""
    for name, config in SHOP_CONFIG.items():
        if config["id"] == shop_id:
            return name
    return DEFAULT_SHOP_NAME


def get_shop_id(shop_name: str) -> str:
    """通过店铺名称获取店铺ID"""
    config = SHOP_CONFIG.get(shop_name)
    return config["id"] if config else DEFAULT_SHOP_ID
