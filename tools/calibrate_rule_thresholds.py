"""用「我們自己的資料」重新校準規則式的閾值，取代原本從 CelebA 抄來的那組。

背景見 規則式閾值Bug_完整診斷記錄_新手版.md：原本的門檻多數落在資料分佈之外
（眉型 2 個死碼、眼型 3 個死碼 + 1 個恆真、鼻型 1 個死碼），導致三個部位分別把
100% / 96% / 98% 的人判成同一個答案。

鐵則：**只能用 train set 找門檻，然後在 val set 驗證。**
用 val set 找門檻等於偷看考題，分數會虛高且無法反映真實表現。
切分方式與 CNN 完全一致（split_by_identity, seed=42, val_ratio=0.25），這樣三個方案才可比。

做法：
    眉型：單一特徵、三個類別 -> grid search 兩個切點。
    鼻型：單一特徵、兩個類別（2026-07-24 起窄鼻併入標準鼻、蒜頭鼻併入寬鼻）-> 一個切點。
    眼型：多類別、3 個特徵 -> 用淺決策樹（深度由 train 內部 CV 選）學規則，再人工移植成 if-else。
          用決策樹是因為它學出來的東西「本身就是規則」，可以直接讀出來寫回程式碼，
          不像 CNN 是黑盒子。深度限制成 3 是為了讓規則短到人看得懂、也不會過擬合 200 多張圖。

輸出：把建議的門檻與 val 分數印出來，人工確認後手動改進 Face_analyzer_BASIC。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ROI_SHADOW_ENABLED", "0")

from Face_analyzer_BASIC import FaceAnalyzer  # noqa: E402
from train_basic_cnn_roi import build_part_data, load_cache, split_by_identity  # noqa: E402
from tools.diagnose_rule_thresholds import brow_features, eye_features, nose_features  # noqa: E402

EXTRACT = {
    "brow_shape": brow_features,
    "eye_shape": eye_features,
    "nose_shape": nose_features,
}


def macro_accuracy(truth, pred, n_classes):
    cm = np.zeros((n_classes, n_classes), dtype=int)
    for t, p in zip(truth, pred):
        cm[t][p] += 1
    recalls = [cm[i][i] / cm[i].sum() for i in range(n_classes) if cm[i].sum()]
    return float(np.mean(recalls)) if recalls else 0.0


def load_part(part):
    """回傳 (train, val)，每個是 (特徵 dict 陣列, 類別索引陣列, 類別名稱)。"""
    all_rois, records = load_cache()
    _, labels, identities, classes = build_part_data(part, all_rois, records)
    rows = [i for i, r in enumerate(records) if part in r["labels"]]
    train_idx, val_idx = split_by_identity(labels, identities, 0.25, 42)

    feats = {}
    for i in set(train_idx) | set(val_idx):
        a = FaceAnalyzer(records[rows[i]]["path"], strict_angle=False, require_insight=False)
        feats[i] = EXTRACT[part](a)

    def pack(idx):
        return [feats[i] for i in idx], np.array([labels[i] for i in idx]), classes

    return pack(train_idx), pack(val_idx), classes


def calibrate_1d(part, feat_name, low_label, high_label, mid_label, grid):
    """單一特徵、三類：找兩個切點。低於 t1 -> low_label，高於 t2 -> high_label，其餘 mid_label。"""
    (tr_f, tr_y, classes), (va_f, va_y, _), _ = load_part(part)
    idx = {name: i for i, name in enumerate(classes)}
    tr_v = np.array([f[feat_name] for f in tr_f])
    va_v = np.array([f[feat_name] for f in va_f])

    def predict(vals, t1, t2):
        return np.array([
            idx[low_label] if v < t1 else (idx[high_label] if v > t2 else idx[mid_label])
            for v in vals
        ])

    best = (-1.0, None, None)
    for t1 in grid:
        for t2 in grid[grid > t1]:
            s = macro_accuracy(tr_y, predict(tr_v, t1, t2), len(classes))
            if s > best[0]:
                best = (s, float(t1), float(t2))

    _, t1, t2 = best
    val_score = macro_accuracy(va_y, predict(va_v, t1, t2), len(classes))

    print(f"\n=== {part}（特徵 {feat_name}）===")
    print(f"  建議門檻：{feat_name} < {t1:.3f} -> {low_label}　"
          f"{feat_name} > {t2:.3f} -> {high_label}　其餘 -> {mid_label}")
    print(f"  train macro = {best[0]:.3f}")
    print(f"  val   macro = {val_score:.3f}  <- 可信的數字")
    return t1, t2, val_score


def calibrate_binary(part, feat_name, low_label, high_label, grid):
    """單一特徵、兩類：找一個切點。低於 t -> low_label，否則 high_label。"""
    (tr_f, tr_y, classes), (va_f, va_y, _), _ = load_part(part)
    idx = {name: i for i, name in enumerate(classes)}
    missing = [n for n in (low_label, high_label) if n not in idx]
    if missing:
        print(f"\n=== {part} ===\n  跳過：資料裡找不到類別 {missing}（實際類別 {classes}）")
        return None, None
    tr_v = np.array([f[feat_name] for f in tr_f])
    va_v = np.array([f[feat_name] for f in va_f])

    def predict(vals, t):
        return np.array([idx[low_label] if v < t else idx[high_label] for v in vals])

    best = (-1.0, None)
    for t in grid:
        s = macro_accuracy(tr_y, predict(tr_v, t), len(classes))
        if s > best[0]:
            best = (s, float(t))

    _, t = best
    val_score = macro_accuracy(va_y, predict(va_v, t), len(classes))
    print(f"\n=== {part}（特徵 {feat_name}，兩類）===")
    print(f"  建議門檻：{feat_name} < {t:.3f} -> {low_label}　否則 -> {high_label}")
    print(f"  train macro = {best[0]:.3f}")
    print(f"  val   macro = {val_score:.3f}  <- 可信的數字")
    return t, val_score


def calibrate_eye():
    """眼型：用淺決策樹學規則，再把樹印成可以直接抄回程式碼的 if-else。

    類別數改由資料決定——2026-07-24 起官方分類表把丹鳳眼併入鳳眼、瞇縫眼併入細長眼，
    眼型從 8 類降為 6 類，寫死類別數只會讓輸出訊息說謊。
    """
    from sklearn.tree import DecisionTreeClassifier, export_text

    (tr_f, tr_y, classes), (va_f, va_y, _), _ = load_part("eye_shape")
    names = ["ear", "angle", "ratio_to_face"]
    tr_X = np.array([[f[n] for n in names] for f in tr_f])
    va_X = np.array([[f[n] for n in names] for f in va_f])

    print(f"\n=== eye_shape（{len(classes)} 類，決策樹）===")

    # 深度必須用 train set 內部的交叉驗證來選，不能用 val 選 ——
    # 拿 val 挑超參數等於偷看考題，選出來的分數會虛高，也失去「未見過的資料」這個意義。
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    best = (-1.0, None)
    for depth in (2, 3, 4, 5):
        scores = cross_val_score(
            DecisionTreeClassifier(max_depth=depth, class_weight="balanced",
                                   random_state=42, min_samples_leaf=8),
            tr_X, tr_y, cv=cv, scoring="balanced_accuracy",
        )
        print(f"  max_depth={depth}  train 內部 5-fold CV = {scores.mean():.3f}")
        if scores.mean() > best[0]:
            best = (float(scores.mean()), depth)

    _, depth = best
    tree = DecisionTreeClassifier(max_depth=depth, class_weight="balanced",
                                  random_state=42, min_samples_leaf=8).fit(tr_X, tr_y)
    tr_s = macro_accuracy(tr_y, tree.predict(tr_X), len(classes))
    va_s = macro_accuracy(va_y, tree.predict(va_X), len(classes))
    print(f"\n  依 CV 選 max_depth={depth}")
    print(f"  train macro = {tr_s:.3f}")
    print(f"  val   macro = {va_s:.3f}  <- 可信的數字（val 完全沒參與選擇）")

    predicted = {classes[i] for i in set(tree.predict(va_X).tolist())}
    missing = [c for c in classes if c not in predicted]
    if missing:
        print(f"\n  !! 注意：這棵樹從不輸出 {missing}"
              f"（{len(classes)} 類只用 3 個弱特徵，難度本來就高）")
    print("\n  學出來的規則（可直接移植成 if-else）：")
    print(export_text(tree, feature_names=names,
                      class_names=list(classes), decimals=3))
    return va_s


def main():
    print("=" * 70)
    print("用自己的資料重新校準規則式閾值（只用 train set 找門檻，val set 驗證）")
    print("=" * 70)

    # 眉型：只用 tail_ratio。arch_ratio 分離度僅 0.40（類內雜訊大於類間差距），沒有鑑別力，放棄。
    calibrate_1d("brow_shape", "tail_ratio",
                 low_label="一字眉", high_label="落尾眉", mid_label="彎月眉",
                 grid=np.arange(-0.06, 0.06, 0.002))

    # 鼻型：ratio_width（鼻寬 / 臉寬）。
    # 2026-07-24 起鼻型是兩類——窄鼻併入標準鼻、蒜頭鼻併入寬鼻（官方分類表），
    # 所以只要找一個切點，不再是三類的兩個切點。
    calibrate_binary("nose_shape", "ratio_width",
                     low_label="標準鼻", high_label="寬鼻",
                     grid=np.arange(0.24, 0.40, 0.002))

    calibrate_eye()

    # 對照用的 CNN 分數不寫死在這裡：寫死的數字在資料或類別定義變動後就會變成謊話，
    # 而這支工具的用途正是在那些變動之後重新校準。請看 cv_summary。
    print("\n\n對照：CNN 的 5-fold 分數見 models/basic_features_roi/ 底下的 cv_summary*.json。")
    print("注意：上面的規則式分數來自單次切分（val_ratio=0.25），CNN 是 5-fold，")
    print("      兩者評估協定不同；差距小於雜訊時不要當成結論。")


if __name__ == "__main__":
    main()
