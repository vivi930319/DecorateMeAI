"""Precision@K 與錯誤率評估(派工書 §準確率與反向測試)。

對七種妝容:跑推薦 → 與人工標準答案(recommendation/gold/<styleId>.json)比對,計算:
    Precision@5、Precision@10   命中率
    分類完整率                  白名單三分類都有關鍵字的比例
    重複率                      推薦結果中重複 id 的比例(應為 0)
    停用商品率                  推薦到 status!=active 的比例(應為 0)
    幻覺商品率                  推薦 id 不在商品資料庫的比例(應為 0)

第一階段目標:Precision@5 >= 80%;重複率/停用率/幻覺率 = 0%。

用法:
    python tests/recommendation/evaluate_precision_at_k.py
    # 可選:--base-url、--keywords recommendation/keywords.json
沒有 gold 檔的妝容會 SKIP。gold 與 keywords 由第 3 人交付,見 recommendation/gold/README.md。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from recommendation import recommendation_service, style_alias  # noqa: E402
from recommendation.keyword_loader import assert_complete, load_keywords  # noqa: E402
from recommendation.product_search import DEFAULT_GATEWAY, all_product_ids  # noqa: E402

GOLD_DIR = ROOT / "recommendation" / "gold"


def precision_at_k(recommended_ids, relevant, k):
    if k <= 0:
        return None
    topk = recommended_ids[:k]
    if not topk:
        return 0.0
    hit = sum(1 for i in topk if i in relevant)
    return hit / len(topk)


def load_gold(style_id):
    p = GOLD_DIR / f"{style_id}.json"
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return set(data.get("relevant") or [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=DEFAULT_GATEWAY)
    ap.add_argument("--keywords", default=None)
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    whitelist = load_keywords(args.keywords)
    missing = assert_complete(whitelist)
    total_pairs = len(style_alias.DISPLAY_NAMES) * 3
    category_completeness = 1 - len(missing) / total_pairs
    print(f"分類完整率:{category_completeness*100:.1f}%"
          + (f"(缺:{'、'.join(missing)})" if missing else ""))

    catalog = all_product_ids(args.base_url)
    print(f"商品資料庫 id 數:{len(catalog)}\n")

    rows, p5s, p10s = [], [], []
    dup_total = disabled_total = halluc_total = rec_total = 0

    for style_id, name in style_alias.STYLE_ALIAS.items():
        relevant = load_gold(style_id)
        if relevant is None:
            print(f"  {name}({style_id}):SKIP(無 gold 標準答案)")
            continue
        result = recommendation_service.recommend(
            {"id": f"AN-eval-{style_id}", "style": style_id, "faceAnalysis": {}},
            limit=max(10, args.limit), base_url=args.base_url,
        )
        products = result["analysisPackage"]["recommendations"]["products"]
        ids = [p["id"] for p in products]

        # 錯誤率
        dup = len(ids) - len(set(ids))
        halluc = sum(1 for i in ids if catalog and i not in catalog)
        rec_total += len(ids); dup_total += dup; halluc_total += halluc
        # 停用率:骨架在 search/rank 已濾啟用,理論為 0;仍統計以防資料變動。
        disabled = sum(1 for p in products if str(p.get("status", "active")).lower() != "active")
        disabled_total += disabled

        p5 = precision_at_k(ids, relevant, 5)
        p10 = precision_at_k(ids, relevant, 10)
        p5s.append(p5); p10s.append(p10)
        rows.append((name, len(ids), p5, p10, dup, disabled, halluc))

    print(f"\n{'妝容':<12}{'n':>4}{'P@5':>8}{'P@10':>8}{'重複':>6}{'停用':>6}{'幻覺':>6}")
    print("-" * 52)
    for name, n, p5, p10, dup, dis, hal in rows:
        print(f"{name:<12}{n:>4}{p5*100:>7.0f}%{p10*100:>7.0f}%{dup:>6}{dis:>6}{hal:>6}")

    if p5s:
        mp5 = sum(p5s) / len(p5s) * 100
        mp10 = sum(p10s) / len(p10s) * 100
        print("-" * 52)
        print(f"平均 Precision@5 = {mp5:.1f}%(目標 ≥80%){'  ✅' if mp5 >= 80 else '  ✗'}")
        print(f"平均 Precision@10 = {mp10:.1f}%")
        rate = lambda x: (x / rec_total * 100) if rec_total else 0.0
        print(f"重複率 {rate(dup_total):.1f}%　停用率 {rate(disabled_total):.1f}%　"
              f"幻覺率 {rate(halluc_total):.1f}%(三者目標皆 0%)")
    else:
        print("\n沒有任何 gold 標準答案 → 無法計算 Precision@K。請第 3 人交付 recommendation/gold/<styleId>.json")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
