"""量出眉/眼/鼻三個部位的規則式判別特徵在真實資料上的分佈，找出閾值錯在哪。

背景：這三個部位的規則式在 val set 上分別把 100% / 96% / 98% 的人判成同一個答案
（彎月眉 / 桃花眼 / 標準鼻），分數等於隨機猜。程式碼註解說閾值是「以 CelebA 分位數校正」，
但本專案的資料是自行拍攝的亞洲人臉，分佈不同，那組閾值搬過來就整組失效。

這支腳本回答兩個問題：
    1. 每個閾值切在資料分佈的哪裡？（是不是切在所有資料之外 -> 該分支是死碼）
    2. 這個特徵本身分得開類別嗎？（如果分不開，調閾值也沒用，得換特徵）

用「分離度」判斷特徵好壞：
    分離度 = 類別間中位數的最大差距 / 類別內的平均標準差
    分離度 < 1 -> 類別內的雜訊比類別間的差距還大，這個特徵沒有鑑別力。
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ROI_SHADOW_ENABLED", "0")

from Face_analyzer_BASIC import FaceAnalyzer  # noqa: E402

# 特徵定義集中在專案根目錄的 rule_features.py：服務端也要用，而 Dockerfile
# 不會 COPY tools/。這裡只做轉出，保持既有 import 路徑可用。
from rule_features import (  # noqa: E402
    _L_BROW, _R_BROW, brow_features, eye_features, face_features,
    lip_features, nose_features,
)


# 每個部位：特徵抽取函式 + 現行閾值。
# 每個閾值寫成 (說明, 比較方向, 門檻值)。比較方向不能省 ——
# 「需 < 0.12」而資料最小值是 0.194，代表這條永遠不成立（死碼）；
# 「需 > 0.16」而資料最小值是 0.194，代表這條永遠成立（恆真）。
# 兩者都是 bug，但意義完全相反，混在一起看會得到錯誤結論。
PARTS = {
    "brow_shape": {
        "extract": brow_features,
        "thresholds": {
            "tail_ratio": [("落尾眉需 tail >", ">", 0.100), ("一字眉需 |tail| <", "<", 0.080)],
            "arch_ratio": [("一字眉需 arch <", "<", 0.115), ("彎月眉需 arch >", ">", 0.155)],
        },
    },
    "eye_shape": {
        "extract": eye_features,
        "thresholds": {
            "ratio_to_face": [("瞇縫眼需 <", "<", 0.12), ("桃花眼需 >", ">", 0.16)],
            "ear": [("細長眼需 <", "<", 0.20), ("丹鳳/細長分界 <=", "<", 0.24),
                    ("杏仁/桃花分界 <=", "<", 0.35), ("圓眼需 >", ">", 0.40)],
            "angle": [("下垂眼需 >", ">", 6.0), ("丹鳳眼需 <", "<", -2.0),
                      ("桃花眼需 <", "<", -1.0)],
        },
    },
    "nose_shape": {
        "extract": nose_features,
        "thresholds": {
            "ratio_width": [("寬鼻需 >=", ">", 0.325), ("窄鼻需 <=", "<", 0.205)],
        },
    },
}


def verdict_for(op: str, thr: float, arr: np.ndarray) -> str:
    """判斷這條閾值在真實資料上是死碼、恆真、還是真的有在切分。"""
    if op == "<":
        hit = float((arr < thr).mean())
        if thr <= arr.min():
            return f"!! 死碼：門檻比資料最小值 {arr.min():.3f} 還低，這條永遠不成立"
        if thr > arr.max():
            return f"!! 恆真：門檻比資料最大值 {arr.max():.3f} 還高，這條永遠成立"
    else:  # ">"
        hit = float((arr > thr).mean())
        if thr >= arr.max():
            return f"!! 死碼：門檻比資料最大值 {arr.max():.3f} 還高，這條永遠不成立"
        if thr < arr.min():
            return f"!! 恆真：門檻比資料最小值 {arr.min():.3f} 還低，這條永遠成立"
    return f"命中 {hit:.0%} 的資料（有在切分）"


def main():
    records = json.loads(Path("data/roi_cache/index.json").read_text(encoding="utf-8"))["records"]

    for part, spec in PARTS.items():
        rows = [r for r in records if part in r["labels"]]
        print(f"\n\n{'='*78}\n### {part}（{len(rows)} 張）\n{'='*78}")

        by_label: dict[str, list[dict[str, float]]] = defaultdict(list)
        for r in rows:
            try:
                a = FaceAnalyzer(r["path"], strict_angle=False, require_insight=False)
                by_label[r["labels"][part]].append(spec["extract"](a))
            except Exception:
                pass

        for feat_name, thresholds in spec["thresholds"].items():
            print(f"\n--- 特徵 {feat_name} ---")
            print(f"{'人工標的真實類別':16s} {'張數':>4s} {'最小':>8s} {'25%':>8s} "
                  f"{'中位':>8s} {'75%':>8s} {'最大':>8s}")

            all_vals, all_labels = [], []
            medians = {}
            stds = []
            for label, feats in sorted(by_label.items()):
                v = np.array([f[feat_name] for f in feats])
                all_vals.extend(v.tolist())
                all_labels.extend([label] * len(v))
                medians[label] = float(np.median(v))
                stds.append(float(np.std(v)))
                print(f"{label:16s} {len(v):4d} {v.min():8.3f} {np.percentile(v,25):8.3f} "
                      f"{np.median(v):8.3f} {np.percentile(v,75):8.3f} {v.max():8.3f}")

            arr = np.array(all_vals)
            print(f"\n  現行閾值 vs 資料的實際範圍（{arr.min():.3f} ~ {arr.max():.3f}）：")
            for desc, op, thr in thresholds:
                print(f"    {desc} {thr:<8} {verdict_for(op, thr, arr)}")

            spread = max(medians.values()) - min(medians.values())
            within = float(np.mean(stds))
            sep = spread / within if within > 1e-9 else 0.0
            flag = "分不開，調閾值也沒用" if sep < 1.0 else "勉強有信號"
            print(f"\n  鑑別力：類別間中位數差距 {spread:.3f} / 類別內標準差 {within:.3f}"
                  f" = 分離度 {sep:.2f}  -> {flag}")


if __name__ == "__main__":
    main()
