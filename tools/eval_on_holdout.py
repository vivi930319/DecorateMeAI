"""在固定保留測試集上評估一組 ONNX 模型，產生可跨版本比較的分數。

這支存在的理由，見 `tools/build_holdout_split.py` 的說明：5-fold 的分數不能跨版本比較，
因為資料一變 folds 就重切。保留集是同一份考卷，所以**不同版本的模型在這裡量出來的
分數可以直接比較**——這是整個流程唯一能回答「新模型比較好嗎」的地方。

前處理直接沿用 `face_roi.roi_to_tensor`，那是訓練與線上推論共用的同一支函式。
自己重寫一份等於在量「另一個模型」，量出來的數字對線上沒有意義。

用法
----
    # 量現行線上模型（models/basic_features_roi）
    .venv\\Scripts\\python.exe tools\\eval_on_holdout.py --label 線上_bundle20260731

    # 量新訓練的候選（放在別的目錄，不要覆蓋線上模型）
    .venv\\Scripts\\python.exe tools\\eval_on_holdout.py --model-dir models\\candidate_20260806 --label 候選_convnext

    # 結果會累積寫進 models/holdout_scores.json，方便並排比較
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import onnxruntime as ort  # noqa: E402
from face_roi import roi_to_tensor  # noqa: E402

CACHE = ROOT / "data" / "roi_cache"
SCORES = ROOT / "models" / "holdout_scores.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description="在固定保留集上評估 ONNX 模型")
    p.add_argument("--split", default="v1", help="保留集版本")
    p.add_argument("--model-dir", default="models/basic_features_roi")
    p.add_argument("--label", required=True, help="這次評估的名稱，會寫進結果檔")
    p.add_argument("--parts", nargs="*", default=None)
    args = p.parse_args()

    split_file = CACHE / f"holdout_split_{args.split}.json"
    if not split_file.exists():
        print(f"找不到 {split_file.name}，請先跑 tools/build_holdout_split.py")
        return 1
    split = json.loads(split_file.read_text(encoding="utf-8"))
    holdout = {s["sha256"]: s for s in split["samples"] if s["split"] == "holdout"}
    print(f"保留集 {args.split}：{len(holdout)} 張")

    rois = np.load(CACHE / "rois.npz", allow_pickle=True)
    records = json.loads((CACHE / "index.json").read_text(encoding="utf-8"))["records"]

    # 保留集認的是 sha256，快取認的是列號，這裡把兩者接起來。
    # 之所以每次重算而不是存進快取：快取會因為任何一次 prepare_roi_cache 而重建，
    # 存進去的對照表會悄悄過期——identity_map 就是這樣壞掉的。
    print("比對 sha256 …")
    row_of = {}
    for i, r in enumerate(records):
        path = Path(r["path"])
        if path.exists():
            digest = sha256_of(path)
            if digest in holdout:
                row_of[digest] = i
    print(f"  對應到快取的保留樣本 {len(row_of)} / {len(holdout)}")
    missing = len(holdout) - len(row_of)
    if missing:
        print(f"  ⚠ 有 {missing} 張在快取裡找不到，請重跑 prepare_roi_cache.py")

    model_dir = ROOT / args.model_dir
    parts = args.parts or ["face_shape", "brow_shape", "eye_shape", "nose_shape", "lip_shape"]
    results = {}

    for part in parts:
        onnx_path = model_dir / f"{part}.onnx"
        classes_path = model_dir / f"{part}_classes.json"
        if not onnx_path.exists() or not classes_path.exists():
            print(f"{part}: 缺模型檔，略過")
            continue
        meta = json.loads(classes_path.read_text(encoding="utf-8"))
        classes = meta["classes"] if isinstance(meta, dict) else meta
        arch = meta.get("architecture", "?") if isinstance(meta, dict) else "?"

        sel = [(d, s) for d, s in holdout.items() if s["part"] == part and d in row_of]
        if not sel:
            print(f"{part}: 保留集裡沒有這個部位的樣本，略過")
            continue

        sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        in_name = sess.get_inputs()[0].name
        arr = rois[part]

        correct = 0
        per_class = {c: [0, 0] for c in classes}  # [命中, 總數]
        unknown = 0
        for digest, s in sel:
            truth = s["label"]
            if truth not in per_class:
                unknown += 1
                continue
            logits = sess.run(None, {in_name: roi_to_tensor(arr[row_of[digest]])})[0][0]
            pred = classes[int(np.argmax(logits))]
            per_class[truth][1] += 1
            if pred == truth:
                per_class[truth][0] += 1
                correct += 1

        recalls = [hit / tot for hit, tot in per_class.values() if tot]
        macro = float(np.mean(recalls)) if recalls else 0.0
        n = sum(t for _, t in per_class.values())
        results[part] = {
            "architecture": arch,
            "n": n,
            "macro_recall": round(macro, 4),
            "accuracy": round(correct / n, 4) if n else 0.0,
            "per_class": {c: {"recall": round(h / t, 4) if t else None, "n": t}
                          for c, (h, t) in per_class.items()},
        }
        if unknown:
            results[part]["skipped_unknown_label"] = unknown

    print(f"\n=== {args.label}（模型目錄 {args.model_dir}）===")
    print(f"{'部位':<12}{'架構':<18}{'n':>5}{'macro':>8}{'acc':>8}")
    print("-" * 52)
    for part, r in results.items():
        print(f"{part:<12}{r['architecture']:<18}{r['n']:>5}{r['macro_recall']:>8.3f}{r['accuracy']:>8.3f}")
    print("\n各類別 recall：")
    for part, r in results.items():
        cells = "、".join(f"{c}={v['recall']:.2f}({v['n']})" if v["recall"] is not None else f"{c}=無樣本"
                         for c, v in r["per_class"].items())
        print(f"  {part:<12}{cells}")

    all_scores = json.loads(SCORES.read_text(encoding="utf-8")) if SCORES.exists() else {}
    all_scores[args.label] = {"split": args.split, "model_dir": args.model_dir, "parts": results}
    SCORES.write_text(json.dumps(all_scores, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已累積寫入 {SCORES.relative_to(ROOT)}（共 {len(all_scores)} 筆評估）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
