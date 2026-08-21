"""
商品推薦演算法 — 基於 analysisPackage 規格（2026-07-13-v2 演算法升級版）

核心邏輯升級：
1. 色彩精準層：skinTone.lab / lipLab (Delta E)
2. 語意風格層：導入 Jaccard 相似度防作弊
3. 特徵匹配層：導入 O(1) 查表的特徵評分矩陣 (Scoring Matrix)
4. 權重分配層：依據 Style 動態調整權重 (Dynamic Weights)
5. 隨機微擾層：加入 Jittering 增加推薦多樣性
"""

import math
from typing import Dict, List, Tuple, Optional, Any
from makeup_keywords import MAKEUP_KEYWORD_WHITELIST, normalize_style

SCHEMA_VERSION = "2026-08-v2"
_FORBIDDEN_INPUT_FIELDS = {"email", "member", "memberemail", "name", "token", "cookie", "authorization", "image", "imagebase64", "photo"}

class AnalysisContractError(ValueError):
    """Raised when a caller sends identity or non-contract analysis data."""

def _minimized_analysis_package(value: dict) -> dict:
    """Accept only recommendation features; ignore unknown model/internal fields."""
    if not isinstance(value, dict):
        raise AnalysisContractError("INVALID_ANALYSIS_PACKAGE")
    normalized_keys = {str(key).replace("_", "").lower() for key in value}
    if normalized_keys & _FORBIDDEN_INPUT_FIELDS:
        raise AnalysisContractError("IDENTITY_DATA_NOT_ALLOWED")
    face = value.get("faceAnalysis") or {}
    if not isinstance(face, dict):
        raise AnalysisContractError("INVALID_FACE_ANALYSIS")
    skin = face.get("skinTone") or {}
    if not isinstance(skin, dict):
        skin = {}
    generated = value.get("generativeText") or {}
    if not isinstance(generated, dict):
        generated = {}
    return {
        "style": str(value.get("style") or "")[:120],
        "faceAnalysis": {
            "faceShape": str(face.get("faceShape") or "")[:40],
            "eyeShape": str(face.get("eyeShape") or "")[:40],
            "lipShape": str(face.get("lipShape") or "")[:40],
            "skinTone": {
                "lab": skin.get("lab"),
                "season": str(skin.get("season") or "unknown")[:40],
                "level": str(skin.get("level") or "")[:80],
                # Missing flag means a legacy package: preserve old behaviour.
                "labReliable": skin.get("labReliable") is not False,
            },
            "lipLab": face.get("lipLab"),
            # Brow/hair colour is intentionally separate from skin tone.  A
            # brow product must never be ranked by proximity to cheek skin.
            "browLab": face.get("browLab"),
            "hairLab": face.get("hairLab"),
            "browTone": str(face.get("browTone") or "")[:40],
        },
        "generativeText": {
            "styleTags": generated.get("styleTags") if isinstance(generated.get("styleTags"), list) else [],
            "preferredColors": generated.get("preferredColors") if isinstance(generated.get("preferredColors"), list) else [],
            "avoidTags": generated.get("avoidTags") if isinstance(generated.get("avoidTags"), list) else [],
        },
    }

# ============================================================
# 1. 風格 Fallback Tags
# ============================================================

STYLE_FALLBACK_TAGS: Dict[str, List[str]] = {
    "港風": ["bold", "dramatic", "smoky", "red", "defined"],
    "韓系亞裔": ["sheer", "dewy", "natural", "soft", "low-saturation"],
    "日常自然妝": ["natural", "light", "soft", "sheer"],
    "千金": ["luxury", "pearl", "champagne", "soft", "shimmer"],
    "Soft Baddie": ["smoky", "bold", "glossy", "defined"],
    "日雜清透": ["sheer", "dewy", "natural", "soft"],
    "病嬌": ["pale", "rosy", "soft", "misty"],
    "男士白開水": ["natural", "minimal", "no-makeup", "matte"],
}

