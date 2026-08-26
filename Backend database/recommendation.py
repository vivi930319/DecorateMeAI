"""
商品推薦演算法 — 基於 analysisPackage 規格（2026-07-13-v2 演算法升級版）

核心邏輯升級：
1. 色彩精準層：skinTone.lab / lipLab (Delta E)
2. 語意風格層：導入 Jaccard 相似度防作弊
3. 特徵匹配層：導入 O(1) 查表的特徵評分矩陣 (Scoring Matrix)
4. 權重分配層：依據 Style 動態調整權重 (Dynamic Weights)
5. 個人化偏好層：以伺服器端既有互動、預算與品牌偏好進行可解釋重排
"""

import math
from typing import Dict, List, Tuple, Optional, Any
from makeup_keywords import MAKEUP_KEYWORD_WHITELIST, normalize_style

SCHEMA_VERSION = "2026-08-v2"
_FORBIDDEN_INPUT_FIELDS = {
    "email", "member", "memberemail", "memberid", "userid", "customerid",
    "name", "fullname", "phone", "phonenumber", "telephone", "mobile",
    "token", "accesstoken", "refreshtoken", "cookie", "authorization",
    "image", "imagebase64", "photo", "photobase64", "rawimage",
}

class AnalysisContractError(ValueError):
    """Raised when a caller sends identity or non-contract analysis data."""

