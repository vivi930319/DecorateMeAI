"""
用 MediaPipe/InsightFace landmark 算出的比例特徵，訓練 Random Forest 分類器。

資料來源：data/basic_full/grouped/<part>/<label>/*.jpg
輸出模型：models/rf_<part>.joblib

這是 pipeline 起步版本，目標是先把「landmark 特徵 -> Random Forest -> 分類結果」
的流程跑通，不是最終準確率調校。之後補齊照片、再重跑這支腳本即可更新模型。
"""

import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
import os
import glob
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import classification_report

from Face_analyzer_BASIC import FaceAnalyzer

DATA_ROOT = os.path.join(os.path.dirname(__file__), "data", "basic_full", "grouped")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _load_image_bytes(path):
    with open(path, "rb") as f:
        return f.read()


# ---- 各部位特徵擷取（沿用 Face_analyzer_BASIC 既有的 landmark 索引與比例邏輯）----

def face_shape_features(fa: FaceAnalyzer):
    face_width      = fa._dist(234, 454)
    forehead_width  = fa._dist(103, 332)
    cheekbone_width = fa._dist(123, 352)
    jaw_width       = fa._dist(132, 361)
    chin_width      = fa._dist(150, 379)
    face_height     = fa._dist(10, 152)
    if face_width < 1e-6 or jaw_width < 1e-6:
        return None

    hw = face_height / face_width
    max_w = max(forehead_width, cheekbone_width, jaw_width)
    return [
        hw,
        forehead_width / max_w,
        cheekbone_width / max_w,
        jaw_width / max_w,
        jaw_width / forehead_width if forehead_width > 1e-6 else 1.0,
        forehead_width / jaw_width if jaw_width > 1e-6 else 1.0,
        cheekbone_width / jaw_width if jaw_width > 1e-6 else 1.0,
        forehead_width / cheekbone_width if cheekbone_width > 1e-6 else 1.0,
        chin_width / jaw_width if jaw_width > 1e-6 else 1.0,
    ]


_L_BROW = (46, 53, 52, 65, 55)
_R_BROW = (276, 283, 282, 295, 285)


def _brow_metrics(fa: FaceAnalyzer, outer_idx, inner_idx, outline):
    head = fa._pt(outer_idx).astype(np.float32)
    tail = fa._pt(inner_idx).astype(np.float32)
    width = float(np.linalg.norm(tail - head))
    if width < 1e-6:
        return 0.0, 0.0
    pts = np.array([fa._pt(i) for i in outline], dtype=np.float32)
    peak_y = float(np.min(pts[:, 1]))
    base_y = (float(head[1]) + float(tail[1])) / 2.0
    arch_ratio = (base_y - peak_y) / width
    tail_ratio = (float(head[1]) - float(tail[1])) / width
    return arch_ratio, tail_ratio


def brow_shape_features(fa: FaceAnalyzer):
    left_arch, left_tail = _brow_metrics(fa, 46, 55, _L_BROW)
    right_arch, right_tail = _brow_metrics(fa, 276, 285, _R_BROW)
    return [
        (left_arch + right_arch) / 2.0,
        (left_tail + right_tail) / 2.0,
    ]


def eye_shape_features(fa: FaceAnalyzer):
    face_width = fa._dist(234, 454)
    if face_width < 1e-6:
        return None

    left = fa._eye_side_metrics(133, 33, (157, 158, 159, 160, 161), 145, (46, 53, 52, 65, 55))
    left["angle"] = -left["angle"]
    right = fa._eye_side_metrics(362, 263, (385, 386, 387, 388, 398), 374, (276, 283, 282, 295, 285))

    eye_width = (left["eye_width"] + right["eye_width"]) / 2.0
    if eye_width < 1e-6:
        return None

    ear = (left["ear"] + right["ear"]) / 2.0
    angle = (left["angle"] + right["angle"]) / 2.0
    ratio_to_face = eye_width / face_width
    lid_curve = (left["lid_curve"] + right["lid_curve"]) / 2.0
    brow_gap = (left["brow_gap"] + right["brow_gap"]) / 2.0

    return [ear, angle, ratio_to_face, lid_curve, brow_gap]