def get_style_tags(analysis_package: dict) -> List[str]:
    generative_text = analysis_package.get("generativeText", {}) or {}
    style_tags = generative_text.get("styleTags")
    if style_tags and isinstance(style_tags, list) and len(style_tags) > 0:
        return [t.lower() for t in style_tags]
    style = normalize_style(analysis_package.get("style")) or (analysis_package.get("style") or "").strip()
    return STYLE_FALLBACK_TAGS.get(style, ["natural", "soft"])

def get_preferred_colors(analysis_package: dict) -> List[str]:
    generative_text = analysis_package.get("generativeText", {}) or {}
    colors = generative_text.get("preferredColors")
    return [c.lower() for c in colors] if colors and isinstance(colors, list) else []

def get_avoid_tags(analysis_package: dict) -> List[str]:
    generative_text = analysis_package.get("generativeText", {}) or {}
    tags = generative_text.get("avoidTags")
    return [t.lower() for t in tags] if tags and isinstance(tags, list) else []

# ============================================================
# 2. 色彩工具 (Delta E 2000 幾何計算)
# ============================================================

def hex_to_rgb(hex_color: str) -> Optional[Tuple[float, float, float]]:
    if not hex_color: return None
    hex_color = str(hex_color).strip().lstrip("#")
    if len(hex_color) == 3: hex_color = "".join(c * 2 for c in hex_color)
    if len(hex_color) != 6: return None
    try: return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    except ValueError: return None

def _pivot_rgb(v: float) -> float:
    v = v / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

def rgb_to_lab(r: float, g: float, b: float) -> Tuple[float, float, float]:
    r, g, b = _pivot_rgb(r), _pivot_rgb(g), _pivot_rgb(b)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) * 100
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) * 100
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) * 100
    def _pivot_xyz(n: float) -> float: return n ** (1/3) if n > 0.008856 else (7.787 * n) + (16 / 116)
    x, y, z = _pivot_xyz(x / 95.047), _pivot_xyz(y / 100.000), _pivot_xyz(z / 108.883)
    return ((116 * y) - 16, 500 * (x - y), 200 * (y - z))

def delta_e(lab1: Optional[Tuple[float, float, float]], lab2: Optional[Tuple[float, float, float]]) -> Optional[float]:
    """Return CIEDE2000 ΔE (not the older CIE76 Euclidean distance)."""
    if not lab1 or not lab2:
        return None
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - math.sqrt((c_bar ** 7) / (c_bar ** 7 + 25.0 ** 7)))
    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)

    def hue(a, b):
        return math.degrees(math.atan2(b, a)) % 360.0 if a or b else 0.0

    h1p, h2p = hue(a1p, b1), hue(a2p, b2)
    delta_lp, delta_cp = l2 - l1, c2p - c1p
    if c1p * c2p == 0:
        delta_hp = 0.0
    else:
        delta_h = h2p - h1p
        if delta_h > 180:
            delta_h -= 360
        elif delta_h < -180:
            delta_h += 360
        delta_hp = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(delta_h / 2.0))

    l_bar, cp_bar = (l1 + l2) / 2.0, (c1p + c2p) / 2.0
    if c1p * c2p == 0:
        hp_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp_bar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360:
        hp_bar = (h1p + h2p + 360) / 2.0
    else:
        hp_bar = (h1p + h2p - 360) / 2.0
    t = (1 - 0.17 * math.cos(math.radians(hp_bar - 30))
         + 0.24 * math.cos(math.radians(2 * hp_bar))
         + 0.32 * math.cos(math.radians(3 * hp_bar + 6))
         - 0.20 * math.cos(math.radians(4 * hp_bar - 63)))
    delta_theta = 30 * math.exp(-((hp_bar - 275) / 25) ** 2)
    rc = 2 * math.sqrt((cp_bar ** 7) / (cp_bar ** 7 + 25.0 ** 7))
    sl = 1 + (0.015 * (l_bar - 50) ** 2) / math.sqrt(20 + (l_bar - 50) ** 2)
    sc = 1 + 0.045 * cp_bar
    sh = 1 + 0.015 * cp_bar * t
    rt = -math.sin(math.radians(2 * delta_theta)) * rc
    return math.sqrt((delta_lp / sl) ** 2 + (delta_cp / sc) ** 2 + (delta_hp / sh) ** 2 + rt * (delta_cp / sc) * (delta_hp / sh))

