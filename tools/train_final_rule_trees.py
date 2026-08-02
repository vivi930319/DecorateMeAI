"""用 100% 清理後資料訓練最終的幾何決策樹，並匯出成服務可載入的檔案。

選擇決策樹的原因

`tools/cv_rule_baseline.py` 在與 CNN 完全相同的 5-fold 上量出來的結果：

    眼型  規則式 0.406 vs CNN 0.332   規則式勝 5/5 fold（+0.074 ± 0.038）
    臉型  規則式 0.544 vs CNN 0.477   規則式勝 4/5 fold（+0.067 ± 0.059）

這兩個部位的類別差異本來就是幾何量——眼型是開合比例與眼角角度，臉型是不同高度的
寬度比值——在幾百張的規模下，CNN 學不回這些量，直接算反而準。

其餘三個部位（眉、鼻、唇）維持 CNN：規則式在那裡輸，但差距都小於逐 fold 差的
標準差，屬於傾向而非定論。

輸出

    models/basic_features_roi/<part>_rule_tree.joblib   sklearn 決策樹
    models/basic_features_roi/<part>_rule_tree.json     類別、特徵順序、深度、可讀規則

JSON 裡附上 `export_text` 的規則文字，讓人能直接讀懂模型在做什麼——這正是選決策樹
而不是別的分類器的理由，別把它退化成又一個黑盒子。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ROI_SHADOW_ENABLED", "0")

from tools.cv_rule_baseline import (  # noqa: E402
    N_FOLDS, SEED, TREE_FEATURES, load_part, macro_accuracy,
)

OUT_DIR = Path("models/basic_features_roi")
RULE_PARTS = ("eye_shape", "face_shape")
FEATURE_CACHE = Path("data/roi_cache/rule_features.json")


def train_one(part: str, cache: dict) -> dict:
    import joblib
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.tree import DecisionTreeClassifier, export_text

    feats, labels, identities, classes = load_part(part, cache)
    names = TREE_FEATURES[part]
    X = np.array([[f[n] for n in names] for f in feats])

    # 深度用全體資料的分層 CV 選。這裡沒有「洩漏」問題：真正的泛化估計已經在
    # cv_rule_baseline 用嚴格的 identity-fold 量過了，這一步只是決定最終要出貨的
    # 那棵樹長多深。拿這裡的分數當泛化指標才是錯的——所以下面刻意不印它當賣點。
    inner = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    best = (-1.0, None)
    for depth in (2, 3, 4, 5):
        scores = cross_val_score(
            DecisionTreeClassifier(max_depth=depth, class_weight="balanced",
                                   random_state=SEED, min_samples_leaf=8),
            X, labels, cv=inner, scoring="balanced_accuracy")
        if scores.mean() > best[0]:
            best = (float(scores.mean()), depth)
    depth = best[1]

    tree = DecisionTreeClassifier(max_depth=depth, class_weight="balanced",
                                  random_state=SEED, min_samples_leaf=8)
    tree.fit(X, labels)
    train_macro = macro_accuracy(labels, tree.predict(X), len(classes))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(tree, OUT_DIR / f"{part}_rule_tree.joblib")
    rules = export_text(tree, feature_names=names, class_names=list(classes), decimals=3)
    meta = {
        "part": part,
        "classes": list(classes),
        "features": names,
        "max_depth": depth,
        "train_count": int(len(labels)),
        "train_macro": round(train_macro, 4),
        "note": ("train_macro 是在訓練資料上的分數，不是泛化估計；"
                 f"泛化請看 rule_cv_results.json（{N_FOLDS}-fold, identity 切分）"),
        "rules": rules,
    }
    (OUT_DIR / f"{part}_rule_tree.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== {part} ===")
    print(f"  類別 {classes}")
    print(f"  特徵 {names}")
    print(f"  選定深度 {depth}，訓練 {len(labels)} 張，train macro {train_macro:.3f}（非泛化指標）")
    print(rules)
    return meta


def main():
    cache = json.loads(FEATURE_CACHE.read_text(encoding="utf-8")) if FEATURE_CACHE.is_file() else {}
    for part in RULE_PARTS:
        train_one(part, cache)
    FEATURE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FEATURE_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"\n已匯出到 {OUT_DIR}")


if __name__ == "__main__":
    main()
