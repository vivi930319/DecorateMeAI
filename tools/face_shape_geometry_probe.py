"""臉型：幾何特徵到底能不能分開 CNN 分不開的那幾對？

為什麼是這個問題，而不是「幾何能不能分類」
------------------------------------------
「幾何分類臉型」已經試過而且輸了：`tools/cascade_face_shape.py` 的階層式 0.437、
扁平決策樹 0.462，CNN 0.522。那條路的死因是**錯誤往下傳遞**——早期的層把樣本吃掉，
後面再準也救不回來。

所以這支不重跑那個實驗。它問的是另一個問題：**在 CNN 已經圈好的兩個候選之間，
幾何能不能當裁判。** 如果能，就值得做「CNN 先判、幾何只在前兩名接近時介入」的融合；
如果連兩類之間都分不開，那融合也不會有效，就此打住，不必寫融合程式碼。

判準：單一特徵的 AUC
--------------------
對每一對類別、每一個幾何特徵，算「用這個特徵單獨去分這兩類」的 AUC。

    AUC 0.50  完全沒有分辨力（等於擲硬幣）
    AUC 0.70  勉強有訊號
    AUC 0.80+ 這個特徵確實分得開這兩類

用 AUC 而不是準確率，是因為它不需要挑門檻——門檻要在訓練集裡選，這裡只是要看
「訊號在不在」。訊號不在的話，門檻怎麼挑都沒用。

特徵抽取要跑 MediaPipe，結果存進 `data/roi_cache/rule_features.json` 重複使用
（跟 tools/cv_rule_baseline.py 同一份快取）。ROI 快取重建後請加 --refresh。

用法
----
    .venv\\Scripts\\python.exe tools\\face_shape_geometry_probe.py
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mediapipe_ascii  # noqa: F401,E402  必須早於 mediapipe
from Face_analyzer_BASIC import FaceAnalyzer  # noqa: E402
from rule_features import EXTRACT  # noqa: E402

PART = "face_shape"
CACHE_DIR = Path("data/roi_cache")
FEATURE_CACHE = CACHE_DIR / "rule_features.json"

# CNN 目前最常混淆的兩對（2026-08-13 報告）。列在這裡是為了讓輸出直接標出來，
# 其餘配對照樣會算，免得只盯著預期的答案看。
FOCUS_PAIRS = [("心形臉", "鵝蛋臉"), ("圓形臉", "方形臉")]


def auc(values: np.ndarray, is_positive: np.ndarray) -> float:
    """Mann–Whitney U 換算的 AUC，用排名算，不需要挑門檻。

    回傳一律 ≥ 0.5：方向不重要，我們問的是「分不分得開」，
    特徵值大的是哪一類由後續的門檻決定。
    """
    ranks = values.argsort().argsort().astype(float) + 1
    n_pos = int(is_positive.sum())
    n_neg = len(values) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    rank_sum = ranks[is_positive].sum()
    score = (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(max(score, 1 - score))


def load_features(refresh: bool) -> tuple[list[dict], list[str]]:
    index = json.loads((CACHE_DIR / "index.json").read_text(encoding="utf-8"))
    records = [r for r in index["records"] if PART in (r.get("labels") or {})]

    cache: dict[str, dict] = {}
    if FEATURE_CACHE.exists() and not refresh:
        cache = json.loads(FEATURE_CACHE.read_text(encoding="utf-8")).get(PART, {})

    features, labels = [], []
    for i, record in enumerate(records, 1):
        path = record["path"]
        row = cache.get(path)
        if row is None:
            try:
                analyzer = FaceAnalyzer(path, strict_angle=False, require_insight=False)
                row = {k: float(v) for k, v in EXTRACT[PART](analyzer).items()}
            except Exception:
                # 偵測不到臉的樣本直接跳過，不要用 0 填——那會變成一個假的群集，
                # 把 AUC 拉向「看起來分得開」。
                continue
            cache[path] = row
        features.append(row)
        labels.append(record["labels"][PART])
        if i % 100 == 0:
            print(f"  特徵 {i}/{len(records)}", flush=True)

    payload = {}
    if FEATURE_CACHE.exists():
        payload = json.loads(FEATURE_CACHE.read_text(encoding="utf-8"))
    payload[PART] = cache
    FEATURE_CACHE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return features, labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="不吃快取，重新抽特徵")
    parser.add_argument("--top", type=int, default=3, help="每一對列出前幾名特徵")
    args = parser.parse_args()

    features, labels = load_features(args.refresh)
    if not features:
        raise SystemExit("沒有抽到任何特徵")

    names = sorted(features[0])
    matrix = np.array([[row[name] for name in names] for row in features])
    labels = np.array(labels)
    classes = sorted(set(labels.tolist()))
    print(f"\n樣本 {len(labels)}、特徵 {len(names)}、類別 {classes}")
    for cls in classes:
        print(f"  {cls}: {(labels == cls).sum()}")

    print("\n每一對類別，單一幾何特徵的最佳 AUC")
    print("（0.50 = 沒有分辨力，0.70 = 有訊號，0.80+ = 分得開）\n")
    rows = []
    for first, second in combinations(classes, 2):
        mask = (labels == first) | (labels == second)
        positive = labels[mask] == first
        scores = [(auc(matrix[mask][:, i], positive), names[i]) for i in range(len(names))]
        scores.sort(reverse=True)
        rows.append(((first, second), scores))

    rows.sort(key=lambda item: item[1][0][0])
    for (first, second), scores in rows:
        focus = "  ← CNN 混淆的那一對" if (first, second) in FOCUS_PAIRS or (second, first) in FOCUS_PAIRS else ""
        best = "、".join(f"{name} {value:.3f}" for value, name in scores[:args.top])
        print(f"{first} vs {second:<5}  最佳 AUC {scores[0][0]:.3f}   {best}{focus}")

    print("\n判讀：最佳 AUC 低於 0.70 的那幾對，幾何連當裁判都不夠格——"
          "對那幾對做融合不會有效果。")


if __name__ == "__main__":
    main()