def _base_fallback_color_score(product: dict, skin_tone: dict) -> float:
    """Use season/level metadata when cheek LAB sampling is marked unreliable."""
    season = str(skin_tone.get("season") or "unknown").casefold()
    level = str(skin_tone.get("level") or "").casefold()
    tokens = " ".join(str(value or "") for value in (
        product.get("undertone"), product.get("shadeName"), product.get("name"),
        " ".join(str(tag) for tag in (product.get("seasonTags") or [])),
    )).casefold()
    season_score = 0.75 if season and season != "unknown" and season in tokens else 0.5
    level_score = 0.25 if level and level in tokens else 0.0
    return min(1.0, season_score + level_score)

def lab_similarity_from_delta_e(de: Optional[float]) -> float:
    if de is None: return 0.5
    if de <= 2.0: return 1.0
    return max(0.0, 1.0 - (de / 20.0))

# ============================================================
# 3. 風格匹配度計算 (升級：Jaccard 相似度演算法)
# ============================================================

def style_tag_similarity(product_tags: List[str], style_tags: List[str],
                         preferred_colors: List[str], avoid_tags: List[str]) -> float:
    """計算商品 tags 與風格 tags 的 Jaccard 匹配度，防標籤作弊"""
    prod_set = set(t.lower() for t in (product_tags or []))
    target_set = set(t.lower() for t in (style_tags + preferred_colors))
    avoid_set = set(t.lower() for t in avoid_tags)

    if not target_set: return 0.5
    if not prod_set: return 0.3  # 沒標籤稍微扣分

    intersection = len(prod_set & target_set)
    union = len(prod_set | target_set)

    # Jaccard 比例 (交集/聯集) + Recall 比例 (命中多少目標)
    jaccard = intersection / union if union > 0 else 0
    recall = intersection / len(target_set)

    # 混和得分：注重命中了幾個目標，但也懲罰無關標籤塞太多的商品
    positive_score = (jaccard * 0.4) + (recall * 0.6)

    # 避開地雷標籤懲罰加重
    avoid_penalty = len(prod_set & avoid_set) * 0.3
    return max(0.0, min(1.0, positive_score - avoid_penalty))

# ============================================================
# 4. 特徵匹配 (升級：多維度評分矩陣 Matrix)
# ============================================================

# 二維查表矩陣，取代原本的 if-else，速度 O(1) 且易於擴充
FEATURE_SCORING_MATRIX = {
    "contour": {"face_shape": {"round": 0.15, "square": 0.15, "oval": 0.05, "diamond": 0.05, "heart": 0.05}},
    "blush": {"face_shape": {"oval": 0.10, "heart": 0.10, "diamond": 0.10}},
    "eye": {"eye_shape": {"almond": 0.10, "peach_blossom": 0.10, "phoenix": 0.10}},
    "lip": {"lip_shape": {"m_shape": 0.10, "petal": 0.10, "full": 0.10}}
}

def feature_match_score(product_category: str, face_analysis: dict) -> float:
    if not face_analysis: return 0.7

    face_shape = (face_analysis.get("faceShape") or "").lower()
    eye_shape = (face_analysis.get("eyeShape") or "").lower()
    lip_shape = (face_analysis.get("lipShape") or "").lower()

    bonus = 0.0
    cat_matrix = FEATURE_SCORING_MATRIX.get(product_category, {})

    if "face_shape" in cat_matrix: bonus += cat_matrix["face_shape"].get(face_shape, 0.0)
    if "eye_shape" in cat_matrix: bonus += cat_matrix["eye_shape"].get(eye_shape, 0.0)
    if "lip_shape" in cat_matrix: bonus += cat_matrix["lip_shape"].get(lip_shape, 0.0)

    return min(1.0, 0.7 + bonus)

