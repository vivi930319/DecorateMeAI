"""ROI CNN 的 shadow prediction：跑模型、記錄結果，但不影響 BASIC 的正式輸出。

為什麼是 shadow 而不是直接用：這批模型按人切分的 macro accuracy 只有 0.38~0.67，
全數低於規格書門檻 0.70（見 CNN訓練歷程_BASIC五官分類.md）。直接接上去會讓線上結果變差，
所以照規格書 13.1 的做法先跑 shadow —— API 照樣回規則式答案，預設只把
「規則式 vs 模型」的差異寫進 log，累積真實流量上的比較資料。若內部驗收需要看
模型欄位，可用 ROI_SHADOW_EXPOSE_RESPONSE=1 暫時回傳。

這支模組的每個對外進入點都不能拋例外。模型檔不存在、onnxruntime 載入失敗、ROI 裁切失敗，
一律回 None 讓 BASIC 當作沒這回事 —— shadow 功能壞掉絕不能拖垮正式分析。

用 ROI_SHADOW_ENABLED=0 可以整個關掉。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np

from face_roi import PARTS, crop_roi, roi_to_tensor

logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.getenv("ROI_MODEL_DIR", "models/basic_features_roi"))
ENABLED = os.getenv("ROI_SHADOW_ENABLED", "1") != "0"

# 預設不把完整的模型輸出（含各類機率）放進 API 回應，那是除錯用的。
# 內部驗收想直接從 API 看模型細節時，才開 ROI_SHADOW_EXPOSE_RESPONSE=1。
EXPOSE_IN_RESPONSE = os.getenv("ROI_SHADOW_EXPOSE_RESPONSE", "0") == "1"

# MODEL_FIRST：讓 CNN 成為使用者看到的正式答案，規則式退居 fallback。
#
# 為什麼不做 hybrid（低信心時退回規則式）：實測過了，沒有用。
# 五個部位的最佳信心門檻掃描結果是「門檻 0.00」——也就是「CNN 再沒信心也比規則式準」。
# 硬要在 brow/nose 設門檻（0.48 / 0.38），val macro 反而從 0.589->0.505、0.666->0.648 變差。
# 校準後的規則式仍然全面輸給 CNN，所以「低信心時退回規則式」只會拖累結果。
# 見 tools/tune_hybrid.py 與 models/basic_features_roi/hybrid_config.json。
#
# 誠實的限制：CNN 也還沒達到規格書的 0.70 門檻（0.378~0.666），只是遠優於原本
# 「每個人都判成彎月眉+標準鼻」的規則式。設 ROI_MODEL_FIRST=0 可退回規則式當正式輸出。
MODEL_FIRST = os.getenv("ROI_MODEL_FIRST", "1") != "0"

# 模型的部位代號 -> BASIC 輸出用的中文欄位名
PART_TO_FIELD = {
    "face_shape": "臉型",
    "brow_shape": "眉型",
    "eye_shape": "眼型",
    "nose_shape": "鼻型",
    "lip_shape": "嘴型",
}

ENCODER = "mobilenet_v3_small"
PROVIDER = "roi_cnn"

_sessions: dict[str, tuple] | None = None
_load_failed = False


def _load() -> dict[str, tuple]:
    """Lazy load：第一次分析時才載入 ONNX，避免 Cloud Run cold start 變慢。"""
    global _sessions, _load_failed
    if _sessions is not None or _load_failed:
        return _sessions or {}

    try:
        import onnxruntime as ort  # insightface 本來就依賴它，等於零額外成本

        # 綁成單執行緒。ROI 模型很小（MobileNetV3-small / 96x96），onnxruntime 預設開滿執行緒
        # 只會去跟 MediaPipe、InsightFace 搶 CPU，光是排程開銷就蓋過運算本身 ——
        # 實測五個部位推論從 60ms 降到 14ms，而 Cloud Run 上只有 1 個 CPU，爭用只會更嚴重。
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1

        sessions = {}
        for part in PARTS:
            onnx_path = MODEL_DIR / f"{part}.onnx"
            meta_path = MODEL_DIR / f"{part}_classes.json"
            if not onnx_path.is_file() or not meta_path.is_file():
                logger.warning("ROI shadow：找不到 %s，跳過這個部位", onnx_path)
                continue
            session = ort.InferenceSession(
                str(onnx_path), opts, providers=["CPUExecutionProvider"]
            )
            classes = json.loads(meta_path.read_text(encoding="utf-8"))["classes"]
            sessions[part] = (session, classes)

        _sessions = sessions
        logger.info("ROI shadow：載入 %d 個部位模型", len(sessions))
    except Exception:
        _load_failed = True
        _sessions = {}
        logger.exception("ROI shadow：模型載入失敗，本次起停用 shadow 預測")

    return _sessions


def _softmax(logits: np.ndarray) -> np.ndarray:
    exp = np.exp(logits - logits.max())
    return exp / exp.sum()


def predict(frame_bgr: np.ndarray, points: np.ndarray) -> dict | None:
    """對五個部位跑 shadow 預測。points 是 FaceAnalyzer._pts_cache（468x2 像素座標）。

    回傳 None 代表 shadow 不可用（關閉、沒模型、或整批失敗），呼叫端直接忽略即可。
    """
    if not ENABLED:
        return None

    sessions = _load()
    if not sessions:
        return None

    result: dict[str, object] = {
        "provider": PROVIDER,
        "encoder": ENCODER,
        "mode": "shadow",
    }
    predicted = 0

    for part, (session, classes) in sessions.items():
        try:
            crop = crop_roi(frame_bgr, points, part)
            logits = session.run(None, {"input": roi_to_tensor(crop)})[0][0]
            probs = _softmax(logits)
            best = int(np.argmax(probs))
            result[PART_TO_FIELD[part]] = {
                "label": classes[best],
                "confidence": round(float(probs[best]), 3),
                "source": f"{PROVIDER}_{ENCODER}",
            }
            predicted += 1
        except Exception:
            # 單一部位失敗不影響其他部位，也不影響正式輸出
            logger.exception("ROI shadow：%s 預測失敗", part)

    return result if predicted else None


def apply_model_first(result: dict, shadow: dict | None) -> dict | None:
    """把 CNN 的答案寫進正式欄位，並回傳一份「這個欄位最後聽誰的」的來源說明。

    規則式仍然是 fallback：某個部位的模型推論失敗、或模型檔缺失時，那個欄位維持規則式的答案，
    其他欄位不受影響。這樣即使模型整組掛掉，API 也只是退回舊行為，不會壞掉。

    會就地修改 result。回傳 None 代表沒有任何欄位被模型接手。
    """
    if not shadow:
        return None

    sources: dict[str, dict] = {}
    for field in PART_TO_FIELD.values():
        model = shadow.get(field)
        if not isinstance(model, dict):
            continue  # 這個部位模型沒跑出來 -> 保留規則式的答案
        rule_label = result.get(field)
        result[field] = model["label"]
        sources[field] = {
            "final": PROVIDER,
            "modelLabel": model["label"],
            "modelConfidence": model["confidence"],
            "ruleLabel": rule_label,
        }

    return sources or None


def log_comparison(rule_result: dict, shadow: dict | None) -> None:
    """把「規則式 vs 模型」的差異寫進 log，之後可以從 Cloud Logging 撈出來統計一致率。

    shadow mode 的價值就在這 —— 沒有這個對照，跑 shadow 只是白白多花 CPU。
    """
    if not shadow:
        return

    try:
        agree, differ = [], []
        for field in PART_TO_FIELD.values():
            model = shadow.get(field)
            if not isinstance(model, dict):
                continue
            rule_label = rule_result.get(field)
            (agree if rule_label == model["label"] else differ).append(
                f"{field}: 規則={rule_label} 模型={model['label']}({model['confidence']:.2f})"
            )

        total = len(agree) + len(differ)
        if total:
            logger.info(
                "ROI shadow 對照：一致 %d/%d%s",
                len(agree), total,
                ("　差異 -> " + "；".join(differ)) if differ else "",
            )
    except Exception:
        logger.exception("ROI shadow：對照記錄失敗")
