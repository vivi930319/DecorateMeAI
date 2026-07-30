"""幾何決策樹推論：目前只剩眼型，而且會被 DINOv2 覆蓋。

## 這個模組正在退場

2026-07-24 它曾經是眼型與臉型的正式答案來源，理由是那時量到：

    眼型  樹 0.406 vs CNN 0.332   樹勝 5/5 fold
    臉型  樹 0.544 vs CNN 0.477   樹勝 4/5 fold

**這個結論已經被推翻兩次。** 資料統一之後（07-29）CNN 就反超了；
身分聚類重建、CNN 調到 40ep/6e-4 之後（07-30）差距更明顯：

    臉型  樹 0.462  vs  CNN 0.522
    眼型  樹 0.428  vs  CNN 0.495  vs  DINOv2 0.542

原因不是樹沒校準——`calibrate_rule_thresholds.py` 每次都重跑。
**門檻同樣是從資料擬合出來的，只是擬合過程不叫訓練。**
資料一換它就退步，而且不會有任何東西提醒你（見發展歷程規格書 §6.5）。

「規則式比較穩、比較可解釋」是這個專案花最久才放掉的錯覺。

## 現在還留著它做什麼

**2026-07-30 起 `RULE_TREE_PARTS` 是空的**，這個模組不再提供任何正式答案：
臉型與眼型都改由 CNN／DINOv2 負責。

眼型曾經留在這裡當「DINOv2 失效時的中間層」，但那是降級——樹在眼型也輸 CNN
0.067，故障時退回樹等於再扣一次分。清空之後五個部位的 fallback 一致落在 CNN。

模組保留不刪：它是規則式的完整實作，也是「規則式比較穩」這個錯覺的紀錄。
要回頭做對照，把部位加回 `RULE_TREE_PARTS` 即可。

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

# 2026-07-30：**清空**。臉型與眼型都不再由幾何樹提供答案。
#
# 上面 docstring 引的那組數字（眼型 0.406、臉型 0.544，樹勝）是 07-24 在舊資料上
# 量的。資料統一、身分聚類重建、CNN 調到 40ep/6e-4 之後，同一套 5-fold 反過來：
#
#     臉型  樹 0.462  vs  CNN 0.522     CNN +0.060
#     眼型  樹 0.428  vs  CNN 0.495     CNN +0.067
#
# 規則式在五個部位全部墊底，而且是在 calibrate_rule_thresholds 重新校準之後——
# 不是「沒校準才輸」。門檻同樣是從資料擬合出來的，只是擬合過程不叫訓練；
# 資料一換它就退步，而且沒有任何機制會提醒你（見發展歷程規格書 §6.5、§7.9）。
#
# 眼型的正式答案是 DINOv2（0.542）。先前把眼型留在這裡當「DINOv2 失效時的中間層」，
# 但那是**降級**：樹在眼型也輸 CNN 0.067，退回樹等於在故障時再扣一次分。
# 清空之後，DINOv2 那條路徑失效時眼型自然落回 CNN——五個部位的 fallback 一致。
#
# 這個模組保留不刪：它是規則式的完整實作與紀錄，要回頭做對照把部位加回來即可。
RULE_TREE_PARTS: tuple[str, ...] = ()

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