# ============================================================
# 5. 各類別與風格動態權重 (升級：Dynamic Weights)
# ============================================================

CATEGORY_BASE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "base": {"colorScore": 0.75, "styleScore": 0.05, "featureScore": 0.10, "availabilityScore": 0.10},
    "lip": {"colorScore": 0.55, "styleScore": 0.30, "featureScore": 0.05, "availabilityScore": 0.10},
    "eye": {"colorScore": 0.25, "styleScore": 0.55, "featureScore": 0.10, "availabilityScore": 0.10},
    "blush": {"colorScore": 0.35, "styleScore": 0.45, "featureScore": 0.10, "availabilityScore": 0.10},
    "contour": {"colorScore": 0.20, "styleScore": 0.25, "featureScore": 0.45, "availabilityScore": 0.10},
    "highlight": {"colorScore": 0.30, "styleScore": 0.45, "featureScore": 0.15, "availabilityScore": 0.10},
    "brow": {"colorScore": 0.25, "styleScore": 0.35, "featureScore": 0.30, "availabilityScore": 0.10},
}
DEFAULT_WEIGHTS = {"colorScore": 0.40, "styleScore": 0.35, "featureScore": 0.15, "availabilityScore": 0.10}

def get_dynamic_weights(category: str, style: str) -> Dict[str, float]:
    """根據使用者追求的風格，動態微調權重"""
    w = dict(CATEGORY_BASE_WEIGHTS.get(category, DEFAULT_WEIGHTS))
    style_lower = style.lower()

    # 如果是日常妝，色彩準確度比風格重要
    if "日常" in style_lower or "自然" in style_lower:
        w["colorScore"] += 0.10
        w["styleScore"] = max(0.0, w["styleScore"] - 0.10)
    # 如果是特殊風格(如港風、病嬌)，風格標籤的權重拉高
    elif "港風" in style_lower or "病嬌" in style_lower or "baddie" in style_lower:
        w["styleScore"] += 0.15
        w["colorScore"] = max(0.0, w["colorScore"] - 0.15)

    return w

# ============================================================
# 6. 核心推薦函數
# ============================================================

