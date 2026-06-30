import math


# 1. RGB 轉 CIELAB 演算法 (標準 sRGB 轉換)
def rgb_to_lab(r, g, b):
    # 先將 RGB 轉為 0~1 並進行 Gamma 校正
    def pivot_rgb(n):
        return (n / 12.92) if n <= 0.04045 else math.pow((n + 0.055) / 1.055, 2.4)

    r, g, b = pivot_rgb(r / 255.0), pivot_rgb(g / 255.0), pivot_rgb(b / 255.0)

    # 轉為 XYZ 色彩空間
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) * 100
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) * 100
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) * 100

    # 轉為 LAB 色彩空間 (參考 D65 標準光源)
    def pivot_xyz(n):
        return math.pow(n, 1 / 3.0) if n > 0.008856 else (7.787 * n) + (16 / 116.0)

    x, y, z = pivot_xyz(x / 95.047), pivot_xyz(y / 100.000), pivot_xyz(z / 108.883)

    L = max(0, (116 * y) - 16)
    a = 500 * (x - y)
    b_val = 200 * (y - z)
    return (L, a, b_val)


# 2. 計算 Delta E 色差
def calculate_delta_e(lab1, lab2):
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    return math.sqrt((L2 - L1) ** 2 + (a2 - a1) ** 2 + (b2 - b1) ** 2)


# 3. 將色差轉換為顏色相似度 (ColorSim)
def get_color_sim(delta_e):
    # Delta E < 2.0 代表人眼極難辨識差異，可視為 100% 相似
    if delta_e <= 2.0:
        return 1.0
    # 假設 Delta E 超過 20 就完全不像，相似度遞減至 0
    return max(0.0, 1.0 - (delta_e / 20.0))


# 4. 綜合推薦演算法
# 稍微修改後的演算法
def rank_products(target_lab, db_products, skin_tone):
    scored_products = []

    # 解析使用者的膚色，用來生成推薦理由 (規格書建議邏輯)
    season = skin_tone.get('season', '未知')
    level = skin_tone.get('level', '一般')

    for prod in db_products:
        # 將資料庫商品的 RGB 轉成 LAB 來跟前端傳來的 target_lab 比對
        prod_lab = rgb_to_lab(prod.r, prod.g, prod.b)
        delta_e = calculate_delta_e(target_lab, prod_lab)

        # 色差越小分數越高 (這裡簡化，直接用色差當唯一標準)
        if delta_e <= 20.0:  # 假設大於20就完全不像，不推薦
            scored_products.append({
                "id": prod.id,
                "name": prod.name,
                "brand": prod.brand,
                "price": prod.price,
                "imageUrl": prod.imageUrl,
                "category": prod.category,
                "tags": prod.tags,
                # 規格書要求的理由，你可以自由發揮
                "matchReason": f"色差 ΔE 僅 {round(delta_e, 1)}，非常適合你{level}深淺的{season}型膚色！"
            })

    # 依照色差 (delta_e) 由小到大排序 (越小越像)
    # 因為剛剛把 delta_e 寫在字串裡，我們可以再算一次或暫存，這裡用個小技巧排序
    scored_products.sort(key=lambda x: calculate_delta_e(target_lab, rgb_to_lab(
        next(p.r for p in db_products if p.id == x["id"]),
        next(p.g for p in db_products if p.id == x["id"]),
        next(p.b for p in db_products if p.id == x["id"])
    )))

    return scored_products[:5]  # 回傳前 5 名