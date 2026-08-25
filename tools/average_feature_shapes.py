"""算出每個分類在**這批資料裡實際的平均形狀**，給前端畫示意圖用。

為什麼需要這支
--------------
分析結果頁要向使用者解釋「你被判成落尾眉，因為落尾眉長這樣」。手繪的示意圖做不到
這件事——手繪的是「我以為落尾眉長怎樣」，畫出來會不自覺往對稱、圓潤、好看靠，
變成插畫而不是臉，而且跟模型實際學到的東西沒有任何關係。

這支改成從資料算：把同一類的所有照片的眉毛 landmark 對齊後平均。畫出來的是
「你的訓練集裡的落尾眉」，不是誰的想像。真人平均起來本來就不對稱、不圓潤，
所以它會自動失去那種插畫感。

它還會順便回答一個更重要的問題：**這些平均形狀彼此差多少**。如果一字眉與落尾眉的
平均線疊起來幾乎重合，那比任何分布圖都更直接地說明 2026-08-24 查到的事——
那條分類界線在資料上非常薄。輸出裡的 `separation` 就是這個數字。

怎麼對齊
--------
不對齊就平均，得到的是一團模糊：每張照片的頭都在不同位置、不同大小、還可能歪著。
這裡用跟 brow_geometry_probe 相同的基準，兩邊的數字才可以互相對照：

    平移  兩眼外眥的中點移到原點
    旋轉  兩眼外眥的連線轉成水平（消除歪頭）
    縮放  兩眼外眥的距離縮成 1

剩下的差異才是眉型本身的差異。

輸出
----
    models/basic_features_roi/average_shapes.json

每個分類含平均座標、樣本數，以及每個點的標準差——標準差可以在前端畫成
「這一類的變異範圍」，讓使用者看到平均線只是中心，不是每個人都長那樣。

用法
----
    ROI_CACHE_DIR=data/roi_cache_dedup python tools/average_feature_shapes.py
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  # 讓 face/ 的模組 import 得到
import json
import os
from collections import defaultdict
from pathlib import Path

import cv2
import mediapipe_ascii  # noqa: F401  # 必須早於 mediapipe，見該模組說明
import mediapipe as mp
import numpy as np

CACHE_DIR = Path(os.environ.get("ROI_CACHE_DIR", "data/roi_cache"))
OUT_PATH = Path(os.environ.get("AVG_SHAPES_OUT",
                               "models/basic_features_roi/average_shapes.json"))
MAX_IMAGE_SIZE = 1024        # 跟 prepare_roi_cache 一致，landmark 尺度才對得上
OUTER_CANTHI = (33, 263)     # 兩眼外眥，對齊用的基準

# 畫圖需要的是**有順序的**點，landmark 索引本身沒有順序。
# 每條線由外側往內側排，前端照這個順序連成曲線。
CONTOURS = {
    "brow_shape": {
        "left_upper":  (70, 63, 105, 66, 107),
        "left_lower":  (46, 53, 52, 65, 55),
        "right_upper": (300, 293, 334, 296, 336),
        "right_lower": (276, 283, 282, 295, 285),
    },
}


def normalise(pts: np.ndarray) -> np.ndarray | None:
    """把整組 landmark 對齊到共同座標系。回傳 None 代表這張不能用。"""
    a, b = pts[OUTER_CANTHI[0]].astype(float), pts[OUTER_CANTHI[1]].astype(float)
    d = b - a
    scale = float(np.hypot(*d))
    if scale <= 1:
        return None
    centre = (a + b) / 2
    # 轉回水平：用兩眼連線的角度反轉。歪頭拍的照片不校正的話，
    # 眉尾高度會被頭部傾角汙染——那正是這裡要量的東西。
    cos, sin = d[0] / scale, d[1] / scale
    rot = np.array([[cos, sin], [-sin, cos]])
    return ((pts.astype(float) - centre) @ rot.T) / scale


def main() -> None:
    index = json.loads((CACHE_DIR / "index.json").read_text(encoding="utf-8"))
    records = index["records"]
    parts = [p for p in CONTOURS if any(p in r.get("labels", {}) for r in records)]
    wanted = [r for r in records if any(p in r.get("labels", {}) for p in parts)]
    print(f"快取 {CACHE_DIR}｜部位 {parts}｜{len(wanted)} 張")

    mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=False,
        min_detection_confidence=0.5)

    # (part, label) -> list of 正規化後的 468x2
    bucket: dict[tuple[str, str], list[np.ndarray]] = defaultdict(list)
    failed = 0
    for i, rec in enumerate(wanted, 1):
        path = Path(rec["path"])
        frame = (cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
                 if path.is_file() else None)
        if frame is None:
            failed += 1
            continue
        h0, w0 = frame.shape[:2]
        s = MAX_IMAGE_SIZE / max(h0, w0)
        if s < 1:
            frame = cv2.resize(frame, (int(w0 * s), int(h0 * s)), interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
        res = mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not res.multi_face_landmarks:
            failed += 1
            continue
        pts = np.array([[lm.x * w, lm.y * h] for lm in res.multi_face_landmarks[0].landmark])
        norm = normalise(pts)
        if norm is None:
            failed += 1
            continue
        for part in parts:
            label = rec["labels"].get(part)
            if label:
                bucket[(part, label)].append(norm)
        if i % 100 == 0:
            print(f"  {i}/{len(wanted)}  失敗 {failed}", flush=True)
    mesh.close()

    out: dict[str, dict] = {}
    for part in parts:
        labels = sorted({l for (p, l) in bucket if p == part})
        out[part] = {"contours": list(CONTOURS[part]), "classes": {}}
        means: dict[str, np.ndarray] = {}

        for label in labels:
            stack = np.stack(bucket[(part, label)])          # (N, 468, 2)
            entry = {"n": int(stack.shape[0]), "lines": {}}
            flat = []
            for name, idxs in CONTOURS[part].items():
                sel = stack[:, list(idxs), :]                # (N, K, 2)
                mean = sel.mean(axis=0)
                std = sel.std(axis=0)
                entry["lines"][name] = {
                    "mean": [[round(float(x), 5), round(float(y), 5)] for x, y in mean],
                    # 每個點的離散程度。畫成帶狀就能讓使用者看到「平均線只是中心」。
                    "std": [round(float(np.hypot(*s)), 5) for s in std],
                }
                flat.append(mean)
            means[label] = np.concatenate(flat)
            out[part]["classes"][label] = entry

        # 平均形狀彼此差多少。單位跟座標一致（眼距=1），所以 0.01 就是眼距的 1%。
        pairs = {}
        for i, a in enumerate(labels):
            for b in labels[i + 1:]:
                pairs[f"{a} vs {b}"] = round(
                    float(np.linalg.norm(means[a] - means[b], axis=1).mean()), 5)
        out[part]["separation"] = dict(sorted(pairs.items(), key=lambda kv: kv[1]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n寫到 {OUT_PATH}（失敗 {failed} 張）")

    for part, data in out.items():
        print(f"\n=== {part} ===")
        for label, e in data["classes"].items():
            avg_std = np.mean([s for l in e["lines"].values() for s in l["std"]])
            print(f"  {label:8} n={e['n']:4}   點的平均離散度 {avg_std:.4f}")
        print(f"\n  平均形狀之間的距離（眼距=1，越小代表兩類越像）：")
        for k, v in data["separation"].items():
            print(f"    {k:22} {v:.5f}")


if __name__ == "__main__":
    main()
