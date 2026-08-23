"""產生可直接在 Excel 裡校對的 CSV：每列一張圖，點超連結就開圖。

為什麼要這支而不是直接用 predictions.csv：
  1. predictions.csv 沒有「人工答案」欄，改在原欄位上會蓋掉模型預測，
     蓋掉之後就再也算不出一致率——那個數字才是校對的目的。
  2. 檔名（0.png）看不出圖在哪。這裡加一欄 Excel HYPERLINK，點了直接開圖，
     不必自己在資料夾裡翻。

用法：
    python tools/make_review_csv.py                      # 200 張抽樣（建議先做這份）
    python tools/make_review_csv.py --full               # 全量 10000 張
    python tools/make_review_csv.py --parts nose_shape   # 只挑要校對的部位，欄位更少

填法：只填「人工_<部位>」欄。跟模型一樣就留空（留空 = 同意模型），
不同意才填正確類別。填完跑 tools/score_review.py --csv <檔案>。
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

PARTS = ["face_shape", "brow_shape", "eye_shape", "nose_shape", "lip_shape"]
ZH = {"face_shape": "臉型", "brow_shape": "眉型", "eye_shape": "眼型",
      "nose_shape": "鼻型", "lip_shape": "唇型"}

ap = argparse.ArgumentParser()
ap.add_argument("--full", action="store_true", help="用全量 10000 張而不是 200 張抽樣")
ap.add_argument("--parts", nargs="*", default=PARTS, help="只輸出這些部位的欄位")
ap.add_argument("--out", default="")
args = ap.parse_args()

if args.full:
    src_csv = Path("data/basic_full/_kaggle_pending_review_20260818/predictions.csv")
    img_dir = Path("data/kaggle_asian_faces/generated_yellow-stylegan2").resolve()
    default_out = "data/basic_full/_kaggle_pending_review_20260818/校對表_全量.csv"
    pred_suffix = "_pred"
    conf_suffix = "_conf"
    top2_suffix = "_top2"
else:
    src_csv = Path("data/basic_full/_sample_for_review_20260818/review.csv")
    img_dir = Path("data/basic_full/_sample_for_review_20260818/images").resolve()
    default_out = "data/basic_full/_sample_for_review_20260818/校對表.csv"
    pred_suffix = "_模型預測"
    conf_suffix = "_信心"
    top2_suffix = "_第二預測"

out = Path(args.out or default_out)
rows = list(csv.DictReader(open(src_csv, encoding="utf-8-sig")))
parts = [p for p in args.parts if p in PARTS]
print(f"來源：{src_csv}（{len(rows)} 列）")
print(f"部位：{'、'.join(ZH[p] for p in parts)}")

cols = ["檔名", "看圖"]
for p in parts:
    cols += [f"模型_{ZH[p]}", f"信心_{ZH[p]}", f"次選_{ZH[p]}", f"人工_{ZH[p]}"]

with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(cols)
    for r in rows:
        fname = r["file"]
        # Excel 的 HYPERLINK：點一下用預設看圖程式開啟本機檔案
        link = f'=HYPERLINK("{(img_dir / fname).as_posix()}","看圖")'
        row = [fname, link]
        for p in parts:
            row += [r.get(f"{p}{pred_suffix}", ""), r.get(f"{p}{conf_suffix}", ""),
                    r.get(f"{p}{top2_suffix}", ""), ""]
        w.writerow(row)

print(f"\n已產生：{out}")
print("填法：只填『人工_XX』欄。同意模型就留空，不同意才填正確類別。")
print(f"評分：python tools/score_review.py --csv \"{out}\"")
