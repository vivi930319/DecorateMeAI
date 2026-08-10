"""臉型/眼型 hybrid 對照:純 CNN vs 純幾何 vs 集成,在 holdout 上量。

回答一個問題:把 MediaPipe 幾何結合 CNN,臉型/眼型會不會比純 CNN 好?
- CNN 預測:ONNX 跑 ROI 快取
- 幾何預測:Face_analyzer_BASIC 的 get_*_shape()(線上真正那份)
- 集成:信心 gating(CNN 有信心用 CNN,否則用幾何)、一致才信、理論上界

用法:
    .venv\\Scripts\\python.exe tools\\hybrid_eval.py --cache data/roi_cache_gcs
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("ROI_SHADOW_ENABLED", "0")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import onnxruntime as ort  # noqa: E402
from face_roi import roi_to_tensor  # noqa: E402
from Face_analyzer_BASIC import FaceAnalyzer  # noqa: E402

PARTS = {"face_shape": "get_face_shape", "eye_shape": "get_eye_shape"}
ZH = {"face_shape": "臉型", "eye_shape": "眼型"}


def metrics(truths, preds, classes):
    """回傳 (accuracy, macro_f1)。pred=None 視為答錯。"""
    idx = {c: i for i, c in enumerate(classes)}
    n = len(classes)
    tp = [0] * n; fp = [0] * n; sup = [0] * n
    correct = 0
    for t, p in zip(truths, preds):
        if t not in idx:
            continue
        sup[idx[t]] += 1
        if p == t:
            tp[idx[t]] += 1; correct += 1
        elif p in idx:
            fp[idx[p]] += 1
    f1s = []
    for i in range(n):
        if not sup[i]:
            continue
        rec = tp[i] / sup[i]
        prec = tp[i] / (tp[i] + fp[i]) if (tp[i] + fp[i]) else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if (prec + rec) else 0.0)
    total = sum(sup)
    return (correct / total if total else 0.0), (float(np.mean(f1s)) if f1s else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="data/roi_cache_gcs")
    ap.add_argument("--model-dir", default="models/basic_features_roi")
    args = ap.parse_args()

    cache = ROOT / args.cache
    model_dir = ROOT / args.model_dir
    records = json.loads((cache / "index.json").read_text(encoding="utf-8"))["records"]
    rois = np.load(cache / "rois.npz", allow_pickle=True)
    split = json.loads((cache / "holdout_split_v1.json").read_text(encoding="utf-8"))
    name_split = {Path(s["relpath"]).name: s["split"] for s in split["samples"]}

    geo_cache = {}

    def geo_pred(path, method):
        if path not in geo_cache:
            try:
                geo_cache[path] = FaceAnalyzer(path, strict_angle=False, require_insight=False)
            except Exception:
                geo_cache[path] = None
        an = geo_cache[path]
        if an is None:
            return None
        try:
            return getattr(an, method)()
        except Exception:
            return None

    for part, method in PARTS.items():
        sess = ort.InferenceSession(str(model_dir / f"{part}.onnx"), providers=["CPUExecutionProvider"])
        inp = sess.get_inputs()[0].name
        meta = json.loads((model_dir / f"{part}_classes.json").read_text(encoding="utf-8"))
        classes = meta["classes"] if isinstance(meta, dict) else meta

        idx = [k for k, r in enumerate(records)
               if part in r["labels"] and name_split.get(Path(r["path"]).name) == "holdout"]
        truths = [records[k]["labels"][part] for k in idx]

        # CNN 預測 + 信心
        batch = np.concatenate([roi_to_tensor(rois[part][k]) for k in idx], axis=0)
        logits = sess.run(None, {inp: batch})[0]
        ex = np.exp(logits - logits.max(axis=1, keepdims=True))
        prob = ex / ex.sum(axis=1, keepdims=True)
        cnn_pred = [classes[j] for j in np.argmax(prob, axis=1)]
        cnn_conf = prob.max(axis=1)

        # 幾何預測
        print(f"[{ZH[part]}] 幾何在 {len(idx)} 張 holdout 上跑 MediaPipe…", flush=True)
        geo = [geo_pred(records[k]["path"], method) for k in idx]

        acc_cnn, f1_cnn = metrics(truths, cnn_pred, classes)
        acc_geo, f1_geo = metrics(truths, geo, classes)

        # 一致率 + 一致時準確率
        agree = [i for i in range(len(idx)) if cnn_pred[i] == geo[i] and geo[i] is not None]
        agree_acc = np.mean([cnn_pred[i] == truths[i] for i in agree]) if agree else 0.0
        disagree = [i for i in range(len(idx)) if i not in agree]
        cnn_win = sum(cnn_pred[i] == truths[i] for i in disagree)
        geo_win = sum(geo[i] == truths[i] for i in disagree)

        # 信心 gating:CNN 信心>=t 用 CNN,否則用幾何(幾何無值時退回 CNN)
        best = None
        for t in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
            ens = [cnn_pred[i] if (cnn_conf[i] >= t or geo[i] is None) else geo[i]
                   for i in range(len(idx))]
            a, f = metrics(truths, ens, classes)
            if best is None or f > best[2]:
                best = (t, a, f)

        # 理論上界:兩者只要有一個對就算對
        oracle = np.mean([truths[i] in (cnn_pred[i], geo[i]) for i in range(len(idx))])

        print(f"\n===== {ZH[part]}（holdout {len(idx)} 張，{len(classes)} 類）=====")
        print(f"  純 CNN          acc={acc_cnn:.3f}  macroF1={f1_cnn:.3f}")
        print(f"  純幾何          acc={acc_geo:.3f}  macroF1={f1_geo:.3f}")
        print(f"  一致率          {len(agree)}/{len(idx)}={len(agree)/len(idx)*100:.0f}%，一致時準確率 {agree_acc*100:.0f}%")
        print(f"  不一致 {len(disagree)} 張：CNN 對 {cnn_win}、幾何對 {geo_win}")
        print(f"  信心 gating(最佳 t={best[0]})  acc={best[1]:.3f}  macroF1={best[2]:.3f}  ({'贏' if best[2]>f1_cnn else '沒贏'}過純 CNN)")
        print(f"  理論上界(完美組合)  acc={oracle:.3f}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
