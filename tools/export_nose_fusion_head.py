"""訓練並匯出鼻型的「幾何 ⊕ DINOv2」融合分類頭。

## 為什麼鼻型要融合，其他部位不要

同一組 5-fold 上量到的錯誤重疊率（同時答錯 ÷ 至少一個答錯）：

    部位          DINOv2∩幾何    三者皆錯
    face_shape       0.43          0.26
    brow_shape       0.37          0.22
    eye_shape        0.35          0.20
    nose_shape       0.09          0.03    ← 只有鼻型真的互補
    lip_shape        0.39          0.22

集成有效的前提是成員錯在不同樣本上。臉／眉／眼／唇有 20~26% 的樣本是所有模型
同時答錯（界線本來就模糊的臉），融合或投票都救不回來；鼻型只有 3%。

逐折驗證（LinearSVC，同一組 fold）：

    DINOv2 單獨      0.8464 ± 0.0788
    幾何單獨          0.8027 ± 0.0731
    幾何⊕DINOv2      0.8844 ± 0.0631     +0.038，勝 4/5 折

⚠️ 誠實標記：配對差的 std 是 0.0351，平均差/標準誤 = 2.42（雙尾 p ≈ 0.07），
**沒有跨過 p<0.05**。採用的理由是三次獨立估計（+0.044/+0.028/+0.038）全部為正、
融合的 std 反而更小，而且**邊際成本是零**——DINOv2 backbone 每次分析已經在
鼻型 ROI 上跑過（見 basic_roi_shadow.DINOV2_PARTS），embedding 現在就在算。

## 把 StandardScaler 摺進權重

訓練時幾何特徵要標準化（原始尺度是比值，與 L2 正規化後的 embedding 差一個數量級，
不標準化的話線性模型會把它們當雜訊）。但推論端不該再多帶一個 scaler 物件——
線性模型可以直接把仿射變換摺進去：

    score = w_e·e + w_g·((g − μ) / σ) + b
          = w_e·e + (w_g / σ)·g + (b − (w_g·μ) / σ)

所以匯出的 coef 是 [w_e, w_g/σ]、intercept 是 b − Σ(w_g·μ/σ)，
推論端照舊只做一次 `X @ coef.T + intercept`，不需要知道 scaler 存在。

輸出：models/basic_features_roi/nose_shape_dinov2_head.npz（389 維）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sklearn.preprocessing import StandardScaler  # noqa: E402
from sklearn.svm import LinearSVC  # noqa: E402

from rule_features import TREE_FEATURES  # noqa: E402
from train_basic_cnn_roi import build_part_data, load_cache  # noqa: E402

PART = "nose_shape"
MODEL_DIR = Path("models/basic_features_roi")
GEOM = TREE_FEATURES[PART]


def main() -> int:
    emb_all = np.load("data/roi_cache/dinov2_embeddings.npz")["embeddings"]
    feats = json.loads(Path("data/roi_cache/rule_features.json").read_text(encoding="utf-8"))[PART]
    all_rois, records = load_cache()
    _, labels, _, classes = build_part_data(PART, all_rois, records)
    rows = [i for i, r in enumerate(records) if PART in r["labels"]]

    E = emb_all[rows]
    G = np.array([[float((feats.get(records[r]["path"]) or {}).get(n, 0.0)) for n in GEOM]
                  for r in rows], dtype=np.float64)
    print(f"{PART}：{len(labels)} 張、{len(classes)} 類、embedding {E.shape[1]} 維 + 幾何 {G.shape[1]} 維")

    scaler = StandardScaler().fit(G)
    clf = LinearSVC(class_weight="balanced", C=1.0, max_iter=5000)
    clf.fit(np.hstack([E, scaler.transform(G)]), labels)

    # ── 把 scaler 摺進權重 ──
    coef = np.asarray(clf.coef_, dtype=np.float64)          # (n_out, 384+G)
    intercept = np.asarray(clf.intercept_, dtype=np.float64)
    n_emb = E.shape[1]
    w_e, w_g = coef[:, :n_emb], coef[:, n_emb:]
    mu, sigma = scaler.mean_, np.where(scaler.scale_ > 1e-12, scaler.scale_, 1.0)

    folded_coef = np.hstack([w_e, w_g / sigma]).astype(np.float32)
    folded_intercept = (intercept - (w_g * (mu / sigma)).sum(axis=1)).astype(np.float32)

    # ── 驗證摺疊沒有改變預測 ──
    raw = np.hstack([E, scaler.transform(G)]) @ coef.T + intercept
    folded = np.hstack([E, G]) @ folded_coef.T.astype(np.float64) + folded_intercept
    max_diff = float(np.abs(raw - folded).max())
    agree = int((np.sign(raw) == np.sign(folded)).all(axis=None))
    print(f"摺疊驗證：決策值最大誤差 {max_diff:.2e}　符號完全一致 {'是' if agree else '否'}")
    if not agree:
        print("*** 摺疊後預測改變，不匯出")
        return 1

    out = MODEL_DIR / f"{PART}_dinov2_head.npz"
    np.savez(out, coef=folded_coef, intercept=folded_intercept,
             kind=np.array("linear_svc_geom_fusion"),
             geom_features=np.array(GEOM), embedding_dim=np.array(n_emb))
    (MODEL_DIR / f"{PART}_dinov2_classes.json").write_text(json.dumps(
        {"classes": list(classes), "architecture": "dinov2_vits14",
         "classifier": "linear_svc_geom_fusion", "geom_features": list(GEOM)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已寫入 {out}　coef={folded_coef.shape}　幾何欄位順序 {list(GEOM)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
