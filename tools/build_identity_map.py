"""把訓練圖片按「是同一個人」聚成群，輸出 identity map 給 prepare_roi_cache 用。

需要這項功能的原因：資料集是從影劇截圖蒐集的，同一個藝人常常有好幾張不同角度、不同場景的照片。
如果訓練/驗證用隨機切分，同一張臉會同時出現在兩邊，模型只要認出「這是誰」就能猜對標籤，
驗證分數會虛高一大截，但換成沒看過的人就崩掉。要量到真實表現，同一個人的所有照片
必須整組只落在 train 或 val 其中一邊 —— 本腳本就是產生「哪些照片是同一個人」的依據。

做法：InsightFace(buffalo_l) 抽 512 維人臉 embedding，L2 正規化後做階層式聚類，
cosine 相似度高於門檻的照片視為同一人。抽不到臉的照片標成 -1（訓練時一律留在 train）。

輸出：
    data/roi_cache/identity_map.json
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis
from sklearn.cluster import AgglomerativeClustering

# 跟 prepare_roi_cache.py 讀同一個環境變數。兩支必須指向**同一個資料集目錄**——
# identity map 的鍵是絕對路徑，指錯目錄的話 ROI 快取會查不到 identity，
# 於是每一筆都變成 -1（身分不明），切分就退化成「全部不進驗證」而沒有任何錯誤訊息。
ROOT = Path(os.environ.get("ROI_DATASET_ROOT", "data/basic_full/grouped"))
OUT_PATH = Path(os.environ.get("IDENTITY_MAP", "data/roi_cache/identity_map.json"))
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_SIZE = 1024


def collect_images() -> list[Path]:
    paths = []
    for part_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        for label_dir in sorted(p for p in part_dir.iterdir() if p.is_dir()):
            paths.extend(
                p.resolve() for p in label_dir.iterdir()
                if p.suffix.lower() in EXTS and not p.name.startswith("._")
            )
    return sorted(set(paths))


def largest_face(faces):
    """一張圖可能框到路人；取面積最大的那張臉，跟 BASIC 分析的取法一致。"""
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


def detect(app, frame: np.ndarray):
    """偵測人臉；臉佔滿整張圖時補邊框重試。

    資料集是截圖裁出來的大頭照，臉常常貼齊畫面邊緣。RetinaFace 這類 anchor-based 偵測器
    需要臉周圍留一點餘裕才框得住，直接餵原圖有四成會漏掉（實測 545/1297）。
    補一圈 BORDER_REPLICATE 等於人工把臉「縮小」回偵測器習慣的比例，實測全數救回。
    """
    faces = app.get(frame)
    if faces:
        return faces
    margin = int(0.4 * max(frame.shape[:2]))
    padded = cv2.copyMakeBorder(frame, margin, margin, margin, margin, cv2.BORDER_REPLICATE)
    return app.get(padded)


def parse_args():
    p = argparse.ArgumentParser(description="用 InsightFace embedding 把訓練圖聚成 identity")
    p.add_argument("--similarity", type=float, default=0.45,
                   help="cosine 相似度門檻，越高越嚴格（越不容易把兩個人併成同一人）")
    p.add_argument("--det-size", type=int, default=640)
    return p.parse_args()


def main():
    args = parse_args()

    app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"],
                       providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(args.det_size, args.det_size))

    paths = collect_images()
    print(f"待處理圖片：{len(paths)} 張")

    embeddings: list[np.ndarray] = []
    embedded_paths: list[Path] = []
    no_face: list[str] = []

    for i, path in enumerate(paths, 1):
        frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            no_face.append(str(path))
            continue

        h0, w0 = frame.shape[:2]
        scale = MAX_IMAGE_SIZE / max(h0, w0)
        if scale < 1:
            frame = cv2.resize(frame, (int(w0 * scale), int(h0 * scale)),
                               interpolation=cv2.INTER_AREA)

        faces = detect(app, frame)
        if not faces:
            no_face.append(str(path))
            continue

        vec = largest_face(faces).normed_embedding
        embeddings.append(np.asarray(vec, dtype=np.float32))
        embedded_paths.append(path)

        if i % 100 == 0:
            print(f"  {i}/{len(paths)}  抽到 {len(embeddings)}  無臉 {len(no_face)}", flush=True)

    matrix = np.stack(embeddings)
    # embedding 已 L2 正規化，cosine distance = 1 - 內積。average linkage 對單張離群照片較不敏感。
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=1.0 - args.similarity,
        metric="cosine",
        linkage="average",
    ).fit(matrix)

    path_to_identity = {str(p): int(c) for p, c in zip(embedded_paths, clustering.labels_)}
    for path in no_face:
        path_to_identity[path] = -1

    sizes = Counter(clustering.labels_.tolist())
    n_ids = len(sizes)
    multi = {k: v for k, v in sizes.items() if v > 1}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {
                "similarity_threshold": args.similarity,
                "n_identities": n_ids,
                "n_images": len(path_to_identity),
                "n_no_face": len(no_face),
                "path_to_identity": path_to_identity,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n完成：{len(embeddings)} 張抽到臉、{len(no_face)} 張沒抽到（標為 -1）")
    print(f"聚出 {n_ids} 個身分，其中 {len(multi)} 個身分有多張照片")
    print(f"最大的群：{sorted(sizes.values(), reverse=True)[:10]}")
    print(f"已寫入 {OUT_PATH}")

    # 同一個人跨越多個標籤 = 標註可能互相矛盾，值得回頭人工看
    by_identity = defaultdict(set)
    for path, ident in path_to_identity.items():
        if ident < 0:
            continue
        parts = Path(path).parts
        by_identity[ident].add(f"{parts[-3]}/{parts[-2]}")
    conflicts = {i: sorted(v) for i, v in by_identity.items()
                 if len({s.split("/")[0] for s in v}) == 1 and len(v) > 1}
    if conflicts:
        print(f"\n注意：{len(conflicts)} 個身分在同一個部位底下被標到不同類別（前 5）：")
        for ident, labels in list(conflicts.items())[:5]:
            print(f"  identity {ident}: {labels}")


if __name__ == "__main__":
    main()
