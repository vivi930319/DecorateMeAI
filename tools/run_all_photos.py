"""把資料集裡所有照片跑過現行模型，逐部位報準確率，並拆 train(看過) / holdout(沒看過)。

用法：
    .venv\\Scripts\\python.exe tools\\run_all_photos.py --cache data/roi_cache_gcs
"""
import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict, Counter

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import onnxruntime as ort  # noqa: E402
from face_roi import roi_to_tensor  # noqa: E402

PARTS = ["face_shape", "brow_shape", "eye_shape", "nose_shape", "lip_shape"]
ZH = {"face_shape": "臉型", "brow_shape": "眉型", "eye_shape": "眼型",
      "nose_shape": "鼻型", "lip_shape": "嘴型"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="data/roi_cache_gcs")
    ap.add_argument("--model-dir", default="models/basic_features_roi")
    ap.add_argument("--split", default="v1")
    args = ap.parse_args()

    cache = ROOT / args.cache
    model_dir = ROOT / args.model_dir
    records = json.loads((cache / "index.json").read_text(encoding="utf-8"))["records"]
    print(f"載入 ROI 快取…（{len(records)} 張）", flush=True)
    rois = np.load(cache / "rois.npz", allow_pickle=True)

    split = json.loads((cache / f"holdout_split_{args.split}.json").read_text(encoding="utf-8"))
    name_split = {Path(s["relpath"]).name: s["split"] for s in split["samples"]}
    grp_of = [name_split.get(Path(r["path"]).name, "unknown") for r in records]

    hit = defaultdict(lambda: defaultdict(int))
    tot = defaultdict(lambda: defaultdict(int))
    conf = defaultdict(Counter)

    for p in PARTS:
        sess = ort.InferenceSession(str(model_dir / f"{p}.onnx"), providers=["CPUExecutionProvider"])
        inp = sess.get_inputs()[0].name
        meta = json.loads((model_dir / f"{p}_classes.json").read_text(encoding="utf-8"))
        classes = meta["classes"] if isinstance(meta, dict) else meta
        idx = [k for k, r in enumerate(records) if p in r["labels"]]
        arr = rois[p]
        batch = np.concatenate([roi_to_tensor(arr[k]) for k in idx], axis=0)
        preds = []
        for s in range(0, len(batch), 256):
            logits = sess.run(None, {inp: batch[s:s + 256]})[0]
            preds.extend(classes[j] for j in np.argmax(logits, axis=1))
        for k, pred in zip(idx, preds):
            truth = records[k]["labels"][p]
            g = grp_of[k]
            ok = pred == truth
            for gg in (g, "all"):
                tot[p][gg] += 1
                hit[p][gg] += ok
            if g == "holdout":
                conf[p][(truth, pred)] += 1
        print(f"  {ZH[p]} 完成（{len(idx)} 張）", flush=True)

    def a(p, g):
        return hit[p][g] / tot[p][g] * 100 if tot[p][g] else 0.0

    print(f"\n{'部位':<6}{'全部':>16}{'train(看過)':>19}{'holdout(沒看過)':>22}")
    print("-" * 63)
    for p in PARTS:
        print(f"{ZH[p]:<6}"
              + f"{hit[p]['all']}/{tot[p]['all']}={a(p,'all'):.1f}%".rjust(15)
              + f"{hit[p]['train']}/{tot[p]['train']}={a(p,'train'):.1f}%".rjust(19)
              + f"{hit[p]['holdout']}/{tot[p]['holdout']}={a(p,'holdout'):.1f}%".rjust(21))
    print("-" * 63)
    for g in ("all", "train", "holdout"):
        h = sum(hit[p][g] for p in PARTS)
        t = sum(tot[p][g] for p in PARTS)
        print(f"合計 {g:<8}: {h}/{t} = {h/t*100:.1f}%")

    print("\n===== holdout 主要誤判去向（各部位前 3）=====")
    for p in PARTS:
        errs = sorted(((f"{t}→{pr}", c) for (t, pr), c in conf[p].items() if t != pr),
                      key=lambda x: -x[1])
        if errs:
            print(f"  {ZH[p]}: " + "、".join(f"{k} {c}次" for k, c in errs[:3]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
