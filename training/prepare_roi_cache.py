"""對每張訓練圖跑一次 MediaPipe，把五個部位的 ROI 裁好存成快取。

快取原因：MediaPipe FaceMesh 每張要 50~100ms，1295 張 × 十幾個 epoch
會讓大部分時間花在重複算同一組 landmark 上。先算一次存起來，訓練就只剩 CNN 本身。

輸出：
    data/roi_cache/rois.npz        每個部位一個 uint8 陣列 (N, size, size, 3)，RGB
    data/roi_cache/index.json      每張圖的路徑、各部位標籤、identity

快取一律存 RGB：crop_roi 回傳的是 BGR，但線上推論走 roi_to_tensor 會先轉成 RGB。
若快取留著 BGR，訓練吃的通道順序就跟推論不同，模型上線後會無聲掉分。
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
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

# 可用環境變數指定來源與輸出目錄，方便在不動到既有資料/快取的情況下重建。
ROOT = Path(os.environ.get("ROI_DATASET_ROOT", "data/basic_full/grouped"))
OUT_DIR = Path(os.environ.get("ROI_CACHE_DIR", "data/roi_cache"))
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_SIZE = 1024  # 跟 Face_analyzer_BASIC 的預設一致，讓 landmark 尺度對得上

# 標註資料夾名 → 官方類別名。
#
# 官方分類表由標註同學定義，是唯一事實來源：
#   臉型 圓形臉／心形臉／方形臉／長形臉／鵝蛋臉
#   眉型 一字眉／彎月眉／落尾眉／挑眉（2026-08-21 新增）
#   眼型 桃杏眼（併入杏仁眼、桃花眼）／圓眼／鳳眼（併入丹鳳眼、瞇縫眼、細長眼）／下垂眼
#   鼻型 標準鼻（併入窄鼻）／寬鼻（併入蒜頭鼻）
#   唇型 薄唇／花瓣唇／微笑唇／厚唇
#
# 使用對照表保留原始標註資料夾，並由 collect_images 處理合併後的重複圖片。
LABEL_ALIASES = {
    # 杏仁眼與桃花眼合併為桃杏眼；丹鳳眼、瞇縫眼與細長眼合併為鳳眼。
    # 別名只查一次，所以每個舊名稱都要直接指向最終分類。
    "eye_shape": {
        "丹鳳眼": "鳳眼", "瞇縫眼": "鳳眼", "細長眼": "鳳眼",
        "杏仁眼": "桃杏眼", "桃花眼": "桃杏眼",
    },
    # brow_shape 刻意不在這裡。**落尾眉不併進彎月眉，這是產品決策**（2026-08-24）。
    #
    # 記在這裡是因為數據會誘使人做相反的事：那天量過，把兩類合併重訓
    # macro 從 0.525 ± 0.036 跳到 0.637 ± 0.020（+0.112），比眼型 6→5 的 +0.069
    # 與唇型 5→4 的 +0.068 都大。同一輪還確認了那條界線在資料上有多薄——
    #
    #   幾何量不出來   tail_rise（眉尾比眉頭低多少，用眼距正規化）的中位數
    #                  落尾眉 -0.056、彎月眉 -0.058，彎月眉還「更落尾」；
    #                  四類的四分位距全部重疊，只用幾何跑決策樹 macro 只有 0.327
    #   不是標錯        find_label_errors 用 CNN + DINOv2 取 out-of-fold、
    #                  門檻放寬到 0.60，兩者都有把握地答錯的樣本是 0 張
    #   不是調參能救    focal + class-weight 讓 macro 降到 0.505；
    #                  換損失、加權重、去重複，彎月↔落尾的互相誤判都在 51~59 之間不動
    #
    # 就算如此仍然分開，跟微笑唇是同一種理由：分類表對使用者的意義不由混淆矩陣決定。
    # 要改善這一對，該做的是重新定義判準並重標，不是把它從分類表上拿掉。
    # 想重看這些數字：tools/brow_geometry_probe.py。
    "nose_shape": {"窄鼻": "標準鼻", "蒜頭鼻": "寬鼻"},
    # M 型唇合併到花瓣唇。微笑唇因會受到表情影響，依產品決策維持獨立。
    # 改善微笑唇判斷時應要求使用者放鬆嘴角，不應只因混淆矩陣而合併分類。
    "lip_shape": {"M型唇": "花瓣唇"},
}

# 合併後的標籤必須存在於官方清單，否則停止訓練並回報資料問題。
#
# ⚠️ 新增類別時**這裡也要加**，否則整個類別會被安靜地跳過：collect_images 只印一行
# 「出現不在官方清單的類別，已跳過」，然後照常跑完、產出快取、訓練成功——但那個
# 類別一張圖都沒進去。2026-08-23 就這樣白跑了一輪（挑眉 100 張全被濾掉）。
# 這個擋法本身是對的（防止資料夾打錯字混進訓練），只是它的代價是新增類別必須登記。
CANONICAL_LABELS = {
    "face_shape": {"圓形臉", "心形臉", "方形臉", "長形臉", "鵝蛋臉"},
    "brow_shape": {"一字眉", "彎月眉", "落尾眉", "挑眉"},
    "eye_shape": {"桃杏眼", "圓眼", "鳳眼", "下垂眼"},
    "nose_shape": {"標準鼻", "寬鼻"},
    "lip_shape": {"薄唇", "花瓣唇", "微笑唇", "厚唇"},
}


def collect_images() -> dict[Path, dict[str, str]]:
    """收集訓練圖並套用官方分類表，同時去重與剔除標註衝突。

    去重的鍵是檔名，不是檔案內容（2026-07-29 改）。原因是這批資料的組織方式：
    同一張原始照片會被裁成不同大小分放到各部位資料夾——`face_shape/心形臉/IMG_7859.jpg`
    是全臉 746x1110，`lip_shape/薄唇/IMG_7859.jpg` 是嘴部特寫 391x486。按內容雜湊去重
    會把它們當成兩張不相干的圖，同一個人的臉型與唇型標註因此接不起來；實測有 164 個
    檔名落在這種情況。標註同學的約定是「同名就是同一張照片」，這裡照那個約定走。

    仍然保留「同一份照片不可同時進 train 與 val」的保護，只是判斷同一份的依據改成檔名。
    舊紀錄裡 per_image 切分分數異常漂亮的原因（重複檔跨切分）沒有變回來。

    抽 ROI 用同名檔案裡尺寸最大的那一份：部位特寫常常小到偵測不到完整人臉，
    全臉那張才抽得出五個部位的 ROI。

    套完對照表後仍對應到多個類別的圖，是標註同學之間真正的判斷分歧
    （例如同一張臉被標成一字眉與彎月眉）。這種樣本的正確答案自己在打架，
    模型學不到一致的決策邊界，一律剔除不訓，並印出來供人工複核。
    """
    by_digest: dict[str, dict[str, str]] = defaultdict(dict)
    digest_to_path: dict[str, Path] = {}
    conflicts: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    unexpected: dict[str, set[str]] = defaultdict(set)
    duplicates: dict[str, list[tuple[str, str]]] = defaultdict(list)
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
            # 同一個類別資料夾內，內容一模一樣的檔案只留一份。
            #
            # 這一層跟下面「按檔名去重」解決的是不同的問題，兩層都需要：
            # 按檔名去重處理的是跨部位的同一張照片（face_shape/IMG_7859.jpg 與
            # lip_shape/IMG_7859.jpg 內容不同但同源），那個約定要保留；這一層處理的是
            # 同一張照片在同一個資料夾裡以不同檔名存了好幾份——檔名不同，按檔名去重
            # 完全攔不住，三份都會變成三個獨立訓練樣本。
            #
            # 2026-08-23 實測：brow_shape/一字眉 有 220 個檔案卻只有 102 張獨立照片，
            # 118 份是重複（多數是 macOS 拖放產生的 .com.apple.Foundation.NSItemProvider.*
            # 暫存檔，是既有照片的第三份拷貝）。其他三類幾乎沒有重複，於是一字眉在
            # 訓練時被看到的次數是別類的兩倍多，模型偏向猜它——落尾眉的 recall 只有
            # 0.311，其中 23 張就是被誤判成一字眉。去重後四類是 102/117/100/103。
            #
            # 保留哪一份用 sorted 決定，讓每次重建的結果一致。
            seen_content: dict[str, Path] = {}
            for path in sorted(label_dir.iterdir()):
                # 點開頭的是 macOS 的資源分叉（._）與拖放暫存檔（.com.apple.*）。
                # 後者的副檔名是正常的 .jpeg，只靠 EXTS 擋不掉。
                if path.suffix.lower() not in EXTS or path.name.startswith("."):
                    continue
                content = hashlib.sha256(path.read_bytes()).hexdigest()
                if content in seen_content:
                    duplicates[f"{part_dir.name}/{label_dir.name}"].append(
                        (path.name, seen_content[content].name))
                    continue
                seen_content[content] = path
                raw_count += 1
                digest = path.name                       # 同名即同一張照片
                # 同名檔案取尺寸最大的那份來抽 ROI：部位特寫太小會偵測不到人臉。
                prev = digest_to_path.get(digest)
                if prev is None or path.stat().st_size > prev.stat().st_size:
                    digest_to_path[digest] = path.resolve()
                existing = by_digest[digest].get(part_dir.name)
                if existing is not None and existing != label:
                    conflicts[part_dir.name][digest] |= {existing, label}
                by_digest[digest][part_dir.name] = label

    for part, labels in sorted(unexpected.items()):
        print(f"警告：{part} 出現不在官方清單的類別，已跳過 → {sorted(labels)}")

    if duplicates:
        total_dup = sum(len(v) for v in duplicates.values())
        print(f"\n同一類別內的重複檔案已剔除，共 {total_dup} 份：")
        for folder, pairs in sorted(duplicates.items(), key=lambda kv: -len(kv[1])):
            print(f"  {folder:28} 去掉 {len(pairs):3} 份")
        (OUT_DIR).mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "content_duplicates.json").write_text(
            json.dumps({k: [{"剔除": a, "保留": b} for a, b in v]
                        for k, v in duplicates.items()},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"（清單見 {OUT_DIR / 'content_duplicates.json'}）")

    images: dict[Path, dict[str, str]] = {}
    dropped_conflict = 0
    for digest, labels in by_digest.items():
        kept = {part: label for part, label in labels.items()
                if digest not in conflicts.get(part, {})}
        dropped_conflict += len(labels) - len(kept)
        if kept:
            images[digest_to_path[digest]] = kept

    print(f"原始檔案 {raw_count} 個 → 依檔名去重後 {len(by_digest)} 張唯一照片")
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
