"""五官規則式／幾何特徵的唯一定義處。

服務端（`basic_rule_trees`）與離線工具（`tools/cv_rule_baseline.py`、
`tools/diagnose_rule_thresholds.py`）都從這裡取用。放在專案根目錄而不是 `tools/`，
是因為 `Dockerfile` 逐檔 `COPY`、不含 `tools/`——特徵定義若留在工具目錄，
線上就載不到，或被迫複製第二份而與離線版本各自漂移。

**訓練與推論必須用同一份特徵**：決策樹是在這些函式的輸出上學的，
線上若餵到定義稍有不同的值，模型會安靜地變差且很難察覺。

所有特徵都是**比值**，不是像素長度：同一張臉拍遠拍近像素會變、比值不會。
"""

from __future__ import annotations

import numpy as np

_L_BROW = (46, 53, 52, 65, 55)
_R_BROW = (276, 283, 282, 295, 285)

# 每個部位餵給決策樹的特徵順序。順序就是模型的輸入契約，改動等於換一個模型。
TREE_FEATURES = {
    "brow_shape": ["tail_ratio", "arch_ratio"],
    "eye_shape": ["ear", "angle", "ratio_to_face"],
    "nose_shape": ["ratio_width"],
    # 不同高度的寬度比值。**這七個就是決策樹實際使用的契約**，順序不能動。
    #
    # 2026-07-30 試過再加六個，結論是都沒有用，所以沒有納入：
    #
    #   jaw_fill / jaw_corner_cos / chin_curvature   下顎「方 vs 圓」   0.4454 → 0.4417
    #   upper_third / mid_third / lower_third        三庭縱向比例       0.4454 → 0.4416
    #
    # 兩組都是為了特定的混淆而設計的（圓↔方互認 23%、長形↔鵝蛋是縱向差異），
    # 量得出來、數值也合理，但決策樹挑完之後表現一樣——代表那些資訊對這個任務
    # 沒有鑑別力。函式保留在下面供日後對照，只是不進契約。
    #
    # 這與另外三條證據一致：五種方法（RGB／輪廓128／輪廓224／幾何7／幾何13）全部
    # 落在 0.442~0.498；解析度加倍只有 +0.009；標註複核中臉型是唯一「模型有把握地
    # 答錯」為 0 張的部位。最可能的解釋是標註者判斷臉型用的不是可測量的幾何量。
    # 詳見〈臉部分析模型_完整發展歷程規格書〉。
    "face_shape": ["height_width", "forehead_norm", "cheek_norm", "jaw_norm",
                   "forehead_to_jaw", "cheek_to_jaw", "chin_to_jaw",
                   "jaw_slope", "gonial_angle", "jaw_slope_diff"],
    "lip_shape": ["height_ratio", "m_diff_ratio", "smile_diff_ratio"],
}


def brow_features(a) -> dict[str, float]:
    def metrics(outer_idx, inner_idx, outline):
        head = a._pt(outer_idx).astype(np.float32)
        tail = a._pt(inner_idx).astype(np.float32)
        width = float(np.linalg.norm(tail - head))
        if width < 1e-6:
            return 0.0, 0.0
        pts = np.array([a._pt(i) for i in outline], dtype=np.float32)
        peak_y = float(np.min(pts[:, 1]))
        base_y = (float(head[1]) + float(tail[1])) / 2.0
        return (base_y - peak_y) / width, (float(head[1]) - float(tail[1])) / width

    la, lt = metrics(46, 55, _L_BROW)
    ra, rt = metrics(276, 285, _R_BROW)
    return {"arch_ratio": (la + ra) / 2.0, "tail_ratio": (lt + rt) / 2.0}


def eye_features(a) -> dict[str, float]:
    face_width = a._dist(234, 454)
    left = a._eye_side_metrics(133, 33, (157, 158, 159, 160, 161), 145, _L_BROW)
    left["angle"] = -left["angle"]
    right = a._eye_side_metrics(362, 263, (385, 386, 387, 388, 398), 374, _R_BROW)
    eye_width = (left["eye_width"] + right["eye_width"]) / 2.0
    return {
        "ear": (left["ear"] + right["ear"]) / 2.0,
        "angle": (left["angle"] + right["angle"]) / 2.0,
        "ratio_to_face": eye_width / face_width if face_width > 1e-6 else 0.0,
    }


def nose_features(a) -> dict[str, float]:
    face_width = a._dist(234, 454)
    nose_width = a._dist(129, 358)
    return {"ratio_width": nose_width / face_width if face_width > 1e-6 else 0.0}


