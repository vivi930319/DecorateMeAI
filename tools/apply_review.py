"""把人工校對過的 CSV 整理成可訓練資料，並回報模型一致率。

重要規則：空白的「人工_XX」代表**尚未校對**，不是同意模型；「不確定」也不進
訓練集。只有人工明確填入合法類別的部位才會建立硬連結／複製到輸出資料夾。
這個預設是刻意保守的，避免把一萬筆尚未看過的模型答案偷偷當成標籤。

預設只試算；加 --apply 才會寫入輸出目錄。輸出是新的，不覆蓋原本按模型預測分好的
資料，讓之後仍能回答「模型到底錯在哪」。
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
CANONICAL = {
    "face_shape": {"圓形臉", "心形臉", "方形臉", "長形臉", "鵝蛋臉"},
    "brow_shape": {"一字眉", "彎月眉", "落尾眉", "挑眉"},
    "eye_shape": {"下垂眼", "圓眼", "桃杏眼", "鳳眼"},
    "nose_shape": {"寬鼻", "標準鼻"},
    "lip_shape": {"厚唇", "微笑唇", "花瓣唇", "薄唇"},
}


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

ap = argparse.ArgumentParser()
ap.add_argument("--csv", required=True, help="校對過的 CSV")
ap.add_argument("--images", default="", help="原圖目錄（預設依 CSV 位置推斷）")
ap.add_argument("--out", default="", help="輸出目錄")
ap.add_argument("--apply", action="store_true", help="實際寫檔（預設只試算）")
ap.add_argument("--include-unreviewed", action="store_true",
                 help="明確允許空白人工欄採用模型答案；不建議用於訓練資料")
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

stats = {p: {"人工確認": 0, "未校對": 0, "不確定": 0, "無效標籤": 0, "缺欄": 0} for p in PARTS}
flow = defaultdict(Counter)
plan = defaultdict(list)
third_party = []

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
            stats[p]["不確定"] += 1
            third_party.append({
                "檔名": fname, "部位": ZH[p], "模型": model,
                "信心": r.get(f"信心_{ZH[p]}", ""), "次選": r.get(f"次選_{ZH[p]}", ""),
                "第一次人工答案": human, "第三方答案": "", "鑑定狀態": "待鑑定",
            })
            continue
        if not human and not args.include_unreviewed:
            stats[p]["未校對"] += 1
            continue
        final = human or model
        if final not in CANONICAL[p]:
            stats[p]["無效標籤"] += 1
            third_party.append({
                "檔名": fname, "部位": ZH[p], "模型": model,
                "信心": r.get(f"信心_{ZH[p]}", ""), "次選": r.get(f"次選_{ZH[p]}", ""),
                "第一次人工答案": final, "第三方答案": "", "鑑定狀態": "資料異常",
            })
            continue
        stats[p]["人工確認"] += 1 if human else 0
        if human and human != model:
            flow[p][(model, human)] += 1
        plan[(p, final)].append(fname)

print(f"{'部位':8s}{'人工確認':>10s}{'未校對':>9s}{'不確定':>9s}{'一致率':>9s}")
total_agree = total_n = 0
for p in PARTS:
    s = stats[p]
    n = s["人工確認"]
    if not n:
        continue
    agree = sum(1 for fname in rows for _ in [0]
                if (fname.get(f"人工_{ZH[p]}") or "").strip()
                and (fname.get(f"人工_{ZH[p]}") or "").strip() not in SKIP
                and (fname.get(f"人工_{ZH[p]}") or "").strip() == (fname.get(f"模型_{ZH[p]}") or "").strip())
    # 只有人工明確確認才納入一致率；模型答案不會因為空白而被計成對。
    total_agree += agree
    total_n += n
    print(f"{ZH[p]:8s}{s['人工確認']:>10d}{s['未校對']:>9d}{s['不確定']:>9d}{agree / n * 100:>8.1f}%")
if total_n:
    print(f"{'合計':8s}{total_agree:>9d}{total_n - total_agree:>9d}{'':>7s}{total_agree / total_n * 100:>8.1f}%")

for p in PARTS:
    if flow[p]:
        print(f"\n{ZH[p]} 的修正流向（模型 → 人工）：")
        for (m, h), c in flow[p].most_common(8):
            print(f"    {m} → {h}　{c}")

print(f"\n將產生 {len(plan)} 個資料夾、{sum(len(v) for v in plan.values())} 個檔案連結（只含人工確認部位）：")
for (p, cls), files in sorted(plan.items()):
    print(f"    {p}/{cls}　{len(files)} 張")

invalid_total = sum(s["無效標籤"] for s in stats.values())
if invalid_total:
    print(f"\nWARNING: {invalid_total} 個人工答案不在 ConvNeXt 類別，已排除並列入第三方鑑定。")

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
    print(f"[注意] 有 {missing} 個檔案在原圖目錄找不到，已跳過")
if third_party:
    third_path = out_dir.parent / "第三方鑑定待處理.csv"
    write_csv(third_path, third_party,
              ["檔名", "部位", "模型", "信心", "次選", "第一次人工答案", "第三方答案", "鑑定狀態"])
    print(f"第三方鑑定清單：{third_path}（{len(third_party)} 筆；未進訓練）")
