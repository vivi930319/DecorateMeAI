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
import random
from pathlib import Path

import numpy as np

import rule_features
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


def _retired_labels(part: str, classes: list[str]) -> set[str]:
    """回傳 `classes` 裡已不在該部位官方分類表中的標籤。

    以 `{part}_classes.json`（CNN 的類別檔，隨每次重訓更新）當作目前的分類表。
    兩者不一致時代表某一邊沒跟上合併，讓不一致的那一邊安靜地繼續預測，
    就會在線上出現使用者回饋選項裡根本沒有的類別。
    """
    canonical_path = MODEL_DIR / f"{part}_classes.json"
    if not canonical_path.is_file():
        return set()
    try:
        canonical = set(json.loads(canonical_path.read_text(encoding="utf-8"))["classes"])
    except Exception:
        return set()
    return set(classes) - canonical

# ── DINOv2 shadow ────────────────────────────────────────────────────────────
# 2026-07-19 的三模型公平比較裡，臉型／眼型／鼻型由 DINOv2 ViT-S/14 + 線性分類器勝出
# （0.522 / 0.387 / 0.863）。但依當時的部署決策，第一階段**只跑 shadow、不接管正式輸出**：
# 先在真實流量上驗證速度與記憶體，並累積與現行 CNN 的對照資料。
#
# 服務端不裝 torch —— backbone 已離線匯出成 ONNX（與 torch 原模型最大誤差 2.6e-05），
# 用既有的 onnxruntime 推論，分類器則是 scikit-learn 的 joblib，兩者都已是相依套件。
#
# 看完 shadow log 要升為正式答案時，設 ROI_DINOV2_MODEL_FIRST=1 即可，不需要改程式。
# 2026-07-31 起**預設關閉**（見下方 DINOV2_FIRST_PARTS 的說明）。
#
# 只清空 DINOV2_FIRST_PARTS 不夠：should_run_dinov2() 會落到抽樣分支，
# 仍有 ROI_DINOV2_SAMPLE_RATE（預設 10%）的請求要付那 330ms 去跑一個
# 已經確定比較差的模型。要留 shadow 對照就設 ROI_DINOV2_ENABLED=1。
DINOV2_ENABLED = os.getenv("ROI_DINOV2_ENABLED", "0") != "0"
DINOV2_MODEL_FIRST = os.getenv("ROI_DINOV2_MODEL_FIRST", "0") == "1"

# 逐部位指定哪些交給 DINOv2 當正式答案（逗號分隔的部位名）。
#
# **不要整批切換。** 同一套 5-fold（identity 切分、40 epochs、lr 6e-4）上量到的是：
#
#     eye_shape    CNN 0.495  DINOv2 0.542   +0.047  ← DINOv2 勝 4/5 折
#     brow_shape   CNN 0.542  DINOv2 0.543   +0.001  （平手）
#     lip_shape    CNN 0.565  DINOv2 0.513   -0.052
#     nose_shape   CNN 0.868  DINOv2 0.846   -0.022
#     face_shape   CNN 0.522  DINOv2 0.424   -0.098
#
# 全開會賺眼型、賠掉其餘四個，淨值是負的。DINOV2_MODEL_FIRST 那個整批開關是
# 早期「先試試看」留下的，保留是為了相容；正式部署請用這一個。
#
# 誠實標記：眼型的 +0.047 落在 std（0.042）之內，不是壓倒性的差距。
# 這組數字先前記成 +0.090，那是在 identity map 過期、桃杏眼 221 張只有 1 張
# 進過驗證集的狀態下量的（見發展歷程規格書 §7.6）；而且對手 CNN 當時用的是
# 還沒調好的 lr 3e-4。修好之後領先幅度縮水，方向沒變。
#
# 代價：DINOv2 佔整個分析約 57% 的時間。若延遲吃不消，把這個環境變數設成空字串
# 退回全 CNN，眼型的代價是 -0.047。
# 2026-07-31：**預設空的**。五個部位全部改用 ConvNeXt-Tiny 之後，DINOv2 完全退場。
#
# 決定依據是同時量到的三件事，不是單看分數：
#
#     準確度   眼型 DINOv2 0.625 → ConvNeXt 0.693；四個部位提升、鼻型持平
#     延遲     DINOv2 backbone 單次前向 110ms、每次分析跑三次 = 330ms
#              ConvNeXt 五個部位合計只要 99ms —— 換過去同時變準又變快
#     代價     映像由 118MB 變 556MB，記憶體需求上調
#
# 通常這種切換要在準確度與延遲之間取捨；這次不用，因為 DINOv2 那 330ms 買到的
# 眼型 0.625，ConvNeXt 用 20ms 就超過了。
#
# 要跑回頭對照就設 ROI_DINOV2_FIRST_PARTS=eye_shape（head 檔仍在映像裡）。
DINOV2_FIRST_PARTS = tuple(
    x.strip() for x in os.getenv("ROI_DINOV2_FIRST_PARTS", "").split(",") if x.strip()
)

