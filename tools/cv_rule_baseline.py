"""規則式／幾何做法的 5-fold 評估——與 CNN 用同一套 fold，讓兩者真的可比。

## 為什麼需要這支

`calibrate_rule_thresholds.py` 用的是**單次切分**（`split_by_identity`,
`val_ratio=0.25`），而 CNN 的分數來自 **5-fold**（`split_kfold_by_identity`）。
兩者評估協定不同，分數不能直接並列比較——單次切分只看一個 val set，雜訊大得多。

2026-07-24 的校準顯示眼型規則式 0.374 對上 CNN 0.332，看起來規則式贏，
但那個差距（0.042）很可能小於單次切分本身的雜訊。這支腳本把規則式接上
**完全相同的 fold**（`split_kfold_by_identity(labels, identities, 5, 42)`，
對同一組 labels/identities 是確定性的），才能斷定誰真的比較好。

## 不能偷看的地方

- **門檻只能在每個 fold 的 train 上搜**，再到該 fold 的 val 評分。
  一次搜完全部資料再報分數等於用考題調參，分數必然虛高。
- **眼型決策樹的深度也要在 train 內部選**（train 再切一次 CV），
  不能拿 val 挑深度。

## 輸出

    models/basic_features_roi/rule_cv_results.json
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
from train_basic_cnn_roi import (  # noqa: E402
    build_part_data, load_cache, split_kfold_by_identity,
)
# 特徵與樹的輸入順序都取自 rule_features——服務端載入同一份定義。
# 訓練與推論的特徵一旦分家，模型會安靜地變差且極難察覺。
from rule_features import EXTRACT, TREE_FEATURES  # noqa: E402
FEATURE_CACHE = Path("data/roi_cache/rule_features.json")
OUT_PATH = Path("models/basic_features_roi/rule_cv_results.json")
N_FOLDS = 5
SEED = 42


def macro_accuracy(truth, pred, n_classes: int) -> float:
    cm = np.zeros((n_classes, n_classes), dtype=int)
    for t, p in zip(truth, pred):
        cm[int(t)][int(p)] += 1
    recalls = [cm[i][i] / cm[i].sum() for i in range(n_classes) if cm[i].sum()]
    return float(np.mean(recalls)) if recalls else 0.0


def load_part(part: str, cache: dict):
    """回傳 (特徵 list, labels, identities, classes)，列順序一致。

    特徵抽取要跑一次 MediaPipe，所以結果存進 `rule_features.json` 重複使用；
    ROI 快取重建後請刪掉該檔（或用 --refresh）。
    """
    all_rois, records = load_cache()
    _, labels, identities, classes = build_part_data(part, all_rois, records)
    rows = [i for i, r in enumerate(records) if part in r["labels"]]

    part_cache = cache.setdefault(part, {})
    feats = []
    for i in range(len(labels)):
        path = records[rows[i]]["path"]
        cached = part_cache.get(path)
        if cached is None:
            analyzer = FaceAnalyzer(path, strict_angle=False, require_insight=False)
            cached = {k: float(v) for k, v in EXTRACT[part](analyzer).items()}
            part_cache[path] = cached
        feats.append(cached)
        if (i + 1) % 100 == 0:
            print(f"    特徵 {i + 1}/{len(labels)}", flush=True)
    return feats, labels, identities, classes


def _fit_threshold_1d(values, y, classes, low_label, high_label, mid_label, grid):
    """三類、單特徵：在 train 上 grid search 兩個切點。"""
    idx = {name: i for i, name in enumerate(classes)}

    def predict(vals, t1, t2):
        return np.array([
            idx[low_label] if v < t1 else (idx[high_label] if v > t2 else idx[mid_label])
            for v in vals
        ])

    best = (-1.0, None, None)
    for t1 in grid:
        for t2 in grid[grid > t1]:
            s = macro_accuracy(y, predict(values, t1, t2), len(classes))
            if s > best[0]:
                best = (s, float(t1), float(t2))
    return best[1], best[2], predict


def _fit_threshold_binary(values, y, classes, low_label, high_label, grid):
    idx = {name: i for i, name in enumerate(classes)}

    def predict(vals, t):
        return np.array([idx[low_label] if v < t else idx[high_label] for v in vals])

    best = (-1.0, None)
    for t in grid:
        s = macro_accuracy(y, predict(values, t), len(classes))
        if s > best[0]:
            best = (s, float(t))
    return best[1], predict


def cv_threshold(part, feat_name, classes_spec, grid, cache):
    feats, labels, identities, classes = load_part(part, cache)
    values = np.array([f[feat_name] for f in feats])
    folds = split_kfold_by_identity(labels, identities, N_FOLDS, SEED)

    per_fold, chosen, true_all, pred_all = [], [], [], []
    for train_idx, val_idx in folds:
        if len(classes_spec) == 3:
            low, high, mid = classes_spec
            t1, t2, predict = _fit_threshold_1d(
                values[train_idx], labels[train_idx], classes, low, high, mid, grid)
            pred = predict(values[val_idx], t1, t2)
            chosen.append({"t1": t1, "t2": t2})
        else:
            low, high = classes_spec
            t, predict = _fit_threshold_binary(
                values[train_idx], labels[train_idx], classes, low, high, grid)
            pred = predict(values[val_idx], t)
            chosen.append({"t": t})
        per_fold.append(macro_accuracy(labels[val_idx], pred, len(classes)))
        true_all.append(labels[val_idx])
        pred_all.append(pred)

    return _summarise(part, classes, per_fold, np.concatenate(true_all),
                      np.concatenate(pred_all), {"feature": feat_name,
                                                 "per_fold_thresholds": chosen})


def cv_tree(part, cache):
    """對任一部位跑「淺決策樹」規則式，與 CNN 同一組 fold。

    用決策樹而不是別的分類器，是因為它學出來的東西**本身就是規則**——可以直接
    印成 if-else 抄回 `Face_analyzer_BASIC`，維持規則式路徑「看得懂、改得動」的
    性質。深度限制加上 `min_samples_leaf=8` 是為了不讓它在幾百張圖上長成
    一棵背答案的樹。
    """
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.tree import DecisionTreeClassifier

    feats, labels, identities, classes = load_part(part, cache)
    names = TREE_FEATURES[part]
    X = np.array([[f[n] for n in names] for f in feats])
    folds = split_kfold_by_identity(labels, identities, N_FOLDS, SEED)

    per_fold, depths, true_all, pred_all = [], [], [], []
    for train_idx, val_idx in folds:
        # 深度在 train 內部再切一次 CV 來選，val 全程不參與。
        inner = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
        best = (-1.0, None)
        for depth in (2, 3, 4, 5):
            scores = cross_val_score(
                DecisionTreeClassifier(max_depth=depth, class_weight="balanced",
                                       random_state=SEED, min_samples_leaf=8),
                X[train_idx], labels[train_idx], cv=inner, scoring="balanced_accuracy")
            if scores.mean() > best[0]:
                best = (float(scores.mean()), depth)
        depth = best[1]
        tree = DecisionTreeClassifier(max_depth=depth, class_weight="balanced",
                                      random_state=SEED, min_samples_leaf=8)
        tree.fit(X[train_idx], labels[train_idx])
        pred = tree.predict(X[val_idx])
        per_fold.append(macro_accuracy(labels[val_idx], pred, len(classes)))
        depths.append(depth)
        true_all.append(labels[val_idx])
        pred_all.append(pred)

    return _summarise(f"{part}(tree)", classes, per_fold, np.concatenate(true_all),
                      np.concatenate(pred_all), {"features": names,
                                                 "per_fold_depth": depths})


def _summarise(part, classes, per_fold, y_true, y_pred, extra):
    per_class = {}
    for i, name in enumerate(classes):
        mask = y_true == i
        per_class[name] = {
            "support": int(mask.sum()),
            "recall": round(float((y_pred[mask] == i).mean()), 4) if mask.sum() else None,
        }
    out = {
        "classes": list(classes),
        "n_folds": N_FOLDS,
        "seed": SEED,
        "fold_macro_accuracies": [round(v, 4) for v in per_fold],
        "mean_macro": round(float(np.mean(per_fold)), 4),
        "std_macro": round(float(np.std(per_fold)), 4),
        "pooled_macro": round(macro_accuracy(y_true, y_pred, len(classes)), 4),
        "per_class": per_class,
        **extra,
    }
    print(f"\n=== {part}（{len(classes)} 類，規則式 5-fold）===")
    print(f"  各 fold macro = {', '.join(f'{v:.3f}' for v in per_fold)}")
    print(f"  平均 {out['mean_macro']:.4f} ± {out['std_macro']:.4f}")
    return out


def main():
    refresh = "--refresh" in sys.argv
    cache = {} if refresh or not FEATURE_CACHE.is_file() else json.loads(
        FEATURE_CACHE.read_text(encoding="utf-8"))

    print("=" * 70)
    print(f"規則式 5-fold（與 CNN 同一組 fold：split_kfold_by_identity, seed={SEED}）")
    print("=" * 70)

    results = {}

    # 單一門檻版：只有眉、鼻適用（各只有一個有鑑別力的特徵）。
    print("\n[1/7] brow_shape（單一門檻）")
    results["brow_shape_threshold"] = cv_threshold(
        "brow_shape", "tail_ratio", ("一字眉", "落尾眉", "彎月眉"),
        np.arange(-0.06, 0.06, 0.002), cache)

    print("\n[2/7] nose_shape（單一門檻）")
    results["nose_shape_threshold"] = cv_threshold(
        "nose_shape", "ratio_width", ("標準鼻", "寬鼻"),
        np.arange(0.24, 0.40, 0.002), cache)

    # 決策樹版：五個部位都跑，這樣「規則式 vs CNN」在每個部位都有可比的數字。
    for i, part in enumerate(("eye_shape", "face_shape", "lip_shape",
                              "brow_shape", "nose_shape"), start=3):
        print(f"\n[{i}/7] {part}（決策樹）")
        results[f"{part}_tree"] = cv_tree(part, cache)

    FEATURE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FEATURE_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # 與 CNN 並列。CNN 分數從 cv_summary 讀，不寫死。
    print("\n\n" + "=" * 70)
    print("規則式 vs CNN（同一組 5-fold，可直接比較）")
    print("=" * 70)
    summary_path = Path("models/basic_features_roi/cv_summary.json")
    cnn, cnn_folds = {}, {}
    if summary_path.is_file():
        raw = json.loads(summary_path.read_text(encoding="utf-8"))
        for part, v in raw.items():
            if not isinstance(v, dict):
                continue
            block = v.get("cv", v)
            cnn[part] = block.get("mean_macro")
            cnn_folds[part] = block.get("fold_macro_accuracies", [])
    print(f"  {'部位':12}{'最佳規則式':>12}{'±std':>8}{'CNN':>9}  勝場   判定")
    for part in ("face_shape", "brow_shape", "eye_shape", "nose_shape", "lip_shape"):
        variants = {k: v for k, v in results.items() if k.startswith(part)}
        if not variants:
            continue
        name, res = max(variants.items(), key=lambda kv: kv[1]["mean_macro"])
        rule, std = res["mean_macro"], res["std_macro"]
        c = cnn.get(part)
        if c is None:
            print(f"  {part:12}{rule:12.4f}{std:8.4f}{'n/a':>9}   -    （找不到 CNN 分數）")
            continue
        # 逐 fold 配對比較：同一個 fold 直接比，比看平均可靠得多。平均值相近時，
        # 「每個 fold 都贏」和「贏兩個輸三個」是完全不同的結論。
        diffs = np.array(res["fold_macro_accuracies"]) - np.array(
            cnn_folds.get(part, [0] * N_FOLDS))
        wins = int((diffs > 0).sum())
        if wins >= 4 and abs(diffs.mean()) > diffs.std():
            verdict = "規則式勝" if diffs.mean() > 0 else "CNN 勝"
        elif wins <= 1 and abs(diffs.mean()) > diffs.std():
            verdict = "CNN 勝" if diffs.mean() < 0 else "規則式勝"
        else:
            verdict = "差距在雜訊內，不下定論"
        tag = name.replace(part + "_", "")
        print(f"  {part:12}{rule:12.4f}{std:8.4f}{c:9.4f}  {wins}/5   {verdict}（{tag}）")
    print(f"\n結果寫入 {OUT_PATH}")


if __name__ == "__main__":
    main()
