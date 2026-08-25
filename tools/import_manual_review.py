"""把人工校對表的答案匯入訓練資料夾。

為什麼值得做
------------
校對表的答案是**看著照片一張一張決定的**，比使用者在手機上憑印象改的回饋可靠，
也比原始標註新。而且這批照片來自亞洲人臉資料集，跟現有訓練集（影劇截圖）分布不同
——2026-08-25 量到的落差就是證據：鼻型線下 CV 0.90，在這批照片上只有 0.52。
補進不同分布的資料是縮小那個落差最直接的方式。

只收判定過的
------------
「不確定」不收。那代表人也看不出來，把它當標籤等於在訓練集裡放一個沒有答案的問題。
空白也不收——沒看過的照片不該因為表格有那一列就進訓練集。

檔名會加來源前綴
----------------
`kaggle_27.png` 而不是 `27.png`。兩個理由：原始訓練集裡已經有 `27.jpg` 這種檔名，
不加前綴會撞名；而 prepare_roi_cache 的去重是按檔名做的，撞名會讓其中一張被安靜地
丟掉。前綴也讓「這批是後來補的」在資料夾裡看得出來。

用法
----
    python tools/import_manual_review.py \
        --xlsx 亞洲人臉一萬筆人工校對/亞洲人臉200筆_ConvNeXt_人工校對.xlsx --dry-run
    python tools/import_manual_review.py --xlsx ... --write
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 中文欄位名 → 部位資料夾名。表格用「唇型」，而資料夾與模型用「lip_shape」；
# 系統其他地方的中文欄位名是「嘴型」，兩種都收。
FIELD_TO_PART = {
    "臉型": "face_shape", "眉型": "brow_shape", "眼型": "eye_shape",
    "鼻型": "nose_shape", "唇型": "lip_shape", "嘴型": "lip_shape",
}
SKIP_VALUES = {"", "不確定", "排除這張", "None"}

# 分類表：每個部位只收自己那幾類。
#
# 這一關是必要的，不是防禦性程式碼。2026-08-25 的預演就抓到一筆「人工_唇型 = 標準鼻」
# ——表格是逐欄填的，填到隔壁欄很容易。放行的話訓練資料夾會多出一個
# `lip_shape/標準鼻/`，而 prepare_roi_cache 的 CANONICAL_LABELS 會把不在清單裡的
# 類別**整個安靜跳過**（只印一行警告），於是那張照片連同它旁邊正確的標註一起消失。
MODEL_DIR = Path("models/basic_features_roi")


def allowed_labels() -> dict[str, set[str]]:
    """部位 → 合法類別。讀 *_classes.json，跟模型與後端 validate() 用同一份。"""
    table: dict[str, set[str]] = {}
    for part in set(FIELD_TO_PART.values()):
        f = MODEL_DIR / f"{part}_classes.json"
        if f.is_file():
            table[part] = set(json.loads(f.read_text(encoding="utf-8"))["classes"])
    return table


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--images", default=None)
    ap.add_argument("--dest", default="data/basic_full/grouped_gcs_post",
                    help="要匯入的訓練資料夾")
    ap.add_argument("--prefix", default="kaggle_", help="檔名前綴，用來標記來源並避免撞名")
    ap.add_argument("--write", action="store_true", help="實際複製檔案（預設只預演）")
    args = ap.parse_args()

    import openpyxl
    wb = openpyxl.load_workbook(args.xlsx)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    hdr = {h: i for i, h in enumerate(rows[0])}

    img_dir = Path(args.images) if args.images else None
    if img_dir is None:
        for r in rows[1:]:
            m = re.search(r'"([^"]+)"', str(r[hdr.get("看圖", 0)]) or "")
            if m:
                img_dir = Path(m.group(1)).parent
                break
    dest = Path(args.dest)
    print(f"  校對表 {Path(args.xlsx).name}｜照片 {img_dir}\n  匯入到 {dest}")

    fields = [f for f in FIELD_TO_PART if f"人工_{f}" in hdr]
    table = allowed_labels()
    bad: list[tuple[str, str, str]] = []
    plan: list[tuple[Path, Path]] = []
    tally: dict[str, Counter] = defaultdict(Counter)
    skipped = Counter()
    missing = 0

    for r in rows[1:]:
        name = str(r[hdr["檔名"]] or "")
        if not name:
            continue
        src = (img_dir / name) if img_dir else None
        for f in fields:
            val = r[hdr[f"人工_{f}"]]
            val = str(val).strip() if val is not None else ""
            if val in SKIP_VALUES:
                if val == "不確定":
                    skipped["不確定"] += 1
                continue
            if src is None or not src.is_file():
                missing += 1
                continue
            part = FIELD_TO_PART[f]
            if part in table and val not in table[part]:
                # 填到隔壁欄了。列出來讓人去修表格，不要自己猜他想填什麼。
                bad.append((name, f, val))
                continue
            plan.append((src, dest / part / val / f"{args.prefix}{name}"))
            tally[part][val] += 1

    print(f"\n  會匯入 {len(plan)} 張（同一張照片的不同部位各算一次）")
    for part in sorted(tally):
        total = sum(tally[part].values())
        print(f"    {part:12} {total:3} 張  {dict(tally[part])}")
    if skipped:
        print(f"\n  跳過：{dict(skipped)}（人也看不出來的不進訓練集）")
    if missing:
        print(f"  找不到照片：{missing} 筆")
    if bad:
        # 不要用 ⚠ 這類符號：Windows 主控台預設 cp950，印不出來會直接拋
        # UnicodeEncodeError，把整支工具停在最後一行報表上。
        print(f"\n  [注意] 不在該部位分類表裡的答案（很可能填到隔壁欄），已跳過 {len(bad)} 筆：")
        for name, field, val in bad:
            print(f"      {name:14} 人工_{field} = 「{val}」")
        print(f"      請在表格裡修好再跑一次；這裡不猜你想填什麼。")

    exists = [d for _, d in plan if d.exists()]
    if exists:
        print(f"\n  已存在、會被覆蓋：{len(exists)} 個")

    if not args.write:
        print(f"\n  這是預演。加上 --write 才會實際複製。前 3 個目標路徑：")
        for _, d in plan[:3]:
            print(f"    {d}")
        return 0

    done = 0
    for src, d in plan:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, d)
        done += 1
    print(f"\n  完成：複製了 {done} 張")
    print(f"  接著重建快取再重訓：")
    print(f"    ROI_DATASET_ROOT={dest} ROI_CACHE_DIR=data/roi_cache_manual "
          f"python training/prepare_roi_cache.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
