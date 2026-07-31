"""PRO 側臉鼻型推論：整張側臉圖 → ConvNeXt-Tiny ONNX → 五類。

## 為什麼不走 BASIC 的 ROI pipeline

BASIC 是「MediaPipe FaceMesh 抓 landmark → 依 ROI_SPECS 裁部位」。這條路在側臉上
不成立：實測 438 張側臉，FaceMesh 只認得 **73.5%**，而且失敗率依類別嚴重偏斜
（塌鼻 60.4%、翹鼻 93.4%）。丟掉失敗樣本不是隨機損失，是把類別分布整個扭曲，
訓出來的模型會系統性偏向「好偵測」的那些鼻型。

所以這裡**餵整張圖**（resize 224×224），不做 landmark 裁切。

## 誠實標記：這個模型的驗證基礎很薄

同一組 5-fold（identity 分組）上 ConvNeXt-Tiny 是 0.5699 ± 0.061（5 類、亂猜 0.200）。
但 **636 張裡有 308 張（48%）抽不到人臉、identity = -1，永遠只在 train**，
實際進驗證集的只有 328 張，而且損失偏斜：

    塌鼻   149 張 → 進 val 110（74%）
    翹鼻   191 張 → 進 val  96（50%）
    直挺鼻 100 張 → 進 val  46（46%）
    蒜頭鼻  96 張 → 進 val  40（42%）
    駝峰鼻 100 張 → 進 val  36（36%）

逐類 recall：塌鼻 0.909、翹鼻 0.667、蒜頭鼻 0.500、直挺鼻 0.391、駝峰鼻 0.389。

**除了塌鼻，每一類的分數都建立在 36~46 張上——每折約 7~9 張，一張值 10 個百分點。**
回應必須帶上這個限制，不能讓使用者以為這是可靠的判斷。

## 失敗策略

任何一步失敗（缺模型、載入失敗、推論失敗）都回 None，讓 PRO 沿用既有回應——
側臉鼻型是加值資訊，不該讓它拖垮整個 PRO 分析。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.getenv("PRO_MODEL_DIR", "models/pro_nose_side"))
ENABLED = os.getenv("PRO_NOSE_SIDE_ENABLED", "1") != "0"
IMG_SIZE = 224

# 與訓練時完全相同的正規化常數。任何一項不一致，分類器就會拿到偏掉的輸入分佈，
# 而且不會報錯——只會安靜地變差。
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_session = None
_classes: list[str] = []
_load_failed = False


def model_status() -> dict:
    """Return readiness metadata without allocating an ONNX session."""
    onnx_path = MODEL_DIR / "nose_shape_side.onnx"
    meta_path = MODEL_DIR / "nose_shape_side_classes.json"
    missing = [str(path) for path in (onnx_path, meta_path) if not path.is_file()]
    return {
        "ready": not missing,
        "required": ENABLED,
        "architecture": "convnext_tiny",
        "missing": missing,
    }


def _load():
    """Lazy load。失敗就永久停用，不重試——每次請求都重試一個載不起來的模型
    只會讓每一次分析都多付一次失敗成本。"""
    global _session, _classes, _load_failed
    if _session is not None or _load_failed:
        return _session
    if not ENABLED:
        _load_failed = True
        return None
    try:
        import onnxruntime as ort

        onnx_path = MODEL_DIR / "nose_shape_side.onnx"
        meta_path = MODEL_DIR / "nose_shape_side_classes.json"
        if not onnx_path.is_file() or not meta_path.is_file():
            logger.info("PRO 側臉鼻型：找不到 %s，停用", onnx_path)
            _load_failed = True
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        _classes = list(meta["classes"])
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        _session = ort.InferenceSession(str(onnx_path), opts,
                                        providers=["CPUExecutionProvider"])
        logger.info("PRO 側臉鼻型：載入 %s（%d 類）", meta.get("architecture"), len(_classes))
        return _session
    except Exception:
        logger.exception("PRO 側臉鼻型：載入失敗，停用")
        _load_failed = True
        return None


def predict(frame_bgr: np.ndarray) -> dict | None:
    """對整張側臉圖分類。回傳 {label, confidence, classes, caveat} 或 None。"""
    session = _load()
    if session is None or frame_bgr is None or frame_bgr.size == 0:
        return None
    try:
        interp = cv2.INTER_AREA if frame_bgr.shape[0] > IMG_SIZE else cv2.INTER_LINEAR
        resized = cv2.resize(frame_bgr, (IMG_SIZE, IMG_SIZE), interpolation=interp)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = ((rgb - _MEAN) / _STD).transpose(2, 0, 1)[None]
        logits = session.run(None, {"input": np.ascontiguousarray(tensor, dtype=np.float32)})[0][0]
        exp = np.exp(logits - logits.max())
        proba = exp / exp.sum()
        best = int(np.argmax(proba))
        return {
            "label": _classes[best],
            "confidence": round(float(proba[best]), 3),
            "classes": list(_classes),
            # 這個欄位不是裝飾：除了塌鼻，每一類的驗證只有 36~46 張。
            # 讓呼叫端與使用者看得到這個限制，而不是把它當成可靠判斷。
            "caveat": "側臉 identity 覆蓋率僅 52%，塌鼻以外各類驗證樣本 36~46 張，僅供參考",
        }
    except Exception:
        logger.exception("PRO 側臉鼻型：推論失敗")
        return None
