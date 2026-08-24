"""用 MediaPipe FaceMesh 產生只保留臉部外輪廓的二值遮罩。"""

from __future__ import annotations

import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mediapipe_ascii  # noqa: F401,E402  # 必須早於 mediapipe，見該模組說明
import mediapipe as mp  # noqa: E402

from face_roi import ROI_SPECS, face_contour_mask, roi_bbox

CACHE_DIR = Path("data/roi_cache")
# 預設輸出。實際檔名在 main() 依 --size 決定（非預設解析度會加後綴），
# 這個常數只留給其他模組參考預設值——不要在 main 裡用它存檔。
MAX_IMAGE_SIZE = 1024

# MediaPipe FaceMesh face oval 的連續順序：額頭中央沿右側下行，再由下巴沿左側回額頭。
FACE_OVAL = np.array([
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
], dtype=np.int32)


def main():
    # 解析度可調。預設沿用 ROI_SPECS 的 128，但圓形臉與方形臉的差別在下顎轉角，
    # 那在 128x128 的二值遮罩上可能只有幾個像素——調高才看得出來。
    # 寫到不同檔名，這樣不同解析度的實驗可以並存比較，不會互相覆蓋。
    ap = argparse.ArgumentParser(description="建立臉部外輪廓二值遮罩快取")
    ap.add_argument("--size", type=int, default=ROI_SPECS["face_shape"]["size"])
    ap.add_argument("--out", default=None, help="輸出檔名；預設 face_contour.npy，非預設解析度會自動加後綴")
    args = ap.parse_args()

    records = json.loads((CACHE_DIR / "index.json").read_text(encoding="utf-8"))["records"]
    size = args.size
    default_size = ROI_SPECS["face_shape"]["size"]
    out_name = args.out or ("face_contour.npy" if size == default_size else f"face_contour_{size}.npy")
    print(f"解析度 {size}x{size} → {out_name}")
    masks = np.zeros((len(records), size, size, 3), dtype=np.uint8)
    mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=False,
        min_detection_confidence=0.5,
    )
    done = failed = 0
    for i, rec in enumerate(records):
        if "face_shape" not in rec["labels"]:
            continue
        frame = cv2.imdecode(np.fromfile(rec["path"], dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            failed += 1
            continue
        h0, w0 = frame.shape[:2]
        scale = MAX_IMAGE_SIZE / max(h0, w0)
        if scale < 1:
            frame = cv2.resize(frame, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
        result = mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not result.multi_face_landmarks:
            failed += 1
            continue
        points = np.array([[int(l.x * w), int(l.y * h)]
                           for l in result.multi_face_landmarks[0].landmark], dtype=np.int32)
        # 用 face_roi 的共用函式，不要在這裡自己畫一份——推論端讀的是同一支。
        mask = face_contour_mask(points, h, w, size)
        if mask is None:
            failed += 1
            continue
        masks[i] = mask
        done += 1
    mesh.close()
    np.save(CACHE_DIR / out_name, masks)
    print(f"face contour cache: success={done}, failed={failed}, output={CACHE_DIR / out_name}")


if __name__ == "__main__":
    main()
