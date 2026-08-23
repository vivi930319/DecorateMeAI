"""讀人工校對過的 CSV，把照片分類到最終資料夾，並回報模型的一致率。

「人工_XX」欄留空 = 同意模型預測；填了值 = 以人工為準。
所以校對只需要動不同意的那幾格，其餘留白。

預設 --dry-run：先看會搬多少、搬去哪，確認無誤再加 --apply 實際寫檔。
輸出目錄是新的，不覆蓋原本按模型預測分好的那份——模型的原始判斷要留著，
否則之後就無法回答「模型到底錯在哪」。
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path

PARTS = ["face_shape", "brow_shape", "eye_shape", "nose_shape", "lip_shape"]
ZH = {"face_shape": "臉型", "brow_shape": "眉型", "eye_shape": "眼型",
      "nose_shape": "鼻型", "lip_shape": "唇型"}
SKIP = {"_不確定", "不確定", "排除", "_排除", "x", "X", "-"}

ap = argparse.ArgumentParser()
ap.add_argument("--csv", required=True, help="校對過的 CSV")
ap.add_argument("--images", default="", help="原圖目錄（預設依 CSV 位置推斷）")
ap.add_argument("--out", default="", help="輸出目錄")
ap.add_argument("--apply", action="store_true", help="實際寫檔（預設只試算）")
args = ap.parse_args()

csv_path = Path(args.csv)
rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))

if args.images:
    img_dir = Path(args.images)
elif "_sample_for_review" in str(csv_path):
    img_dir = csv_path.parent / "images"
else:
    img_dir = Path("data/kaggle_asian_faces/generated_yellow-stylegan2")

out_dir = Path(args.out or (csv_path.parent / "已校對"))

print(f"CSV：{csv_path}（{len(rows)} 列）")
print(f"原圖：{img_dir}")
print(f"輸出：{out_dir}" + ("" if args.apply else "　（試算模式，未寫檔）"))
print()

stats = {p: {"同意": 0, "修正": 0, "跳過": 0, "缺欄": 0} for p in PARTS}
flow = defaultdict(Counter)
plan = defaultdict(list)

for r in rows:
    fname = r.get("檔名") or r.get("file")
    if not fname:
        continue
    for p in PARTS:
        model = (r.get(f"模型_{ZH[p]}") or "").strip()
        human = (r.get(f"人工_{ZH[p]}") or "").strip()
        if not model:
            stats[p]["缺欄"] += 1
            continue
        if human in SKIP:
            stats[p]["跳過"] += 1
            continue
        final = human or model
        if human and human != model:
            stats[p]["修正"] += 1
            flow[p][(model, human)] += 1
        else:
            stats[p]["同意"] += 1
        plan[(p, final)].append(fname)

print(f"{'部位':8s}{'同意模型':>9s}{'人工修正':>9s}{'跳過':>7s}{'一致率':>9s}")
total_agree = total_n = 0
for p in PARTS:
    s = stats[p]
    n = s["同意"] + s["修正"]
    if not n:
        continue
    total_agree += s["同意"]
    total_n += n
    print(f"{ZH[p]:8s}{s['同意']:>9d}{s['修正']:>9d}{s['跳過']:>7d}{s['同意'] / n * 100:>8.1f}%")
if total_n:
    print(f"{'合計':8s}{total_agree:>9d}{total_n - total_agree:>9d}{'':>7s}{total_agree / total_n * 100:>8.1f}%")

for p in PARTS:
    if flow[p]:
        print(f"\n{ZH[p]} 的修正流向（模型 → 人工）：")
        for (m, h), c in flow[p].most_common(8):
            print(f"    {m} → {h}　{c}")

print(f"\n將產生 {len(plan)} 個資料夾、{sum(len(v) for v in plan.values())} 個檔案連結：")
for (p, cls), files in sorted(plan.items()):
    print(f"    {p}/{cls}　{len(files)} 張")

if not args.apply:
    print("\n這是試算。確認無誤後加 --apply 實際寫檔。")
    raise SystemExit

if out_dir.exists():
    shutil.rmtree(out_dir)
missing = 0
for (p, cls), files in plan.items():
    dst = out_dir / p / cls
    dst.mkdir(parents=True, exist_ok=True)
    for fname in files:
        src = img_dir / fname
        if not src.exists():
            missing += 1
            continue
        try:
            os.link(src, dst / fname)       # 硬連結：不佔額外空間
        except OSError:
            shutil.copy2(src, dst / fname)

print(f"\n完成：{out_dir}")
if missing:
    print(f"⚠ 有 {missing} 個檔案在原圖目錄找不到，已跳過")
