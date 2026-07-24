"""用 MediaPipe FaceMesh 產生眉毛與嘴唇的二值形狀遮罩。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mediapipe_ascii  # noqa: F401,E402  # 必須早於 mediapipe，見該模組說明
import mediapipe as mp  # noqa: E402
from face_roi import ROI_SPECS, roi_bbox  # noqa: E402

CACHE_DIR = Path("data/roi_cache")
MAX_IMAGE_SIZE = 1024

CONTOURS = {
    "brow_shape": [
        [70, 63, 105, 66, 107, 55, 65, 52, 53, 46],
        [300, 293, 334, 296, 336, 285, 295, 282, 283, 276],
    ],
    "lip_shape": [
        [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291,
         308, 324, 318, 402, 317, 14, 87, 178, 88, 95, 78],
    ],
}


def main():
    records = json.loads((CACHE_DIR / "index.json").read_text(encoding="utf-8"))["records"]
    outputs = {
        part: np.zeros((len(records), ROI_SPECS[part]["size"], ROI_SPECS[part]["size"], 3), dtype=np.uint8)
        for part in CONTOURS
    }
    counts = {part: 0 for part in CONTOURS}
    mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=False,
        min_detection_confidence=0.5,
    )
    for i, rec in enumerate(records):
        parts = [part for part in CONTOURS if part in rec["labels"]]
        if not parts:
            continue
        frame = cv2.imdecode(np.fromfile(rec["path"], dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        h0, w0 = frame.shape[:2]
        scale = MAX_IMAGE_SIZE / max(h0, w0)
        if scale < 1:
            frame = cv2.resize(frame, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
        result = mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not result.multi_face_landmarks:
            continue
        points = np.array([[int(l.x * w), int(l.y * h)]
                           for l in result.multi_face_landmarks[0].landmark], dtype=np.int32)
        for part in parts:
            x1, y1, x2, y2 = roi_bbox(points, part, h, w)
            side = max(x2 - x1, y2 - y1)
            canvas = np.zeros((side, side), dtype=np.uint8)
            for indices in CONTOURS[part]:
                polygon = points[np.asarray(indices)] - np.array([x1, y1], dtype=np.int32)
                cv2.fillPoly(canvas, [polygon], 255, lineType=cv2.LINE_AA)
            size = ROI_SPECS[part]["size"]
            mask = cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA)
            outputs[part][i] = cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
            counts[part] += 1
    mesh.close()
    for part, array in outputs.items():
        path = CACHE_DIR / f"{part}_contour.npy"
        np.save(path, array)
        print(f"{part}: success={counts[part]}, output={path}")


if __name__ == "__main__":
    main()
