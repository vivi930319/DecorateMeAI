"""排出「哪兩個類別該合併」的候選，附證據與預估收益。

用途

這個專案至今所有明確有效的改動都是合併類別：

    窄鼻 → 標準鼻     整個類別塌陷（標註看的不是鼻翼寬度）
    杏仁眼+桃花眼 → 桃杏眼   macro 0.473 → 0.542（DINOv2）
    M型唇 → 花瓣唇           macro 0.492 → 0.560（CNN 40ep/3e-4）

前兩次是人工看混淆矩陣看出來的。人工的問題不是慢，是會漏——
臉型的「圓形臉 ↔ 方形臉」互認率 23%，跟眼型那組一樣高，但因為先看了眼型就沒再往下看。

三項證據

對每一組類別配對算：

1. 雙向互認率 —— 兩類互相認錯的量，佔它們總量的比例。
   要看雙向：單向被吃（A→B 多、B→A 少）通常是「A 的樣本不夠典型」，
   不是界線不存在，合併不一定對。

2. 內容相同卻標成不同類別 —— 同一張照片被放進兩個類別資料夾。
   這是最硬的證據：標註者自己就分不開。

3. 合併後的預估 recall —— 把兩類視為一類重算，看能救回多少。

安全性

它只印出候選與證據。合併是產品決定——刪掉一個類別代表使用者從此
選不到那個選項，那不是模型分數能決定的事。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

SUMMARY = Path("models/basic_features_roi/cv_summary.json")
CONFLICTS = Path("data/roi_cache/label_conflicts.json")


def load_conflicts():
    """part -> {(類別A, 類別B): 幾組}，內容相同卻標成不同類別的統計。"""
    if not CONFLICTS.is_file():
        return {}
    raw = json.loads(CONFLICTS.read_text(encoding="utf-8"))
    out = {}
    for part, items in raw.items():
        table = {}
        for labels in items.values():
            key = tuple(sorted(labels))
            if len(key) == 2:
                table[key] = table.get(key, 0) + 1
        out[part] = table
    return out


def analyse(part, cv, conflicts):
    classes = cv["classes"]
    M = np.array(cv["pooled_confusion_matrix"], dtype=float)
    n = len(classes)
    totals = M.sum(axis=1)
    rows = []
    for i in range(n):
        for j in range(i + 1, n):
            ab, ba = M[i][j], M[j][i]
            pair_total = totals[i] + totals[j]
            if pair_total <= 0:
                continue
            mutual = (ab + ba) / pair_total
            # 對稱度：1.0 代表兩邊互認一樣多，接近 0 代表單向被吃。
            symmetry = min(ab, ba) / max(ab, ba) if max(ab, ba) > 0 else 0.0
            merged_recall = (M[i][i] + ab + ba + M[j][j]) / pair_total
            now = (M[i][i] + M[j][j]) / pair_total
            rows.append({
                "a": classes[i], "b": classes[j],
                "mutual": mutual, "symmetry": symmetry,
                "ab": int(ab), "ba": int(ba),
                "recall_now": now, "recall_merged": merged_recall,
                "gain": merged_recall - now,
                "conflicts": conflicts.get(part, {}).get(tuple(sorted((classes[i], classes[j]))), 0),
                "recall_a": M[i][i] / totals[i] if totals[i] else 0.0,
                "recall_b": M[j][j] / totals[j] if totals[j] else 0.0,
            })
    rows.sort(key=lambda r: -(r["mutual"] + r["conflicts"] * 0.01))
    return classes, rows


def verdict(r, n_classes):
    """把證據翻成一句話的判斷。刻意保守——這是要給人決定的。"""
    if n_classes <= 2:
        return "已經只有兩類，不能再併"
    if r["conflicts"] >= 5:
        return "★ 強烈建議：標註者自己就分不開（有內容相同卻標不同類的樣本）"
    if r["mutual"] >= 0.20 and r["symmetry"] >= 0.55:
        return "★ 建議：互認率高且對稱，像是界線不存在"
    if r["mutual"] >= 0.20:
        return "△ 單向被吃，比較像樣本不夠典型——先查那一類的資料，不要急著合併"
    if r["mutual"] >= 0.12:
        return "· 有混淆但不嚴重"
    return ""


def main():
    ap = argparse.ArgumentParser(description="排出該合併的類別候選")
    ap.add_argument("--summary", default=str(SUMMARY), help="要分析哪一份 cv_summary")
    ap.add_argument("--top", type=int, default=3, help="每個部位列幾組")
    args = ap.parse_args()

    path = Path(args.summary)
    if not path.is_file():
        raise SystemExit(f"找不到 {path}——先跑 train_basic_cnn_roi.py --cv 5")
    data = json.loads(path.read_text(encoding="utf-8"))
    conflicts = load_conflicts()

    print(f"分析來源：{path}")
    print("互認率 = 兩類互相認錯的量 ÷ 兩類總量　　對稱 = 1.0 表示兩邊認錯一樣多\n")

    for part, entry in data.items():
        cv = entry.get("cv") or entry
        if "pooled_confusion_matrix" not in cv:
            continue
        classes, rows = analyse(part, cv, conflicts)
        print(f"{'='*74}")
        print(f"{part}   {len(classes)} 類   macro={cv.get('mean_macro', 0):.3f}")
        weakest = min(range(len(classes)),
                      key=lambda i: rows and 0 or 0) if False else None
        for r in rows[:args.top]:
            v = verdict(r, len(classes))
            print(f"  {r['a']} ↔ {r['b']}")
            print(f"     互認率 {r['mutual']:.1%}（{r['a']}→{r['b']} {r['ab']} 張、"
                  f"{r['b']}→{r['a']} {r['ba']} 張，對稱 {r['symmetry']:.2f}）")
            print(f"     各自 recall {r['recall_a']:.2f} / {r['recall_b']:.2f}"
                  f"　合併後這一類約 {r['recall_merged']:.2f}（+{r['gain']:.2f}）")
            if r["conflicts"]:
                print(f"     內容相同卻標成不同類別：{r['conflicts']} 組")
            if v:
                print(f"     {v}")
        print()


if __name__ == "__main__":
    main()
