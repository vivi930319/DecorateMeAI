"""從 MediaPipe FaceMesh landmark 裁出各部位的 ROI 影像。

訓練（train_basic_cnn_roi.py）和線上推論（Face_analyzer_BASIC.py）共用這支模組。
兩邊的裁切定義只要飄掉一點，模型看到的分佈就跟訓練時不同，準確率會無聲崩掉，
所以 ROI_SPECS 是唯一事實來源，不要在別處另外寫一份裁切邏輯。

輸入的 landmark 就是 FaceAnalyzer._pts_cache（468x2 的像素座標），
反正正常流程本來就會算，裁切本身幾乎不花額外時間。
"""

from __future__ import annotations

import cv2
import numpy as np

# MediaPipe FaceMesh 468 點的部位索引。
# 眉/眼刻意左右合併成單一 ROI：眉間距、兩眼間距本身就是判斷眉型/眼型的線索，
# 分開裁會把這個資訊丟掉。
_BROW_POINTS = (
    46, 53, 52, 65, 55, 70, 63, 105, 66, 107,        # 左眉
    276, 283, 282, 295, 285, 300, 293, 334, 296, 336,  # 右眉
)
_EYE_POINTS = (
    33, 133, 159, 145, 160, 158, 153, 144, 157, 161, 163, 173,   # 左眼
    362, 263, 386, 374, 387, 385, 380, 373, 388, 398, 390, 466,  # 右眼
)
_NOSE_POINTS = (
    168, 6, 197, 195, 5, 4, 1, 19, 94, 2,
    129, 358, 98, 327, 64, 294, 240, 460, 99, 328,
)
_LIP_POINTS = (
    61, 291, 0, 17, 13, 14, 37, 267, 39, 269, 40, 270,
    84, 314, 85, 315, 181, 405, 146, 375, 178, 402, 80, 310, 88, 318,
)
# 臉型看的是整體輪廓，用臉的外框點。
_FACE_POINTS = (
    10, 152, 234, 454, 103, 332, 123, 352, 132, 361, 150, 379,
    109, 338, 21, 251, 162, 389, 127, 356, 93, 323, 58, 288, 172, 397, 136, 365, 148, 377,
)

# margin: bbox 各方向外擴的比例。部位需要一點周邊 context 才判斷得出形狀，
# 但擴太多就會把髮型、背景帶進來，讓 CNN 有機會學到跟部位無關的東西。
# size: 餵給 CNN 的正方形邊長。部位用 96，臉型需要更多細節用 128。
ROI_SPECS = {
    "face_shape": {"points": _FACE_POINTS, "margin": 0.08, "size": 128},
    "brow_shape": {"points": _BROW_POINTS, "margin": 0.35, "size": 96},
    "eye_shape":  {"points": _EYE_POINTS,  "margin": 0.35, "size": 96},
    "nose_shape": {"points": _NOSE_POINTS, "margin": 0.28, "size": 96},
    "lip_shape":  {"points": _LIP_POINTS,  "margin": 0.30, "size": 96},
}

PARTS = tuple(ROI_SPECS)


def roi_bbox(points: np.ndarray, part: str, frame_h: int, frame_w: int) -> tuple[int, int, int, int]:
    """回傳 (x1, y1, x2, y2)。先算部位 bbox，外擴 margin，再補成正方形。

    補正方形是為了讓 resize 不會把部位拉扁 —— 唇型的「厚/薄」、眼型的「圓/細長」
    全靠長寬比，非等比縮放會直接毀掉這個訊號。
    """
    spec = ROI_SPECS[part]
    pts = points[list(spec["points"])]
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)

    w, h = x2 - x1, y2 - y1
    margin = spec["margin"]
    x1 -= w * margin
    x2 += w * margin
    y1 -= h * margin
    y2 += h * margin

    # 補成正方形：以短邊往中心兩側撐開到跟長邊一樣
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    side = max(x2 - x1, y2 - y1)
    half = side / 2.0
    return (
        int(round(cx - half)), int(round(cy - half)),
        int(round(cx + half)), int(round(cy + half)),
    )


def crop_roi(frame: np.ndarray, points: np.ndarray, part: str) -> np.ndarray:
    """裁出部位 ROI 並縮放到該部位的固定尺寸。回傳 BGR uint8。

    bbox 超出畫面時用邊緣像素補（BORDER_REPLICATE），不用黑邊 ——
    黑邊會在 ROI 邊界造出一條假的高對比邊緣，CNN 會去學它。
    """
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = roi_bbox(points, part, h, w)

    pad_left = max(0, -x1)
    pad_top = max(0, -y1)
    pad_right = max(0, x2 - w)
    pad_bottom = max(0, y2 - h)
    if pad_left or pad_top or pad_right or pad_bottom:
        frame = cv2.copyMakeBorder(
            frame, pad_top, pad_bottom, pad_left, pad_right, cv2.BORDER_REPLICATE
        )
        x1 += pad_left
        x2 += pad_left
        y1 += pad_top
        y2 += pad_top

    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        raise ValueError(f"{part} 的 ROI 是空的（landmark 異常）")

    size = ROI_SPECS[part]["size"]
    interp = cv2.INTER_AREA if crop.shape[0] > size else cv2.INTER_LINEAR
    return cv2.resize(crop, (size, size), interpolation=interp)


IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def roi_to_tensor(crop_bgr: np.ndarray) -> np.ndarray:
    """BGR uint8 ROI -> (1, 3, H, W) float32，ImageNet 正規化。訓練與 ONNX 推論共用。"""
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    normed = (rgb - IMAGENET_MEAN) / IMAGENET_STD
    return np.ascontiguousarray(normed.transpose(2, 0, 1)[None], dtype=np.float32)

# MediaPipe FACEMESH_FACE_OVAL 的點序（36 點，沿著臉部外框）。
# 寫死在這裡而不是每次從 mp.solutions 取，是因為推論端不見得會初始化 FaceMesh 物件，
# 而這串順序是固定的。
FACE_OVAL = np.array([
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
], dtype=np.int32)


def face_contour_mask(points, h, w, size):
    """把臉部外框畫成二值遮罩（size x size x 3，uint8）。

    **訓練與推論必須共用這一份。** 遮罩的每個細節——外接框怎麼取、填充還是描邊、
    線寬多少、用哪種內插縮放——都會影響模型看到的東西。複製第二份到推論端，
    兩邊遲早會走樣，屆時線上表現掉了也查不出原因，因為離線重測是好的。
    這跟 face_measurements() 註解講的是同一件事。

    臉型改用輪廓輸入的理由見〈臉部分析模型_完整發展歷程規格書〉：
    RGB 的分數各折在 0.408~0.614 之間跳（±0.074），輪廓穩定在 0.46~0.53（±0.025）——
    平均差在雜訊內，但 RGB 依賴膚色髮型這些跟臉型無關、又會隨資料改變的線索。
    """
    import cv2

    x1, y1, x2, y2 = roi_bbox(points, "face_shape", h, w)
    side = max(x2 - x1, y2 - y1)
    if side <= 0:
        return None
    canvas = np.zeros((side, side), dtype=np.uint8)
    polygon = np.asarray(points, dtype=np.int32)[FACE_OVAL] - np.array([x1, y1], dtype=np.int32)
    cv2.fillPoly(canvas, [polygon], 255, lineType=cv2.LINE_AA)
    cv2.polylines(canvas, [polygon], True, 255,
                  thickness=max(2, side // 100), lineType=cv2.LINE_AA)
    mask = cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
