"""側臉鼻型：MediaPipe 在側臉上讀不讀得到？讀到之後幾何分不分得開？

兩個問題，一次回答
------------------
1. **偵測率**：FaceMesh 在側臉照上到底有多少張抓得到臉，逐類分別是多少。
   這件事有前科——實測 438 張只認得 73.5%，而且失敗率**依類別偏斜**
   （塌鼻 60.4%、翹鼻 93.4%）。偏斜比低更麻煩：它會讓「抓得到的樣本」
   自己變成一個有偏的子集，任何在上面算出來的分數都不能代表全體。

2. **可分性**：對抓得到的那些，用 `pro_nose_geometry` 的九個特徵，
   逐對類別算單一特徵的最佳 AUC——問的是「幾何能不能當裁判」，
   不是「幾何能不能自己分類」（後者已知會輸：geometry 單獨 macro 0.315）。

   最該看的是 **駝峰鼻 vs 塌鼻**：這兩類的定義本來就是幾何上的相反
   （鼻樑中段外凸 vs 內凹），`dorsal_convexity` 這個特徵就是為它們算的。
   如果連這一對都分不開，那代表 landmark 在側臉上的位置不可靠，
   不是特徵設計有問題。

用法
----
    .venv\\Scripts\\python.exe tools\\pro_nose_geometry_probe.py
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
import argparse
import hashlib
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mediapipe_ascii  # noqa: F401,E402  必須早於 mediapipe
import mediapipe as mp  # noqa: E402

import pro_nose_geometry  # noqa: E402

ROOT = Path("data/pro_full/grouped/nose_shape_side")
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
LABEL_ALIASES = {"朝天鼻": "翹鼻"}   # 朝天鼻的內容全部也在翹鼻資料夾裡，見 train_pro_nose_side
MAX_EDGE = 1024


def auc(values: np.ndarray, is_positive: np.ndarray) -> float:
    """Mann–Whitney U 換算的 AUC。回傳 ≥ 0.5：只問分不分得開，不問方向。"""
    ranks = values.argsort().argsort().astype(float) + 1
    n_pos = int(is_positive.sum())
    n_neg = len(values) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    score = (ranks[is_positive].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(max(score, 1 - score))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()

    if not ROOT.exists():
        raise SystemExit(f"找不到 {ROOT}，先跑 tools/sync_datasets.py --pull")

    # 去重用檔案內容雜湊：同一張圖被複製到兩個類別資料夾時，看檔名看不出來。
    by_digest: dict[str, tuple[Path, str]] = {}
    for class_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        label = LABEL_ALIASES.get(class_dir.name, class_dir.name)
        for path in sorted(class_dir.iterdir()):
            if path.suffix.lower() in EXTS:
                by_digest.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), (path, label))

    mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=False,
        min_detection_confidence=0.3)

    total = Counter()
    detected = Counter()
    features: list[np.ndarray] = []
    labels: list[str] = []

    for i, (path, label) in enumerate(by_digest.values(), 1):
        total[label] += 1
        # 不能用 cv2.imread：類別資料夾名是中文（塌鼻／翹鼻…），Windows 上
        # imread 對非 ASCII 路徑一律回 None，而它不會報錯——實測 639 張全部
        # 「偵測不到臉」，看起來像 MediaPipe 讀不到側臉，其實是根本沒讀到檔案。
        image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            continue
        scale = MAX_EDGE / max(image.shape[:2])
        if scale < 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        result = mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        if not result.multi_face_landmarks:
            continue
        height, width = image.shape[:2]
        points = np.array([[lm.x * width, lm.y * height]
                           for lm in result.multi_face_landmarks[0].landmark])
        vector = pro_nose_geometry.extract(points)
        if vector is None:
            continue
        detected[label] += 1
        features.append(vector)
        labels.append(label)
        if i % 100 == 0:
            print(f"  {i}/{len(by_digest)}", flush=True)
    mesh.close()

    print("\n① FaceMesh 在側臉上的偵測率（含幾何特徵算得出來）")
    print(f"{'類別':<8}{'抓到':>6}{'總數':>6}{'偵測率':>9}")
    for label in sorted(total):
        rate = detected[label] / total[label] if total[label] else 0
        print(f"{label:<8}{detected[label]:>6}{total[label]:>6}{rate:>8.1%}")
    overall = sum(detected.values()) / max(sum(total.values()), 1)
    print(f"{'合計':<8}{sum(detected.values()):>6}{sum(total.values()):>6}{overall:>8.1%}")

    if len(set(labels)) < 2:
        raise SystemExit("抓到的類別不足兩類，無法比較")

    matrix = np.array(features)
    labels_array = np.array(labels)
    names = list(pro_nose_geometry.FEATURE_NAMES)

    print("\n② 每一對類別，單一幾何特徵的最佳 AUC")
    print("（0.50 = 沒有分辨力，0.70 = 有訊號，0.80+ = 分得開）\n")
    rows = []
    for first, second in combinations(sorted(set(labels)), 2):
        mask = (labels_array == first) | (labels_array == second)
        positive = labels_array[mask] == first
        scores = sorted(((auc(matrix[mask][:, i], positive), names[i])
                         for i in range(len(names))), reverse=True)
        rows.append(((first, second), scores))

    rows.sort(key=lambda item: item[1][0][0])
    for (first, second), scores in rows:
        mark = "  ← 幾何上互為相反，最該分得開" if {first, second} == {"駝峰鼻", "塌鼻"} else ""
        best = "、".join(f"{name} {value:.3f}" for value, name in scores[:args.top])
        print(f"{first} vs {second:<5}  最佳 AUC {scores[0][0]:.3f}   {best}{mark}")

    print("\n③ dorsal_convexity（鼻樑中段凸出量，正=駝峰 負=塌）逐類分布")
    column = names.index("dorsal_convexity")
    grouped = defaultdict(list)
    for value, label in zip(matrix[:, column], labels):
        grouped[label].append(value)
    print(f"{'類別':<8}{'中位數':>10}{'平均':>10}{'標準差':>10}{'n':>6}")
    for label in sorted(grouped):
        values = np.array(grouped[label])
        print(f"{label:<8}{np.median(values):>10.4f}{values.mean():>10.4f}"
              f"{values.std():>10.4f}{len(values):>6}")


if __name__ == "__main__":
    main()
