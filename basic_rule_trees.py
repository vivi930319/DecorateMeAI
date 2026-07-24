"""幾何決策樹推論：眼型與臉型的正式答案來源。

## 為什麼這兩個部位不用 CNN

`tools/cv_rule_baseline.py` 把規則式接上與 CNN **完全相同**的 5-fold
（`split_kfold_by_identity`, seed=42），逐 fold 配對比較：

    眼型  樹 0.406 vs CNN 0.332   樹勝 5/5 fold（+0.074 ± 0.038）
    臉型  樹 0.544 vs CNN 0.477   樹勝 4/5 fold（+0.067 ± 0.059）

其餘三個部位（眉、鼻、唇）維持 CNN——樹在那裡輸，但差距都小於逐 fold 差的標準差，
是傾向不是定論，所以不動既有部署。

會贏並不意外：眼型的類別差異是「開合比例（ear）」與「眼角角度（angle）」，
臉型是「不同高度的寬度比值」，兩者本來就是幾何量而非紋理。幾百張的規模下，
CNN 得從像素重新學會這些量，直接算反而準。

## 安全性

跟 `basic_roi_shadow` 同樣的鐵則：**每個對外進入點都不能拋例外**。模型檔缺失、
joblib 版本不合、landmark 抽特徵失敗，一律回 None 讓 BASIC 沿用既有答案。
分類器換路徑絕不能拖垮正式分析。

`ROI_RULE_TREE_ENABLED=0` 可整個關掉，退回原本的 CNN／規則式行為。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np

import rule_features

logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.getenv("ROI_MODEL_DIR", "models/basic_features_roi"))
ENABLED = os.getenv("ROI_RULE_TREE_ENABLED", "1") != "0"

# 只有這兩個部位在同一套 5-fold 上贏過 CNN。要新增部位，先拿 cv_rule_baseline
# 的逐 fold 配對結果說話，不要憑平均值——平均相近時「每個 fold 都贏」與
# 「贏兩個輸三個」是完全不同的結論。
RULE_TREE_PARTS = ("eye_shape", "face_shape")

PART_TO_FIELD = {
    "face_shape": "臉型",
    "eye_shape": "眼型",
}

PROVIDER = "rule_tree"

_loaded = False
_models: dict[str, dict] = {}


def _load() -> dict[str, dict]:
    global _loaded
    if _loaded:
        return _models
    _loaded = True
    if not ENABLED:
        return _models
    try:
        import joblib
    except Exception:
        logger.warning("規則樹：joblib 不可用，跳過")
        return _models

    for part in RULE_TREE_PARTS:
        model_path = MODEL_DIR / f"{part}_rule_tree.joblib"
        meta_path = MODEL_DIR / f"{part}_rule_tree.json"
        if not model_path.is_file() or not meta_path.is_file():
            logger.warning("規則樹：找不到 %s，這個部位維持原本的答案來源", model_path)
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            _models[part] = {
                "tree": joblib.load(model_path),
                "classes": meta["classes"],
                "features": meta["features"],
            }
        except Exception:
            logger.exception("規則樹：載入 %s 失敗，這個部位維持原本的答案來源", part)
    return _models


def predict(analyzer) -> dict[str, dict] | None:
    """回傳 {部位: {label, confidence}}；不可用時回 None。

    `analyzer` 是已經算好 landmark 的 `FaceAnalyzer`，特徵由 `rule_features`
    抽取——與訓練時同一份定義，避免線上餵到略有不同的值而安靜地變差。
    """
    models = _load()
    if not models:
        return None

    out: dict[str, dict] = {}
    for part, bundle in models.items():
        try:
            feats = rule_features.EXTRACT[part](analyzer)
            x = np.array([[float(feats[name]) for name in bundle["features"]]])
            proba = bundle["tree"].predict_proba(x)[0]
            idx = int(np.argmax(proba))
            out[part] = {
                "label": bundle["classes"][idx],
                "confidence": round(float(proba[idx]), 4),
            }
        except Exception:
            logger.exception("規則樹：%s 推論失敗，這個部位維持原本的答案", part)
    return out or None


def apply(result: dict, prediction: dict[str, dict] | None) -> dict[str, str]:
    """把樹的答案寫進 result，回傳被覆蓋欄位的來源標記。"""
    sources: dict[str, str] = {}
    if not prediction:
        return sources
    for part, info in prediction.items():
        field = PART_TO_FIELD.get(part)
        label = info.get("label")
        if not field or not label:
            continue
        result[field] = label
        sources[field] = PROVIDER
    return sources
