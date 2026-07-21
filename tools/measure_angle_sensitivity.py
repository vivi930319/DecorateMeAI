"""量測五官判斷的準確率隨臉部角度怎麼衰減。

要回答的問題：**正臉門檻該設在幾度？**

`Face_analyzer_BASIC` 現在有三層角度政策（正常／標記可信度低／不輸出），
門檻是 `FACE_YAW_UNCERTAIN` 與 `FACE_YAW_UNRELIABLE`。那兩個數字是 2026-07-22
用這支腳本的前身量出來的，但當時**量錯了對象**——量的是規則式 `get_face_shape()`，
而線上開著 `ROI_MODEL_FIRST=1`，使用者看到的是 CNN 覆蓋後的答案。

所以這支工具預設走 `export_json()`，也就是線上真正輸出的那條路徑。
要跟規則式對照時才加 `--rule-only`。

三個變因要分開跑，不要混在一起看：

  1. 資料集   CelebA（西方臉）vs data/asian_faces（目標族群）
  2. 分類器   ROI_MODEL_FIRST=1（線上）vs =0（規則式）
  3. 五官     臉型／眉型／眼型／鼻型／嘴型，各自的敏感軸可能不同

2026-07-22 用它跑出來的第一組結果（`data/basic_full/grouped/face_shape`，386 張）：

    |yaw|        規則式    CNN（線上）
    0-5°         0.538     0.831
    5-8°         0.389     0.741
    8-12°        0.339     0.769
    12-18°       0.162     0.812
    18-25°       0.031     0.781

**規則式對角度極度敏感，CNN 幾乎不受影響。** 所以角度抑制預設是關的——
按規則式的曲線去抑制，等於把 CNN 八成準確的答案丟掉。

⚠️ 但這組數字**還沒排除訓練集**。這支工具目前對整個資料夾評估，裡面可能包含
CNN 訓練過的影像，準確率與那條平坦度都可能是記憶效應。要當結論用，得先限制在
val split——做法見 `eval_rule_baseline.py`，它 import `train_basic_cnn_roi` 的
`build_part_data` / `split_by_identity` 用同一個 seed 重算切分。這件事還沒做。

已知的另一個缺口：眼型很可能是 **pitch 敏感**的（抬頭低頭直接改變眼睛開合），
但從來沒量過，所以 `FACE_PITCH_LIMIT` 至今沒有依據。用 `--axis pitch --part eye_shape`
就是在補這個洞。

用法
----
    # 線上路徑，臉型，看 yaw
    python tools/measure_angle_sensitivity.py --data data/basic_full/grouped/face_shape

    # 規則式對照
    python tools/measure_angle_sensitivity.py --data ... --rule-only

    # 眼型對 pitch 的敏感度
    python tools/measure_angle_sensitivity.py --data data/basic_full/grouped/eye_shape \
        --part eye_shape --axis pitch

資料夾格式：`<--data>/<標籤>/*.jpg`，資料夾名稱就是正確答案。

⚠️ Windows 注意：路徑含中文時 MediaPipe 的 C++ 載入層會失敗
（`FileNotFoundError: face_landmark_front_cpu.binarypb`）。專案若放在
`OneDrive - 淡江大學` 這種路徑底下，先建一條純 ASCII 的 junction 再從那裡執行：

    mklink /J C:\dev\pp12 "C:\...\PythonProject12"
    C:\dev\pp12\.venv\Scripts\python.exe tools/measure_angle_sensitivity.py ...
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PART_TO_FIELD = {
    "face_shape": "臉型",
    "brow_shape": "眉型",
    "eye_shape": "眼型",
    "nose_shape": "鼻型",
    "lip_shape": "嘴型",
}

# 桶界刻意跨過程式裡現有的三個門檻（8 / 12 / 18），才看得出它們落在曲線哪裡
DEFAULT_BUCKETS = "0,5,8,12,18,25,999"


def parse_buckets(text):
    edges = [float(x) for x in text.split(",")]
    return list(zip(edges[:-1], edges[1:]))


def bucket_label(value, buckets):
    for low, high in buckets:
        if low <= value < high:
            return f"{low:g}-{high:g}"
    return "out-of-range"


def main():
    parser = argparse.ArgumentParser(
        description="Measure how facial-feature accuracy degrades with head angle.")
    parser.add_argument("--data", required=True,
                        help="資料夾，底下每個子資料夾名稱就是標籤")
    parser.add_argument("--part", default="face_shape", choices=sorted(PART_TO_FIELD),
                        help="要評估哪個五官（預設 face_shape）")
    parser.add_argument("--axis", default="yaw", choices=["yaw", "pitch"],
                        help="按哪個角度分桶（預設 yaw）")
    parser.add_argument("--rule-only", action="store_true",
                        help="只跑規則式，不讓 CNN 覆蓋。用來跟線上路徑對照")
    parser.add_argument("--buckets", default=DEFAULT_BUCKETS,
                        help=f"分桶邊界，逗號分隔（預設 {DEFAULT_BUCKETS}）")
    parser.add_argument("--limit", type=int, default=0,
                        help="只跑前 N 張，0 表示全部（除錯用）")
    parser.add_argument("--output", default="models/basic_features_roi/angle_sensitivity.json")
    parser.add_argument("--csv", default="",
                        help="另外輸出每張圖的明細，方便自己交叉分析")
    args = parser.parse_args()

    # 必須在 import 之前設定：兩個模組都在 import 時就讀環境變數決定行為
    if args.rule_only:
        os.environ["ROI_MODEL_FIRST"] = "0"
        os.environ["ROI_DINOV2_MODEL_FIRST"] = "0"

    # 把角度抑制關掉，否則這支工具會量到自己。
    #
    # FaceAnalyzer 在 |yaw| 超過 FACE_YAW_UNRELIABLE 時把臉型換成「無法判斷」，
    # 那個字串永遠不等於任何標籤，於是超標的每一桶都會是 0.000——看起來像分類器
    # 在該角度徹底崩潰，其實只是抑制生效了。第一次跑就踩到這個。
    #
    # 這裡要量的是**底層分類器的真實衰減**，用來決定門檻該設在哪；
    # 門檻本身必須在量測時不存在。
    os.environ["FACE_YAW_UNRELIABLE"] = "9999"
    os.environ["FACE_YAW_UNCERTAIN"] = "9999"

    import Face_analyzer_BASIC as fab

    field = PART_TO_FIELD[args.part]
    buckets = parse_buckets(args.buckets)

    root = Path(args.data)
    if not root.is_dir():
        parser.error(f"找不到資料夾：{root}")

    images = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        for pattern in ("*.jpg", "*.jpeg", "*.png"):
            images.extend((path, folder.name) for path in sorted(folder.glob(pattern)))
    if args.limit:
        images = images[: args.limit]
    if not images:
        parser.error(f"{root} 底下沒有影像")

    print(f"路徑：{'規則式（--rule-only）' if args.rule_only else 'export_json（線上路徑）'}")
    print(f"評估：{field}　分桶依據：|{args.axis}|　共 {len(images)} 張\n", flush=True)

    stats = defaultdict(lambda: {"n": 0, "hit": 0})
    failures = defaultdict(int)
    rows = []

    for index, (path, truth) in enumerate(images, 1):
        try:
            raw = path.read_bytes()
            pose = fab._detect_pose(raw)
            # strict_angle=False：要的就是「如果不擋，會判成什麼」——被擋掉的那些
            # 正是我們想知道品質如何的樣本。
            # require_insight=False：pose 上面算過了，不必再跑一次 InsightFace。
            analyzer = fab.FaceAnalyzer(raw, strict_angle=False, require_insight=False)
            analyzer.pose_yaw, analyzer.pose_pitch = pose["yaw"], pose["pitch"]
            predicted = analyzer.export_json()[field]
        except Exception as exc:
            failures[type(exc).__name__] += 1
            continue

        angle = abs(float(pose[args.axis]))
        label = bucket_label(angle, buckets)
        hit = int(predicted == truth)
        stats[label]["n"] += 1
        stats[label]["hit"] += hit
        rows.append({
            "image": str(path), "truth": truth, "predicted": predicted,
            "yaw": pose["yaw"], "pitch": pose["pitch"], "bucket": label, "correct": hit,
        })

        if index % 100 == 0:
            print(f"  {index}/{len(images)}", flush=True)

    total = sum(row["n"] for row in stats.values())
    overall = sum(row["hit"] for row in stats.values()) / total if total else 0.0
    classes = len({row["truth"] for row in rows})
    chance = 1.0 / classes if classes else 0.0

    print(f"\n=== {field}　準確率 vs |{args.axis}| ===")
    print(f"{'區間':>12}  {'張數':>5}  {'準確率':>7}   vs 隨機")
    for low, high in buckets:
        label = f"{low:g}-{high:g}"
        row = stats.get(label)
        if not row or not row["n"]:
            continue
        accuracy = row["hit"] / row["n"]
        # 低於隨機猜測的區間要一眼看得出來——那代表在那個角度給答案等於誤導
        flag = "  ← 低於隨機" if accuracy < chance else ""
        print(f"{label + '°':>12}  {row['n']:>5}  {accuracy:>7.3f}{flag}")
    print(f"\n整體 {overall:.3f}　{classes} 類，隨機基準 {chance:.3f}")
    if failures:
        print(f"失敗：{dict(failures)}")

    summary = {
        "part": args.part, "field": field, "axis": args.axis,
        "path": "rule_only" if args.rule_only else "export_json",
        "data": str(root), "classes": classes, "chance": round(chance, 4),
        "overall_accuracy": round(overall, 4),
        "buckets": {
            label: {"n": row["n"], "accuracy": round(row["hit"] / row["n"], 4)}
            for label, row in sorted(stats.items()) if row["n"]
        },
        "failures": dict(failures),
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n摘要 -> {out}")

    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"明細 -> {csv_path}")


if __name__ == "__main__":
    main()
