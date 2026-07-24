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
    "face_shape": ["height_width", "forehead_norm", "cheek_norm", "jaw_norm",
                   "forehead_to_jaw", "cheek_to_jaw", "chin_to_jaw"],
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
    return {
        "height_width": m["face_height"] / max(m["face_width"], 1e-6),
        "forehead_norm": fw / max_w,
        "cheek_norm": ch / max_w,
        "jaw_norm": jw / max_w,
        "forehead_to_jaw": fw / max(jw, 1e-6),
        "cheek_to_jaw": ch / max(jw, 1e-6),
        "chin_to_jaw": m["chin_width"] / max(jw, 1e-6),
    }


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