# Shadow 階段的抽樣率。
#
# 實測（12 張、本機 CPU）各段耗時佔比：
#     InsightFace 角度 199ms(33%)　MediaPipe 17ms(3%)　規則式 21ms(4%)
#     ROI CNN 19ms(3%)　**DINOv2 343ms(57%)**　合計 599ms
#
# DINOv2 是整個分析裡最貴的一段，而在 shadow 模式下它的輸出只進對照 log，
# 不影響使用者看到的任何欄位——等於每個人都替一份離線比較實驗付了 57% 的等待時間。
#
# 對照實驗要的是統計，不是每一筆。抽 10% 就能看出兩個模型在哪些部位系統性分歧，
# 成本降到十分之一。要收更快就調高，要完全關掉設 ROI_DINOV2_ENABLED=0。
#
# MODEL_FIRST 開啟時不抽樣：那時 DINOv2 是正式答案，少跑一次就是少一個人的結果。
DINOV2_SAMPLE_RATE = max(0.0, min(1.0, float(os.getenv("ROI_DINOV2_SAMPLE_RATE", "0.1"))))
DINOV2_ENCODER = "dinov2_vits14"
DINOV2_PROVIDER = "roi_dinov2"
DINOV2_SIZE = 224

# 只有這三個部位選用 DINOv2；眉型與唇型的最佳模型仍是 MobileNetV3，不必多花這筆推論成本。
#
# 分類器不直接載 joblib：pickle 會綁定 sklearn 版本，訓練環境是 1.9.0、部署映像是 1.7.2，
# 實測 LogisticRegression.predict_proba 會拋 AttributeError，官方也警告可能產生無效結果。
# 兩個分類器都是線性模型，改成只存 coef／intercept，用 numpy 算 X @ coef.T + intercept。
# 權重由 tools/export_dinov2_heads.py 產生，並已驗證與 sklearn 預測完全一致。
DINOV2_PARTS = ("face_shape", "eye_shape", "nose_shape")


def dinov2_first_parts() -> tuple[str, ...]:
    """哪些部位由 DINOv2 提供正式答案。整批開關優先於逐部位設定。"""
    if DINOV2_MODEL_FIRST:
        return DINOV2_PARTS
    return tuple(p for p in DINOV2_FIRST_PARTS if p in DINOV2_PARTS)

# 與 tools/dinov2_cv_experiment.py 相同的 ImageNet 正規化常數；改動會讓 embedding 對不上訓練分佈。
_DINO_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_DINO_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_sessions: dict[str, tuple] | None = None
_load_failed = False
_dino: tuple | None = None
_dino_load_failed = False


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