def recommend_products(analysis_package: dict, candidates: List[dict],
                       limit: int = 12, categories: Optional[List[str]] = None) -> dict:

    analysis_package = _minimized_analysis_package(analysis_package)
    if not isinstance(candidates, list) or len(candidates) > 5000:
        raise AnalysisContractError("INVALID_CANDIDATE_SET")
    limit = max(1, min(int(limit), 50))

    face_analysis = analysis_package.get("faceAnalysis", {}) or {}
    skin_tone = face_analysis.get("skinTone", {}) or {}
    lip_lab_raw = face_analysis.get("lipLab")
    brow_lab_raw = face_analysis.get("browLab") or face_analysis.get("hairLab")

    target_skin_lab = _parse_lab(skin_tone.get("lab"))
    target_lip_lab = _parse_lab(lip_lab_raw)
    target_brow_lab = _parse_lab(brow_lab_raw)

    style = normalize_style(analysis_package.get("style"))
    if not style:
        raise AnalysisContractError("UNKNOWN_MAKEUP_STYLE")
    analysis_package["style"] = style
    style_tags = get_style_tags(analysis_package)
    preferred_colors = get_preferred_colors(analysis_package)
    avoid_tags = get_avoid_tags(analysis_package)
    generative_text = analysis_package.get("generativeText", {}) or {}
    fallback_used = not (generative_text.get("styleTags") and isinstance(generative_text["styleTags"], list) and len(generative_text["styleTags"]) > 0)
    fallback_reason = f"generativeText.styleTags missing; used style default tags for '{style}'" if fallback_used else None

    # With no explicit filter, accept every category present in the live candidate
    # set. This keeps newly introduced DB categories eligible via DEFAULT_WEIGHTS.
    allowed_categories = set(categories) if categories else {
        str(prod.get("category") or "").lower() for prod in candidates if prod.get("category")
    }

    keyword_map = MAKEUP_KEYWORD_WHITELIST[style]
    category_keyword_keys = {"eye": "eyeshadows", "blush": "blushes", "lip": "lipsticks"}
    keyword_matches_present = False
    prepared = []
    for prod in candidates:
        cat = (prod.get("category") or "").lower()
        dictionary_category = category_keyword_keys.get(cat)
        keywords = keyword_map.get(dictionary_category, []) if dictionary_category else []
        searchable = " ".join(str(part or "") for part in (
            prod.get("name"), prod.get("brand"), prod.get("description"), prod.get("specs"), prod.get("shadeName"),
            " ".join(str(tag) for tag in (prod.get("tags") or prod.get("styleTags") or [])),
        )).casefold()
        hits = [word for word in keywords if word.casefold() in searchable]
        keyword_matches_present = keyword_matches_present or bool(hits)
        prepared.append((prod, hits))

    # First preference: actual keyword hits.  If a newly imported product does not
    # yet have a matching keyword, retain it through the documented fallback rather
    # than silently making it permanently ineligible.
    active_candidates = prepared
    keyword_fallback = not keyword_matches_present
    scored: List[dict] = []
    for prod, keyword_hits in active_candidates:
        cat = (prod.get("category") or "").lower()
        if (cat not in allowed_categories or not prod.get("inStock", True)
                or not prod.get("id") or not str(prod.get("name") or "").strip()):
            continue

        prod_lab = _parse_lab(prod.get("lab"))
        if cat == "lip" and target_lip_lab:
            target_color_lab = target_lip_lab
        elif cat == "brow":
            target_color_lab = target_brow_lab
        else:
            target_color_lab = target_skin_lab

        # a. Color
        skin_lab_reliable = skin_tone.get("labReliable") is not False
        use_base_fallback = cat == "base" and not skin_lab_reliable
        brow_color_unavailable = cat == "brow" and target_brow_lab is None
        de = None if (use_base_fallback or brow_color_unavailable) else delta_e(target_color_lab, prod_lab)
        color_score = (_base_fallback_color_score(prod, skin_tone) if use_base_fallback
                       else (0.5 if brow_color_unavailable else lab_similarity_from_delta_e(de)))

        # b. Style
        prod_tags = prod.get("tags") or []
        style_score = style_tag_similarity(prod_tags, style_tags, preferred_colors, avoid_tags)
        if keyword_hits:
            style_score = max(style_score, min(1.0, 0.65 + len(keyword_hits) * 0.1))

        # c. Feature
        face_score = feature_match_score(cat, face_analysis)
        availability_score = 1.0

        # 動態加權
        w = get_dynamic_weights(cat, style)
        base_final_score = (
            w["colorScore"] * color_score +
            w["styleScore"] * style_score +
            w["featureScore"] * face_score +
            w["availabilityScore"] * availability_score
        )

        # Deterministic score: identical input/data must yield identical output
        # so contract tests and Precision@K evaluation are reproducible.
        final_score = base_final_score

        scored.append({
            "id": prod["id"],
            "type": prod.get("type") or cat,
            "candidateKey": prod.get("candidateKey") or f"{prod.get('type') or cat}:{prod['id']}",
            "sourceId": prod.get("sourceId"),
            "category": cat,
            "brand": prod.get("brand", ""),
            "name": prod.get("name", ""),
            "shadeName": prod.get("shadeName") or prod.get("shade_name", ""),
            "imageUrl": prod.get("imageUrl") or prod.get("image_url", ""),
            "productUrl": prod.get("productUrl") or prod.get("product_url", "") or prod.get("sale_page_id", ""),
            "sourceUrl": prod.get("sourceUrl") or "",
            "salePageId": prod.get("salePageId") or prod.get("sale_page_id", ""),
            "coverageCategory": prod.get("coverageCategory") or prod.get("type") or cat,
            "price": prod.get("price", 0),
            "currency": prod.get("currency", "TWD"),
            "tags": prod_tags,
            "lab": prod_lab,
            "score": round(final_score, 4),
            "matchScore": round(final_score, 4),
            "colorMethod": ("season_level" if use_base_fallback else
                            ("brow_color_unavailable" if brow_color_unavailable else "ciede2000")),
            "keywordMatches": keyword_hits,
            "matchedKeywords": keyword_hits,
            "scoreBreakdown": {
                "colorScore": round(color_score, 4),
                "styleScore": round(style_score, 4),
                "featureScore": round(face_score, 4),
                "availabilityScore": round(availability_score, 4),
            },
            "matchReason": ("膚色取樣可信度不足，未使用 ΔE 比色，改以季型與膚色分級排序" if use_base_fallback
                            else ("缺少可靠眉毛／髮色資料，未以膚色比較眉彩色號，改以風格與特徵排序" if brow_color_unavailable
                            else (_keyword_match_reason(style, dictionary_category, keyword_hits) or _generate_match_reason(cat, color_score, style_score, face_score, de, style_tags, preferred_colors)))),
        })

    # 排序：先比總分，總分一樣比色彩準確度
    scored.sort(key=lambda x: (x["score"], -(x["scoreBreakdown"]["colorScore"])), reverse=True)
    final = _diversify_categories(scored, limit)

    returned_categories = {item["coverageCategory"] for item in final}
    requested_categories = sorted({str(prod.get("coverageCategory") or prod.get("type") or prod.get("category") or "") for prod, _ in prepared if prod.get("coverageCategory") or prod.get("type") or prod.get("category")})
    skipped = {category: "資料庫沒有可用商品" for category in requested_categories if category not in returned_categories}
    skin_tone_fallback = skin_tone.get("labReliable") is False and any(
        item.get("category") == "base" for item in final
    )
    brow_fallback = any(item.get("colorMethod") == "brow_color_unavailable" for item in final)
    primary_by_type = {}
    for item in final:
        # Without a measured brow/hair colour there is no defensible "best"
        # eyebrow colour. Keep diagnostic fallback data but do not hard-push one.
        if item.get("category") == "brow" and item.get("colorMethod") == "brow_color_unavailable":
            continue
        primary_by_type.setdefault(item.get("coverageCategory") or item.get("type"), item)
    primary = [
        {"type": product_type, "product": product, "matchScore": product["matchScore"]}
        for product_type, product in primary_by_type.items()
    ]
    primary_keys = {item["product"].get("candidateKey") for item in primary}
    threshold = 0.80
    alternates = [
        {"type": item.get("coverageCategory") or item.get("type"), "product": item, "matchScore": item["matchScore"]}
        for item in final if item.get("candidateKey") not in primary_keys and item["matchScore"] >= threshold
        and not (item.get("category") == "brow" and item.get("colorMethod") == "brow_color_unavailable")
    ]
    fallback_reasons = []
    if skin_tone_fallback:
        fallback_reasons.append({
        "code": "SKIN_TONE_LAB_UNRELIABLE",
        "message": "膚色取樣可信度不足，未使用 ΔE 比色，改以季型與膚色分級排序",
        "affected": ["foundations"],
        })
    if brow_fallback:
        fallback_reasons.append({
            "code": "BROW_COLOR_UNAVAILABLE",
            "message": "缺少可靠眉毛或髮色資料，未以膚色比較眉彩色號，改以風格與特徵排序",
            "affected": ["eyebrows"],
        })
    if keyword_fallback:
        fallback_reasons.append({"code": "STYLE_KEYWORD_NO_MATCH", "message": "沒有商品命中風格關鍵字，已改以合格資料庫商品排序", "affected": []})
    fallback_reason = fallback_reasons[0] if fallback_reasons else None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "products": final,
        # `fallbackUsed` is reserved for the database-search fallback that the
        # frontend needs to surface.  Style-tag defaults are normal scoring
        # behaviour and are exposed separately for diagnostics.
        "fallbackUsed": bool(fallback_reasons),
        "fallbackReason": fallback_reason,
        "fallbackReasons": fallback_reasons,
        "styleTagFallbackUsed": fallback_used,
        "styleTagFallbackReason": fallback_reason,
        "coverage": {"requested": len(requested_categories), "returned": len(returned_categories), "skipped": skipped},
        "skinToneLabReliable": skin_tone.get("labReliable") is not False,
        "primary": primary,
        "alternates": alternates,
        "threshold": threshold,
    }

