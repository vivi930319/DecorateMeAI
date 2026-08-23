"""比對人工校對後的照片位置與模型原本的預測，算出每個部位的一致率。

用法：
    python tools/score_review.py
    python tools/score_review.py --sample data/basic_full/_sample_for_review_20260818

流程是「拖曳式校對」：照片一開始放在模型預測的格子裡，人工把放錯的拖到正確的格子。
所以「照片最後在哪一格」就是人工答案，與 baseline.json 記錄的模型預測比對即可。

刻意不把 _不確定／_排除這張 算進一致率的分母：前者代表人也看不出來，
後者代表這張臉不該進訓練集。把它們算成「模型錯」會低估模型，
算成「模型對」會高估——兩種都是在拿無法判定的樣本充數，所以單獨回報。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

PARTS = [("face_shape", "1_臉型"), ("brow_shape", "2_眉型"), ("eye_shape", "3_眼型"),
         ("nose_shape", "4_鼻型"), ("lip_shape", "5_唇型")]
SPECIAL = {"_不確定", "_排除這張"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="data/basic_full/_sample_for_review_20260818")
    args = ap.parse_args()

    sample = Path(args.sample)
    baseline = json.loads((sample / "baseline.json").read_text(encoding="utf-8"))
    review = sample / "校對"

    grand_agree = grand_total = 0
    for part, folder in PARTS:
        base = review / folder
        if not base.is_dir():
            print(f"{folder}：找不到資料夾，跳過")
            continue

        human: dict[str, str] = {}
        for cls_dir in base.iterdir():
            if not cls_dir.is_dir():
                continue
            for f in cls_dir.iterdir():
                if f.is_file():
                    human[f.name] = cls_dir.name

        pairs = []
        special = Counter()
        for fname, cls in human.items():
            key = f"{part}|{fname}"
            if key not in baseline:
                continue
            if cls in SPECIAL:
                special[cls] += 1
                continue
            pairs.append((baseline[key]["pred"], cls, baseline[key]))

        if not pairs:
            print(f"\n=== {folder} ===  尚未校對（或全部標為不確定／排除）")
            continue

        agree = sum(1 for p, h, _ in pairs if p == h)
        total = len(pairs)
        grand_agree += agree
        grand_total += total

        print(f"\n=== {folder} ===")
        print(f"  一致率 {agree}/{total} = {agree / total * 100:.1f}%"
              + (f"　（另有 {dict(special)} 未計入）" if special else ""))

        # Top-2 補救率：第一預測錯、但第二預測對
        rescued = sum(1 for p, h, m in pairs if p != h and m.get("top2") == h)
        wrong = total - agree
        if wrong:
            print(f"  第一預測錯的 {wrong} 張裡，第二預測猜中 {rescued} 張"
                  f"（{rescued / wrong * 100:.0f}%）")

        # 高信心錯誤——最危險的那種
        hi = [(p, h, m) for p, h, m in pairs
              if p != h and m.get("conf") and float(m["conf"]) >= 0.8]
        if hi:
            print(f"  ⚠ 信心 ≥0.8 卻判錯的：{len(hi)} 張（{len(hi) / total * 100:.0f}%）")

        flow = Counter((p, h) for p, h, _ in pairs if p != h)
        if flow:
            print("  錯誤流向（模型說 → 人工說）：")
            for (p, h), c in flow.most_common(6):
                print(f"      {p} → {h}　{c}")

        per = defaultdict(lambda: [0, 0])
        for p, h, _ in pairs:
            per[h][1] += 1
            if p == h:
                per[h][0] += 1
        print("  各類別 recall（以人工答案為準）：")
        for cls, (ok, n) in sorted(per.items(), key=lambda x: -x[1][1]):
            print(f"      {cls:8s} {ok:3d}/{n:3d} = {ok / n * 100:5.1f}%")

    if grand_total:
        print(f"\n{'=' * 46}")
        print(f"五個部位合計一致率 {grand_agree}/{grand_total} = "
              f"{grand_agree / grand_total * 100:.1f}%")


if __name__ == "__main__":
    main()