def _load_dinov2() -> tuple | None:
    """Lazy load DINOv2 backbone 與線性分類器。任何一步失敗就永久停用，不影響其他預測。"""
    global _dino, _dino_load_failed
    if _dino is not None or _dino_load_failed:
        return _dino
    if not DINOV2_ENABLED:
        _dino_load_failed = True
        return None

    try:
        import onnxruntime as ort

        backbone_path = MODEL_DIR / f"{DINOV2_ENCODER}.onnx"
        if not backbone_path.is_file():
            logger.info("DINOv2 shadow：找不到 %s，停用", backbone_path)
            _dino_load_failed = True
            return None

        # 同 _load()：綁單執行緒，避免跟 MediaPipe／InsightFace 搶 Cloud Run 上唯一的 CPU。
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        backbone = ort.InferenceSession(
            str(backbone_path), opts, providers=["CPUExecutionProvider"]
        )

        heads = {}
        for part in DINOV2_PARTS:
            head_path = MODEL_DIR / f"{part}_dinov2_head.npz"
            # 用獨立的類別檔，不能共用 {part}_classes.json：鼻型的 CNN 仍是三分類（含窄鼻），
            # DINOv2 已改用 grouped_yun 二分類，共用會讓 CNN 的 classes[best] 索引越界。
            meta_path = MODEL_DIR / f"{part}_dinov2_classes.json"
            if not head_path.is_file() or not meta_path.is_file():
                logger.info("DINOv2 shadow：找不到 %s，跳過這個部位", head_path)
                continue
            classes = json.loads(meta_path.read_text(encoding="utf-8"))["classes"]

            # 守衛：DINOv2 head 的類別若含目前分類表已淘汰的名稱，就不要載入。
            #
            # 2026-07-24 眼型由八類併為六類（丹鳳眼→鳳眼、瞇縫眼→細長眼），CNN 已用
            # 清理後資料重訓，但 DINOv2 head 沒有跟著重訓。少了這道檢查，只要有人設
            # ROI_DINOV2_MODEL_FIRST=1，線上就會吐出「丹鳳眼」這種已經不在契約裡的標籤，
            # 而且前端的回饋選項也沒有它——使用者選不到，看起來只像是模型很爛。
            retired = _retired_labels(part, classes)
            if retired:
                logger.warning(
                    "DINOv2 shadow：%s 的 head 仍是舊分類（含 %s），與目前的 %s 不一致，"
                    "跳過。重訓 head 後才會重新啟用。",
                    part, "、".join(sorted(retired)), meta_path.name.replace("_dinov2", ""),
                )
                continue

            with np.load(head_path) as data:
                coef = data["coef"].astype(np.float32)
                # 融合頭：輸入是 [embedding, 幾何特徵]，coef 比 embedding 寬。
                # 幾何欄位的**順序**存在 npz 裡，推論時照它取值——順序對不上不會報錯，
                # 只會讓分類器拿到打亂的輸入，然後安靜地變差。
                geom = [str(x) for x in data["geom_features"]] if "geom_features" in data else []
                heads[part] = (coef, data["intercept"].astype(np.float32), classes, geom)

        if not heads:
            _dino_load_failed = True
            return None

        _dino = (backbone, heads)
        logger.info("DINOv2 shadow：載入 backbone 與 %d 個部位分類器", len(heads))
    except Exception:
        _dino_load_failed = True
        logger.exception("DINOv2 shadow：載入失敗，本次起停用")

    return _dino


def _dino_tensor(frame_bgr: np.ndarray, points: np.ndarray, part: str) -> np.ndarray:
    """裁出 224x224 ROI 並做成 DINOv2 的輸入，與訓練時的前處理逐步對齊。"""
    import cv2

    from face_roi import roi_bbox

    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = roi_bbox(points, part, h, w)
    pad_l, pad_t = max(0, -x1), max(0, -y1)
    pad_r, pad_b = max(0, x2 - w), max(0, y2 - h)
    if pad_l or pad_t or pad_r or pad_b:
        frame_bgr = cv2.copyMakeBorder(
            frame_bgr, pad_t, pad_b, pad_l, pad_r, cv2.BORDER_REPLICATE
        )
        x1, x2, y1, y2 = x1 + pad_l, x2 + pad_l, y1 + pad_t, y2 + pad_t
    crop = frame_bgr[y1:y2, x1:x2]
    interp = cv2.INTER_AREA if crop.shape[0] > DINOV2_SIZE else cv2.INTER_LINEAR
    crop = cv2.resize(crop, (DINOV2_SIZE, DINOV2_SIZE), interpolation=interp)

    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return ((rgb - _DINO_MEAN) / _DINO_STD).transpose(2, 0, 1)[None]


def _dino_decide(coef: np.ndarray, intercept: np.ndarray, emb: np.ndarray) -> tuple[int, float]:
    """線性分類器的推論：回傳 (類別索引, 信心)。

    信心只是把邊界距離壓到 0~1 方便閱讀，不是校準過的機率；不同部位之間不可互相比較。
    二分類時 coef 只有一列，decision > 0 代表第二類。
    """
    scores = emb @ coef.T + intercept
    if scores.shape[0] == 1:  # 二分類
        margin = float(scores[0])
        return (1 if margin > 0 else 0), float(1.0 / (1.0 + np.exp(-abs(margin))))
    best = int(np.argmax(scores))
    top2 = np.sort(scores)[-2:]
    return best, float(1.0 / (1.0 + np.exp(-(top2[1] - top2[0]))))


