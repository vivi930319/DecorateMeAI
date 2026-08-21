"""Server-side makeup style keyword dictionary.

This is recommendation policy, not frontend data.  Keep it on the algorithm
service so changing products or keyword strategy never requires a frontend build.
"""

MAKEUP_KEYWORD_WHITELIST = {
    "男士白開水": {
        "eyeshadows": ["暖杏", "米杏", "小蜜桃", "原生裸光", "知性奶茶", "裸光"],
        "blushes": ["奶霜杏", "杏桃色", "蜜桃奶茶", "杏仁烤茶", "蜜柚寶寶", "初戀裸粉"],
        "lipsticks": ["白桃奶咖", "杏甜奶茶", "性感裸粉", "輕裸甜心", "水光", "水唇膏"],
    },
    "Soft Baddie": {
        "eyeshadows": ["焦糖摩卡", "星辰藍", "仙紫星空", "星光", "閃閃"],
        "blushes": ["焦糖肉桂", "烏梅奶凍", "肉桂奶茶", "日曬古銅", "暖銅光澤"],
        "lipsticks": ["榛果可可", "咖啡摩卡", "肉桂紅茶", "廢土黑咖", "焦糖肉桂", "摩卡意濃"],
    },
    "韓系亞裔": {
        "eyeshadows": ["小煙粉", "低調粉", "微暮絲絨", "空氣眼影", "空氣"],
        "blushes": ["煙粉色", "紫丁香", "暮紫煙霞", "微醺葡萄", "薄櫻粉"],
        "lipsticks": ["玫瑰豆沙", "煙燻漿果", "灰枯玫瑰", "白桃烏龍", "冷淡嫩粉"],
    },
    "日雜清透": {
        "eyeshadows": ["巴洛克金", "俏麗蜜桃", "春日小雛菊", "赤香粉", "柔光"],
        "blushes": ["春櫻粉", "半熟白桃", "蜜桃香檳", "仙桃寶寶", "櫻花奶凍"],
        "lipsticks": ["甜橙蘇打", "純慾赤裸", "撩心寶寶粉", "春日櫻雪", "粉晶"],
    },
    "千金": {
        "eyeshadows": ["香檳星塵", "銀白星光", "閃閃繁星", "星璨粉紅", "星塵"],
        "blushes": ["荊棘薔薇", "月光薰衣草", "雨時落櫻", "櫻花", "光感"],
        "lipsticks": ["藍調紅寶石", "薔薇秘語", "極光晶", "水光", "緞光"],
    },
    "港風": {
        "eyeshadows": ["柔和棕調", "棕調", "光綻", "邃影", "棕"],
        "blushes": ["黑糖歐蕾", "榛果奶凍", "勃根地酒紅", "金屬光", "古銅"],
        "lipsticks": ["復古正紅", "嗆紅小辣椒", "酒漬櫻桃", "惡女血紅", "罪愛黯紅", "絲絨霧感"],
    },
    "病嬌": {
        "eyeshadows": ["玫瑰花園", "莓果粉", "浪漫紫羅蘭", "夕陽紅寶", "紫羅蘭"],
        "blushes": ["豐潤莓果", "血色", "櫻桃酒紅", "深紅梅色", "甜莓粉"],
        "lipsticks": ["覆盆莓酒", "櫻桃可樂", "梅子熟時", "紅酒派對", "迷情漿果", "水唇膏"],
    },
}

# The frontend can send either the stable id or its user-facing name.
STYLE_ALIAS = {
    "softbaddie": "Soft Baddie", "soft baddie": "Soft Baddie",
    "richgirl": "千金", "千金": "千金",
    "hongkong": "港風", "港風": "港風",
    "koreanclean": "韓系亞裔", "韓系亞裔": "韓系亞裔",
    "yandere": "病嬌", "病嬌": "病嬌",
    "japaneseclear": "日雜清透", "日雜清透": "日雜清透",
    "mensplain": "男士白開水", "男士白開水": "男士白開水",
}


def normalize_style(value):
    key = " ".join(str(value or "").strip().casefold().split())
    return STYLE_ALIAS.get(key)
