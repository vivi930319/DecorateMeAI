"""七種妝容風格的商品比對辭典。

為什麼要重做
------------
舊的標籤分不出風格，這是可以量的：3721 筆商品裡

    occasionTags  只有一個值 daily，100% 覆蓋
    styleTags     只有三個值，daily 也是 100% 覆蓋，剩下 natural 32%、elegant 5%
    finishTags    85% 是 natural

用兩個有區分力的值去分七種風格，數學上做不到——所以演算法「沒算到」不是門檻設錯，
是輸入本身沒有訊號。

改建在有訊號的欄位上
--------------------
    hex        3504 / 3721（94%）有值，這是最強的訊號：顏色直接決定風格
    category   8 種，決定「這個風格用不用得到這類商品」
    name       品牌產品線名居多，但質地詞（霧 / matte / 水感 / 緞光 / 珠光）是真的

顏色用 HSL 判斷而不是 RGB：色相（是不是紅、是不是珊瑚）、飽和度（濃還是淡）、
明度（深還是亮）正好對應人講妝感的方式，RGB 三個通道沒有一個對得上。

⚠️ 這份是**規則提案，不是標註結果**。它依照顏色與類別推論，沒有人看過每一筆
商品實際長什麼樣。命中數異常（某個風格命中 0 筆或三千筆）就是規則錯了，
要回來調而不是照單全收。
"""
from __future__ import annotations

import colorsys

# ── 顏色工具 ────────────────────────────────────────────────────────────


