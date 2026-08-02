"""臉型階層式分類：先把長形臉拉出來，再分其餘，最後用曲線分圓 vs 方。

分層分類的原因

扁平的五分類讓每個特徵為每個決策競爭。但這五類的判斷依據不同：

    長形臉    看縱向比例（height_width、三庭）——實測 recall 0.573~0.602，五類最高
    心形臉    看上寬下窄（forehead_to_jaw）
    圓 vs 方  看下頜線的彎直（jaw_slope、gonial_angle）——互認率 23%、對稱 0.89

決策樹在扁平設定下必須用同一組分割去同時處理這三種問題，
結果是每個分割都在妥協。實測也是這樣：加了下顎曲率、三庭、下頜線角度之後，
總平均幾乎不動，但逐類 recall 此消彼長（圓形臉 +0.077 卻讓鵝蛋臉 -0.079）。

階層式讓每一層只用該層需要的特徵，彼此不互相干擾。

三層

    L1  長形臉 vs 其餘     縱向特徵
    L2  心形臉 vs 其餘     上寬下窄
    L3  鵝蛋臉 vs 其餘     全項中庸
    L4  圓形臉 vs 方形臉   下頜線曲線（二分類）

誠實標記

每一層都用同一組 5-fold identity 切分，跟扁平版可直接比較。
階層式的風險是錯誤會往下傳遞——L1 判錯的樣本，後面幾層再準也救不回來。

該看的指標是 precision，不是 accuracy（2026-07-30 修正）

第一版每層只印 accuracy。在 1-vs-rest 且類別比約 1:4 的情況下，
accuracy 會被多數類撐高，看不出誤抓——而誤抓正是階層式唯一致命的錯誤：
被前面的層抓走的樣本會被鎖死，後面再準也救不回來。

改印 precision 之後才看到真正的問題：

    長形臉層  precision 0.515   誤吃 心形臉 38、鵝蛋臉 28
    心形臉層  precision 0.257   誤吃 鵝蛋臉 42、圓形臉 34
    鵝蛋臉層  precision 0.300

鵝蛋臉 recall 只有 0.171，不是因為第三層分不出來，
是因為它 105 個樣本裡有 70 個在輪到它之前就被前兩層吃掉了。

病因是 `class_weight="balanced"`：它讓每一層都搶著開火。
一般分類任務要它，階層式正好相反——早期層要高 precision，不確定就放行。
拿掉之後 macro 0.398 → 0.435，鵝蛋臉 recall 0.171 → 0.438。

（也試過 predict_proba 加高門檻。用巢狀切分在訓練折內選門檻，五折全部選到 0.5，
也就是門檻沒有額外幫助——真正的問題就是 class_weight。）

結論：修好了，但仍然不該上線

    階層式（修正後）  0.437 ± 0.032
    扁平決策樹        0.462
    CNN 40ep/6e-4     0.522   ← 目前臉型的正式答案來源

「每層只用該層需要的特徵」這個假設是合理的，
但省下來的好處補不回錯誤往下傳遞的代價。 本程式保留作為對照紀錄。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sklearn.metrics import recall_score  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402

from train_basic_cnn_roi import split_kfold_by_identity  # noqa: E402

FEATURES = Path("data/roi_cache/rule_features.json")
INDEX = Path("data/roi_cache/index.json")

# 每一層用哪些特徵。刻意只給該層需要的——給多了就退回扁平版的問題。
#
# 鵝蛋臉排在第三層，是第一版跑完才調的。第一版把它留到最後跟圓/方一起分，
# recall 從 0.461 崩到 0.176：鵝蛋臉的定義是「哪一項都不極端」，
# 它在下頜線上沒有自己的位置（斜角 35.1°，夾在長形 33.8° 與心形 37.5° 之間），
# 當殘餘類別會被切散。提前處理，讓最後一層只剩真正互斥的圓 vs 方。
LEVELS = [
    ("長形臉", ["height_width", "cheek_to_jaw", "forehead_to_jaw"]),
    ("心形臉", ["forehead_to_jaw", "cheek_to_jaw", "chin_to_jaw", "forehead_norm"]),
    # 鵝蛋臉：給它完整的一組，讓樹自己找「各項都落在中間」的那個區域
    ("鵝蛋臉", ["height_width", "forehead_norm", "cheek_norm", "jaw_norm",
              "forehead_to_jaw", "cheek_to_jaw", "chin_to_jaw",
              "jaw_slope", "gonial_angle"]),
]
# 最後一層只剩圓 vs 方，二分類——這正是下頜線特徵最擅長的
# （圓 28.3° vs 方 31.4°，再加 gonial_angle）。
FINAL_FEATURES = ["jaw_slope", "gonial_angle", "jaw_slope_diff",
                  "jaw_norm", "cheek_to_jaw", "chin_to_jaw"]


def load():
    feats = json.loads(FEATURES.read_text(encoding="utf-8"))["face_shape"]
    records = json.loads(INDEX.read_text(encoding="utf-8"))["records"]
    X, y, ids, paths = [], [], [], []
    for i, rec in enumerate(records):
        lab = rec["labels"].get("face_shape")
        f = feats.get(rec["path"])
        if not lab or not f:
            continue
        X.append(f)
        y.append(lab)
        ids.append(rec.get("identity", i))
        paths.append(rec["path"])
    return X, np.array(y), np.array(ids), paths


def pick(X, names):
    return np.array([[row.get(n, 0.0) for n in names] for row in X], dtype=np.float32)


def main():
    ap = argparse.ArgumentParser(description="臉型階層式分類對照")
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    X, y, ids, _ = load()
    classes = sorted(set(y))
    missing = [n for n in FINAL_FEATURES if n not in X[0]]
    if missing:
        raise SystemExit(f"特徵快取缺少 {missing}——先跑 tools/cv_rule_baseline.py --refresh")

    y_idx = np.array([classes.index(v) for v in y])
    folds = split_kfold_by_identity(y_idx, ids, 5, args.seed)

    fold_macros, level_acc = [], {name: [] for name, _ in LEVELS}
    level_acc["final3"] = []
    pooled_true, pooled_pred = [], []
    # 誤抓統計：階層式唯一致命的錯誤是「抓走不屬於這一層的樣本」，
    # 那些會被鎖死。accuracy 看不出來，要看 precision 與誤吃成分。
    level_hits = {name: {"fired": 0, "correct": 0, "eaten": {}} for name, _ in LEVELS}

    for train_idx, val_idx in folds:
        pred = np.empty(len(val_idx), dtype=object)
        remaining_tr = np.array(train_idx)
        remaining_va = np.array(val_idx)
        va_pos = {int(v): k for k, v in enumerate(val_idx)}

        for name, feat_names in LEVELS:
            if len(remaining_tr) == 0 or len(remaining_va) == 0:
                break
            Xtr = pick([X[i] for i in remaining_tr], feat_names)
            ytr = (y[remaining_tr] == name).astype(int)
            if len(np.unique(ytr)) < 2:
                continue
            clf = DecisionTreeClassifier(max_depth=args.depth, random_state=args.seed)
            clf.fit(Xtr, ytr)
            Xva = pick([X[i] for i in remaining_va], feat_names)
            hit = clf.predict(Xva).astype(bool)
            level_acc[name].append(float(((y[remaining_va] == name) == hit).mean()))
            caught = y[remaining_va[hit]]
            level_hits[name]["fired"] += int(hit.sum())
            level_hits[name]["correct"] += int((caught == name).sum())
            for c in caught[caught != name]:
                level_hits[name]["eaten"][c] = level_hits[name]["eaten"].get(c, 0) + 1
            for v in remaining_va[hit]:
                pred[va_pos[int(v)]] = name
            remaining_va = remaining_va[~hit]
            remaining_tr = remaining_tr[y[remaining_tr] != name]

        # 最後一層：剩下的三類用下頜線曲線分
        if len(remaining_tr) and len(remaining_va):
            Xtr = pick([X[i] for i in remaining_tr], FINAL_FEATURES)
            clf = DecisionTreeClassifier(max_depth=args.depth, random_state=args.seed)
            clf.fit(Xtr, y[remaining_tr])
            out = clf.predict(pick([X[i] for i in remaining_va], FINAL_FEATURES))
            level_acc["final3"].append(float((out == y[remaining_va]).mean()))
            for v, o in zip(remaining_va, out):
                pred[va_pos[int(v)]] = o

        for k, v in enumerate(pred):
            if v is None:
                pred[k] = classes[0]
        fold_macros.append(recall_score(y[val_idx], pred, average="macro", zero_division=0))
        pooled_true.extend(y[val_idx])
        pooled_pred.extend(pred)

    print(f"\n階層式 macro = {np.mean(fold_macros):.4f} ± {np.std(fold_macros):.4f}")
    print(f"  各 fold {[f'{m:.3f}' for m in fold_macros]}")
    print("\n每一層自己的準確率（錯誤會往下傳遞，這兩個要一起看）:")
    for name, accs in level_acc.items():
        if accs:
            label = {"final3": "圓 vs 方（下頜線）"}.get(name, f"{name} vs 其餘")
            print(f"  {label:<22} {np.mean(accs):.3f}")

    print("\n每一層抓到的東西裡有多少是真的（precision——階層式該看這個）:")
    for name, s in level_hits.items():
        if not s["fired"]:
            continue
        prec = s["correct"] / s["fired"]
        eaten = sorted(s["eaten"].items(), key=lambda kv: -kv[1])
        print(f"  {name} 層　觸發 {s['fired']}　真的是 {s['correct']}　"
              f"precision {prec:.3f}（{1 - prec:.0%} 被鎖死）")
        if eaten:
            print(f"      誤吃：{'、'.join(f'{c} {n}' for c, n in eaten)}")

    print("\n逐類 recall:")
    pooled_true, pooled_pred = np.array(pooled_true), np.array(pooled_pred)
    for c in classes:
        m = pooled_true == c
        print(f"  {c:6s} {float((pooled_pred[m] == c).mean()):.3f}  (n={int(m.sum())})")

    print("\n對照（同一組 5-fold）：扁平決策樹 0.462　CNN 40ep/6e-4 0.522（臉型正式答案）")


if __name__ == "__main__":
    main()
