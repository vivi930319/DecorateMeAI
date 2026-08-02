"""在「跟 CNN 完全相同的 val set」上評估現行規則式分類器，做為 CNN 的對照 baseline。

本腳本要回答的問題只有一個：
    CNN 到底有沒有贏過現在線上跑的規則式？

沒有這個數字，「CNN macro accuracy 0.45」是好是壞實際上無從判斷 ——
如果規則式在同一批圖上只有 0.30，那 0.45 就是大幅進步；如果規則式有 0.60，那 CNN 就是退步。

公平性的關鍵：val set 必須跟訓練時完全一致。所以這裡直接 import train_basic_cnn_roi 的
build_part_data / split_by_identity，用同一個 seed 與 val_ratio 重算切分，而不是自己再寫一份
（自己重寫一份，只要有一點點不一樣，比較就沒有意義了）。

規則式的預測直接呼叫 Face_analyzer_BASIC.FaceAnalyzer 的 get_*_shape()，
也就是線上真正在跑的那份程式碼，不是複製一份出來。

輸出：
    models/basic_features_roi/rule_baseline.json
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import numpy as np

# 跑 baseline 時不需要 shadow，關掉省時間（也避免 log 混淆）
os.environ.setdefault("ROI_SHADOW_ENABLED", "0")

from Face_analyzer_BASIC import FaceAnalyzer  # noqa: E402
from train_basic_cnn_roi import (  # noqa: E402
    OUT_DIR,
    build_part_data,
    load_cache,
    split_by_identity,
)

# 部位 -> FaceAnalyzer 上對應的規則式方法
PART_TO_RULE = {
    "face_shape": "get_face_shape",
    "brow_shape": "get_eyebrow_shape",
    "eye_shape": "get_eye_shape",
    "nose_shape": "get_nose_shape",
    "lip_shape": "get_lip_shape",
}


def macro_accuracy(confusion: np.ndarray) -> float:
    """各類 recall 的平均。用 macro 而不是 accuracy，少數類才不會被多數類蓋掉。"""
    recalls = [
        confusion[i][i] / confusion[i].sum()
        for i in range(len(confusion))
        if confusion[i].sum()
    ]
    return float(np.mean(recalls)) if recalls else 0.0


def parse_args():
    p = argparse.ArgumentParser(description="評估規則式在 CNN 同一個 val set 上的表現")
    # 這三個預設值必須跟 train_basic_cnn_roi.py 的預設一致，否則切出來的 val set 會不同
    p.add_argument("--val-ratio", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--parts", nargs="*", default=list(PART_TO_RULE))
    return p.parse_args()


def main():
    args = parse_args()
    all_rois, records = load_cache()

    cnn_summary = {}
    summary_path = OUT_DIR / "training_summary.json"
    if summary_path.is_file():
        cnn_summary = json.loads(summary_path.read_text(encoding="utf-8"))

    # 同一張圖可能同時是多個部位的 val 樣本，快取 FaceAnalyzer 避免重複跑 MediaPipe
    rule_cache: dict[str, dict[str, str]] = {}
    failed: list[tuple[str, str]] = []

    def rule_predict(path: str) -> dict[str, str]:
        if path not in rule_cache:
            try:
                analyzer = FaceAnalyzer(path, strict_angle=False, require_insight=False)
                rule_cache[path] = {
                    part: getattr(analyzer, method)()
                    for part, method in PART_TO_RULE.items()
                }
            except Exception as exc:
                failed.append((path, str(exc)))
                rule_cache[path] = {}
        return rule_cache[path]

    results = {}

    for part in args.parts:
        _, labels, identities, classes = build_part_data(part, all_rois, records)
        rows = [i for i, r in enumerate(records) if part in r["labels"]]
        _, val_idx = split_by_identity(labels, identities, args.val_ratio, args.seed)

        class_to_idx = {name: i for i, name in enumerate(classes)}
        n = len(classes)
        confusion = np.zeros((n, n), dtype=np.int64)
        unknown = 0  # 規則式吐出資料集裡沒有的標籤

        print(f"\n===== {part} =====（val {len(val_idx)} 張）", flush=True)
        for count, i in enumerate(val_idx, 1):
            record = records[rows[i]]
            truth = class_to_idx[record["labels"][part]]
            pred_label = rule_predict(record["path"]).get(part)

            if pred_label in class_to_idx:
                confusion[truth][class_to_idx[pred_label]] += 1
            else:
                unknown += 1
            if count % 25 == 0:
                print(f"  {count}/{len(val_idx)}", flush=True)

        rule_macro = macro_accuracy(confusion)
        rule_acc = float(np.trace(confusion) / confusion.sum()) if confusion.sum() else 0.0
        cnn_macro = (
            cnn_summary.get(part, {}).get("identity", {}).get("best", {}).get("macro_accuracy")
        )

        results[part] = {
            "classes": classes,
            "val_count": len(val_idx),
            "rule_accuracy": rule_acc,
            "rule_macro_accuracy": rule_macro,
            "rule_unknown_label_count": unknown,
            "cnn_macro_accuracy": cnn_macro,
            "cnn_minus_rule": (cnn_macro - rule_macro) if cnn_macro is not None else None,
            "confusion_matrix": confusion.tolist(),
            "per_class_recall": [
                float(confusion[i][i] / confusion[i].sum()) if confusion[i].sum() else None
                for i in range(n)
            ],
            "random_guess": 1.0 / n,
        }

    out_path = OUT_DIR / "rule_baseline.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n\n========== 規則式 vs CNN（同一個 val set，按人切分，macro accuracy）==========")
    print(f"{'部位':12s} {'規則式':>8s} {'CNN':>8s} {'CNN-規則式':>11s} {'隨機猜':>7s}")
    for part, r in results.items():
        cnn = r["cnn_macro_accuracy"]
        diff = r["cnn_minus_rule"]
        cnn_s = f"{cnn:.3f}" if cnn is not None else "-"
        diff_s = f"{diff:+.3f}" if diff is not None else "-"
        print(f"{part:12s} {r['rule_macro_accuracy']:8.3f} {cnn_s:>8s} {diff_s:>11s} "
              f"{r['random_guess']:7.3f}")

    if failed:
        print(f"\n規則式分析失敗 {len(failed)} 張（前 3）：")
        for path, reason in failed[:3]:
            print(f"  - {Path(path).name}: {reason}")
    print(f"\n已寫入 {out_path}")


if __name__ == "__main__":
    main()
