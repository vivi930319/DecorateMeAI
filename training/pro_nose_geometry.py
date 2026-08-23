"""從 MediaPipe landmark 算側臉鼻型的幾何特徵。

用途

側臉鼻型的分類依據本來就是幾何：駝峰鼻是鼻樑中段外凸、塌鼻是內凹、朝天鼻與
翹鼻是鼻尖上旋角度大、直挺鼻是鼻樑接近直線。只餵像素等於要模型從零學會這些量，
在 434 張的規模下很難學得起來——實測純像素做法只有 macro 0.44，而且幾乎只學會
「是不是塌鼻」（最大類）。

這裡把那些判斷依據直接算出來當特徵。

用的點

`face_roi._NOSE_POINTS` 的前段就是鼻部中線（由上而下）：

    168 (鼻根) → 6 → 197 → 195 → 5 → 4 (鼻尖) → 1 → 19 → 94 → 2 (鼻基底/人中上緣)

側臉時 FaceMesh 仍會輸出全部 468 點（遮蔽側用估計值），中線這幾點正好落在輪廓上，
是這批資料裡最可靠的一段。

尺度與方向正規化

- 尺度：所有長度都除以「鼻根→鼻基底」的距離，消掉拍攝遠近與影像解析度。
- 方向：以鼻根→鼻基底向量為 y 軸建立局部座標系，臉朝左或朝右都會被轉成同一個
  方向（見 `_local_frame` 的鏡射處理），否則同一種鼻型會因為朝向不同被拆成兩群。
"""

from __future__ import annotations

import numpy as np

# 鼻部中線，由上而下
MIDLINE = (168, 6, 197, 195, 5, 4, 1, 2)
NOSE_ROOT = 168     # 鼻根（兩眼之間凹陷處）
NOSE_TIP = 4        # 鼻尖
NOSE_BASE = 2       # 鼻基底
LEFT_EYE = 33
RIGHT_EYE = 263
CHIN = 152

FEATURE_NAMES = (
    "bridge_angle",        # 鼻樑相對臉部縱軸的傾角
    "dorsal_convexity",    # 鼻樑中段相對「鼻根—鼻尖」連線的凸出量（正=駝峰，負=塌）
    "dorsal_max_dev",      # 中段最大偏離量（不分正負，量曲度大小）
    "tip_rotation",        # 鼻尖上旋角（朝天鼻/翹鼻會偏大）
    "tip_projection",      # 鼻尖前突量／鼻長
    "nose_length_ratio",   # 鼻長／臉長
    "columella_angle",     # 鼻小柱（鼻尖→鼻基底）相對縱軸的角
    "bridge_straightness",  # 中線各點對直線的殘差（越小越直挺）
    "upper_lower_ratio",   # 上半段長／下半段長
)


def _local_frame(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """建立以鼻根為原點的局部座標系，回傳 (y 軸, x 軸, 尺度)。

    y 軸 = 鼻根 → 鼻基底（臉的縱向）。x 軸 = 垂直於它、指向鼻尖那一側，
    這樣不論人臉朝左或朝右，「鼻尖方向」永遠是 +x，特徵才不會被朝向拆成兩群。
    """
    root = pts[NOSE_ROOT].astype(np.float64)
    base = pts[NOSE_BASE].astype(np.float64)
    axis = base - root
    scale = float(np.linalg.norm(axis))
    if scale < 1e-6:
        raise ValueError("鼻根與鼻基底重合，無法建立座標系")
    y = axis / scale
    x = np.array([-y[1], y[0]])          # 逆時針轉 90°
    tip = pts[NOSE_TIP].astype(np.float64) - root
    if float(tip @ x) < 0:               # 讓鼻尖永遠落在 +x
        x = -x
    return y, x, scale


def _project(pts: np.ndarray, idx: int, root: np.ndarray,
             y: np.ndarray, x: np.ndarray, scale: float) -> tuple[float, float]:
    v = pts[idx].astype(np.float64) - root
    return float(v @ x) / scale, float(v @ y) / scale


def extract(pts: np.ndarray) -> np.ndarray | None:
    """回傳 `FEATURE_NAMES` 順序的特徵向量；landmark 不合用時回 None。"""
    try:
        y, x, scale = _local_frame(pts)
    except ValueError:
        return None
    root = pts[NOSE_ROOT].astype(np.float64)

    # 中線各點在局部座標的 (前突, 縱向)
    profile = np.array([_project(pts, i, root, y, x, scale) for i in MIDLINE])
    tip_x, tip_y = _project(pts, NOSE_TIP, root, y, x, scale)
    base_x, base_y = _project(pts, NOSE_BASE, root, y, x, scale)

    # 鼻樑傾角：鼻根→鼻尖 相對縱軸
    bridge_angle = float(np.degrees(np.arctan2(tip_x, tip_y + 1e-9)))

    # 鼻樑凸度：中段各點相對「鼻根→鼻尖」弦的有號偏離。
    # 正值＝往前凸出（駝峰），負值＝內凹（塌鼻）。這是本模組最核心的一個量。
    chord = np.array([tip_x, tip_y])
    chord_len = float(np.linalg.norm(chord)) + 1e-9
    normal = np.array([chord[1], -chord[0]]) / chord_len
    mid_idx = [MIDLINE.index(i) for i in (6, 197, 195, 5)]
    devs = np.array([float(profile[i] @ normal) for i in mid_idx])
    dorsal_convexity = float(devs.mean())
    dorsal_max_dev = float(np.abs(devs).max())

    # 直挺度：中線點對最小平方直線的殘差
    t = profile[:, 1]
    coeff = np.polyfit(t, profile[:, 0], 1)
    residual = profile[:, 0] - np.polyval(coeff, t)
    bridge_straightness = float(np.sqrt((residual ** 2).mean()))

    # 鼻尖上旋：鼻尖→鼻基底 相對縱軸的夾角
    col = np.array([base_x - tip_x, base_y - tip_y])
    columella_angle = float(np.degrees(np.arctan2(col[0], col[1] + 1e-9)))
    tip_rotation = float(np.degrees(np.arctan2(tip_x - base_x, abs(tip_y - base_y) + 1e-9)))

    tip_projection = float(tip_x)

    # 鼻長／臉長（鼻根→下巴），量鼻子在臉上的相對尺寸
    chin_v = pts[CHIN].astype(np.float64) - root
    face_len = float(np.linalg.norm(chin_v)) / scale
    nose_length_ratio = float(1.0 / (face_len + 1e-9))

    # 上下半段比例：鼻根→鼻尖 vs 鼻尖→鼻基底
    upper = float(np.linalg.norm([tip_x, tip_y]))
    lower = float(np.linalg.norm(col))
    upper_lower_ratio = float(upper / (lower + 1e-9))

    out = np.array([
        bridge_angle, dorsal_convexity, dorsal_max_dev, tip_rotation,
        tip_projection, nose_length_ratio, columella_angle,
        bridge_straightness, upper_lower_ratio,
    ], dtype=np.float32)
    return out if np.all(np.isfinite(out)) else None
