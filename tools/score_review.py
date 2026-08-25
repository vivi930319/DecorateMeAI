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
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

PARTS = [("face_shape", "1_臉型"), ("brow_shape", "2_眉型"), ("eye_shape", "3_眼型"),
         ("nose_shape", "4_鼻型"), ("lip_shape", "5_唇型")]
SPECIAL = {"_不確定", "_排除這張"}
CSV_PARTS = {
    "face_shape": ("臉型", "模型_臉型", "信心_臉型", "次選_臉型", "人工_臉型"),
    "brow_shape": ("眉型", "模型_眉型", "信心_眉型", "次選_眉型", "人工_眉型"),
    "eye_shape": ("眼型", "模型_眼型", "信心_眼型", "次選_眼型", "人工_眼型"),
    "nose_shape": ("鼻型", "模型_鼻型", "信心_鼻型", "次選_鼻型", "人工_鼻型"),
    "lip_shape": ("唇型", "模型_唇型", "信心_唇型", "次選_唇型", "人工_唇型"),
}
VALID_LABELS = {
    "face_shape": {"圓形臉", "心形臉", "方形臉", "長形臉", "鵝蛋臉"},
    "brow_shape": {"一字眉", "彎月眉", "落尾眉", "挑眉"},
    "eye_shape": {"下垂眼", "圓眼", "桃杏眼", "鳳眼"},
    "nose_shape": {"寬鼻", "標準鼻"},
    "lip_shape": {"厚唇", "微笑唇", "花瓣唇", "薄唇"},
}


def score_csv(path: Path, summary_json: Path | None = None) -> None:
    """評分 Excel 匯出的 CSV；空白不是同意，而是尚未校對。"""
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    total_agree = total_reviewed = total_uncertain = 0
    output = {"source": str(path), "rows": len(rows), "parts": {}, "model": "ConvNeXt-Tiny"}
    for part, (zh, pred_col, conf_col, top2_col, human_col) in CSV_PARTS.items():
        reviewed = agree = uncertain = invalid = unreviewed = 0
        flow = Counter()
        confidence = {"correct": [], "wrong": []}
        for row in rows:
            predicted = str(row.get(pred_col) or "").strip()
            human = str(row.get(human_col) or "").strip()
            if not human:
                unreviewed += 1
                continue
            if human in {"不確定", "_不確定"}:
                uncertain += 1
                continue
            if human not in VALID_LABELS[part]:
                invalid += 1
                continue
            reviewed += 1
            ok = predicted == human
            agree += int(ok)
            if not ok:
                flow[(predicted, human)] += 1
            try:
                confidence["correct" if ok else "wrong"].append(float(row.get(conf_col) or ""))
            except (TypeError, ValueError):
                pass

        total_agree += agree
        total_reviewed += reviewed
        total_uncertain += uncertain
        rate = agree / reviewed if reviewed else None
        print(f"\n=== {zh}（{part}）===")
        print(f"  人工已校對 {reviewed}　未校對 {unreviewed}　不確定 {uncertain}")
        if reviewed:
            print(f"  模型一致率 {agree}/{reviewed} = {rate * 100:.1f}%")
            rescued = sum(1 for row in rows
                          if (row.get(human_col) or "").strip()
                          and (row.get(human_col) or "").strip() in VALID_LABELS[part]
                          and (row.get(pred_col) or "").strip() != (row.get(human_col) or "").strip()
                          and (row.get(top2_col) or "").strip() == (row.get(human_col) or "").strip())
            print(f"  第一預測錯但次選猜中的：{rescued} 張")
        if flow:
            print("  錯誤流向（模型說 → 人工說）：")
            for (predicted, human), count in flow.most_common(8):
                print(f"      {predicted} → {human}　{count}")
        output["parts"][part] = {
            "reviewed": reviewed, "unreviewed": unreviewed, "uncertain": uncertain, "invalid": invalid,
            "agree": agree, "accuracy": rate,
            "errorFlow": [{"predicted": p, "human": h, "count": n}
                          for (p, h), n in flow.most_common()],
            "meanConfidenceCorrect": (sum(confidence["correct"]) / len(confidence["correct"])
                                       if confidence["correct"] else None),
            "meanConfidenceWrong": (sum(confidence["wrong"]) / len(confidence["wrong"])
                                     if confidence["wrong"] else None),
        }

    print(f"\n{'=' * 46}")
    if total_reviewed:
        print(f"已校對部位合計一致率 {total_agree}/{total_reviewed} = "
              f"{total_agree / total_reviewed * 100:.1f}%")
    invalid_total = sum(v["invalid"] for v in output["parts"].values())
    print(f"未校對部位 {sum(v['unreviewed'] for v in output['parts'].values())}；"
          f"不確定部位 {total_uncertain}；無效標籤 {invalid_total}（都不可進訓練）")
    if summary_json:
        summary_json.parent.mkdir(parents=True, exist_ok=True)
        summary_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n摘要已寫入：{summary_json}")


def score_drag_review(sample: Path) -> None:
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
            print(f"  [注意] 信心 ≥0.8 卻判錯的：{len(hi)} 張（{len(hi) / total * 100:.0f}%）")

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="data/basic_full/_sample_for_review_20260818")
    ap.add_argument("--csv", default="", help="Excel 校對表 CSV；空白欄位視為未校對，不視為同意")
    ap.add_argument("--summary-json", default="", help="把 CSV 評分摘要另存成 JSON")
    args = ap.parse_args()
    if args.csv:
        score_csv(Path(args.csv), Path(args.summary_json) if args.summary_json else None)
    else:
        score_drag_review(Path(args.sample))


if __name__ == "__main__":
    main()