def nose_shape_features(fa: FaceAnalyzer):
    nose_width = fa._dist(129, 358)
    face_width = fa._dist(234, 454)
    if face_width < 1e-6:
        return None
    return [nose_width / face_width]


def lip_shape_features(fa: FaceAnalyzer):
    lip_width = fa._dist(61, 291)
    lip_height = fa._dist(0, 17)
    if lip_width < 1e-6:
        return None
    ratio = lip_height / lip_width

    peak_left_y = fa._pt(37)[1]
    peak_right_y = fa._pt(267)[1]
    center_y = fa._pt(0)[1]
    m_diff = center_y - (peak_left_y + peak_right_y) / 2

    corner_avg_y = (fa._pt(61)[1] + fa._pt(291)[1]) / 2
    smile_diff = center_y - corner_avg_y

    return [ratio, m_diff / lip_width, smile_diff / lip_width]


PARTS = {
    "face_shape": face_shape_features,
    "brow_shape": brow_shape_features,
    "eye_shape": eye_shape_features,
    "nose_shape": nose_shape_features,
    "lip_shape": lip_shape_features,
}


def build_dataset(part, feature_fn):
    part_dir = os.path.join(DATA_ROOT, part)
    X, y, failed = [], [], []

    labels = sorted(
        d for d in os.listdir(part_dir)
        if os.path.isdir(os.path.join(part_dir, d))
    )
    for label in labels:
        label_dir = os.path.join(part_dir, label)
        files = [
            p for p in glob.glob(os.path.join(label_dir, "*"))
            if p.lower().endswith(IMAGE_EXTS)
        ]
        for path in files:
            try:
                image_bytes = _load_image_bytes(path)
                fa = FaceAnalyzer(image_bytes, strict_angle=False)
                feats = feature_fn(fa)
                if feats is None:
                    failed.append((path, "特徵計算失敗（比例分母為 0）"))
                    continue
                X.append(feats)
                y.append(label)
            except Exception as e:
                failed.append((path, str(e)))

    return np.array(X, dtype=np.float32), np.array(y), failed


def train_part(part, feature_fn):
    print(f"\n===== {part} =====")
    X, y, failed = build_dataset(part, feature_fn)

    if failed:
        print(f"跳過 {len(failed)} 張圖片（偵測失敗或特徵無效）：")
        for path, reason in failed[:5]:
            print(f"  - {os.path.basename(path)}: {reason}")
        if len(failed) > 5:
            print(f"  ...還有 {len(failed) - 5} 張")

    if len(X) == 0:
        print("沒有可用的訓練資料，略過。")
        return

    labels, counts = np.unique(y, return_counts=True)
    print(f"可用樣本數：{len(X)}，類別數：{len(labels)}")
    for lb, cnt in zip(labels, counts):
        print(f"  - {lb}: {cnt} 張")

    min_count = int(counts.min())
    n_splits = max(2, min(5, min_count))
    if min_count < 2:
        print("有類別樣本數小於 2，無法做交叉驗證，直接訓練最終模型並略過驗證報告。")
        clf = RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42)
        clf.fit(X, y)
    else:
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        clf = RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42)
        y_pred = cross_val_predict(clf, X, y, cv=skf)
        print(f"\n{n_splits}-fold 交叉驗證結果（樣本數很少，僅供參考）：")
        print(classification_report(y, y_pred, zero_division=0))
        clf.fit(X, y)  # 用全部資料訓練最終模型

    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path = os.path.join(MODEL_DIR, f"rf_{part}.joblib")
    joblib.dump(clf, model_path)
    print(f"模型已存到 {model_path}")


def main():
    for part, feature_fn in PARTS.items():
        train_part(part, feature_fn)


if __name__ == "__main__":
    main()
