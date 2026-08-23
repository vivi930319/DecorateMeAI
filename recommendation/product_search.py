"""查詢啟用商品。商品 100% 來自資料庫,不硬編碼、不採信 Ollama 虛構名稱。

經 Gateway 的公開商品清單:GET /product-api/api/products。
這一層只負責「取回啟用中的商品」;比對與排序在 product_ranker。
"""
from __future__ import annotations

import requests

DEFAULT_GATEWAY = "https://ai-gateway-258021445391.asia-east1.run.app"
PRODUCTS_PATH = "/product-api/api/products"


class ProductDbError(RuntimeError):
    """商品資料庫失效/逾時。對應 502 PRODUCT_DB_UNAVAILABLE / 504 PRODUCT_DB_TIMEOUT。"""


def fetch_products(category: str | None = None, *, base_url: str = DEFAULT_GATEWAY,
                   limit: int = 200, timeout: float = 15.0,
                   session: requests.Session | None = None) -> list[dict]:
    """取回啟用中的商品(可選分類過濾)。逾時/連線失敗轉成 ProductDbError,不吞掉。"""
    http = session or requests
    params = {"limit": str(limit), "status": "active"}
    if category:
        params["type"] = category
    try:
        res = http.get(f"{base_url}{PRODUCTS_PATH}", params=params, timeout=timeout)
    except requests.Timeout as exc:
        raise ProductDbError(f"商品服務逾時:{exc}") from exc
    except requests.RequestException as exc:
        raise ProductDbError(f"商品服務連線失敗:{exc}") from exc
    if res.status_code >= 500:
        raise ProductDbError(f"商品服務回 {res.status_code}")
    if not res.ok:
        return []
    data = res.json() if res.content else {}
    items = data.get("items") or data.get("products") or []
    # 只留啟用、有 id 與 type 的;停用/缺欄位在這裡先濾一輪(排序前)。
    out = []
    for p in items:
        if not isinstance(p, dict):
            continue
        if str(p.get("status", "active")).lower() != "active":
            continue
        if p.get("id") is None or not p.get("type"):
            continue
        out.append(p)
    return out


def all_product_ids(base_url: str = DEFAULT_GATEWAY, *, session=None) -> set[str]:
    """回傳資料庫裡所有商品 id(含各分類),供『幻覺商品率』判斷:
    推薦結果的 id 不在這個集合裡 = 幻覺(不是真實商品)。"""
    ids: set[str] = set()
    for cat in ("eyeshadows", "blushes", "lipsticks", "foundations",
                "eyeliner_mascara", "eyebrows", "contouring", "highlighters"):
        try:
            for p in fetch_products(cat, base_url=base_url, session=session):
                ids.add(f"{p.get('type')}:{p.get('id')}")
        except ProductDbError:
            continue
    return ids
