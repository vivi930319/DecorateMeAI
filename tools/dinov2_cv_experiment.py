"""DINOv2 frozen encoder + 傳統分類器 vs MobileNetV3 fine-tune：同一把尺的對決。

這是 DINOv2_臉部特徵分類模型規格書.md 第 3 節建議的路線：小資料場景下，
用自監督預訓練的 frozen encoder 抽 embedding、再訓練輕量分類器，
理論上比從頭 fine-tune 一個 CNN 更不容易過擬合。

第一輪沒做它的理由是「量尺不可信（單次切分雜訊 ±0.1），換架構只會得到另一組
不可信的數字」。現在 5-fold CV 就位，而且這裡用**完全相同的 fold**
（split_kfold_by_identity, seed=42 —— 對同一批 labels/identities 是確定性的），
所以 DINOv2 的分數跟 CNN 基準可以直接逐 fold 相比。

流程：
    1. 從原圖重新裁 ROI 成 224x224（DINOv2 的原生輸入。快取的 96x96 放大會糊，
       所以重跑一次 MediaPipe 用同一套 roi_bbox 裁大圖）
    2. DINOv2 ViT-S/14 抽 CLS embedding（384 維，L2 正規化）→ 存快取
    3. 每個部位：同一組 5-fold，各 fold 訓 LogisticRegression 與 linear SVM
    4. 印出與 CNN 基準的逐部位對比

輸出：
    data/roi_cache/dinov2_embeddings.npz
    models/basic_features_roi/dinov2_cv_results.json
"""

from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from face_roi import PARTS, roi_bbox  # noqa: E402
from train_basic_cnn_roi import build_part_data, load_cache, split_kfold_by_identity  # noqa: E402

EMB_PATH = Path("data/roi_cache/dinov2_embeddings.npz")
CONTOUR_EMB_PATH = Path("data/roi_cache/dinov2_face_contour_embeddings.npz")
OUT_PATH = Path("models/basic_features_roi/dinov2_cv_results.json")
DINO_SIZE = 224
MAX_IMAGE_SIZE = 1024  # 跟 prepare_roi_cache 一致，landmark 尺度才對得上

# ImageNet 正規化（DINOv2 官方前處理）
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def crop_roi_224(frame, points, part):
    """跟 face_roi.crop_roi 同一套 bbox 邏輯，但輸出 224x224 給 DINOv2。"""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = roi_bbox(points, part, h, w)
    pad_l, pad_t = max(0, -x1), max(0, -y1)
    pad_r, pad_b = max(0, x2 - w), max(0, y2 - h)
    if pad_l or pad_t or pad_r or pad_b:
        frame = cv2.copyMakeBorder(frame, pad_t, pad_b, pad_l, pad_r, cv2.BORDER_REPLICATE)
        x1, x2, y1, y2 = x1 + pad_l, x2 + pad_l, y1 + pad_t, y2 + pad_t
    crop = frame[y1:y2, x1:x2]
    interp = cv2.INTER_AREA if crop.shape[0] > DINO_SIZE else cv2.INTER_LINEAR
    return cv2.resize(crop, (DINO_SIZE, DINO_SIZE), interpolation=interp)


def compute_embeddings():
    """對每張圖裁它所屬部位的 224 ROI，過 DINOv2 存 embedding。有快取直接用。"""
    if EMB_PATH.is_file():
        # 快取的列順序是綁在 index.json 的 records 上的。ROI 快取一重建，筆數就對不上，
        # 沿用舊快取會拿 A 圖的 embedding 配 B 圖的標籤——而且只有在剛好越界時才會爆，
        # 沒越界的話是安靜地全部算錯。所以這裡對筆數，不合就重算。
        cached = np.load(EMB_PATH)
        want = len(json.loads(Path("data/roi_cache/index.json").read_text(encoding="utf-8"))["records"])
        if len(cached["embeddings"]) == want:
            print(f"已有 embedding 快取 {EMB_PATH}（{want} 筆），直接使用")
            return cached
        print(f"embedding 快取筆數不符（快取 {len(cached['embeddings'])}、目前 {want}），重新計算")

    # 必須早於 mediapipe：專案路徑含「淡江大學」，不套這個修復 FaceMesh 一定初始化失敗
    # （見 mediapipe_ascii 模組說明與訓練記錄書 §三）。prepare_roi_cache 早就這樣做了，
    # 這支當初漏掉——因為它多半吃現成的 embedding 快取，不會走到要開 FaceMesh 的這一段。
    import mediapipe_ascii  # noqa: F401
    import mediapipe as mp
    import torch

    print("載入 DINOv2 ViT-S/14（第一次會從 torch.hub 下載權重）...", flush=True)
    dino = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14")
    dino.eval()

    records = json.loads(Path("data/roi_cache/index.json").read_text(encoding="utf-8"))["records"]
    face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=False,
        min_detection_confidence=0.5,
    )

    # index.json 的 records 順序就是 rois.npz 的列順序，embedding 也照同一順序存，
    # 這樣 build_part_data 選出來的 row index 可以直接拿來查 embedding。
    embeddings = np.zeros((len(records), 384), dtype=np.float32)
    failed = 0

    with torch.inference_mode():
        for i, rec in enumerate(records):
            frame = cv2.imdecode(np.fromfile(rec["path"], dtype=np.uint8), cv2.IMREAD_COLOR)
            h0, w0 = frame.shape[:2]
            scale = MAX_IMAGE_SIZE / max(h0, w0)
            if scale < 1:
                frame = cv2.resize(frame, (int(w0 * scale), int(h0 * scale)),
                                   interpolation=cv2.INTER_AREA)
            h, w = frame.shape[:2]
            res = face_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            if not res.multi_face_landmarks:
                failed += 1  # 快取階段全數成功過，這裡理論上不會發生；發生就留零向量並記數
                continue
            pts = np.array([[int(l.x * w), int(l.y * h)]
                            for l in res.multi_face_landmarks[0].landmark], dtype=np.int32)

            part = next(iter(rec["labels"]))  # 每張圖只屬於一個部位
            crop = crop_roi_224(frame, pts, part)
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            x = torch.from_numpy(((rgb - _MEAN) / _STD).transpose(2, 0, 1)[None])
            emb = dino(x).squeeze(0).numpy()
            embeddings[i] = emb / (np.linalg.norm(emb) + 1e-9)

            if (i + 1) % 100 == 0:
                print(f"  {i + 1}/{len(records)}  失敗 {failed}", flush=True)

    face_mesh.close()
    np.savez_compressed(EMB_PATH, embeddings=embeddings)
    print(f"embedding 完成：{len(records)} 張、失敗 {failed}，已存 {EMB_PATH}")
    return {"embeddings": embeddings}


