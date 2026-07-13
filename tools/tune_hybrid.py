"""決定 hybrid 的信心門檻：CNN 信心多高時才採用它的答案，否則退回規則式。

hybrid 的邏輯（規格書 13.2）：

    CNN 信心 >= 門檻  ->  用 CNN 的答案
    CNN 信心 <  門檻  ->  用（已校準的）規則式的答案

門檻設太低 = 幾乎都聽 CNN 的（CNN 不確定時也硬要用，會出錯）
門檻設太高 = 幾乎都聽規則式的（浪費了 CNN 準的那些）

鐵則：**門檻只能用 train set 挑，再拿 val set 驗證。**
拿 val 挑門檻等於偷看考題 —— 本專案已經犯過一次（用 val 選決策樹深度，分數虛高 0.018），
不要再犯第二次。

輸出：每個部位的建議門檻，以及 hybrid / 純 CNN / 純規則式 三者在 val 上的對照。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ROI_SHADOW_ENABLED", "0")

import onnxruntime as ort  # noqa: E402

from Face_analyzer_BASIC import FaceAnalyzer  # noqa: E402
from face_roi import PARTS, roi_to_tensor  # noqa: E402
from train_basic_cnn_roi import OUT_DIR, build_part_data, load_cache, split_by_identity  # noqa: E402

PART_TO_RULE = {
    "face_shape": "get_face_shape",
    "brow_shape": "get_eyebrow_shape",
    "eye_shape": "get_eye_shape",
    "nose_shape": "get_nose_shape",
    "lip_shape": "get_lip_shape",
}


def macro_accuracy(truth, pred, n):
    cm = np.zeros((n, n), dtype=int)
    for t, p in zip(truth, pred):
        cm[t][p] += 1
    rec = [cm[i][i] / cm[i].sum() for i in range(n) if cm[i].sum()]
    return float(np.mean(rec)) if rec else 0.0


def main():
    all_rois, records = load_cache()
    results = {}

    print("=" * 74)
    print("Hybrid 信心門檻校準（門檻用 train set 挑，val set 只用來驗證）")
    print("=" * 74)

    for part in PARTS:
        rois, labels, identities, classes = build_part_data(part, all_rois, records)
        rows = [i for i, r in enumerate(records) if part in r["labels"]]
        train_idx, val_idx = split_by_identity(labels, identities, 0.25, 42)
        n = len(classes)
        cls_to_idx = {c: i for i, c in enumerate(classes)}

        # CNN 的預測與信心（ROI 快取已是 RGB，跟訓練時一致）
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        session = ort.InferenceSession(str(OUT_DIR / f"{part}.onnx"), opts,
                                       providers=["CPUExecutionProvider"])
        cnn_pred, cnn_conf = {}, {}
        for i in set(train_idx) | set(val_idx):
            # ROI 快取存的是 RGB，roi_to_tensor 期待 BGR 會再轉一次 —— 這裡直接自己正規化
            img = rois[i].astype(np.float32) / 255.0
            from face_roi import IMAGENET_MEAN, IMAGENET_STD
            x = ((img - IMAGENET_MEAN) / IMAGENET_STD).transpose(2, 0, 1)[None].astype(np.float32)
            logits = session.run(None, {"input": x})[0][0]
            e = np.exp(logits - logits.max())
            probs = e / e.sum()
            cnn_pred[i] = int(np.argmax(probs))
            cnn_conf[i] = float(probs.max())

        # 規則式的預測（跑真正的 FaceAnalyzer，也就是線上那份程式碼）
        rule_pred = {}
        for i in set(train_idx) | set(val_idx):
            try:
                a = FaceAnalyzer(records[rows[i]]["path"], strict_angle=False,
                                 require_insight=False)
                label = getattr(a, PART_TO_RULE[part])()
                rule_pred[i] = cls_to_idx.get(label, -1)
            except Exception:
                rule_pred[i] = -1

        def hybrid(idx, thr):
            out = []
            for i in idx:
                if cnn_conf[i] >= thr or rule_pred[i] < 0:
                    out.append(cnn_pred[i])
                else:
                    out.append(rule_pred[i])
            return out

        truth_tr = [int(labels[i]) for i in train_idx]
        truth_va = [int(labels[i]) for i in val_idx]

        # 只用 train set 掃描門檻
        best = (-1.0, None)
        for thr in np.arange(0.0, 1.01, 0.02):
            s = macro_accuracy(truth_tr, hybrid(train_idx, thr), n)
            if s > best[0]:
                best = (s, float(thr))
        _, thr = best

        val_hybrid = macro_accuracy(truth_va, hybrid(val_idx, thr), n)
        val_cnn = macro_accuracy(truth_va, [cnn_pred[i] for i in val_idx], n)
        val_rule = macro_accuracy(
            truth_va, [rule_pred[i] if rule_pred[i] >= 0 else cnn_pred[i] for i in val_idx], n)
        used_cnn = float(np.mean([cnn_conf[i] >= thr for i in val_idx]))

        results[part] = {
            "confidence_threshold": thr,
            "val_hybrid": val_hybrid,
            "val_cnn_only": val_cnn,
            "val_rule_only": val_rule,
            "val_fraction_using_cnn": used_cnn,
            "classes": classes,
        }

        print(f"\n=== {part} ===")
        print(f"  建議信心門檻：{thr:.2f}（val set 有 {used_cnn:.0%} 的樣本會採用 CNN）")
        print(f"  val macro：純規則式 {val_rule:.3f}　純 CNN {val_cnn:.3f}　"
              f"hybrid {val_hybrid:.3f}")
        winner = max(("規則式", val_rule), ("CNN", val_cnn), ("hybrid", val_hybrid),
                     key=lambda kv: kv[1])
        print(f"  -> 最佳：{winner[0]}（{winner[1]:.3f}）")

    out = OUT_DIR / "hybrid_config.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n\n" + "=" * 74)
    print(f"{'部位':12s} {'規則式':>8s} {'CNN':>8s} {'hybrid':>8s} {'門檻':>6s} {'採用CNN比例':>10s}")
    for part, r in results.items():
        print(f"{part:12s} {r['val_rule_only']:8.3f} {r['val_cnn_only']:8.3f} "
              f"{r['val_hybrid']:8.3f} {r['confidence_threshold']:6.2f} "
              f"{r['val_fraction_using_cnn']:10.0%}")
    print(f"\n已寫入 {out}")


if __name__ == "__main__":
    main()