def _keyword_match_reason(style: str, category: Optional[str], hits: List[str]) -> str:
    if not hits:
        return ""
    return f"命中{style}妝 {category or '商品'} 關鍵字：{'、'.join(hits[:3])}"

def _parse_lab(value: Any) -> Optional[Tuple[float, float, float]]:
    if value is None: return None
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try: return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError): return None
    if isinstance(value, dict):
        try: return (float(value.get("L", 0)), float(value.get("a", 0)), float(value.get("b", 0)))
        except (TypeError, ValueError): return None
    return None

def _diversify_categories(scored: List[dict], limit: int) -> List[dict]:
    from collections import defaultdict
    by_cat: Dict[str, List[dict]] = defaultdict(list)
    for item in scored: by_cat[item.get("coverageCategory") or item["category"]].append(item)

    result: List[dict] = []
    seen_ids: set = set()

    for cat in sorted(by_cat.keys()):
        for item in by_cat[cat]:
            key = item.get("candidateKey") or f"{item.get('type')}:{item['id']}"
            if key not in seen_ids:
                result.append(item); seen_ids.add(key)
                break

    if len(result) < limit:
        for cat in sorted(by_cat.keys()):
            count = 0
            for item in by_cat[cat]:
                key = item.get("candidateKey") or f"{item.get('type')}:{item['id']}"
                if key not in seen_ids and count < 1:
                    result.append(item); seen_ids.add(key)
                    count += 1
            if len(result) >= limit: break

    if len(result) < limit:
        for item in scored:
            key = item.get("candidateKey") or f"{item.get('type')}:{item['id']}"
            if key not in seen_ids and len(result) < limit:
                result.append(item); seen_ids.add(key)

    return result[:limit]

