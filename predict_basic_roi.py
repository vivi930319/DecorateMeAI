"""丟一張圖進來，看 ROI CNN 對五個部位分別預測什麼、信心多少。

用途是人工抽驗模型，不是線上推論路徑 —— 線上 BASIC 目前仍走規則式，這批模型還沒接上。

用法：
    python predict_basic_roi.py 某張照片.jpg
    python predict_basic_roi.py 某張照片.jpg --save-roi out/   # 順便把裁出來的 ROI 存檔，
                                                              # 可以直接看模型到底看到了什麼

輸出的信心是 softmax 機率。要注意信心高不等於答案對 —— 這批模型的驗證 macro accuracy
只有 0.38~0.67，信心值本身也還沒有校準過。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import mediapipe_ascii  # noqa: F401  # 必須早於 mediapipe，見該模組說明
import mediapipe as mp
import numpy as np
import onnxruntime as ort

from face_roi import PARTS, crop_roi, roi_to_tensor

MODEL_DIR = Path("models/basic_features_roi")
MAX_IMAGE_SIZE = 1024  # 跟 prepare_roi_cache / Face_analyzer_BASIC 一致


def load_models():
    models = {}
    for part in PARTS:
        onnx_path = MODEL_DIR / f"{part}.onnx"
        meta_path = MODEL_DIR / f"{part}_classes.json"
        if not onnx_path.is_file():
            raise SystemExit(f"找不到 {onnx_path}，請先跑 train_basic_cnn_roi.py")
        session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        classes = json.loads(meta_path.read_text(encoding="utf-8"))["classes"]
        models[part] = (session, classes)
    return models


def landmarks(frame: np.ndarray) -> np.ndarray:
    face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=False,
        min_detection_confidence=0.5,
    )
    result = face_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    face_mesh.close()
    if not result.multi_face_landmarks:
        raise SystemExit("這張圖偵測不到人臉")

    h, w = frame.shape[:2]
    return np.array(
        [[int(lm.x * w), int(lm.y * h)] for lm in result.multi_face_landmarks[0].landmark],
        dtype=np.int32,
    )


def softmax(logits: np.ndarray) -> np.ndarray:
    exp = np.exp(logits - logits.max())
    return exp / exp.sum()


def main():
    parser = argparse.ArgumentParser(description="用 ROI CNN 對單張圖預測五個部位")
    parser.add_argument("image", type=Path)
    parser.add_argument("--save-roi", type=Path, default=None,
                        help="把裁切出來的 ROI 存到這個資料夾，方便確認模型看到的是什麼")
    parser.add_argument("--top", type=int, default=3, help="每個部位列出前幾名")
    args = parser.parse_args()

    frame = cv2.imdecode(np.fromfile(str(args.image), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise SystemExit(f"讀不到圖片：{args.image}")

    h0, w0 = frame.shape[:2]
    scale = MAX_IMAGE_SIZE / max(h0, w0)
    if scale < 1:
        frame = cv2.resize(frame, (int(w0 * scale), int(h0 * scale)),
                           interpolation=cv2.INTER_AREA)

    pts = landmarks(frame)
    models = load_models()

    if args.save_roi:
        args.save_roi.mkdir(parents=True, exist_ok=True)

    print(f"\n{args.image.name}\n" + "=" * 46)
    for part in PARTS:
        crop = crop_roi(frame, pts, part)
        session, classes = models[part]
        logits = session.run(None, {"input": roi_to_tensor(crop)})[0][0]
        probs = softmax(logits)

        ranked = sorted(zip(classes, probs), key=lambda kv: kv[1], reverse=True)
        head = "  ".join(f"{name} {prob:.0%}" for name, prob in ranked[:args.top])
        print(f"{part:12s} -> {ranked[0][0]:5s} ({ranked[0][1]:.0%})   |  {head}")

        if args.save_roi:
            cv2.imwrite(str(args.save_roi / f"{part}.jpg"), crop)

    if args.save_roi:
        print(f"\nROI 已存到 {args.save_roi}/")
    print("\n注意：這批模型驗證 macro accuracy 只有 0.38~0.67，預測錯是常態，僅供抽驗參考。")


if __name__ == "__main__":
    main()
