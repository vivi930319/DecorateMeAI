"""用 MediaPipe FaceMesh 產生只保留臉部外輪廓的二值遮罩。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from face_roi import ROI_SPECS, roi_bbox

CACHE_DIR = Path("data/roi_cache")
OUT_PATH = CACHE_DIR / "face_contour.npy"
MAX_IMAGE_SIZE = 1024

# MediaPipe FaceMesh face oval 的連續順序：額頭中央沿右側下行，再由下巴沿左側回額頭。
FACE_OVAL = np.array([
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
], dtype=np.int32)


def main():
    records = json.loads((CACHE_DIR / "index.json").read_text(encoding="utf-8"))["records"]
    size = ROI_SPECS["face_shape"]["size"]
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
        x1, y1, x2, y2 = roi_bbox(points, "face_shape", h, w)
        side = max(x2 - x1, y2 - y1)
        canvas = np.zeros((side, side), dtype=np.uint8)
        polygon = points[FACE_OVAL] - np.array([x1, y1], dtype=np.int32)
        cv2.fillPoly(canvas, [polygon], 255, lineType=cv2.LINE_AA)
        cv2.polylines(canvas, [polygon], True, 255, thickness=max(2, side // 100), lineType=cv2.LINE_AA)
        mask = cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA)
        masks[i] = cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
        done += 1
    mesh.close()
    np.save(OUT_PATH, masks)
    print(f"face contour cache: success={done}, failed={failed}, output={OUT_PATH}")


if __name__ == "__main__":
    main()