def _generate_match_reason(category: str, color_score: float, style_score: float,
                           feature_score: float, de: Optional[float],
                           style_tags: List[str], preferred_colors: List[str]) -> str:
    parts: List[str] = []
    if color_score >= 0.85 and de is not None:
        if de < 3: parts.append("色調與您的膚色幾乎完美匹配")
        elif de < 6: parts.append("色號非常接近您的膚色")
        else: parts.append("色彩契合度佳")
    elif color_score >= 0.6: parts.append("色彩相近")

    if style_score >= 0.7:
        if preferred_colors: parts.append(f"符合推薦色系「{'、'.join(preferred_colors[:3])}」")
        if style_tags: parts.append(f"契合 {style_tags[0] if len(style_tags) <= 1 else style_tags[0] + ' 風格'}")
    elif style_score >= 0.4: parts.append("風格搭配適中")

    if feature_score >= 0.8:
        cat_name = {"base": "底妝", "lip": "唇型", "eye": "眼型", "blush": "臉型", "contour": "修容", "highlight": "打亮", "brow": "眉型"}.get(category, category)
        parts.append(f"極致修飾您的{cat_name}")

    if not parts: return f"綜合推薦度 {round(color_score * 100)}%"
    return "、".join(parts)

def health_check() -> dict:
    return {"status": "ok", "service": "product-recommendation"}

# 保留相容舊 API
recommend_cosmetics = recommend_products
