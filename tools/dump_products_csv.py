"""把商品服務的全部商品抓成一份 CSV。

用途是離線整理妝容風格辭典：styleTags / finishTags / seasonTags / occasionTags /
featureTags / avoidTags 這幾欄就是辭典要對的東西，而在網頁上一頁一頁看沒辦法比對。

直接打上游而不是經 Gateway： Gateway 那條公開商品路徑會套用它自己的分頁與欄位
裁切，這裡要的是原始資料。上游網址是會變動的 Cloudflare 快速通道，所以做成參數，
預設值取自 Gateway 目前的 PRODUCT_DATABASE_URL。

用法
----
    python tools/dump_products_csv.py
    python tools/dump_products_csv.py --out 商品清單.csv
    python tools/dump_products_csv.py --base-url https://xxx.trycloudflare.com
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "https://wichita-motels-counties-invitations.trycloudflare.com"

# 欄位順序照「整理辭典時的閱讀順序」排，不是照 API 回傳順序：
# 先認出是哪個商品，再看它被標成什麼，最後才是價格與來源。
COLUMNS = [
    "id", "brand", "name", "category", "type",
    "shadeName", "shadeCode", "hex",
    "styleTags", "finishTags", "seasonTags", "occasionTags", "featureTags", "avoidTags",
    "coverage", "undertone", "texture",
    "recommendationReady", "dataQualityScore",
    "price", "currency", "status", "inStock",
    "shadeCount", "lab", "imageUrl", "sourceUrl", "sourceSite", "updatedAt",
]


def _flatten(value) -> str:
    """陣列用 | 串起來，物件轉成緊湊 JSON。

    用 | 不用逗號：這是 CSV，逗號會讓欄位在 Excel 裡看起來像被切開（實際上有引號
    包住不會壞，但人眼分不出那是一個欄位還是多個）。
    """
    if value is None:
        return ""
    if isinstance(value, list):
        if value and isinstance(value[0], (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return " | ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _fetch(url: str, attempts: int = 3):
    """抓一頁。上游走快速通道，斷線是常態，所以重試。

    這是唯讀的 GET，重放沒有副作用——不像寫入那樣需要顧慮重複。
    """
    last = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"抓取失敗（重試 {attempts} 次）：{last}\n網址：{url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--out", default="商品清單.csv")
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()

    rows = []
    cursor = None
    total = None
    while True:
        params = {"limit": str(args.page_size)}
        if cursor:
            params["cursor"] = cursor
        url = f"{args.base_url.rstrip('/')}/api/products?{urllib.parse.urlencode(params)}"
        payload = _fetch(url)
        if total is None:
            total = payload.get("total")
            print(f"上游回報總數：{total}")
        items = payload.get("items") or []
        rows.extend(items)
        cursor = payload.get("nextCursor")
        print(f"  已抓 {len(rows)}{f' / {total}' if total else ''}", flush=True)
        if not cursor or not items:
            break

    # utf-8-sig：Excel 在 Windows 上不看 BOM 就會用 CP950 解讀，中文全變亂碼。
    # 這份檔案的用途就是拿去 Excel 排序篩選，所以 BOM 不能省。
    with open(args.out, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for item in rows:
            writer.writerow([_flatten(item.get(column)) for column in COLUMNS])

    print(f"\n寫出 {len(rows)} 筆 → {args.out}")
    if total is not None and len(rows) != total:
        print(f"⚠️ 與上游回報的 {total} 筆不符，可能中途換頁失敗或資料同時被修改。")

    # 辭典要對的是標籤，所以順便報一下標籤的覆蓋率——空的比例太高的話，
    # 拿這份資料改辭典會像在對一張大部分是空白的表。
    for column in ("styleTags", "finishTags", "seasonTags", "occasionTags"):
        filled = sum(1 for item in rows if item.get(column))
        print(f"  {column:14s} 有值 {filled:5d} / {len(rows)}  ({filled / max(1, len(rows)):.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