def compute_contour_embeddings():
    """對 MediaPipe 臉部外輪廓遮罩抽 DINOv2 embedding，列順序與 index.json 對齊。"""
    if CONTOUR_EMB_PATH.is_file():
        cached = np.load(CONTOUR_EMB_PATH)["embeddings"]
        want = len(json.loads(Path("data/roi_cache/index.json").read_text(encoding="utf-8"))["records"])
        if len(cached) == want:
            print(f"已有輪廓 embedding 快取 {CONTOUR_EMB_PATH}（{want} 筆），直接使用")
            return cached
        print(f"輪廓 embedding 快取筆數不符（快取 {len(cached)}、目前 {want}），重新計算")
    import torch

    masks = np.load("data/roi_cache/face_contour.npy", mmap_mode="r")
    print("載入 DINOv2 ViT-S/14，抽取臉部輪廓 embedding...", flush=True)
    dino = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14")
    dino.eval()
    embeddings = np.zeros((len(masks), 384), dtype=np.float32)
    with torch.inference_mode():
        for i, mask in enumerate(masks):
            if not mask.any():
                continue
            rgb = cv2.resize(mask, (DINO_SIZE, DINO_SIZE), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
            x = torch.from_numpy(((rgb - _MEAN) / _STD).transpose(2, 0, 1)[None])
            vector = dino(x).squeeze(0).numpy()
            embeddings[i] = vector / (np.linalg.norm(vector) + 1e-9)
    np.savez_compressed(CONTOUR_EMB_PATH, embeddings=embeddings)
    return embeddings


def compute_feature_contour_embeddings(parts):
    """對眉／唇等 MediaPipe 二值形狀遮罩抽取 DINOv2 embedding。"""
    import torch

    results = {}
    missing = []
    for part in parts:
        path = Path(f"data/roi_cache/dinov2_{part}_contour_embeddings.npz")
        if path.is_file():
            results[part] = np.load(path)["embeddings"]
        else:
            missing.append(part)
    if not missing:
        return results

    print("載入 DINOv2 ViT-S/14，抽取部位形狀 embedding...", flush=True)
    dino = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14")
    dino.eval()
    with torch.inference_mode():
        for part in missing:
            masks = np.load(f"data/roi_cache/{part}_contour.npy", mmap_mode="r")
            embeddings = np.zeros((len(masks), 384), dtype=np.float32)
            for i, mask in enumerate(masks):
                if not mask.any():
                    continue
                rgb = cv2.resize(mask, (DINO_SIZE, DINO_SIZE), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
                x = torch.from_numpy(((rgb - _MEAN) / _STD).transpose(2, 0, 1)[None])
                vector = dino(x).squeeze(0).numpy()
                embeddings[i] = vector / (np.linalg.norm(vector) + 1e-9)
            path = Path(f"data/roi_cache/dinov2_{part}_contour_embeddings.npz")
            np.savez_compressed(path, embeddings=embeddings)
            results[part] = embeddings
    return results


def macro_accuracy(truth, pred, n):
    cm = np.zeros((n, n), dtype=int)
    for t, p in zip(truth, pred):
        cm[t][p] += 1
    rec = [cm[i][i] / cm[i].sum() for i in range(n) if cm[i].sum()]
    return float(np.mean(rec)) if rec else 0.0


def pooled_classification_metrics(confusion):
    """由聚合混淆矩陣計算每類 precision / recall / F1 與整體 macro 指標。"""
    confusion = np.asarray(confusion, dtype=np.int64)
    precision, recall, f1 = [], [], []
    for i in range(len(confusion)):
        tp = int(confusion[i, i])
        predicted = int(confusion[:, i].sum())
        actual = int(confusion[i, :].sum())
        p = tp / predicted if predicted else 0.0
        r = tp / actual if actual else 0.0
        precision.append(p)
        recall.append(r)
        f1.append(2 * p * r / (p + r) if p + r else 0.0)
    return {
        "pooled_confusion_matrix": confusion.tolist(),
        "pooled_per_class_precision": precision,
        "pooled_per_class_recall": recall,
        "pooled_per_class_f1": f1,
        "pooled_macro_precision": float(np.mean(precision)),
        "pooled_macro_recall": float(np.mean(recall)),
        "pooled_macro_f1": float(np.mean(f1)),
        "pooled_accuracy": float(np.trace(confusion) / confusion.sum()),
    }


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.svm import LinearSVC

    parser = argparse.ArgumentParser(description="DINOv2 五官分類 5-fold 實驗")
    parser.add_argument("--identity-mode", choices=("cluster", "per_image"), default="cluster")
    parser.add_argument("--parts", nargs="*", default=list(PARTS))
    parser.add_argument("--face-input", choices=("rgb", "contour"), default="rgb")
    parser.add_argument("--contour-parts", nargs="*", default=[], choices=list(PARTS))
    args = parser.parse_args()

    emb = (compute_contour_embeddings() if args.face_input == "contour"
           else compute_embeddings()["embeddings"])
    feature_contour_embeddings = compute_feature_contour_embeddings(args.contour_parts)
    all_rois, records = load_cache()

    # CNN 的 5-fold CV 基準（同 fold），用來逐部位對比
    cnn_baseline = {}
    for part in args.parts:
        p = Path(f"models/basic_features_roi/{part}_cv_metrics.json")
        if p.is_file():
            cv = json.loads(p.read_text(encoding="utf-8"))["cv"]
            if cv.get("n_folds") == 5:
                cnn_baseline[part] = (cv["mean_macro"], cv["std_macro"])

    classifiers = {
        "logreg": lambda: LogisticRegression(max_iter=3000, class_weight="balanced", C=1.0),
        "svm": lambda: LinearSVC(class_weight="balanced", C=1.0, max_iter=5000),
    }

    results = {}
    print(f"\n{'部位':12s} {'DINOv2+LogReg':>16s} {'DINOv2+SVM':>14s} {'CNN 基準':>16s}")
    for part in args.parts:
        rows = [i for i, r in enumerate(records) if part in r["labels"]]
        _, labels, identities, classes = build_part_data(part, all_rois, records)
        if args.identity_mode == "per_image":
            identities = np.arange(len(labels), dtype=np.int64)
        X = feature_contour_embeddings.get(part, emb)[rows]
        folds = split_kfold_by_identity(labels, identities, 5, 42)  # 跟 CNN CV 完全相同的 fold

        part_res = {"classes": classes}
        for name, make in classifiers.items():
            fold_scores = []
            pooled_confusion = np.zeros((len(classes), len(classes)), dtype=np.int64)
            for train_idx, val_idx in folds:
                clf = make().fit(X[train_idx], labels[train_idx])
                pred = clf.predict(X[val_idx])
                fold_scores.append(macro_accuracy(labels[val_idx], pred, len(classes)))
                for truth, guessed in zip(labels[val_idx], pred):
                    pooled_confusion[int(truth), int(guessed)] += 1
            part_res[name] = {
                "fold_macros": fold_scores,
                "mean": float(np.mean(fold_scores)),
                "std": float(np.std(fold_scores)),
                **pooled_classification_metrics(pooled_confusion),
            }
        part_res["identity_mode"] = args.identity_mode
        part_res["face_input"] = args.face_input
        results[part] = part_res

        lr, sv = part_res["logreg"], part_res["svm"]
        cnn = cnn_baseline.get(part)
        cnn_s = f"{cnn[0]:.3f} ± {cnn[1]:.3f}" if cnn else "-"
        print(f"{part:12s} {lr['mean']:>8.3f} ± {lr['std']:.3f} {sv['mean']:>7.3f} ± {sv['std']:.3f} {cnn_s:>16s}")

    # 檔名要照實反映跑的是什麼。先前這裡把 "per_image" 寫死在兩個輪廓分支裡，
    # 於是 --identity-mode cluster 的輪廓實驗會被存成 dinov2_cv_per_image_contour_results.json
    # ——而依規格書 §八 的規則，檔名帶 per_image 的數字是「不可採信」的那一類。
    # 可信的結果被貼上不可信的標籤，比存錯地方更難發現。
    tag = ("_per_image" if args.identity_mode == "per_image" else "") + \
          ("_contour" if args.face_input == "contour" else "") + \
          ("_feature_contour" if args.contour_parts else "")
    out_path = OUT_PATH.with_name(f"dinov2_cv{tag}_results.json")
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已寫入 {out_path}")


if __name__ == "__main__":
    main()
