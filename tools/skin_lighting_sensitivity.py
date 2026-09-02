"""同一張臉，換個拍攝條件，膚色會漂移多少？

為什麼問這個
------------
「推薦的色號對不上」有幾個候選成因：取樣把頭髮算進去、色號範圍框畫錯、
商品端的色碼品質，以及**拍攝條件**。前兩個已經查過——分割取樣只讓 L* 動了 0.17，
框則根本不參與色差計算。剩下拍攝條件沒有被量化過，而 delta_e_ciede2000 的註解
早就把它列為已知影響：「會受到拍攝光源、白平衡、相機處理及商品色碼品質影響」。

這支把那句話變成數字：對同一張照片施加幾種常見的拍攝差異，量膚色 LAB 的漂移，
再用 CIEDE2000 換算成色差。判斷的標準很簡單——

    如果拍攝條件造成的 ΔE，比相鄰粉底色號之間的距離還大，
    那麼「推薦哪一號」在使用者換一盞燈之後就會換一個答案。

那不是演算法調得不夠好，是輸入本身的精度不足以支撐那個判斷。

模擬的是什麼
------------
不是隨便亂改像素，而是三種真實會發生的事：
  * 曝光      —— 室內昏暗 vs 窗邊，手機自動曝光補不完
  * 白平衡    —— 暖黃燈泡 vs 冷白日光燈，相機的 AWB 常常猜錯
  * 對比      —— 不同手機的成像風格

用法
----
    python tools/skin_lighting_sensitivity.py            # 預設 6 張
    python tools/skin_lighting_sensitivity.py --limit 12
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for folder in ("face", "shared"):
    sys.path.insert(0, str(ROOT / folder))

PATTERNS = (
    "data/kaggle_asian_faces/generated_yellow-stylegan2/*.png",
    "data/basic_usable/raw_images/*.jpg",
    "data/pro_full/grouped/nose_shape_side/*/*.jpg",
)


def _collect(limit: int) -> list[str]:
    per_source = max(1, limit // len(PATTERNS))
    found: list[str] = []
    for pattern in PATTERNS:
        found += sorted(glob.glob(str(ROOT / pattern)))[:per_source]
    return found[:limit]


def _exposure(bgr, factor: float):
    """整體變亮或變暗，模擬曝光差異。"""
    return np.clip(bgr.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def _white_balance(bgr, warm: float):
    """把藍通道與紅通道往相反方向推，模擬色溫偏移。warm > 0 是偏暖。"""
    out = bgr.astype(np.float32)
    out[:, :, 2] *= (1.0 + warm)   # R
    out[:, :, 0] *= (1.0 - warm)   # B
    return np.clip(out, 0, 255).astype(np.uint8)


def _contrast(bgr, factor: float):
    """繞著中灰調整對比，模擬不同手機的成像風格。"""
    out = (bgr.astype(np.float32) - 128.0) * factor + 128.0
    return np.clip(out, 0, 255).astype(np.uint8)


VARIANTS = [
    ("原圖", lambda img: img),
    ("曝光 −20%", lambda img: _exposure(img, 0.80)),
    ("曝光 +20%", lambda img: _exposure(img, 1.20)),
    ("白平衡偏暖", lambda img: _white_balance(img, 0.08)),
    ("白平衡偏冷", lambda img: _white_balance(img, -0.08)),
    ("對比 +15%", lambda img: _contrast(img, 1.15)),
]


def _skin_lab(bgr):
    """跑完整的膚色流程，回傳 (L, a, b)。這張照片不可用時回 None。"""
    from Face_analyzer_BASIC import FaceAnalyzer

    # FaceAnalyzer 只吃 str 或 bytes。用 PNG 而不是 JPEG：JPEG 的色度次取樣本身
    # 就會動到 a*/b*，那會混進我們想量的拍攝差異裡，讓結果偏大而且說不清是誰造成的。
    ok, buffer = cv2.imencode(".png", bgr)
    if not ok:
        return None
    try:
        analyzer = FaceAnalyzer(buffer.tobytes(), strict_angle=False, require_insight=False)
        *_unused, season, shade, L, a, b = analyzer.get_skin_color()
    except Exception:
        return None
    return (L, a, b), season, shade


def main() -> int:
    from Face_analyzer_BASIC import delta_e_ciede2000

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()

    paths = _collect(args.limit)
    if not paths:
        print("找不到測試照片。")
        return 1

    print(f"{len(paths)} 張照片 × {len(VARIANTS)} 種拍攝條件\n")
    all_deltas: list[float] = []
    season_flips = shade_flips = usable = 0

    for path in paths:
        bgr = cv2.imread(path)
        if bgr is None:
            continue
        base = _skin_lab(bgr)
        if base is None:
            print(f"{os.path.basename(path)[:26]:<28}跳過（分析不了）")
            continue
        base_lab, base_season, base_shade = base
        usable += 1
        print(f"{os.path.basename(path)[:26]:<28}原圖 L*{base_lab[0]:.1f} a*{base_lab[1]:.1f} "
              f"b*{base_lab[2]:.1f}　{base_season}／{base_shade}")

        for name, transform in VARIANTS[1:]:
            got = _skin_lab(transform(bgr))
            if got is None:
                print(f"    {name:<14}分析失敗")
                continue
            lab, season, shade = got
            delta = delta_e_ciede2000(base_lab, lab)
            all_deltas.append(delta)
            flags = []
            if season != base_season:
                season_flips += 1
                flags.append(f"四季型→{season}")
            if shade != base_shade:
                shade_flips += 1
                flags.append(f"分級→{shade}")
            print(f"    {name:<14}ΔE {delta:5.2f}   L*{lab[0]:6.1f} a*{lab[1]:5.1f} b*{lab[2]:5.1f}"
                  f"   {'　'.join(flags)}")
        print()

    if not all_deltas:
        print("沒有任何一張跑得完。")
        return 1

    ordered = sorted(all_deltas)
    n = len(ordered)
    total = usable * (len(VARIANTS) - 1)
    print("=" * 78)
    print(f"{usable} 張照片、{n} 次變化")
    print(f"  ΔE 中位數 {ordered[n // 2]:.2f}   平均 {sum(ordered) / n:.2f}   "
          f"最大 {ordered[-1]:.2f}")
    print(f"  四季型被改變：{season_flips}/{total}")
    print(f"  膚色分級被改變：{shade_flips}/{total}")
    print()
    print("怎麼讀這個數字：業界常說 ΔE 2.3 是「一般人看得出差別」的門檻，而相鄰粉底")
    print("色號之間的距離通常也在個位數。若上面的中位數已經接近或超過那個範圍，")
    print("代表換一盞燈就足以改變推薦結果——那是輸入精度的問題，不是排序演算法的問題。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
