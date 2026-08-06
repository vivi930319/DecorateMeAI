"""線上信任分數：用真實使用者的修正回饋，量模型在實際使用情境下的表現。

為什麼要有線上這一套（線下已經有保留測試集了）
------------------------------------------------
兩邊量的**不是同一件事**：

| | 線下（holdout_split_v*.json） | 線上（本程式） |
| --- | --- | --- |
| 資料 | 我們蒐集的素材（影劇截圖） | 真實使用者自己拍的照片 |
| 分布 | 專業打光、正面、高畫質 | 手機自拍、各種光線、隨手拍 |
| 標註 | 組內定義的分類 | 使用者本人認為自己是什麼 |
| 回答 | 模型學會這個資料集了嗎 | 模型對真實使用者管用嗎 |

**兩邊的差距本身就是結論。** 線下高線上低，代表訓練素材跟真實使用者的分布不一樣；
兩邊接近，代表蒐集的素材有代表性。任何一邊單獨看都答不出「這個模型可不可信」。

資料哪裡來
----------
使用者在前端按「判斷正確」或修改五官後送出，後端 `face_feedback._record_eval_event`
會往 `face_eval_events` 寫一筆：哪些部位被接受、哪些被改、模型當時說什麼。
文件 id 是 job_id，所以同一次分析重送不會重複計數。

**注意這是自願回饋，不是隨機抽樣。** 願意動手修正的人，多半是覺得結果不對的人，
所以這個分數偏向**低估**。它適合當下限與趨勢，不適合當精確值——報告時要寫明。

用法
----
    # 需要 Firestore 讀取權限
    .venv\\Scripts\\python.exe tools\\online_trust_score.py

    # 存成 JSON 以便跟線下分數並排
    .venv\\Scripts\\python.exe tools\\online_trust_score.py --out models\\online_trust.json
"""
import argparse
import collections
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EVAL_COL = "face_eval_events"
HOLDOUT_SCORES = ROOT / "models" / "holdout_scores.json"

# 中文欄位名 → 部位代碼，讓線上線下能對照。
FIELD_TO_PART = {
    "臉型": "face_shape", "眉型": "brow_shape", "眼型": "eye_shape",
    "鼻型": "nose_shape", "嘴型": "lip_shape",
}



