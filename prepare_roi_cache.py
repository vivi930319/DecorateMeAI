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

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

import cv2
import mediapipe_ascii  # noqa: F401  # 必須早於 mediapipe，見該模組說明
import mediapipe as mp
import numpy as np

from face_roi import PARTS, crop_roi

ROOT = Path("data/basic_full/grouped")
OUT_DIR = Path("data/roi_cache")
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_SIZE = 1024  # 跟 Face_analyzer_BASIC 的預設一致，讓 landmark 尺度對得上

# 標註資料夾名 → 官方類別名。
#
# 官方分類表由標註同學定義，是唯一事實來源：
#   臉型 圓形臉／心形臉／方形臉／長形臉／鵝蛋臉
#   眉型 一字眉／彎月眉／落尾眉
#   眼型 細長眼（併入瞇縫眼）／桃花眼／杏仁眼／圓眼／鳳眼（併入丹鳳眼）／下垂眼
#   鼻型 標準鼻（併入窄鼻）／寬鼻（併入蒜頭鼻）
#   唇型 薄唇／花瓣唇／微笑唇／厚唇／M型唇
#
# 刻意用對照表而不是去搬檔案：標註資料夾是人工分好的原始事實，搬動它就沒辦法
# 反悔，也看不出當初到底怎麼歸的。歸類決定寫在這裡，改一行就能換回去。
#
# 這些合併多數「已經做過一半」——舊類別的圖被複製到新類別資料夾，但舊資料夾沒刪，
# 於是同一張圖同時存在於兩個類別底下。套上對照表之後它們就是同類重複，交給
# 去重處理即可（見 collect_images）。
LABEL_ALIASES = {
    "eye_shape": {"丹鳳眼": "鳳眼", "瞇縫眼": "細長眼"},
    "nose_shape": {"窄鼻": "標準鼻", "蒜頭鼻": "寬鼻"},
}

# 官方類別清單。對照表套完後若冒出不在清單裡的類別，代表資料夾多了沒講好的分類，
# 寧可吵起來也不要安靜地訓進去。
CANONICAL_LABELS = {
    "face_shape": {"圓形臉", "心形臉", "方形臉", "長形臉", "鵝蛋臉"},
    "brow_shape": {"一字眉", "彎月眉", "落尾眉"},
    "eye_shape": {"細長眼", "桃花眼", "杏仁眼", "圓眼", "鳳眼", "下垂眼"},
    "nose_shape": {"標準鼻", "寬鼻"},
    "lip_shape": {"薄唇", "花瓣唇", "微笑唇", "厚唇", "M型唇"},
}


def collect_images() -> dict[Path, dict[str, str]]:
    """收集訓練圖並套用官方分類表，同時去重與剔除標註衝突。

    為什麼要按「檔案內容」去重而不是按路徑：這批資料裡有大量位元組完全相同的
    重複檔（合併類別時用複製而非搬移留下的）。同一份像素若被切到 train 與 val
    兩邊，模型是在驗證集上看它訓練時背過的東西，分數會虛高又測不出泛化——
    這正是舊紀錄裡 per_image 切分分數異常漂亮的真正原因。

    套完對照表後仍對應到多個類別的圖，是標註同學之間真正的判斷分歧
    （例如同一張臉被標成一字眉與彎月眉）。這種樣本的正確答案自己在打架，
    模型學不到一致的決策邊界，一律剔除不訓，並印出來供人工複核。
    """
    by_digest: dict[str, dict[str, str]] = defaultdict(dict)
    digest_to_path: dict[str, Path] = {}
    conflicts: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    unexpected: dict[str, set[str]] = defaultdict(set)
    raw_count = 0

    for part_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        if part_dir.name not in PARTS:
            continue
        aliases = LABEL_ALIASES.get(part_dir.name, {})
        canonical = CANONICAL_LABELS.get(part_dir.name, set())
        for label_dir in sorted(p for p in part_dir.iterdir() if p.is_dir()):
            # 資料夾名撞到部位名（例如 nose_shape/nose_shape）是拷貝殘留的巢狀
            # 目錄，不是類別。iterdir 不遞迴所以本來就撈不到圖，這裡明講一次，
            # 免得日後有人「修好」成遞迴反而把重複資料吃進來。
            if label_dir.name in PARTS:
                continue
            label = aliases.get(label_dir.name, label_dir.name)
            if canonical and label not in canonical:
                unexpected[part_dir.name].add(f"{label_dir.name} → {label}")
                continue
            for path in label_dir.iterdir():
                if path.suffix.lower() not in EXTS or path.name.startswith("._"):
                    continue
                raw_count += 1
                digest = hashlib.md5(path.read_bytes()).hexdigest()
                digest_to_path.setdefault(digest, path.resolve())
                existing = by_digest[digest].get(part_dir.name)
                if existing is not None and existing != label:
                    conflicts[part_dir.name][digest] |= {existing, label}
                by_digest[digest][part_dir.name] = label

    for part, labels in sorted(unexpected.items()):
        print(f"警告：{part} 出現不在官方清單的類別，已跳過 → {sorted(labels)}")

    images: dict[Path, dict[str, str]] = {}
    dropped_conflict = 0
    for digest, labels in by_digest.items():
        kept = {part: label for part, label in labels.items()
                if digest not in conflicts.get(part, {})}
        dropped_conflict += len(labels) - len(kept)
        if kept:
            images[digest_to_path[digest]] = kept

    print(f"原始檔案 {raw_count} 個 → 內容去重後 {len(by_digest)} 張唯一圖")
    for part in PARTS:
        n = sum(1 for labels in images.values() if part in labels)
        c = len(conflicts.get(part, {}))
        print(f"  {part:12} 可用 {n:4} 張，剔除標註衝突 {c:3} 張")
    if dropped_conflict:
        print(f"（衝突樣本已剔除，總計 {dropped_conflict} 個部位標籤；清單見 "
              f"{OUT_DIR / 'label_conflicts.json'}）")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "label_conflicts.json").write_text(
        json.dumps(
            {part: {digest_to_path[d].name: sorted(v) for d, v in items.items()}
             for part, items in conflicts.items()},
            ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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
