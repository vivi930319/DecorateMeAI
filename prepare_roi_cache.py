"""對每張訓練圖跑一次 MediaPipe，把五個部位的 ROI 裁好存成快取。

為什麼要快取：MediaPipe FaceMesh 每張要 50~100ms，1295 張 × 十幾個 epoch
會讓大部分時間花在重複算同一組 landmark 上。先算一次存起來，訓練就只剩 CNN 本身。

輸出：
    data/roi_cache/rois.npz        每個部位一個 uint8 陣列 (N, size, size, 3)，RGB
    data/roi_cache/index.json      每張圖的路徑、各部位標籤、identity

快取一律存 RGB：crop_roi 回傳的是 BGR，但線上推論走 roi_to_tensor 會先轉成 RGB。
若快取留著 BGR，訓練吃的通道順序就跟推論不同，模型上線後會無聲掉分。
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from face_roi import PARTS, crop_roi

ROOT = Path("data/basic_full/grouped")
OUT_DIR = Path("data/roi_cache")
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_SIZE = 1024  # 跟 Face_analyzer_BASIC 的預設一致，讓 landmark 尺度對得上


def collect_images() -> dict[Path, dict[str, str]]:
    images: dict[Path, dict[str, str]] = defaultdict(dict)
    for part_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        if part_dir.name not in PARTS:
            continue
        for label_dir in sorted(p for p in part_dir.iterdir() if p.is_dir()):
            for path in label_dir.iterdir():
                if path.suffix.lower() in EXTS and not path.name.startswith("._"):
                    images[path.resolve()][part_dir.name] = label_dir.name
    return images


def main():
    identity_path = Path(os.environ.get("IDENTITY_MAP", "data/roi_cache/identity_map.json"))
    path_to_identity: dict[str, int] = {}
    if identity_path.is_file():
        data = json.loads(identity_path.read_text(encoding="utf-8"))
        path_to_identity = data.get("path_to_identity", {})
        print(f"已載入 identity map：{len(path_to_identity)} 張圖 / "
              f"{len(set(path_to_identity.values()))} 個身分")
    else:
        print(f"警告：找不到 {identity_path}，identity 會全部標成 -1（無法做按人切分）")

    images = collect_images()
    paths = sorted(images)
    print(f"待處理圖片：{len(paths)} 張")

    face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=False,
        min_detection_confidence=0.5,
    )

    rois: dict[str, list[np.ndarray]] = {part: [] for part in PARTS}
    records: list[dict] = []
    failed: list[tuple[str, str]] = []

    for i, path in enumerate(paths, 1):
        frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            failed.append((str(path), "圖片讀取失敗"))
            continue

        h0, w0 = frame.shape[:2]
        scale = MAX_IMAGE_SIZE / max(h0, w0)
        if scale < 1:
            frame = cv2.resize(frame, (int(w0 * scale), int(h0 * scale)),
                               interpolation=cv2.INTER_AREA)

        h, w = frame.shape[:2]
        result = face_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not result.multi_face_landmarks:
            failed.append((str(path), "沒偵測到人臉"))
            continue

        pts = np.array(
            [[int(lm.x * w), int(lm.y * h)] for lm in result.multi_face_landmarks[0].landmark],
            dtype=np.int32,
        )

        try:
            crops = {part: crop_roi(frame, pts, part) for part in PARTS}
        except ValueError as exc:
            failed.append((str(path), str(exc)))
            continue

        for part in PARTS:
            rois[part].append(cv2.cvtColor(crops[part], cv2.COLOR_BGR2RGB))
        records.append({
            "path": str(path),
            "labels": images[path],
            "identity": path_to_identity.get(str(path), -1),
        })

        if i % 100 == 0:
            print(f"  {i}/{len(paths)}  成功 {len(records)}  失敗 {len(failed)}", flush=True)

    face_mesh.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUT_DIR / "rois.npz",
        **{part: np.stack(rois[part]) for part in PARTS},
    )
    (OUT_DIR / "index.json").write_text(
        json.dumps({"records": records, "failed": failed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n完成：{len(records)} 張成功、{len(failed)} 張失敗")
    for part in PARTS:
        print(f"  {part:12s} ROI shape = {np.stack(rois[part]).shape}")
    if failed:
        print("\n失敗樣本（前 5）：")
        for path, reason in failed[:5]:
            print(f"  - {Path(path).name}: {reason}")


if __name__ == "__main__":
    main()