def face_features(a) -> dict[str, float]:
    """臉型的幾何量。

    量測直接取自 `FaceAnalyzer.face_measurements()`——刻意不在這裡重寫一份沿著
    臉部外框取寬度的邏輯，否則規則式與模型會用到兩份會各自漂移的量測。
    """
    m = a.face_measurements()
    if m is None:
        return {k: 0.0 for k in TREE_FEATURES["face_shape"]}
    fw, ch, jw = m["forehead_width"], m["cheekbone_width"], m["jaw_width"]
    max_w = max(fw, ch, jw, 1e-6)
    feats = {
        "height_width": m["face_height"] / max(m["face_width"], 1e-6),
        "forehead_norm": fw / max_w,
        "cheek_norm": ch / max_w,
        "jaw_norm": jw / max_w,
        "forehead_to_jaw": fw / max(jw, 1e-6),
        "cheek_to_jaw": ch / max(jw, 1e-6),
        "chin_to_jaw": m["chin_width"] / max(jw, 1e-6),
    }
    # 這六個實測無幫助，不進 TREE_FEATURES 的契約，因此也不放進回傳值——
    # 決策樹是按 TREE_FEATURES 的順序取值的，多塞 key 只會讓人以為它們有被用到。
    # 要重跑對照實驗時，把下面兩行取消註解並同步改 TREE_FEATURES["face_shape"]。
    #   feats.update(_jaw_shape_features(a))
    #   feats.update(_vertical_thirds(a))
    feats.update(_jawline_angles(a))
    return feats


def _jawline_angles(a) -> dict[str, float]:
    """下頜線的傾斜角。

    跟先前失敗的 _jaw_shape_features 差在**測量的穩定度**：那組要從 36 個外框點
    估曲率（三點外接圓），在那個取樣密度下雜訊比訊號大。這裡只量**兩個明確
    landmark 之間連線的方向**，不需要估任何導數，量出來穩得多。

    這也是大家第一次玩 MediaPipe 最常做的事——把外輪廓的點連成線。
    連起來之後，下頜線的斜率就是現成的：

      jaw_slope       下頜角→下巴 這條線與水平的夾角（度）。
                      方形臉的下頜線接近水平，長形／鵝蛋臉往下巴斜得陡。
      gonial_angle    下頜角處，「耳前→下頜角」與「下頜角→下巴」的夾角（度）。
                      這是顱面測量學真正在用的角，方臉小、尖臉大。
      jaw_slope_diff  左右兩側 jaw_slope 的差，量臉的不對稱。

    landmark：耳前 132/361、下頜角 172/397、下巴 152。
    量測前一律旋正，否則頭一歪角度就全錯。
    """
    import numpy as np

    try:
        pts = np.array([a._pt(i) for i in (132, 172, 361, 397, 152)], dtype=np.float32)
        ear_l, gon_l, ear_r, gon_r, chin = a._align_points_by_eyes(pts)
    except Exception:
        return {"jaw_slope": 0.0, "gonial_angle": 0.0, "jaw_slope_diff": 0.0}

    def slope_deg(gon):
        v = chin - gon
        if abs(v[0]) < 1e-6 and abs(v[1]) < 1e-6:
            return 0.0
        return float(abs(np.degrees(np.arctan2(v[1], abs(v[0]) + 1e-6))))

    def gonial_deg(ear, gon):
        v1, v2 = ear - gon, chin - gon
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 < 1e-6 or n2 < 1e-6:
            return 0.0
        cos = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
        return float(np.degrees(np.arccos(cos)))

    sl, sr = slope_deg(gon_l), slope_deg(gon_r)
    gl, gr = gonial_deg(ear_l, gon_l), gonial_deg(ear_r, gon_r)
    return {
        "jaw_slope": (sl + sr) / 2.0,
        "gonial_angle": (gl + gr) / 2.0,
        "jaw_slope_diff": abs(sl - sr),
    }


def _vertical_thirds(a) -> dict[str, float]:
    """三庭：髮際→眉心、眉心→鼻底、鼻底→下巴，各佔臉高的比例。

    這是傳統面相學的「三庭」，也是這組特徵裡**唯一的縱向資訊**——
    先前十個特徵全部在描述「哪裡寬」與「轉角尖不尖」，沒有一個描述上中下的分配。
    而長形臉與鵝蛋臉的寬度分布很接近，差別正是中庭被拉長；心形臉則是上庭寬、下庭短。

    量測前先用 _align_points_by_eyes 旋正，否則頭一歪，縱向距離就全部失真。
    三個值相加恆為 1，決策樹只會用到其中兩個的資訊——保留三個是為了讓分割條件
    直接對應到「哪一庭偏長」，寫進報告時看得懂。

    landmark：10 額頭頂、9 眉心、2 鼻底、152 下巴尖。
    """
    import numpy as np

    try:
        pts = np.array([a._pt(i) for i in (10, 9, 2, 152)], dtype=np.float32)
        top, brow, nose, chin = a._align_points_by_eyes(pts)
    except Exception:
        return {"upper_third": 0.0, "mid_third": 0.0, "lower_third": 0.0}

    total = float(chin[1] - top[1])
    if total < 1e-6:
        return {"upper_third": 0.0, "mid_third": 0.0, "lower_third": 0.0}
    return {
        "upper_third": float(brow[1] - top[1]) / total,
        "mid_third": float(nose[1] - brow[1]) / total,
        "lower_third": float(chin[1] - nose[1]) / total,
    }


