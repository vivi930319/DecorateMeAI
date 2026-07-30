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
    # 唇部留空：它走下面 lip_mask() 的三通道特例，不走通用的 fillPoly。
    "lip_shape": [],
}

# 唇部單獨處理，因為它需要「外緣形狀」與「厚度」兩種資訊，一條環表達不了。
#
# 先前是把外唇與內唇串成一條 22 點的環再 fillPoly——兩個環接在一起會被當成一個
# 自交多邊形，填出來的形狀不對，而且**厚度資訊整個消失**。
# 唇型四類裡「厚唇 vs 薄唇」就是厚度，「花瓣唇 vs 微笑唇」是外緣曲線，兩個都得留。
#
# MediaPipe 的 468 點在嘴唇這一區特別密（外環 20 點、內環 20 點），勾勒得很細，
# 所以改成三通道各存一種資訊：
#
#   R  外唇填滿      → 整體輪廓與寬高比（薄唇窄扁、厚唇飽滿）
#   G  唇帶（外減內） → 厚度分布
#   B  外唇描邊      → 外緣曲線本身（微笑唇的嘴角上揚）
LIP_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291,
             375, 321, 405, 314, 17, 84, 181, 91, 146]
LIP_INNER = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308,
             324, 318, 402, 317, 14, 87, 178, 88, 95]


def lip_mask(points, x1, y1, side, size):
    """三通道唇部遮罩：R=外唇填滿、G=唇帶厚度、B=外緣描邊。"""
    off = np.array([x1, y1], dtype=np.int32)
    outer = np.asarray(points, dtype=np.int32)[LIP_OUTER] - off
    inner = np.asarray(points, dtype=np.int32)[LIP_INNER] - off

    filled = np.zeros((side, side), dtype=np.uint8)
    cv2.fillPoly(filled, [outer], 255, lineType=cv2.LINE_AA)

    hole = np.zeros((side, side), dtype=np.uint8)
    cv2.fillPoly(hole, [inner], 255, lineType=cv2.LINE_AA)
    band = cv2.subtract(filled, hole)          # 真正的唇肉

    edge = np.zeros((side, side), dtype=np.uint8)
    cv2.polylines(edge, [outer], True, 255,
                  thickness=max(2, side // 60), lineType=cv2.LINE_AA)

    return cv2.resize(np.stack([filled, band, edge], axis=-1),
                      (size, size), interpolation=cv2.INTER_AREA)


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
            if part == "lip_shape":
                outputs[part][i] = lip_mask(points, x1, y1, side, ROI_SPECS[part]["size"])
                counts[part] += 1
                continue
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
