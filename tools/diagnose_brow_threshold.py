"""量出眉型規則式的兩個判別比值在真實資料上的分佈，找出閾值錯在哪。

現行規則（Face_analyzer_BASIC.get_eyebrow_shape）：

    if tail_ratio > 0.100:                             -> 落尾眉
    if arch_ratio < 0.115 and abs(tail_ratio) < 0.080: -> 一字眉
    if arch_ratio > 0.155 and abs(tail_ratio) < 0.115: -> 彎月眉
    return "彎月眉"                                     <- fallback 也是彎月眉

實測結果是 51 張 val 圖全部被判成彎月眉，代表前三個條件幾乎從不成立。
本腳本按「人工標好的真實類別」分組，印出 arch_ratio / tail_ratio 的分位數，
用來回答兩個問題：

    1. 現行閾值到底切在分佈的哪裡？（是不是切在所有資料之外）
    2. 這兩個特徵本身分得開三類嗎？（如果分不開，調閾值也沒用，得換特徵）
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 讓 tools/ 底下也能 import 根目錄模組
os.environ.setdefault("ROI_SHADOW_ENABLED", "0")

from Face_analyzer_BASIC import FaceAnalyzer  # noqa: E402

# 跟 get_eyebrow_shape 完全一樣的計算，抽出來單獨量
_L_BROW = (46, 53, 52, 65, 55)
_R_BROW = (276, 283, 282, 295, 285)


def brow_ratios(analyzer: FaceAnalyzer) -> tuple[float, float]:
    def metrics(outer_idx, inner_idx, outline):
        head = analyzer._pt(outer_idx).astype(np.float32)
        tail = analyzer._pt(inner_idx).astype(np.float32)
        width = float(np.linalg.norm(tail - head))
        if width < 1e-6:
            return 0.0, 0.0
        pts = np.array([analyzer._pt(i) for i in outline], dtype=np.float32)
        peak_y = float(np.min(pts[:, 1]))
        base_y = (float(head[1]) + float(tail[1])) / 2.0
        return (base_y - peak_y) / width, (float(head[1]) - float(tail[1])) / width

    la, lt = metrics(46, 55, _L_BROW)
    ra, rt = metrics(276, 285, _R_BROW)
    return (la + ra) / 2.0, (lt + rt) / 2.0


def main():
    records = json.loads(Path("data/roi_cache/index.json").read_text(encoding="utf-8"))["records"]
    rows = [r for r in records if "brow_shape" in r["labels"]]
    print(f"眉型圖片：{len(rows)} 張\n")

    by_label: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for i, r in enumerate(rows, 1):
        try:
            analyzer = FaceAnalyzer(r["path"], strict_angle=False, require_insight=False)
            by_label[r["labels"]["brow_shape"]].append(brow_ratios(analyzer))
        except Exception:
            pass
        if i % 50 == 0:
            print(f"  {i}/{len(rows)}", flush=True)

    print("\n\n========== arch_ratio 分佈（弓起程度）==========")
    print(f"{'真實類別':8s} {'張數':>5s} {'最小':>7s} {'25%':>7s} {'中位':>7s} {'75%':>7s} {'最大':>7s}")
    for label, vals in sorted(by_label.items()):
        a = np.array([v[0] for v in vals])
        print(f"{label:8s} {len(a):5d} {a.min():7.3f} {np.percentile(a,25):7.3f} "
              f"{np.median(a):7.3f} {np.percentile(a,75):7.3f} {a.max():7.3f}")
    print("\n現行閾值：一字眉需 arch < 0.115　彎月眉需 arch > 0.155")

    print("\n\n========== tail_ratio 分佈（眉尾相對眉頭的高低）==========")
    print(f"{'真實類別':8s} {'張數':>5s} {'最小':>7s} {'25%':>7s} {'中位':>7s} {'75%':>7s} {'最大':>7s}")
    for label, vals in sorted(by_label.items()):
        t = np.array([v[1] for v in vals])
        print(f"{label:8s} {len(t):5d} {t.min():7.3f} {np.percentile(t,25):7.3f} "
              f"{np.median(t):7.3f} {np.percentile(t,75):7.3f} {t.max():7.3f}")
    print("\n現行閾值：落尾眉需 tail > 0.100　一字眉需 |tail| < 0.080　彎月眉需 |tail| < 0.115")

    # 每個條件實際命中幾張？
    print("\n\n========== 現行三個條件的命中率 ==========")
    all_vals = [v for vals in by_label.values() for v in vals]
    arch = np.array([v[0] for v in all_vals])
    tail = np.array([v[1] for v in all_vals])
    n = len(all_vals)
    c1 = int((tail > 0.100).sum())
    c2 = int(((arch < 0.115) & (np.abs(tail) < 0.080)).sum())
    c3 = int(((arch > 0.155) & (np.abs(tail) < 0.115)).sum())
    print(f"  條件1 落尾眉 (tail > 0.100)                    命中 {c1:4d}/{n}  ({c1/n:.1%})")
    print(f"  條件2 一字眉 (arch < 0.115 且 |tail| < 0.080)  命中 {c2:4d}/{n}  ({c2/n:.1%})")
    print(f"  條件3 彎月眉 (arch > 0.155 且 |tail| < 0.115)  命中 {c3:4d}/{n}  ({c3/n:.1%})")
    print(f"  以上皆不中 -> fallback「彎月眉」               {n-c1-c2-c3:4d}/{n}  ({(n-c1-c2-c3)/n:.1%})")

    # 這兩個特徵本身分得開嗎？用「單一特徵最佳切分能達到的 macro accuracy」當上限估計
    print("\n\n========== 這兩個特徵分得開三類嗎 ==========")
    labels = [lab for lab, vals in by_label.items() for _ in vals]
    for name, feat in (("arch_ratio", arch), ("tail_ratio", tail)):
        print(f"\n{name}：各類別的中位數")
        meds = {lab: float(np.median([v for v, l in zip(feat, labels) if l == lab]))
                for lab in sorted(by_label)}
        for lab, m in meds.items():
            print(f"    {lab:8s} {m:7.3f}")
        spread = max(meds.values()) - min(meds.values())
        within = np.mean([np.std([v for v, l in zip(feat, labels) if l == lab])
                          for lab in by_label])
        print(f"    類別間中位數差距 {spread:.3f}　類別內標準差 {within:.3f}"
              f"　-> 分離度 {spread/within if within else 0:.2f}")
        print("       （分離度 < 1 表示類別內的雜訊比類別間的差距還大，這個特徵分不開）")


if __name__ == "__main__":
    main()