def _jaw_shape_features(a) -> dict[str, float]:
    """下半臉的「方 vs 圓」。

    上面那七個特徵全部是**不同高度的寬度比值**——它們描述「哪裡寬」，
    但描述不了「轉角是尖的還是圓的」。圓形臉與方形臉的寬度分布其實很接近，
    差別在下顎轉角：方臉是接近直角的折線，圓臉是連續的弧。
    量不到那個，這兩類就只能靠運氣分（實測互認率 23%、對稱 0.89）。

    三個量都對臉高正規化，所以跟拍攝距離無關：

      jaw_fill        下半臉輪廓所圍的面積 ÷ 其外接矩形面積。
                      方形接近 1.0，圓形接近 π/4≈0.79，尖下巴更低。
      jaw_corner_cos  下顎轉角處的夾角餘弦。越接近 0 越像直角（方），
                      越接近 -1 越平順（圓）。
      chin_curvature  下巴最低點附近的曲率，用三點外接圓半徑的倒數。
    """
    pts = a.face_outline_points() if hasattr(a, "face_outline_points") else None
    if pts is None or len(pts) < 8:
        return {"jaw_fill": 0.0, "jaw_corner_cos": 0.0, "chin_curvature": 0.0}
    import numpy as np

    y_min, y_max = float(pts[:, 1].min()), float(pts[:, 1].max())
    height = max(y_max - y_min, 1e-6)
    # 只取下半臉：轉角與下巴都在這裡，上半部的髮際線反而是雜訊
    lower = pts[pts[:, 1] >= y_min + height * 0.55]
    if len(lower) < 5:
        return {"jaw_fill": 0.0, "jaw_corner_cos": 0.0, "chin_curvature": 0.0}

    # 依角度排序成一條連續輪廓（landmark 的原始順序不保證沿著邊界走）
    cx, cy = float(lower[:, 0].mean()), float(lower[:, 1].mean())
    order = np.argsort(np.arctan2(lower[:, 1] - cy, lower[:, 0] - cx))
    poly = lower[order]

    # ① 填充率：多邊形面積 ÷ 外接矩形面積
    x, y = poly[:, 0], poly[:, 1]
    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    bbox = max((x.max() - x.min()) * (y.max() - y.min()), 1e-6)
    jaw_fill = float(area / bbox)

    # ② 轉角銳利度：找最左與最右的點，量它與前後鄰點形成的夾角
    def corner_cos(i):
        p0, p1, p2 = poly[(i - 2) % len(poly)], poly[i], poly[(i + 2) % len(poly)]
        v1, v2 = p0 - p1, p2 - p1
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 < 1e-6 or n2 < 1e-6:
            return 0.0
        return float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    jaw_corner_cos = float(np.mean([corner_cos(int(np.argmin(poly[:, 0]))),
                                    corner_cos(int(np.argmax(poly[:, 0])))]))

    # ③ 下巴曲率：最低點與左右鄰點的外接圓半徑倒數，對臉高正規化
    bi = int(np.argmax(poly[:, 1]))
    p0, p1, p2 = poly[(bi - 2) % len(poly)], poly[bi], poly[(bi + 2) % len(poly)]
    d01, d12, d02 = (np.linalg.norm(p0 - p1), np.linalg.norm(p1 - p2), np.linalg.norm(p0 - p2))
    tri = abs((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])) / 2.0
    radius = (d01 * d12 * d02) / (4.0 * tri) if tri > 1e-6 else 1e6
    chin_curvature = float(height / max(radius, 1e-6))

    return {"jaw_fill": jaw_fill, "jaw_corner_cos": jaw_corner_cos, "chin_curvature": chin_curvature}


def lip_features(a) -> dict[str, float]:
    """唇型的幾何量，與 `FaceAnalyzer.get_lip_shape()` 用的是同一組。"""
    lip_width = a._dist(61, 291)
    lip_height = a._dist(0, 17)
    if lip_width < 1e-6:
        return {"height_ratio": 0.0, "m_diff_ratio": 0.0, "smile_diff_ratio": 0.0}
    center_y = a._pt(0)[1]
    peak_avg_y = (a._pt(37)[1] + a._pt(267)[1]) / 2.0
    corner_avg_y = (a._pt(61)[1] + a._pt(291)[1]) / 2.0
    return {
        "height_ratio": lip_height / lip_width,
        "m_diff_ratio": float(center_y - peak_avg_y) / lip_width,
        "smile_diff_ratio": float(center_y - corner_avg_y) / lip_width,
    }


EXTRACT = {
    "brow_shape": brow_features,
    "eye_shape": eye_features,
    "nose_shape": nose_features,
    "face_shape": face_features,
    "lip_shape": lip_features,
}
