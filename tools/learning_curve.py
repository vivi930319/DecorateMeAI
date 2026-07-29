"""量「再加多少張圖，分數會變多少」——用學習曲線回答，不用猜。

做法：對每個部位，把可用的**身分**（不是圖）抽樣成 20%~100% 五種規模，
每種規模跑 5-fold identity 切分，記下 val macro。
用身分抽樣是因為同一個人有多張照片，抽圖會讓同一張臉同時進 train 與 val，分數虛高。

模型用 DINOv2 embedding + LogisticRegression：embedding 已經有快取，
不必每個規模都重跑一次 CNN 訓練，幾秒就跑得完整條曲線。
它在眼型／眉型／鼻型也是今天量到最好的那個。
"""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import recall_score

from train_basic_cnn_roi import build_part_data, load_cache, split_kfold_by_identity
from face_roi import PARTS

FRACTIONS = (0.2, 0.4, 0.6, 0.8, 1.0)
SEED = 42


def main():
    emb = np.load("data/roi_cache/dinov2_embeddings.npz")["embeddings"]
    records = json.loads(Path("data/roi_cache/index.json").read_text(encoding="utf-8"))["records"]
    all_rois, _rec = load_cache()
    out = {}
    for part in PARTS:
        rows = [i for i, r in enumerate(records) if part in r["labels"]]
        _, labels, identities, classes = build_part_data(part, all_rois, records)
        ids = np.asarray(identities)
        X, y = emb[rows], np.asarray(labels)
        uniq = np.unique(ids)
        rng = np.random.default_rng(SEED)
        print(f"\n=== {part} === 共 {len(rows)} 張 / {len(uniq)} 個身分 / {len(classes)} 類")
        print(f"{'比例':>6}{'張數':>7}{'身分':>7}{'macro':>9}{'±std':>8}")
        curve = []
        for frac in FRACTIONS:
            keep_n = max(len(classes) * 3, int(round(len(uniq) * frac)))
            scores = []
            for rep in range(3 if frac < 1.0 else 1):
                sel = uniq if frac >= 1.0 else rng.choice(uniq, size=min(keep_n, len(uniq)), replace=False)
                m = np.isin(ids, sel)
                if len(np.unique(y[m])) < len(classes):
                    continue
                folds = split_kfold_by_identity(y[m], ids[m], 5, SEED + rep)
                for tr, va in folds:
                    if len(np.unique(y[m][tr])) < 2:
                        continue
                    clf = LogisticRegression(max_iter=2000, C=1.0)
                    clf.fit(X[m][tr], y[m][tr])
                    scores.append(recall_score(y[m][va], clf.predict(X[m][va]), average="macro", zero_division=0))
            if not scores:
                continue
            n_img = int(m.sum())
            print(f"{frac:>6.0%}{n_img:>7}{len(sel):>7}{np.mean(scores):>9.3f}{np.std(scores):>8.3f}")
            curve.append({"fraction": frac, "images": n_img, "identities": int(len(sel)),
                          "macro": float(np.mean(scores)), "std": float(np.std(scores))})
        out[part] = {"classes": classes, "total_images": len(rows), "curve": curve}
    Path("models/basic_features_roi/learning_curve.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n已寫入 models/basic_features_roi/learning_curve.json")


if __name__ == "__main__":
    main()