def should_run_dinov2() -> bool:
    """這一次請求要不要跑 DINOv2。

    抽樣只適用於 shadow 模式。DINOV2_MODEL_FIRST 開啟時它是正式答案，
    每一次都得跑——少跑一次就是少一個人的分類結果。
    """
    if not DINOV2_ENABLED:
        return False
    # 有任何部位以 DINOv2 為正式答案時就不能抽樣——抽中才跑的話，
    # 沒抽中的那 90% 使用者會靜靜地拿到 CNN 的答案，而且從回應看不出來。
    if dinov2_first_parts():
        return True
    if DINOV2_MODEL_FIRST:
        return True
    if DINOV2_SAMPLE_RATE >= 1.0:
        return True
    if DINOV2_SAMPLE_RATE <= 0.0:
        return False
    return random.random() < DINOV2_SAMPLE_RATE


def predict_dinov2(frame_bgr: np.ndarray, points: np.ndarray) -> dict | None:
    """DINOv2 shadow 預測。與 predict() 相同的容錯原則：失敗一律回 None／略過該部位。

    抽樣判斷放在 should_run_dinov2()，呼叫端要先問過再進來——這裡也擋一次，
    避免有人直接呼叫時繞過抽樣。
    """
    if not should_run_dinov2():
        return None
    loaded = _load_dinov2()
    if not loaded:
        return None
    backbone, heads = loaded

    result: dict[str, object] = {
        "provider": DINOV2_PROVIDER,
        "encoder": DINOV2_ENCODER,
        "mode": "model_first" if DINOV2_MODEL_FIRST else "shadow",
    }
    predicted = 0

    for part, (coef, intercept, classes, geom_names) in heads.items():
        try:
            tensor = _dino_tensor(frame_bgr, points, part)
            emb = backbone.run(None, {"images": tensor})[0][0]
            # 訓練時對 embedding 做過 L2 正規化，推論必須一致，否則分類器輸入分佈會偏掉
            emb = emb / (np.linalg.norm(emb) + 1e-9)

            # 融合頭（目前只有鼻型）：把幾何特徵接在 embedding 後面。
            # StandardScaler 已經在匯出時摺進權重，這裡餵原始值即可。
            # 特徵與 landmark 索引跟訓練共用 rule_features 的同一個函式，避免兩份公式走鐘。
            if geom_names:
                feats = rule_features.nose_features_from_points(points)
                missing = [n for n in geom_names if n not in feats]
                if missing:
                    # 大聲失敗：少一維會讓後面的維度整排錯位，比直接不預測更糟。
                    raise KeyError(f"{part} 融合頭需要的幾何特徵缺少 {missing}")
                emb = np.concatenate([emb, np.array([feats[n] for n in geom_names],
                                                    dtype=np.float32)])
            if emb.shape[0] != coef.shape[1]:
                raise ValueError(
                    f"{part} 特徵維度 {emb.shape[0]} 與 head 的 {coef.shape[1]} 不符")

            best, confidence = _dino_decide(coef, intercept, emb)
            result[PART_TO_FIELD[part]] = {
                "label": classes[best],
                "confidence": round(confidence, 3),
                "source": f"{DINOV2_PROVIDER}_{DINOV2_ENCODER}",
            }
            predicted += 1
        except Exception:
            logger.exception("DINOv2 shadow：%s 預測失敗", part)

    return result if predicted else None


def log_dinov2_comparison(cnn_shadow: dict | None, dino_shadow: dict | None) -> None:
    """記錄 DINOv2 與現行 CNN 的差異，這是 shadow 階段唯一的產出，沒有它就只是白燒 CPU。"""
    if not dino_shadow:
        return

    try:
        agree, differ = [], []
        for field in PART_TO_FIELD.values():
            dino = dino_shadow.get(field)
            if not isinstance(dino, dict):
                continue
            cnn = (cnn_shadow or {}).get(field)
            cnn_label = cnn["label"] if isinstance(cnn, dict) else None
            (agree if cnn_label == dino["label"] else differ).append(
                f"{field}: CNN={cnn_label} DINOv2={dino['label']}({dino['confidence']:.2f})"
            )

        total = len(agree) + len(differ)
        if total:
            logger.info(
                "DINOv2 shadow 對照：一致 %d/%d%s",
                len(agree), total,
                ("　差異 -> " + "；".join(differ)) if differ else "",
            )
    except Exception:
        logger.exception("DINOv2 shadow：對照記錄失敗")


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