def wilson_interval(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """比例的 Wilson 信賴區間。

    不用常態近似（p ± z·√(p(1-p)/n)）：樣本小或比例接近 0/1 時它會給出超出 [0,1]
    的區間，然後在最需要謹慎的地方過度自信。Wilson 在 n 很小的時候仍然守規矩，
    而觸發重訓的判斷正好都發生在資料還不多的階段。
    """
    if total == 0:
        return 0.0, 1.0
    p = hits / total
    d = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / d
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def class_counts(model_dir: Path) -> dict:
    """每個部位有幾個類別。門檻必須相對於它——同一個數字對不同部位意義完全不同：
    鼻型 2 類的隨機基準就是 0.50，拿 0.50 當門檻等於「比丟銅板還差才算退化」；
    臉型 5 類的隨機基準是 0.20，同一個 0.50 卻是 2.5 倍隨機，模型正常也會一直觸發。
    """
    out = {}
    for path in sorted(model_dir.glob("*_classes.json")):
        if "dinov2" in path.name:
            continue
        part = path.name.replace("_classes.json", "")
        out[part] = len(json.loads(path.read_text(encoding="utf-8"))["classes"])
    return out


def drift_verdict(part, stats, n_classes, offline_score, min_n, keep_ratio):
    """判斷這個部位是不是該重訓。三個條件都要成立才算數。

    1. **樣本夠**：前 4 筆裡有 2 筆修正就是 50%，那什麼都不代表。
    2. **統計上確定**：看信賴區間的**上界**，不是點估計。上界都低於門檻，
       才排除得掉「只是運氣差」。
    3. **相對於自己的水準**：門檻＝隨機基準 +（線下分數 − 隨機基準）× keep_ratio。
       意思是「線上掉到只剩線下水準的六成」，而不是一個對所有部位都一樣的絕對值。
    """
    n, hits = stats["n"], stats["agreed"]
    random_baseline = 1.0 / n_classes
    if offline_score is None:
        return {"part": part, "verdict": "無法判斷", "reason": "沒有線下分數可當基準"}
    threshold = random_baseline + (offline_score - random_baseline) * keep_ratio
    lo, hi = wilson_interval(hits, n)
    if n < min_n:
        return {"part": part, "verdict": "資料不足", "n": n, "threshold": round(threshold, 3),
                "reason": f"只有 {n} 筆，需要 {min_n} 筆才有判斷力"}
    if hi < threshold:
        return {"part": part, "verdict": "建議重訓", "n": n, "trust": stats["trust"],
                "ci": [round(lo, 3), round(hi, 3)], "threshold": round(threshold, 3),
                "reason": f"信賴區間上界 {hi:.3f} 低於門檻 {threshold:.3f}"}
    return {"part": part, "verdict": "正常", "n": n, "trust": stats["trust"],
            "ci": [round(lo, 3), round(hi, 3)], "threshold": round(threshold, 3),
            "reason": f"上界 {hi:.3f} 未低於門檻 {threshold:.3f}"}


def load_events(limit: int):
    from google.cloud import firestore

    client = firestore.Client(project="decorate-me")
    return [d.to_dict() for d in client.collection(EVAL_COL).limit(limit).stream()]


def main():
    p = argparse.ArgumentParser(description="用使用者修正回饋算線上信任分數")
    p.add_argument("--limit", type=int, default=5000)
    p.add_argument("--out", default=None)
    p.add_argument("--offline-label", default="B_合併後_ConvNeXt",
                   help="要拿來對照的線下評估標籤（models/holdout_scores.json 裡的鍵）")
    p.add_argument("--check-drift", action="store_true",
                   help="判斷各部位是否該重訓，並說明理由")
    p.add_argument("--min-n", type=int, default=30,
                   help="判斷前該部位至少要有幾筆回饋")
    p.add_argument("--keep-ratio", type=float, default=0.6,
                   help="門檻＝隨機基準+(線下分數-隨機基準)×本值。0.6 代表掉到線下水準的六成才警告")
    args = p.parse_args()

    try:
        events = load_events(args.limit)
    except Exception as exc:
        print(f"讀不到 {EVAL_COL}：{type(exc).__name__} {str(exc)[:160]}")
        print("需要 Firestore 讀取權限。若在本機遇到 TLS 憑證錯誤，"
              "見《搬機環境地雷_工具鏈與編碼_2026-08-06》§3——防毒軟體攔截 HTTPS 會造成這個症狀。")
        return 2

    if not events:
        print(f"{EVAL_COL} 目前沒有資料。")
        print("使用者要在前端完成一次分析並按下「判斷正確」或修改五官後送出，才會產生一筆。")
        return 1

    agreed = collections.Counter()
    corrected = collections.Counter()
    confusion = collections.defaultdict(collections.Counter)
    for e in events:
        for f in e.get("agreed") or []:
            agreed[f] += 1
        for f in e.get("corrected") or []:
            corrected[f] += 1
            was = (e.get("predicted") or {}).get(f)
            if was:
                confusion[f][was] += 1

    print(f"=== 線上信任分數（{len(events)} 次回饋）===")
    print(f"{'部位':<8}{'接受':>6}{'被改':>6}{'合計':>6}{'信任分數':>10}")
    print("-" * 40)
    online = {}
    for field, part in FIELD_TO_PART.items():
        ok, ng = agreed[field], corrected[field]
        total = ok + ng
        if not total:
            print(f"{field:<8}{'—':>6}{'—':>6}{'—':>6}{'尚無資料':>10}")
            continue
        score = ok / total
        online[part] = {"agreed": ok, "corrected": ng, "n": total, "trust": round(score, 4)}
        print(f"{field:<8}{ok:>6}{ng:>6}{total:>6}{score:>10.3f}")

    print("\n最常被改掉的原始判斷（指出哪兩類分不開）：")
    for field, counter in confusion.items():
        if counter:
            top = "、".join(f"{k}×{v}" for k, v in counter.most_common(3))
            print(f"  {field:<8}{top}")

    # 線下對照
    if HOLDOUT_SCORES.exists():
        offline = json.loads(HOLDOUT_SCORES.read_text(encoding="utf-8")).get(args.offline_label, {})
        parts = offline.get("parts") or {}
        if parts:
            print(f"\n=== 線上 vs 線下（線下＝{args.offline_label}）===")
            print(f"{'部位':<12}{'線上信任':>10}{'線下 macro':>12}{'差距':>8}")
            print("-" * 44)
            for part, o in online.items():
                off = parts.get(part, {}).get("macro_recall")
                if off is None:
                    continue
                print(f"{part:<12}{o['trust']:>10.3f}{off:>12.3f}{o['trust']-off:>+8.3f}")
            print("\n差距的讀法：線上明顯低於線下 → 訓練素材與真實使用者的分布不同；"
                  "兩者接近 → 蒐集的素材有代表性。")

    print("\n⚠ 這是自願回饋，不是隨機抽樣——會修正的人多半是覺得結果不對的人，"
          "所以本分數偏向低估，適合當下限與趨勢。")

    if args.out:
        Path(args.out).write_text(json.dumps(
            {"n_events": len(events), "parts": online, "drift": verdicts},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已寫出 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
