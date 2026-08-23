"""依關鍵字對商品計分並排序。

派工書 §執行流程 step 5:依名稱、description、specs、styleTags 與分類計分。
step 6:排除停用、重複及必要欄位不足商品。step 7:依分類與分數排序,回傳最多 limit 筆。

計分是關鍵字命中的加權和,不同欄位權重不同(名稱最重,tags 次之)。
分數正規化到 0~1 當 matchScore,並帶回 matchedKeywords 供追蹤與反查。
"""
from __future__ import annotations

# 各欄位命中一個關鍵字的權重。名稱命中最能代表相關性。
_FIELD_WEIGHTS = {
    "name": 3.0,
    "styleTags": 2.0,
    "description": 1.5,
    "specs": 1.0,
}
_REQUIRED_FIELDS = ("id", "type", "name")


def _text_of(product: dict, field: str) -> str:
    v = product.get(field)
    if isinstance(v, (list, tuple)):
        return " ".join(str(x) for x in v)
    if isinstance(v, dict):
        return " ".join(str(x) for x in v.values())
    return str(v or "")


def score_product(product: dict, keywords: list[str]) -> tuple[float, list[str]]:
    """回傳 (原始分數, 命中的關鍵字)。名稱/tags/描述/規格各自加權。"""
    matched: list[str] = []
    raw = 0.0
    fields = {f: _text_of(product, f) for f in _FIELD_WEIGHTS}
    for kw in keywords:
        k = str(kw).strip()
        if not k:
            continue
        hit = False
        for field, weight in _FIELD_WEIGHTS.items():
            if k in fields[field]:
                raw += weight
                hit = True
        if hit:
            matched.append(k)
    return raw, matched


def _has_required(product: dict) -> bool:
    return all(product.get(f) not in (None, "") for f in _REQUIRED_FIELDS)


def rank(products: list[dict], keywords: list[str], *, limit: int = 12) -> list[dict]:
    """對一批(同分類)商品計分、去重、排序,回傳最多 limit 筆標準化推薦項。

    去重鍵是 type:id。停用與必要欄位不足在此排除(啟用過濾已在 search 做過一輪,這裡再保險)。
    matchScore 以本批最高原始分正規化到 0~1;完全沒命中的(raw=0)不回傳。
    """
    seen: set[str] = set()
    scored: list[tuple[float, list[str], dict]] = []
    for p in products:
        if not _has_required(p):
            continue
        if str(p.get("status", "active")).lower() != "active":
            continue
        key = f"{p.get('type')}:{p.get('id')}"
        if key in seen:
            continue
        seen.add(key)
        raw, matched = score_product(p, keywords)
        if raw <= 0:
            continue
        scored.append((raw, matched, p))

    if not scored:
        return []
    top = max(s[0] for s in scored)
    scored.sort(key=lambda s: (-s[0], str(s[2].get("id"))))

    out = []
    for raw, matched, p in scored[:limit]:
        out.append({
            "id": f"{p.get('type')}:{p.get('id')}",
            "type": p.get("type"),
            "name": p.get("name"),
            "brand": p.get("brand", ""),
            "price": p.get("price"),
            "currency": p.get("currency", "TWD"),
            "imageUrl": p.get("imageUrl") or p.get("image_url") or "",
            "sourceUrl": p.get("sourceUrl") or p.get("source_url") or "",
            "matchScore": round(raw / top, 4) if top else 0.0,
            "matchedKeywords": matched,
        })
    return out
