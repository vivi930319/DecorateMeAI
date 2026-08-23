"""推薦服務主流程(派工書 §執行流程)。

1. 驗證 analysisPackage。 2. 正規化妝容名稱。 3. 讀關鍵字。 4. 查啟用商品。
5. 計分。 6. 排除停用/重複/缺欄位。 7. 依分類與分數排序,回傳最多 limit 筆。

正式回應以 analysisPackage.recommendations.products 為主。不要求前端傳資料庫或整份字典。
空結果不是 500、也不回假商品(回 RECOMMENDATION_EMPTY + 空陣列)。
"""
from __future__ import annotations

from . import keyword_loader, product_ranker, product_search
from .keyword_loader import CATEGORIES
from .style_alias import UnknownMakeupStyle, normalize_style


class RecommendationError(Exception):
    """帶錯誤碼的推薦錯誤,對應派工書 §錯誤回傳。"""
    def __init__(self, code: str, message: str, http: int):
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


def _validate_package(pkg) -> None:
    if not isinstance(pkg, dict):
        raise RecommendationError("INVALID_ANALYSIS_PACKAGE", "analysisPackage 缺失或格式錯誤", 422)
    if "style" not in pkg:
        raise RecommendationError("INVALID_ANALYSIS_PACKAGE", "analysisPackage 缺少 style", 422)


def recommend(analysis_package: dict, *, limit: int = 12,
              base_url: str = product_search.DEFAULT_GATEWAY,
              keywords_path=None, session=None) -> dict:
    """回傳 {success, analysisPackage:{id, recommendations:{products,style,code?}}}。

    limit 不合法丟 INVALID_REQUEST;未知妝容丟 UNKNOWN_MAKEUP_STYLE;
    商品庫失效丟 PRODUCT_DB_UNAVAILABLE/TIMEOUT(由 product_search 轉上來)。
    """
    if not isinstance(limit, int) or not (1 <= limit <= 100):
        raise RecommendationError("INVALID_REQUEST", "limit 超出範圍(1~100)", 400)

    _validate_package(analysis_package)
    try:
        style_name = normalize_style(analysis_package.get("style"))
    except UnknownMakeupStyle as exc:
        raise RecommendationError("UNKNOWN_MAKEUP_STYLE", str(exc), 422) from exc

    whitelist = keyword_loader.load_keywords(keywords_path)

    # 逐分類查詢 → 計分 → 取前段;再合併依分數排序,最後截到 limit。
    per_category: list[dict] = []
    try:
        for cat in CATEGORIES:
            kws = keyword_loader.keywords_for(whitelist, style_name, cat)
            if not kws:
                continue
            products = product_search.fetch_products(cat, base_url=base_url, session=session)
            per_category += product_ranker.rank(products, kws, limit=limit)
    except product_search.ProductDbError as exc:
        code = "PRODUCT_DB_TIMEOUT" if "逾時" in str(exc) else "PRODUCT_DB_UNAVAILABLE"
        raise RecommendationError(code, str(exc), 504 if code.endswith("TIMEOUT") else 502) from exc

    # 跨分類再去重 + 依 matchScore 排序,截 limit。
    seen, merged = set(), []
    for item in sorted(per_category, key=lambda x: -x["matchScore"]):
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        merged.append(item)
    products = merged[:limit]

    recommendations = {"style": style_name, "products": products}
    if not products:
        recommendations["code"] = "RECOMMENDATION_EMPTY"  # 合法但查無商品,回空陣列不報錯
    return {
        "success": True,
        "analysisPackage": {
            "id": analysis_package.get("id"),
            "recommendations": recommendations,
        },
    }