def hex_to_hsl(value: str):
    """#RRGGBB → (色相 0-360, 飽和度 0-1, 明度 0-1)。認不得就回 None。"""
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        r, g, b = (int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return (h * 360.0, s, l)


def _hue_in(hue: float, low: float, high: float) -> bool:
    """色相是環狀的：紅色跨過 0 度，所以 350–20 這種範圍要能表示。"""
    if low <= high:
        return low <= hue <= high
    return hue >= low or hue <= high


# ── 風格辭典 ────────────────────────────────────────────────────────────
#
# 每個風格對每個類別給一組條件。欄位意義：
#   hue        色相範圍（度），跨 0 度用 (低, 高) 且低 > 高
#   sat        飽和度範圍 0-1，決定「濃」還是「淡」
#   light      明度範圍 0-1，決定「深」還是「亮」
#   keywords   名稱或 finishTags 命中就加分（不是必要條件）
#   avoid      名稱命中就扣分，用來把互相撞的風格推開
#   weight     這個類別對這個風格有多重要（唇色決定港風，但決定不了韓系）
#
# 沒有列到的類別代表「這個風格不特別挑它」，不是「不能用」。

STYLE_RULES: dict[str, dict] = {
    "natural": {
        "label": "自然裸妝",
        "note": "基準線：低飽和、接近唇色本身。它不該跟任何風格搶，所以條件最寬。",
        "categories": {
            "唇彩": {"sat": (0.10, 0.50), "light": (0.35, 0.70), "weight": 1.0,
                     "keywords": ["mlbb", "裸", "豆沙", "自然", "nude"],
                     "avoid": ["正紅", "霧面", "matte"]},
            "底妝": {"weight": 0.8, "keywords": ["輕透", "薄", "sheer", "自然"],
                     "avoid": ["高遮瑕", "full"]},
            "腮紅": {"sat": (0.10, 0.45), "weight": 0.6},
        },
    },
    "softBaddie": {
        "label": "Soft Baddie",
        "note": "眼妝是主角：深暈染、霧感、玫瑰調。唇要深且帶光。",
        "categories": {
            "眼影": {"sat": (0.15, 0.75), "light": (0.15, 0.55), "weight": 1.4,
                     "keywords": ["霧", "matte", "大地", "棕", "brown", "smoky", "煙燻"],
                     "avoid": ["亮片", "glitter", "珠光"]},
            "唇彩": {"hue": (330, 20), "sat": (0.30, 0.80), "light": (0.25, 0.50),
                     "weight": 1.2, "keywords": ["莓", "玫瑰", "mauve", "藕", "glossy", "水光"]},
            "修容": {"weight": 1.2, "keywords": ["修容", "contour", "深"]},
            "眼線/睫毛": {"weight": 1.0, "keywords": ["濃密", "捲翹", "眼線", "liner"]},
        },
    },
    "koreanClean": {
        "label": "韓系亞裔",
        "note": "亮、嫩、水。不用修容——那是它跟 Soft Baddie 最大的分界。",
        "categories": {
            "底妝": {"weight": 1.4, "keywords": ["水光", "光澤", "dewy", "glow", "保濕", "hydrating"],
                     "avoid": ["霧面", "matte", "控油"]},
            "唇彩": {"hue": (340, 25), "sat": (0.35, 0.85), "light": (0.40, 0.68),
                     "weight": 1.3, "keywords": ["果凍", "唇釉", "水潤", "tint", "漸層", "glossy", "shine"],
                     "avoid": ["霧面", "matte", "絲絨"]},
            "腮紅": {"hue": (0, 30), "sat": (0.30, 0.75), "light": (0.55, 0.80),
                     "weight": 1.2, "keywords": ["蜜桃", "peach", "珊瑚", "coral"]},
            "眼線/睫毛": {"weight": 0.9, "keywords": ["纖長", "束感", "自然"]},
            "修容": {"weight": -1.0, "note": "韓系不修容，命中要扣分"},
        },
    },
    "japaneseClear": {
        "label": "日雜清透",
        "note": "奶茶／珊瑚調 + 細珠光，底妝維持輕透。刻意不走韓系的水光肌。",
        "categories": {
            "眼影": {"hue": (10, 45), "sat": (0.15, 0.60), "light": (0.45, 0.80),
                     "weight": 1.3, "keywords": ["奶茶", "珊瑚", "蜜桃", "珠光", "細閃", "pearl", "coral"]},
            "腮紅": {"hue": (5, 35), "sat": (0.25, 0.70), "light": (0.55, 0.82),
                     "weight": 1.2, "keywords": ["珊瑚", "橘", "蜜桃", "coral", "orange"]},
            "唇彩": {"hue": (0, 35), "sat": (0.35, 0.80), "light": (0.42, 0.68),
                     "weight": 1.1, "keywords": ["珊瑚", "coral", "光澤", "shine", "唇蜜"]},
            "底妝": {"weight": 0.8, "keywords": ["輕透", "薄", "satin", "緞"],
                     "avoid": ["水光", "dewy", "高遮瑕"]},
        },
    },
    "richGirl": {
        "label": "千金",
        "note": "精緻、貴、金屬細閃。最容易跟 Soft Baddie 撞，所以刻意排除霧面煙燻。",
        "categories": {
            "眼影": {"hue": (20, 50), "sat": (0.20, 0.70), "light": (0.35, 0.75),
                     "weight": 1.4, "keywords": ["香檳", "金", "champagne", "gold", "細閃", "珠光",
                                                  "shimmer", "metallic", "大地"],
                     "avoid": ["煙燻", "smoky", "全霧"]},
            "唇彩": {"hue": (350, 30), "sat": (0.25, 0.65), "light": (0.38, 0.62),
                     "weight": 1.2, "keywords": ["奶茶", "玫瑰棕", "rose", "beige", "緞光", "satin"],
                     "avoid": ["正紅", "螢光"]},
            "打亮": {"weight": 1.3, "keywords": ["打亮", "highlight", "香檳", "金", "珠光"]},
            "眼線/睫毛": {"weight": 0.9, "keywords": ["極細", "精緻", "自然"]},
        },
    },
    "hongKong": {
        "label": "港風",
        "note": "紅唇與眉眼輪廓做主角。眼影不加重——這是它跟 Soft Baddie 的分界。",
        "categories": {
            "唇彩": {"hue": (352, 12), "sat": (0.55, 1.0), "light": (0.25, 0.50),
                     "weight": 1.8, "keywords": ["正紅", "磚紅", "紅", "red", "霧面", "matte", "絲絨"],
                     "avoid": ["裸", "mlbb", "豆沙", "果凍"]},
            "眉毛彩妝": {"weight": 1.3, "keywords": ["眉", "brow", "深", "灰棕"]},
            "眼線/睫毛": {"weight": 1.0, "keywords": ["眼線", "liner", "黑"]},
            "眼影": {"weight": 0.4, "note": "存在即可，不加重"},
        },
    },
    "yandere": {
        "label": "病嬌",
        "note": "蒼白底 + 眼下紅粉暈染 + 暈開的莓紅唇。整體收斂，只有眼下是重點。",
        "categories": {
            "腮紅": {"hue": (340, 10), "sat": (0.30, 0.80), "light": (0.55, 0.80),
                     "weight": 1.6, "keywords": ["紅", "粉", "臥蠶", "眼下", "暈染"]},
            "唇彩": {"hue": (335, 10), "sat": (0.40, 0.85), "light": (0.28, 0.50),
                     "weight": 1.2, "keywords": ["莓", "berry", "暈", "咬唇", "漸層"]},
            "底妝": {"light": (0.60, 0.95), "weight": 1.1,
                     "keywords": ["白", "透白", "蒼白", "冷白", "亮白"]},
            "眉毛彩妝": {"weight": 0.8, "keywords": ["淡", "空氣", "細"]},
        },
    },
    "mensPlain": {
        "label": "男士白開水",
        "note": "只勻膚，不上色。所有帶顏色的類別一律負分。",
        "categories": {
            "底妝": {"sat": (0.0, 0.25), "weight": 1.5,
                     "keywords": ["自然", "遮瑕", "控油", "素顏", "薄"],
                     "avoid": ["水光", "光澤", "打亮"]},
            "眉毛彩妝": {"weight": 0.9, "keywords": ["自然", "淡", "灰"]},
            "唇彩": {"weight": -1.5, "note": "上色的一律排除"},
            "眼影": {"weight": -1.5},
            "腮紅": {"weight": -1.5},
            "打亮": {"weight": -1.0},
        },
    },
}


def score_product(product: dict, style_id: str) -> float:
    """一件商品對某個風格的分數。0 代表這個風格用不到它。

    分數不是機率，只是排序用的相對值：同一個風格內比較大小有意義，
    跨風格比較沒有意義（各風格的類別權重不同）。
    """
    rule = STYLE_RULES.get(style_id)
    if not rule:
        return 0.0
    category = str(product.get("category") or "").strip()
    spec = rule["categories"].get(category)
    if spec is None:
        return 0.0

    weight = float(spec.get("weight", 1.0))
    if weight < 0:
        return weight  # 這個風格明確排除這個類別

    score = weight
    text = " ".join(str(product.get(f) or "") for f in ("name", "shadeName", "finishTags")).lower()

    # 顏色：命中範圍加分，明確落在範圍外扣分。沒有 hex 就不加不扣——
    # 6% 的商品沒有顏色資料，不該因為缺資料被判成不適合。
    hsl = hex_to_hsl(product.get("hex"))
    if hsl:
        hue, sat, light = hsl
        checks = []
        if "hue" in spec:
            checks.append(_hue_in(hue, *spec["hue"]))
        if "sat" in spec:
            checks.append(spec["sat"][0] <= sat <= spec["sat"][1])
        if "light" in spec:
            checks.append(spec["light"][0] <= light <= spec["light"][1])
        if checks:
            hit = sum(1 for c in checks if c)
            score += weight * (hit / len(checks)) * 1.5
            if hit == 0:
                score -= weight * 0.8

    for word in spec.get("keywords", ()):
        if word.lower() in text:
            score += weight * 0.35
    for word in spec.get("avoid", ()):
        if word.lower() in text:
            score -= weight * 0.6

    return round(max(0.0, score), 3)


def best_styles(product: dict, top: int = 3) -> list[tuple[str, float]]:
    """這件商品最適合哪幾個風格。全部 0 分就回空清單。"""
    scored = [(sid, score_product(product, sid)) for sid in STYLE_RULES]
    scored = [(sid, s) for sid, s in scored if s > 0]
    return sorted(scored, key=lambda kv: -kv[1])[:top]


def assign_by_category(rows: list[dict], keep_ratio: float = 0.25) -> dict[str, list[tuple[dict, float]]]:
    """每個「風格 × 類別」各取分數最高的一部分，回傳 {風格: [(商品, 分數)]}。

    為什麼要在類別內部取，不是全域取
    --------------------------------
    唇彩佔全部商品的 41%（1544 / 3721），所以任何全域門檻都會被它主宰：
    實測全域取前 10% 時，韓系挑到 358 支唇膏卻**一個底妝都沒有**——而水光肌
    正是韓系的核心。千金也一樣，挑到 315 支唇、只有 58 個眼影，而它的重點是
    眼影的細閃。

    演算法要的是「這個風格在每個類別各有哪些候選」，不是一份被某個類別灌爆的清單。
    """
    from collections import defaultdict

    out: dict[str, list[tuple[dict, float]]] = {}
    for style_id in STYLE_RULES:
        by_category = defaultdict(list)
        for row in rows:
            score = score_product(row, style_id)
            if score > 0:
                by_category[str(row.get("category") or "")].append((row, score))
        picked: list[tuple[dict, float]] = []
        for items in by_category.values():
            items.sort(key=lambda kv: -kv[1])
            picked += items[:max(1, int(len(items) * keep_ratio))]
        out[style_id] = picked
    return out


if __name__ == "__main__":
    import argparse
    import csv
    import io

    parser = argparse.ArgumentParser(description="把商品清單依風格分類成一份 CSV。")
    parser.add_argument("--products", default="商品清單_20260905.csv")
    parser.add_argument("--out", default="商品風格分類.csv")
    parser.add_argument("--keep", type=float, default=0.25,
                        help="每個風格×類別保留分數前幾成（0.25 = 前 25%%）")
    args = parser.parse_args()

    rows = list(csv.DictReader(io.open(args.products, encoding="utf-8-sig")))
    assigned = assign_by_category(rows, args.keep)

    # 一列一個「商品 × 風格」：這個形狀在 Excel 裡可以直接用樞紐分析，
    # 而「一列一商品、風格擠在同一格」沒辦法。
    with open(args.out, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["風格", "風格代碼", "分數", "類別", "品牌", "商品名稱",
                         "色號", "hex", "價格", "商品id"])
        for style_id, items in assigned.items():
            label = STYLE_RULES[style_id]["label"]
            for row, score in sorted(items, key=lambda kv: (kv[0].get("category", ""), -kv[1])):
                writer.writerow([label, style_id, score, row.get("category"), row.get("brand"),
                                 row.get("name"), row.get("shadeName"), row.get("hex"),
                                 row.get("price"), row.get("id")])

    total = sum(len(v) for v in assigned.values())
    print(f"寫出 {total} 列（商品 × 風格）→ {args.out}")
    for style_id, items in assigned.items():
        print(f"  {STYLE_RULES[style_id]['label']:<12} {len(items):>4}")
