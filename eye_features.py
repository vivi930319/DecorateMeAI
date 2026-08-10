"""眼型精密幾何特徵的唯一定義處(含虹膜,需 refine_landmarks=True 的 478 點)。

跟 `rule_features.py` 同樣的原則:訓練(tools/train_eye_fusion.py)與線上推論
(basic_roi_shadow)共用這一份,公式與 landmark 索引只有一份——融合頭把這些幾何值
接在 eye CNN 機率後面,訓練與推論只要有一點對不上,分類器就會安靜地拿到偏掉的輸入。

放在專案根目錄而不是 tools/:Dockerfile 逐檔 COPY、不含 tools/,特徵定義留在工具目錄
線上就載不到。所有特徵都是比值/角度,不是像素長度——拍遠拍近像素會變、比值不會。

需要 refine_landmarks=True 才有的索引:左虹膜中心 468/環 469-472,右虹膜中心 473/環 474-477。
虹膜露出(iris_openness / upper_cover / lower_show)是分「圓眼 / 下垂眼 / 鳳眼」的關鍵訊號,
對應眼科的 margin-reflex distance(MRD),refine=False 的 468 點量不到。
"""
from __future__ import annotations

import numpy as np

# 眼周索引沿用 Face_analyzer_BASIC._eye_side_metrics,再加虹膜。
_EYES = [
    dict(inner=133, outer=33, upper=(157, 158, 159, 160, 161), lower=(145, 144, 153, 163),
         iris_c=468, iris_r=(469, 470, 471, 472)),
    dict(inner=362, outer=263, upper=(385, 386, 387, 388, 398), lower=(374, 380, 381, 382),
         iris_c=473, iris_r=(474, 475, 476, 477)),
]

# 融合頭的特徵順序 = 輸入契約,改動等於換一個模型。
EYE_FUSION_FEATURES = ["ear", "ratio_to_face", "canthal_tilt", "upper_curve", "lower_curve",
                       "iris_openness", "upper_cover", "lower_show", "apex_x"]


def align_points(points: np.ndarray) -> np.ndarray:
    """用兩眼中心連線旋正,讓角度與縱向量測不受頭歪影響。"""
    pts = np.asarray(points, dtype=np.float32)
    lc = pts[[33, 133, 145, 159]].mean(0)
    rc = pts[[263, 362, 374, 386]].mean(0)
    ang = np.arctan2(rc[1] - lc[1], rc[0] - lc[0])
    c, s = np.cos(-ang), np.sin(-ang)
    R = np.array([[c, -s], [s, c]], dtype=np.float32)
    return (pts - pts.mean(0)) @ R.T


def eye_features_from_points(points: np.ndarray) -> dict[str, float]:
    """吃 478×2 的 refine landmark 陣列,回傳左右平均後的眼型幾何特徵(dict)。

    少於 478 點(沒開 refine_landmarks)會抓不到虹膜索引而丟 IndexError——
    呼叫端要確保傳進來的是 refine=True 的結果。
    """
    P = align_points(points)
    face_w = float(np.linalg.norm(P[234] - P[454])) or 1.0
    rows = []
    for e in _EYES:
        inner, outer = P[e["inner"]], P[e["outer"]]
        up = P[list(e["upper"])]; lo = P[list(e["lower"])]
        ic = P[e["iris_c"]]; ir = P[list(e["iris_r"])]
        w = float(np.linalg.norm(outer - inner)) or 1.0
        up_mid, lo_mid = up.mean(0), lo.mean(0)
        h = abs(float(up_mid[1] - lo_mid[1]))
        iris_d = float(2 * np.mean(np.linalg.norm(ir - ic, axis=1))) or 1.0
        rows.append([
            h / w,                                                    # ear
            w / face_w,                                               # ratio_to_face
            float(np.degrees(np.arctan2(inner[1] - outer[1], abs(inner[0] - outer[0]) + 1e-6))),  # canthal_tilt
            (float(up[:, 1].max() - up[:, 1].min())) / (h + 1e-6),    # upper_curve
            (float(lo[:, 1].max() - lo[:, 1].min())) / (h + 1e-6),    # lower_curve
            h / iris_d,                                               # iris_openness
            float(ic[1] - up_mid[1]) / iris_d,                        # upper_cover
            float(lo_mid[1] - ic[1]) / iris_d,                        # lower_show
            abs(float(up[np.argmin(up[:, 1])][0] - inner[0]) / ((outer[0] - inner[0]) or 1.0)),  # apex_x
        ])
    avg = np.mean(rows, axis=0)
    return dict(zip(EYE_FUSION_FEATURES, (float(v) for v in avg)))