def _minimized_analysis_package(value: dict) -> dict:
    """Accept only recommendation features; ignore unknown model/internal fields."""
    if not isinstance(value, dict):
        raise AnalysisContractError("INVALID_ANALYSIS_PACKAGE")
    def contains_forbidden_field(node: Any) -> bool:
        if isinstance(node, dict):
            for key, child in node.items():
                normalized = "".join(ch for ch in str(key).casefold() if ch.isalnum())
                if normalized in _FORBIDDEN_INPUT_FIELDS or contains_forbidden_field(child):
                    return True
        elif isinstance(node, list):
            return any(contains_forbidden_field(child) for child in node)
        return False

    if contains_forbidden_field(value):
        raise AnalysisContractError("IDENTITY_DATA_NOT_ALLOWED")
    if "faceAnalysis" not in value or not isinstance(value.get("faceAnalysis"), dict):
        raise AnalysisContractError("INVALID_ANALYSIS_PACKAGE")
    face = value["faceAnalysis"]
    if not isinstance(face, dict):
        raise AnalysisContractError("INVALID_FACE_ANALYSIS")
    skin = face.get("skinTone") or {}
    if not isinstance(skin, dict):
        skin = {}
    generated = value.get("generativeText") or {}
    if not isinstance(generated, dict):
        generated = {}
    lab = skin.get("lab")
    lab_reliable = skin.get("labReliable") is not False and _usable_lab(lab)
    return {
        "style": str(value.get("style") or "")[:120],
        "faceAnalysis": {
            "faceShape": str(face.get("faceShape") or "")[:40],
            "eyeShape": str(face.get("eyeShape") or "")[:40],
            "lipShape": str(face.get("lipShape") or "")[:40],
            "skinTone": {
                "lab": lab,
                "season": str(skin.get("season") or "unknown")[:40],
                "level": str(skin.get("level") or "")[:80],
                "labReliable": lab_reliable,
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
# 1.5 個人化偏好（不接受身分資料）
# ============================================================

def _normalized_label_list(value: Any, limit: int = 20) -> List[str]:
    """Normalize user-entered non-sensitive labels such as brands.

    The client must never send a member id/email here.  Identity is resolved by
    the API from the authenticated session, while this function only accepts
    presentation preferences needed for the ranking calculation.
    """
    if not isinstance(value, list):
        return []
    values = []
    for item in value[:limit]:
        text = str(item or "").strip()
        if text and len(text) <= 100:
            values.append(text.casefold())
    return values


def _minimized_recommendation_options(value: Any) -> dict:
    """Keep only declared, non-identifying recommendation controls."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise AnalysisContractError("INVALID_REQUEST")
    def has_forbidden_key(node: Any) -> bool:
        if isinstance(node, dict):
            return any(
                "".join(ch for ch in str(key).casefold() if ch.isalnum()) in _FORBIDDEN_INPUT_FIELDS
                or has_forbidden_key(child)
                for key, child in node.items()
            )
        return isinstance(node, list) and any(has_forbidden_key(child) for child in node)
    if has_forbidden_key(value):
        raise AnalysisContractError("IDENTITY_DATA_NOT_ALLOWED")
    if any(isinstance(value.get(key), list) and len(value[key]) > 20
           for key in ("preferredBrands", "avoidedBrands")):
        raise AnalysisContractError("INVALID_REQUEST")
    if "pricePreference" in value and not isinstance(value.get("pricePreference"), dict):
        raise AnalysisContractError("INVALID_REQUEST")
    price = value.get("pricePreference") or {}

    def _amount(name: str) -> Optional[float]:
        try:
            raw = price.get(name)
            if raw is None:
                return None
            if isinstance(raw, bool):
                raise ValueError
            amount = float(raw)
            if not math.isfinite(amount) or not 0 <= amount <= 1_000_000:
                raise ValueError
            return amount
        except (TypeError, ValueError):
            raise AnalysisContractError("INVALID_REQUEST")

    minimum, maximum = _amount("min"), _amount("max")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise AnalysisContractError("INVALID_REQUEST")
    raw_mode = price.get("mode")
    mode = str(raw_mode).casefold() if isinstance(raw_mode, str) else ""
    if "mode" in price and (raw_mode is None or mode not in {"value", "low", "high"}):
        raise AnalysisContractError("INVALID_REQUEST")
    return {
        "preferredBrands": _normalized_label_list(value.get("preferredBrands")),
        "avoidedBrands": _normalized_label_list(value.get("avoidedBrands")),
        "pricePreference": {"min": minimum, "max": maximum,
                            "mode": mode or None},
    }


def _usable_lab(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return False
    if not all(isinstance(component, (int, float)) and not isinstance(component, bool)
               and math.isfinite(float(component)) for component in value):
        return False
    lightness, axis_a, axis_b = (float(component) for component in value)
    return 0 <= lightness <= 100 and abs(axis_a) <= 128 and abs(axis_b) <= 128


def _price_as_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    match = __import__("re").search(r"(?:\d[\d,.]*)", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _preference_scores(product: dict, options: dict, behavior: dict) -> Tuple[float, float, float]:
    """Return price-fit, explicit-brand-fit, and server-side behavior scores.

    Missing controls deliberately score neutral (0.5) so new or anonymous users
    are ranked purely by cosmetic content rather than receiving a penalty.
    """
    price = _price_as_number(product.get("price"))
    pref = options.get("pricePreference") or {}
    low, high, mode = pref.get("min"), pref.get("max"), pref.get("mode")
    if price is None or (low is None and high is None):
        price_fit = 0.5
    elif low is not None and high is not None and low <= price <= high:
        price_fit = 1.0
    elif low is not None and price < low:
        price_fit = max(0.0, 1.0 - ((low - price) / max(low, 1.0)))
    elif high is not None and price > high:
        price_fit = max(0.0, 1.0 - ((price - high) / max(high, 1.0)))
    else:
        price_fit = 0.7
    if mode == "low" and price is not None:
        price_fit = min(1.0, price_fit + 0.1)
    elif mode == "high" and price is not None:
        price_fit = min(1.0, price_fit + 0.03)

    brand = str(product.get("brand") or "").casefold()
    if brand and brand in set(options.get("avoidedBrands") or []):
        brand_fit = 0.0
    elif brand and brand in set(options.get("preferredBrands") or []):
        brand_fit = 1.0
    else:
        brand_fit = 0.5

    category_affinity = (behavior.get("categoryAffinities") or {}).get(str(product.get("category") or "").casefold(), 0.0)
    brand_affinity = (behavior.get("brandAffinities") or {}).get(brand, 0.0) if brand else 0.0
    behavior_score = min(1.0, (0.6 * float(category_affinity)) + (0.4 * float(brand_affinity)))
    return price_fit, brand_fit, behavior_score

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
                       limit: int = 12, categories: Optional[List[str]] = None,
                       recommendation_options: Optional[dict] = None,
                       behavior_profile: Optional[dict] = None) -> dict:

    analysis_package = _minimized_analysis_package(analysis_package)
    recommendation_options = _minimized_recommendation_options(recommendation_options)
    behavior_profile = behavior_profile if isinstance(behavior_profile, dict) else {}
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
        prepared.append((prod, hits, searchable))

    # First preference: actual keyword hits.  If a newly imported product does not
    # yet have a matching keyword, retain it through the documented fallback rather
    # than silently making it permanently ineligible.
    active_candidates = prepared
    keyword_fallback = not keyword_matches_present
    scored: List[dict] = []
    for prod, keyword_hits, searchable in active_candidates:
        cat = (prod.get("category") or "").lower()
        if (cat not in allowed_categories or not prod.get("inStock", True)
                or not prod.get("id") or not str(prod.get("name") or "").strip()):
            continue
        if str(prod.get("brand") or "").casefold() in set(recommendation_options["avoidedBrands"]):
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
        prod_tags = prod.get("tags") or prod.get("styleTags") or []
        style_score = style_tag_similarity(prod_tags, style_tags, preferred_colors, [])
        if keyword_hits:
            style_score = max(style_score, min(1.0, 0.65 + len(keyword_hits) * 0.1))
        avoid_hits = [tag for tag in avoid_tags if tag and tag.casefold() in searchable]
        preferred_color_hits = [color for color in preferred_colors if color and color.casefold() in searchable]
        style_score = max(0.0, min(1.0, style_score + 0.12 * len(preferred_color_hits)
                                   - 0.20 * len(avoid_hits)))

        # c. Feature
        face_score = feature_match_score(cat, face_analysis)
        availability_score = 1.0
        price_fit, explicit_brand_fit, behavior_score = _preference_scores(
            prod, recommendation_options, behavior_profile
        )

        # 動態加權
        w = get_dynamic_weights(cat, style)
        cosmetic_score = (
            w["colorScore"] * color_score +
            w["styleScore"] * style_score +
            w["featureScore"] * face_score +
            w["availabilityScore"] * availability_score
        )

        # Explicit price/brand choices are a modest re-ranking signal.  They
        # cannot override colour/style compatibility on their own.
        has_explicit_preference = bool(
            recommendation_options["preferredBrands"] or recommendation_options["avoidedBrands"]
            or recommendation_options["pricePreference"]["min"] is not None
            or recommendation_options["pricePreference"]["max"] is not None
        )
        preference_score = (price_fit + explicit_brand_fit) / 2.0
        content_score = (0.90 * cosmetic_score + 0.10 * preference_score) if has_explicit_preference else cosmetic_score

        # Behaviour is calculated by the server from authenticated member
        # interactions.  A cold-start user retains the content score exactly.
        interaction_count = int(behavior_profile.get("interactionCount") or 0)
        behavior_weight = min(0.15, 0.03 * interaction_count) if interaction_count else 0.0
        base_final_score = (1.0 - behavior_weight) * content_score + behavior_weight * behavior_score

        # Deterministic score: identical input/data must yield identical output
        # so contract tests and Precision@K evaluation are reproducible.
        final_score = base_final_score

        reason_text, reason_evidence = _build_match_reason(
            cat, style, color_score, style_score, face_score, de, keyword_hits,
            preferred_colors, preferred_color_hits, brow_color_unavailable,
            use_base_fallback,
        )
        scored.append({
            "id": prod["id"],
            "type": prod.get("type") or cat,
            "candidateKey": prod.get("candidateKey") or f"{prod.get('type') or cat}:{prod['id']}",
            "sourceId": prod.get("sourceId"),
            "category": cat,
            "brand": prod.get("brand", ""),
            "name": prod.get("name", ""),
            "shadeName": prod.get("shadeName") or prod.get("shade_name", ""),
            "shadeCode": prod.get("shadeCode") or prod.get("shade_code"),
            "seriesId": prod.get("seriesId") or prod.get("series_id"),
            "depthIndex": prod.get("depthIndex") if prod.get("depthIndex") is not None else prod.get("depth_index"),
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
            "avoidTagHits": avoid_hits,
            "preferredColorHits": preferred_color_hits,
            "scoreBreakdown": {
                "colorScore": round(color_score, 4),
                "styleScore": round(style_score, 4),
                "featureScore": round(face_score, 4),
                "availabilityScore": round(availability_score, 4),
                "priceFit": round(price_fit, 4),
                "brandAffinity": round(explicit_brand_fit, 4),
                "behaviorScore": round(behavior_score, 4),
                "contentScore": round(content_score, 4),
            },
            "matchReason": reason_text,
            "matchReasons": reason_evidence,
        })
        scored[-1]["recommendationPresentation"] = _build_user_presentation(
            scored[-1], style, face_analysis, skin_tone
        )

    # 排序：先比總分，總分一樣比色彩準確度
    scored.sort(key=lambda x: (x["score"], -(x["scoreBreakdown"]["colorScore"])), reverse=True)
    final = _diversify_categories(scored, limit)

    returned_categories = {item["coverageCategory"] for item in final}
    requested_categories = sorted({str(prod.get("coverageCategory") or prod.get("type") or prod.get("category") or "") for prod, _, _ in prepared if prod.get("coverageCategory") or prod.get("type") or prod.get("category")})
    skipped = {category: "資料庫沒有可用商品" for category in requested_categories if category not in returned_categories}
    skin_tone_fallback = skin_tone.get("labReliable") is False and any(
        item.get("category") == "base" for item in final
    )
    primary_by_type = {}
    for item in final:
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
    ]
    fallback_reasons = []
    if skin_tone_fallback:
        fallback_reasons.append({
        "code": "SKIN_TONE_LAB_UNRELIABLE",
        "message": "膚色取樣可信度不足，未使用 ΔE 比色，改以季型與膚色分級排序",
        "affected": ["foundations"],
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
        "shadeRecommendation": _foundation_shade_recommendation(scored),
        "personalization": {
            "applied": bool(behavior_profile.get("interactionCount") or recommendation_options["preferredBrands"]
                            or recommendation_options["avoidedBrands"]
                            or recommendation_options["pricePreference"]["min"] is not None
                            or recommendation_options["pricePreference"]["max"] is not None),
            "interactionCount": int(behavior_profile.get("interactionCount") or 0),
            "behaviorWeight": round(min(0.15, 0.03 * int(behavior_profile.get("interactionCount") or 0))
                                    if behavior_profile.get("interactionCount") else 0.0, 4),
        },
    }

def _keyword_match_reason(style: str, category: Optional[str], hits: List[str]) -> str:
    if not hits:
        return ""
    return f"命中{style}妝 {category or '商品'} 關鍵字：{'、'.join(hits[:3])}"

def _parse_lab(value: Any) -> Optional[Tuple[float, float, float]]:
    if value is None: return None
    if _usable_lab(value):
        return tuple(float(component) for component in value)
    if isinstance(value, dict):
        candidate = [value.get("L"), value.get("a"), value.get("b")]
        return tuple(float(component) for component in candidate) if _usable_lab(candidate) else None
    return None


def _build_match_reason(category: str, style: str, color_score: float, style_score: float,
                        feature_score: float, de: Optional[float], keyword_hits: List[str],
                        preferred_colors: List[str], preferred_color_hits: List[str],
                        brow_style_only: bool, base_fallback: bool) -> Tuple[str, List[dict]]:
    reasons = []
    if base_fallback:
        reasons.append({"priority": 1, "reasonCode": "skin_tone_season_match", "personalized": True,
                        "text": "膚色取樣可信度不足，已依季型與膚色分級排序",
                        "evidence": {"userField": "skinTone.season/level", "productField": "seasonTags/undertone",
                                     "colorScore": round(color_score, 4)}})
    elif category == "brow" and brow_style_only:
        reasons.append({"priority": 1, "reasonCode": "brow_style_match", "personalized": True,
                        "text": f"符合{style}妝的眉彩風格",
                        "evidence": {"userField": "style", "productField": "styleTags/description",
                                     "styleScore": round(style_score, 4)}})
    elif de is not None:
        field = "lipLab" if category == "lip" else "skinTone.lab"
        subject = "唇色" if category == "lip" else "膚色"
        reasons.append({"priority": 1, "reasonCode": "lip_color_match" if category == "lip" else "skin_color_match",
                        "personalized": True, "text": f"此色號與您的{subject}相近（色差 {de:.1f}）",
                        "evidence": {"userField": field, "productField": "colorLab", "deltaE": round(de, 2),
                                     "colorScore": round(color_score, 4)}})
    if keyword_hits:
        keyword = keyword_hits[0]
        reasons.append({"priority": len(reasons) + 1, "reasonCode": "style_keyword_match", "personalized": True,
                        "text": f"您的妝容風格為{style}妝，商品的「{keyword}」特質符合此風格",
                        "evidence": {"userField": "style", "productField": "name/description/styleTags",
                                     "matchedKeywords": keyword_hits[:3], "styleScore": round(style_score, 4)}})
    if preferred_color_hits:
        reasons.append({"priority": len(reasons) + 1, "reasonCode": "preferred_color_match", "personalized": True,
                        "text": f"商品符合您偏好的「{'、'.join(preferred_color_hits[:3])}」色系",
                        "evidence": {"userField": "generativeText.preferredColors", "productField": "product content",
                                     "matchedColors": preferred_color_hits[:3]}})
    if not reasons:
        reasons.append({"priority": 1, "reasonCode": "overall_match", "personalized": True,
                        "text": f"依{style}妝風格與臉部特徵綜合排序",
                        "evidence": {"userField": "style/faceAnalysis", "productField": "product features",
                                     "styleScore": round(style_score, 4), "featureScore": round(feature_score, 4)}})
    return "、".join(reason["text"] for reason in reasons), reasons


def _build_user_presentation(product: dict, style: str, face_analysis: dict,
                             skin_tone: dict) -> dict:
    """Translate ranking evidence into warm, user-facing copy without exposing formulas."""
    category = product.get("category") or ""
    percent = max(0, min(100, round(float(product.get("matchScore") or 0) * 100)))
    if percent >= 90:
        tier = "高度匹配"
    elif percent >= 80:
        tier = "很適合你的整體妝容"
    elif percent >= 70:
        tier = "適合你的妝容風格"
    elif percent >= 60:
        tier = "可以參考的搭配選擇"
    else:
        tier = "其他搭配選擇"

    category_copy = {
        "base": ("與你的膚色高度匹配", "這款底妝的明暗與色調和你的膚色協調，適合呈現自然貼合的底妝效果。"),
        "lip": ("與你的自然唇色高度協調", f"這款唇色能融入你的自然唇色，也符合{style}妝的整體感受。"),
        "eye": ("符合你的眼型與妝容風格", f"這款眼妝商品能配合你的眼部特徵，也符合{style}妝的風格。"),
        "blush": ("讓氣色自然融入整體妝容", f"這款腮紅能與你的膚色協調，也符合{style}妝的妝容特質。"),
        "contour": ("適合你的臉部輪廓", "這款修容適合配合你的臉部特徵，自然加強輪廓與立體感。"),
        "highlight": ("符合你的整體妝感", f"這款打亮能增添細緻光澤，讓{style}妝的五官輪廓更完整。"),
        "brow": ("符合你的整體妝容風格", f"這款眉彩適合打造與{style}妝協調的眉妝，讓整體妝容更完整。"),
    }
    headline, summary = category_copy.get(
        category, (tier, f"這款商品符合你的{style}妝風格與個人偏好。")
    )
    if category == "base" and product.get("colorMethod") == "season_level":
        headline = "符合你的膚色特徵與妝容風格"
        summary = "這次的照片可能受到光線影響，因此系統改用膚色明暗、季型與妝容風格提供建議。"
    elif category == "base" and percent < 90:
        headline = tier

    season_labels = {"warm": "暖色調膚色", "cool": "冷色調膚色", "neutral": "中性膚色"}
    face_labels = {"oval": "鵝蛋臉", "round": "圓臉", "square": "方臉", "heart": "心形臉", "diamond": "鑽石臉"}
    eye_labels = {"almond": "杏眼", "peach_blossom": "桃花眼", "phoenix": "丹鳳眼"}
    lip_labels = {"full": "豐唇", "m_shape": "M 字唇", "petal": "花瓣唇"}
    traits = []
    season = str(skin_tone.get("season") or "").casefold()
    level = str(skin_tone.get("level") or "").strip()
    if category in {"base", "blush", "highlight"} and season and season != "unknown":
        traits.append(season_labels.get(season, str(skin_tone.get("season"))))
    if category == "base" and level:
        traits.append(level)
    if category in {"blush", "contour", "brow"} and face_analysis.get("faceShape"):
        raw = str(face_analysis["faceShape"])
        traits.append(face_labels.get(raw.casefold(), raw))
    if category == "eye" and face_analysis.get("eyeShape"):
        raw = str(face_analysis["eyeShape"])
        traits.append(eye_labels.get(raw.casefold(), raw))
    if category == "lip" and face_analysis.get("lipShape"):
        raw = str(face_analysis["lipShape"])
        traits.append(lip_labels.get(raw.casefold(), raw))
    traits.append(f"{style}妝")
    return {
        "systemLabel": "根據系統演算法推薦",
        "matchPercent": percent,
        "matchLabel": f"{percent}% MATCH",
        "matchTier": tier,
        "headline": headline,
        "summary": summary,
        "suitedTraits": list(dict.fromkeys(traits)),
        "reasonTexts": [reason.get("text") for reason in product.get("matchReasons", []) if reason.get("text")][:4],
        "disclaimer": "推薦匹配度是系統用於商品排序的綜合結果，不代表實際上妝效果或準確率保證。",
    }


def _foundation_shade_recommendation(scored: List[dict]) -> Optional[dict]:
    foundations = [item for item in scored if item.get("category") == "base" and item.get("lab")]
    if not foundations:
        return None
    anchor = max(foundations, key=lambda item: item["score"])
    series_id, depth_index = anchor.get("seriesId"), anchor.get("depthIndex")
    official = series_id and depth_index is not None
    if official:
        same_series = [item for item in foundations if item is not anchor
                       and item.get("seriesId") == series_id and item.get("depthIndex") is not None]
        lighter = max((item for item in same_series if item["depthIndex"] < depth_index),
                      key=lambda item: item["depthIndex"], default=None)
        darker = min((item for item in same_series if item["depthIndex"] > depth_index),
                     key=lambda item: item["depthIndex"], default=None)
    else:
        anchor_l = anchor["lab"][0]
        lighter = min((item for item in foundations if item is not anchor and item["lab"][0] > anchor_l),
                      key=lambda item: item["lab"][0] - anchor_l, default=None)
        darker = min((item for item in foundations if item is not anchor and item["lab"][0] < anchor_l),
                     key=lambda item: anchor_l - item["lab"][0], default=None)
    def choice(item, relation, label, description):
        return None if item is None else {
            "relation": relation, "label": label, "description": description,
            "shadeCode": item.get("shadeCode") or item.get("shadeName") or item.get("name"),
            "matchPercent": round(float(item.get("matchScore") or 0) * 100), "product": item,
        }
    return {
        "method": "official_depth_index" if official else "lab_lightness_approximation",
        "seriesId": series_id if official else None,
        "anchor": choice(anchor, "anchor", "主推薦色號", "目前最接近你的膚色明暗與色調。"),
        "lighter": choice(lighter, "lighter_variant", "淺一階" if official else "較明亮的替代色",
                           "適合希望提亮膚色或呈現較明亮妝效時比較。"),
        "darker": choice(darker, "darker_variant", "深一階" if official else "較深的替代色",
                          "適合近期有日曬或偏好自然健康妝效時比較。"),
        "disclaimer": ("色階依同品牌同系列的正式深淺順序提供；實際顏色仍可能受到光線、螢幕與上妝方式影響。"
                       if official else "目前缺少品牌正式色階順序，以下依 L* 明度提供相近替代色，不代表品牌定義的淺一階或深一階。"),
    }

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
