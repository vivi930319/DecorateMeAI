"""
商品推薦演算法 — 基於 analysisPackage 規格（2026-07-13-v2 演算法升級版）

核心邏輯升級：
1. 色彩精準層：粉底使用 skinTone.lab (Delta E)
2. 語意風格層：導入 Jaccard 相似度防作弊
3. 特徵匹配層：導入 O(1) 查表的特徵評分矩陣 (Scoring Matrix)
4. 權重分配層：依據 Style 動態調整權重 (Dynamic Weights)
5. 個人化偏好層：以伺服器端既有互動、預算與品牌偏好進行可解釋重排
"""

import math
from typing import Dict, List, Tuple, Optional, Any
from makeup_keywords import MAKEUP_KEYWORD_WHITELIST, normalize_style

SCHEMA_VERSION = "2026-08-v2"
FOUNDATION_SKIN_MAX_DELTA_E = 2.0
SHADE_ALTERNATIVE_MAX_DELTA_E = 5.0
FOUNDATION_IN_STORE_DISCLAIMER = "請以實際至實體專櫃試色與購買體驗為準。"
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
    # A legacy client sometimes sends labReliable=false together with a valid
    # Lab triple.  The numeric measurement is authoritative: only missing,
    # non-finite or out-of-range Lab values are rejected.
    lab_reliable = _usable_lab(lab)
    return {
        "style": str(value.get("style") or "")[:120],
        "faceAnalysis": {
            "faceShape": str(face.get("faceShape") or "")[:40],
            "browShape": str(face.get("browShape") or "unknown")[:40],
            "eyeShape": str(face.get("eyeShape") or "")[:40],
            "lipShape": str(face.get("lipShape") or "")[:40],
            "skinTone": {
                "lab": lab,
                "season": str(skin.get("season") or "unknown")[:40],
                "level": str(skin.get("level") or "")[:80],
                "labReliable": lab_reliable,
                "sourceLabReliable": skin.get("labReliable") if isinstance(skin.get("labReliable"), bool) else None,
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
    # Keep the strict <= 2 acceptance threshold separate from ranking.  Giving
    # every accepted shade a flat 1.0 made a 1.9 ΔE shade tie with a 0.2 ΔE
    # shade, so database order could decide the foundation recommendation.
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

BROW_SHAPE_LABELS = {
    "straight": "一字眉", "curved": "彎月眉", "drooping_tail": "落尾眉",
    "arched": "挑眉", "unknown": "未知眉型",
}

# These are product-content signals, not beauty rules inferred from identity.
# If a product has no matching content signal the feature score stays neutral.
BROW_SHAPE_PRODUCT_SIGNALS = {
    "straight": {
        "prefer": ("平眉", "一字眉", "straight", "眉粉", "自然", "natural", "soft"),
        "avoid": ("高眉峰", "arched", "強力拉提"),
    },
    "curved": {
        "prefer": ("彎月眉", "弧形", "curved", "柔和", "soft", "圓頭"),
        "avoid": ("俐落眉峰", "sharp arch"),
    },
    "drooping_tail": {
        "prefer": ("拉提", "上揚", "lifting", "眉峰", "defined", "精細", "precision"),
        "avoid": ("下垂", "drooping"),
    },
    "arched": {
        "prefer": ("自然", "natural", "柔和", "soft", "細芯", "精細", "precision"),
        "avoid": ("拉提", "上揚", "lifting", "高眉峰", "high arch"),
    },
}

def feature_match_score(product_category: str, face_analysis: dict,
                        product_content: str = "") -> float:
    if not face_analysis: return 0.7

    face_shape = (face_analysis.get("faceShape") or "").lower()
    eye_shape = (face_analysis.get("eyeShape") or "").lower()
    lip_shape = (face_analysis.get("lipShape") or "").lower()
    brow_shape = (face_analysis.get("browShape") or "unknown").lower()

    bonus = 0.0
    cat_matrix = FEATURE_SCORING_MATRIX.get(product_category, {})

    if "face_shape" in cat_matrix: bonus += cat_matrix["face_shape"].get(face_shape, 0.0)
    if "eye_shape" in cat_matrix: bonus += cat_matrix["eye_shape"].get(eye_shape, 0.0)
    if "lip_shape" in cat_matrix: bonus += cat_matrix["lip_shape"].get(lip_shape, 0.0)

    if product_category == "brow" and brow_shape in BROW_SHAPE_PRODUCT_SIGNALS:
        content = str(product_content or "").casefold()
        signals = BROW_SHAPE_PRODUCT_SIGNALS[brow_shape]
        preferred_hits = sum(1 for term in signals["prefer"] if term.casefold() in content)
        avoided_hits = sum(1 for term in signals["avoid"] if term.casefold() in content)
        bonus += min(0.20, preferred_hits * 0.05)
        bonus -= min(0.20, avoided_hits * 0.10)

    return max(0.0, min(1.0, 0.7 + bonus))

# ============================================================
# 5. 各類別與風格動態權重 (升級：Dynamic Weights)
# ============================================================

CATEGORY_BASE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "base": {"colorScore": 0.75, "styleScore": 0.05, "featureScore": 0.10, "availabilityScore": 0.10},
    # 唇彩以整體妝容風格與臉部特徵排序。自然唇色會受到唇彩遮蓋力、
    # 妝效與疊擦方式影響，因此不拿 lipLab 計算或顯示色差。
    "lip": {"colorScore": 0.00, "styleScore": 0.75, "featureScore": 0.15, "availabilityScore": 0.10},
    "eye": {"colorScore": 0.00, "styleScore": 0.90, "featureScore": 0.00, "availabilityScore": 0.10},
    "blush": {"colorScore": 0.00, "styleScore": 0.90, "featureScore": 0.00, "availabilityScore": 0.10},
    "contour": {"colorScore": 0.00, "styleScore": 0.90, "featureScore": 0.00, "availabilityScore": 0.10},
    "highlight": {"colorScore": 0.00, "styleScore": 0.90, "featureScore": 0.00, "availabilityScore": 0.10},
    "brow": {"colorScore": 0.00, "styleScore": 0.90, "featureScore": 0.00, "availabilityScore": 0.10},
}
DEFAULT_WEIGHTS = {"colorScore": 0.00, "styleScore": 0.90, "featureScore": 0.00, "availabilityScore": 0.10}

def get_dynamic_weights(category: str, style: str) -> Dict[str, float]:
    """根據使用者追求的風格，動態微調權重"""
    w = dict(CATEGORY_BASE_WEIGHTS.get(category, DEFAULT_WEIGHTS))
    if category not in {"base", "lip"}:
        return w
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
    brow_lab_raw = face_analysis.get("browLab") or face_analysis.get("hairLab")

    target_skin_lab = _parse_lab(skin_tone.get("lab"))
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
    style_tag_fallback_reason = f"generativeText.styleTags missing; used style default tags for '{style}'" if fallback_used else None

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
    foundation_candidate_types = set()
    foundation_delta_values: List[float] = []
    foundation_qualified_count = 0
    skin_lab_reliable = skin_tone.get("labReliable") is not False and target_skin_lab is not None
    for prod, keyword_hits, searchable in active_candidates:
        cat = (prod.get("category") or "").lower()
        if (cat not in allowed_categories or not prod.get("inStock", True)
                or not prod.get("id") or not str(prod.get("name") or "").strip()):
            continue
        if str(prod.get("brand") or "").casefold() in set(recommendation_options["avoidedBrands"]):
            continue
        if cat == "base":
            foundation_candidate_types.add(
                str(prod.get("coverageCategory") or prod.get("type") or cat)
            )

        prod_lab = _parse_lab(prod.get("lab"))
        if cat == "base":
            target_color_lab = target_skin_lab
        else:
            target_color_lab = None

        # a. Color
        use_base_fallback = cat == "base" and not skin_lab_reliable
        color_applicable = cat == "base"
        color_available = color_applicable and target_color_lab is not None and prod_lab is not None
        de = None if (use_base_fallback or not color_available) else delta_e(target_color_lab, prod_lab)
        color_score = (_base_fallback_color_score(prod, skin_tone) if use_base_fallback
                       else (lab_similarity_from_delta_e(de) if color_available else 0.0))
        foundation_skin_match = None
        if cat == "base":
            accepted = bool(de is not None and 0.0 <= de <= FOUNDATION_SKIN_MAX_DELTA_E)
            foundation_skin_match = {
                "metric": "CIEDE2000",
                "symbol": "ΔE00",
                "deltaE": round(float(de), 2) if de is not None else None,
                "minInclusive": 0.0,
                "maxInclusive": FOUNDATION_SKIN_MAX_DELTA_E,
                "accepted": accepted,
                "displayEligible": accepted,
                "displayStatus": "recommended" if accepted else "not_eligible",
            }
            if de is not None:
                foundation_delta_values.append(float(de))
            if accepted:
                foundation_qualified_count += 1

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
        face_score = feature_match_score(cat, face_analysis, searchable)
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
            preferred_colors, preferred_color_hits, cat == "brow",
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
            "shadeCode": (prod.get("shadeCode") or prod.get("shade_code")
                          or prod.get("shadeName") or prod.get("shade_name")),
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
                            ("ciede2000" if color_available else "style_only")),
            # Internal full-precision value used for foundation ordering.  It
            # is removed before the response is returned; the public contract
            # continues to expose the rounded foundationSkinMatch.deltaE.
            "_foundationDeltaE": float(de) if cat == "base" and de is not None else None,
            "foundationSkinMatch": foundation_skin_match,
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

    # Keep the complete foundation pool for same-series shade alternatives,
    # while exposing strict matches plus, when needed, one clearly-labelled
    # closest available shade.  The 0–2 range remains the strict match rule,
    # but the nearest measured shade is still useful when no strict match exists.
    scored.sort(key=lambda x: (
        -float(x["score"]),
        -float(x["scoreBreakdown"]["colorScore"]),
        str(x.get("candidateKey") or ""),
    ))
    shade_candidate_pool = list(scored)
    foundation_items = [item for item in shade_candidate_pool if item.get("category") == "base"]
    mac_foundation_items = [
        item for item in foundation_items
        if str(item.get("brand") or "").strip().casefold() == "mac"
        and item.get("_foundationDeltaE") is not None
    ]
    foundation_anchor_brand = "MAC" if mac_foundation_items else None
    foundation_anchor_pool = mac_foundation_items or [
        item for item in foundation_items if item.get("_foundationDeltaE") is not None
    ]
    foundation_delta_values = [
        float(item["_foundationDeltaE"]) for item in foundation_anchor_pool
    ]
    foundation_qualified_count = sum(
        bool((item.get("foundationSkinMatch") or {}).get("accepted"))
        for item in foundation_anchor_pool
    )
    eligible_foundation_keys = {
        item.get("candidateKey") for item in foundation_anchor_pool
        if bool((item.get("foundationSkinMatch") or {}).get("accepted"))
    }
    scored = [
        item for item in scored
        if item.get("category") != "base"
        or item.get("candidateKey") in eligible_foundation_keys
    ]
    closest_display_foundation = None
    if foundation_qualified_count == 0 and skin_lab_reliable:
        display_candidates = [
            item for item in foundation_anchor_pool
            if item.get("category") == "base"
            and (item.get("foundationSkinMatch") or {}).get("deltaE") is not None
            and FOUNDATION_SKIN_MAX_DELTA_E
                < float(item["foundationSkinMatch"]["deltaE"])
        ]
        closest_display_foundation = min(
            display_candidates,
            key=lambda item: (
                float(item.get("_foundationDeltaE")),
                -float(item["score"]),
                str(item.get("candidateKey") or ""),
            ),
            default=None,
        )
    if closest_display_foundation is not None:
        closest_delta = float(closest_display_foundation["foundationSkinMatch"]["deltaE"])
        closest_display_foundation["foundationSkinMatch"].update({
            "displayEligible": True,
            "displayStatus": "closest_available",
            "displayMaxInclusive": None,
        })
        closest_text = (
            "資料庫目前沒有與你膚色極近似（色差 0～2）的色號；"
            f"以下提供目前最相近的色號（色差 {closest_delta:.1f}）。"
            f"{FOUNDATION_IN_STORE_DISCLAIMER}"
        )
        closest_display_foundation["matchReason"] = closest_text
        closest_display_foundation["matchReasons"] = [{
            "priority": 1,
            "reasonCode": "foundation_closest_available",
            "personalized": True,
            "text": closest_text,
            "evidence": {
                "userField": "skinTone.lab", "productField": "colorLab",
                "deltaE": round(closest_delta, 2),
                "strictMaxDeltaE": FOUNDATION_SKIN_MAX_DELTA_E,
                "displayMaxDeltaE": None,
            },
        }]
        presentation = closest_display_foundation["recommendationPresentation"]
        presentation.update({
            "systemLabel": "目前最接近的可比較色號",
            "matchLabel": None,
            "showMatchPercent": False,
            "matchTier": "未達相近色號門檻",
            "headline": "目前商品清單中沒有相近色號",
            "summary": closest_text,
            "reasonTexts": [closest_text],
        })
        scored.append(closest_display_foundation)
        scored.sort(key=lambda x: (
            -float(x["score"]),
            -float(x["scoreBreakdown"]["colorScore"]),
            str(x.get("candidateKey") or ""),
        ))
    final = _diversify_categories(scored, limit)

    returned_categories = {item["coverageCategory"] for item in final}
    requested_categories = sorted({str(prod.get("coverageCategory") or prod.get("type") or prod.get("category") or "") for prod, _, _ in prepared if prod.get("coverageCategory") or prod.get("type") or prod.get("category")})
    scored_categories = {
        item.get("coverageCategory") or item.get("type") for item in scored
        if item.get("coverageCategory") or item.get("type")
    }
    foundation_requested = bool(foundation_candidate_types)
    closest_foundation_delta = min(foundation_delta_values, default=None)
    if not foundation_requested:
        foundation_match_status = "not_requested"
        foundation_status_code = None
        foundation_status_message = "本次候選沒有粉底液商品"
    elif not skin_lab_reliable:
        foundation_match_status = "unavailable"
        foundation_status_code = "SKIN_TONE_LAB_UNRELIABLE"
        foundation_status_message = "膚色 LAB 不可靠，無法驗證粉底色差是否在 0～2，因此未回傳粉底推薦"
    elif not foundation_delta_values:
        foundation_match_status = "unavailable"
        foundation_status_code = "FOUNDATION_PRODUCT_LAB_UNAVAILABLE"
        foundation_status_message = "粉底缺少可用 LAB，無法驗證色差是否在 0～2，因此未回傳粉底推薦"
    elif foundation_qualified_count == 0 and closest_display_foundation is not None:
        foundation_match_status = "closest_available"
        foundation_status_code = "FOUNDATION_CLOSEST_AVAILABLE"
        foundation_status_message = (
            "資料庫目前沒有與你膚色極近似（色差 0～2）的色號；"
            f"以下提供目前最相近的色號（色差 {closest_foundation_delta:.2f}）。"
            f"{FOUNDATION_IN_STORE_DISCLAIMER}"
        )
    else:
        foundation_match_status = "matched"
        foundation_status_code = None
        foundation_status_message = (
            f"共有 {foundation_qualified_count} 個粉底色號符合膚色色差 0～{FOUNDATION_SKIN_MAX_DELTA_E:.0f}。"
            f"{FOUNDATION_IN_STORE_DISCLAIMER}"
        )

    def skipped_reason(category: str) -> str:
        if category in scored_categories:
            return "本次 limit 已用完，未涵蓋此類別"
        if category in foundation_candidate_types:
            return foundation_status_message
        return "資料庫沒有可用商品"

    skipped = {
        category: skipped_reason(category)
        for category in requested_categories if category not in returned_categories
    }
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
    if foundation_requested and not skin_lab_reliable:
        fallback_reasons.append({
        "code": "SKIN_TONE_LAB_UNRELIABLE",
        "message": foundation_status_message,
        "affected": ["foundations"],
        })
    elif foundation_status_code in {
        "FOUNDATION_PRODUCT_LAB_UNAVAILABLE", "FOUNDATION_CLOSEST_AVAILABLE",
    }:
        fallback_reasons.append({
            "code": foundation_status_code,
            "message": foundation_status_message,
            "affected": ["foundations"],
        })
    if keyword_fallback:
        fallback_reasons.append({"code": "STYLE_KEYWORD_NO_MATCH", "message": "沒有商品命中風格關鍵字，已改以合格資料庫商品排序", "affected": []})
    fallback_reason = fallback_reasons[0] if fallback_reasons else None
    shade_recommendation = _foundation_shade_recommendation(scored, shade_candidate_pool)
    for item in shade_candidate_pool:
        item.pop("_foundationDeltaE", None)
    for item in final:
        _apply_recommendation_display_policy(item)
    for wrapped in [*primary, *alternates]:
        wrapped["matchScore"] = wrapped["product"].get("matchScore")

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
        "styleTagFallbackReason": style_tag_fallback_reason,
        "coverage": {"requested": len(requested_categories), "returned": len(returned_categories), "skipped": skipped},
        "skinToneLabReliable": skin_tone.get("labReliable") is not False,
        "colorDifferencePolicy": {
            "foundationSkinMatch": {
                "metric": "CIEDE2000", "symbol": "ΔE00",
                "minInclusive": 0.0, "maxInclusive": FOUNDATION_SKIN_MAX_DELTA_E,
                "mode": "hard_filter", "comparisonTarget": "使用者膚色與粉底色號",
            },
            "foundationAnchor": {
                "brand": foundation_anchor_brand,
                "mode": ("mac_primary_then_cross_brand_alternatives"
                         if foundation_anchor_brand else "nearest_available_brand"),
                "reason": ("膚色分類以 MAC 色號系統為主軸"
                           if foundation_anchor_brand else "目前沒有可比較的 MAC 色號"),
            },
            "foundationClosestAvailable": {
                "metric": "CIEDE2000", "symbol": "ΔE00",
                "minExclusive": FOUNDATION_SKIN_MAX_DELTA_E,
                "maxInclusive": None,
                "mode": "always_return_nearest_when_no_strict_match",
                "comparisonTarget": "使用者膚色與目前商品清單中最接近的粉底色號",
            },
            "shadeAlternative": {
                "metric": "CIEDE2000", "symbol": "ΔE00",
                "minInclusive": 0.0, "maxInclusive": SHADE_ALTERNATIVE_MAX_DELTA_E,
                "mode": "same_brand_same_series_guard",
                "comparisonTarget": "主推薦粉底與淺／深替代色",
            },
        },
        "foundationMatchStatus": {
            "status": foundation_match_status,
            "code": foundation_status_code,
            "message": foundation_status_message,
            "qualifiedCount": foundation_qualified_count,
            "evaluatedCount": len(foundation_delta_values),
            "closestDeltaE": round(closest_foundation_delta, 2) if closest_foundation_delta is not None else None,
            "displayedCandidateKey": (
                closest_display_foundation.get("candidateKey") if closest_display_foundation is not None else None
            ),
            "anchorBrand": foundation_anchor_brand,
        },
        "primary": primary,
        "alternates": alternates,
        "threshold": threshold,
        "shadeRecommendation": shade_recommendation,
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
    elif category == "base" and de is not None:
        reasons.append({"priority": 1, "reasonCode": "skin_color_match",
                        "personalized": True,
                        "text": f"此色號與您的膚色相近（色差 {de:.1f}）。{FOUNDATION_IN_STORE_DISCLAIMER}",
                        "evidence": {"userField": "skinTone.lab", "productField": "colorLab", "deltaE": round(de, 2),
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
        "lip": ("符合你的整體妝容風格", f"這款唇彩依照你的臉部特徵與{style}妝整體搭配推薦。"),
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

    comparison_copy = {
        "base": {
            "basis": "skin_tone",
            "title": "為什麼粉底要和膚色比較？",
            "text": "粉底會覆蓋大面積肌膚，所以系統會比較膚色與色號的明暗、冷暖及整體色差，降低上臉後過白、過深或色調不協調的情況。",
        },
        "lip": {
            "basis": "makeup_style",
            "title": "這款唇彩如何挑選？",
            "text": f"唇彩主要依照你的臉部特徵與{style}妝整體搭配推薦，不以原始唇色計算色差。",
        },
    }
    comparison = comparison_copy.get(category, {
        "basis": "makeup_style",
        "title": "這款商品如何挑選？",
        "text": f"這個品類不使用膚色色差排序，主要根據你選擇的{style}妝風格與商品特質推薦。",
    })

    delta_e_value = next((
        reason.get("evidence", {}).get("deltaE")
        for reason in product.get("matchReasons", [])
        if reason.get("evidence", {}).get("deltaE") is not None
    ), None)
    color_difference_explanation = None
    if category == "base" and delta_e_value is not None:
        delta_e_value = round(float(delta_e_value), 2)
        if delta_e_value <= 2:
            difference_level = "非常接近"
            difference_summary = f"兩個顏色非常接近，通常不容易察覺差異。{FOUNDATION_IN_STORE_DISCLAIMER}"
        elif delta_e_value <= 5:
            difference_level = "目前最相近色號"
            difference_summary = f"資料庫目前沒有極近似色號；這是目前最相近的選擇。{FOUNDATION_IN_STORE_DISCLAIMER}"
        elif delta_e_value <= 10:
            difference_level = "目前最相近色號"
            difference_summary = f"資料庫目前沒有極近似色號；這是目前最相近的選擇。{FOUNDATION_IN_STORE_DISCLAIMER}"
        else:
            difference_level = "目前最相近色號"
            difference_summary = f"資料庫目前沒有極近似色號；這是目前最相近的選擇。{FOUNDATION_IN_STORE_DISCLAIMER}"
        comparison_target = "膚色與粉底色號"
        foundation_acceptance_rule = {
            "minInclusive": 0.0,
            "maxInclusive": FOUNDATION_SKIN_MAX_DELTA_E,
            "accepted": delta_e_value <= FOUNDATION_SKIN_MAX_DELTA_E,
            "description": "粉底液色差 0～2 屬於極近似；若沒有極近似色號，仍回傳資料庫中最相近的一件。",
        }
        difference_ranges = [
            {"min": 0, "max": 2, "label": "符合粉底推薦門檻", "description": "與膚色非常接近，可列入粉底推薦"},
            {"minExclusive": 2, "max": None, "label": "資料庫目前最相近色號", "description": "沒有極近似色號時仍顯示最相近的一件，且不顯示 MATCH 百分比"},
        ]
        color_difference_explanation = {
            "metric": "CIEDE2000",
            "symbol": "ΔE00",
            "value": delta_e_value,
            "displayValue": f"色差 {delta_e_value:.1f}",
            "comparisonTarget": comparison_target,
            "acceptanceRule": foundation_acceptance_rule,
            "level": difference_level,
            "summary": difference_summary,
            "shortExplanation": "色差數字越小，代表兩個顏色在視覺上越接近；0 代表完全相同。",
            "fullExplanation": (
                f"系統先把{comparison_target}轉成 CIELAB，再用 CIEDE2000 比較明暗、彩度與色相。"
                + "粉底液色差 0～2 屬於極近似；找不到時仍會回傳資料庫中最相近的一件，但不顯示 MATCH 百分比。"
                + f"色差越小越接近，但照片光線、相機白平衡、螢幕與實際上妝方式仍會影響觀感。{FOUNDATION_IN_STORE_DISCLAIMER}"
            ),
            "ranges": difference_ranges,
            "qa": [
                {
                    "question": "色差數字代表什麼？",
                    "answer": "色差是兩個顏色的視覺距離，數字越小越接近，0 代表完全相同。",
                },
                {
                    "question": f"色差 {delta_e_value:.1f} 代表什麼？",
                    "answer": difference_summary,
                },
                {
                    "question": "系統怎麼計算色差？",
                    "answer": f"系統把{comparison_target}轉成 CIELAB，再用 CIEDE2000 綜合比較明暗、彩度與色相。",
                },
                {
                    "question": "色差小就一定適合嗎？",
                    "answer": f"不一定。色差用於推薦排序，實際效果仍會受到光線、膚況、螢幕與上妝方式影響。{FOUNDATION_IN_STORE_DISCLAIMER}",
                },
            ],
        }

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
    if category == "brow" and face_analysis.get("browShape"):
        raw = str(face_analysis["browShape"])
        if raw.casefold() != "unknown":
            traits.append(BROW_SHAPE_LABELS.get(raw.casefold(), raw))
    if category == "eye" and face_analysis.get("eyeShape"):
        raw = str(face_analysis["eyeShape"])
        traits.append(eye_labels.get(raw.casefold(), raw))
    if category == "lip" and face_analysis.get("lipShape"):
        raw = str(face_analysis["lipShape"])
        traits.append(lip_labels.get(raw.casefold(), raw))
    traits.append(f"{style}妝")
    low_score_sensitive_category = category in {"contour", "highlight", "brow"} and percent < 70
    show_match_percent = category != "lip" and not low_score_sensitive_category
    return {
        "systemLabel": "根據臉部分析結果",
        "matchPercent": percent if show_match_percent else None,
        "matchLabel": f"{percent}% MATCH" if show_match_percent else None,
        "showMatchPercent": show_match_percent,
        "matchTier": tier,
        "headline": headline,
        "summary": summary,
        "comparisonBasis": comparison["basis"],
        "comparisonExplanation": {"title": comparison["title"], "text": comparison["text"]},
        "colorDifferenceExplanation": color_difference_explanation,
        "suitedTraits": list(dict.fromkeys(traits)),
        "reasonTexts": [reason.get("text") for reason in product.get("matchReasons", []) if reason.get("text")][:4],
        "disclaimer": (FOUNDATION_IN_STORE_DISCLAIMER if category == "base" else
                       "推薦匹配度是系統用於商品排序的綜合結果，不代表實際上妝效果或準確率保證。"),
    }


def _apply_recommendation_display_policy(item: dict) -> None:
    """Expose only scores that are useful and appropriate for customer display."""
    presentation = item.get("recommendationPresentation") or {}
    display_score = bool(presentation.get("showMatchPercent"))
    item["displayScore"] = display_score
    item["recommendationLabel"] = (
        presentation.get("matchLabel") if display_score else "根據臉部分析結果推薦"
    )
    item["reason"] = item.get("matchReason")
    if display_score:
        return

    category = str(item.get("category") or "")
    if category in {"lip", "contour", "highlight", "brow"}:
        item["reason"] = "依妝容風格與臉部分析結果推薦"
    item["score"] = None
    item["matchScore"] = None
    item["scoreBreakdown"] = None


def _normalized_product_text(value: Any) -> str:
    """Normalize brand/series text used only for exact family boundaries."""
    return " ".join(str(value or "").strip().casefold().split())


def _foundation_family_key(item: dict) -> Optional[Tuple[str, str, str]]:
    """Return a conservative brand + product-family key.

    An explicit series id is authoritative.  Legacy rows have no series id, so
    their family name is derived only by removing the row's own shade suffix
    from the product name.  We never infer an official shade order from names.
    """
    brand = _normalized_product_text(item.get("brand"))
    if not brand:
        return None
    series_id = _normalized_product_text(item.get("seriesId"))
    if series_id:
        return brand, "series", series_id

    name = str(item.get("name") or "").strip()
    if not name:
        return None
    shade_suffixes = {
        str(value).strip() for value in (item.get("shadeName"), item.get("shadeCode"))
        if str(value or "").strip()
    }
    for suffix in sorted(shade_suffixes, key=len, reverse=True):
        if name.casefold().endswith(suffix.casefold()):
            family_name = name[:-len(suffix)].rstrip(" -–—_:/|()[]")
            if family_name:
                return brand, "name", _normalized_product_text(family_name)
    return brand, "name", _normalized_product_text(name)


def _foundation_shade_recommendation(scored: List[dict],
                                     shade_candidate_pool: Optional[List[dict]] = None) -> Optional[dict]:
    anchor_candidates = [
        item for item in scored
        if item.get("category") == "base" and item.get("lab")
        and bool((item.get("foundationSkinMatch") or {}).get("accepted"))
    ]
    if not anchor_candidates:
        return None
    foundation_pool = [
        item for item in (shade_candidate_pool if shade_candidate_pool is not None else scored)
        if item.get("category") == "base" and item.get("lab")
    ]
    anchor = min(anchor_candidates, key=lambda item: (
        float(item.get("_foundationDeltaE") if item.get("_foundationDeltaE") is not None
              else (item.get("foundationSkinMatch") or {}).get("deltaE", float("inf"))),
        -float(item.get("score") or 0),
        str(item.get("candidateKey") or ""),
    ))
    series_id, depth_index = anchor.get("seriesId"), anchor.get("depthIndex")
    anchor_brand = _normalized_product_text(anchor.get("brand"))
    official = series_id and depth_index is not None
    if official:
        same_series = [item for item in foundation_pool if item is not anchor
                       and anchor_brand
                       and _normalized_product_text(item.get("brand")) == anchor_brand
                       and item.get("seriesId") == series_id and item.get("depthIndex") is not None]
        lighter = max((item for item in same_series if item["depthIndex"] < depth_index),
                      key=lambda item: item["depthIndex"], default=None)
        darker = min((item for item in same_series if item["depthIndex"] > depth_index),
                     key=lambda item: item["depthIndex"], default=None)
    else:
        anchor_l = anchor["lab"][0]
        anchor_family = _foundation_family_key(anchor)
        def is_safe_family_alternative(item: dict) -> bool:
            shade_delta = delta_e(anchor.get("lab"), item.get("lab"))
            return (
                item is not anchor
                and anchor_family is not None
                and _foundation_family_key(item) == anchor_family
                and shade_delta is not None
                and shade_delta <= SHADE_ALTERNATIVE_MAX_DELTA_E
            )
        same_family = [
            item for item in foundation_pool if is_safe_family_alternative(item)
        ]
        lighter = min((item for item in same_family if item["lab"][0] > anchor_l),
                      key=lambda item: item["lab"][0] - anchor_l, default=None)
        darker = min((item for item in same_family if item["lab"][0] < anchor_l),
                     key=lambda item: anchor_l - item["lab"][0], default=None)
    # Even an official adjacent shade should still be a plausible comparison.
    # A large hue/chroma jump is more likely to confuse than help the shopper.
    def within_alternative_delta_cap(item: Optional[dict]) -> Optional[dict]:
        if item is None:
            return None
        shade_delta = delta_e(anchor.get("lab"), item.get("lab"))
        return item if shade_delta is not None and shade_delta <= SHADE_ALTERNATIVE_MAX_DELTA_E else None
    lighter = within_alternative_delta_cap(lighter)
    darker = within_alternative_delta_cap(darker)

    def choice(item, relation, label, description):
        if item is None:
            return None
        anchor_delta_e = delta_e(anchor.get("lab"), item.get("lab"))
        lightness_difference = float(item["lab"][0]) - float(anchor["lab"][0])
        return {
            "relation": relation, "label": label, "description": description,
            "shadeCode": item.get("shadeCode") or item.get("shadeName") or item.get("name"),
            "depthIndex": item.get("depthIndex"),
            "anchorDeltaE": round(float(anchor_delta_e), 2) if anchor_delta_e is not None else None,
            "lightnessDifference": round(lightness_difference, 2),
            "matchScore": round(float(item.get("matchScore") or 0), 4),
            "matchPercent": round(float(item.get("matchScore") or 0) * 100),
            "product": item,
        }
    return {
        "method": "official_depth_index" if official else "lab_lightness_approximation",
        "seriesId": series_id if official else None,
        "selectionScope": "same_brand_same_series",
        "alternativeMaxDeltaE": SHADE_ALTERNATIVE_MAX_DELTA_E,
        "anchor": choice(anchor, "anchor", "主推薦色號", "目前最接近你的膚色明暗與色調。"),
        "lighter": choice(lighter, "lighter_variant", "淺一階" if official else "較明亮的替代色",
                           "適合希望提亮膚色或呈現較明亮妝效時比較。"),
        "darker": choice(darker, "darker_variant", "深一階" if official else "較深的替代色",
                          "適合近期有日曬或偏好自然健康妝效時比較。"),
        "disclaimer": ("色階依同品牌同系列的正式深淺順序提供，且只回傳與主推薦色號 "
                       f"ΔE00 不超過 {SHADE_ALTERNATIVE_MAX_DELTA_E:.1f} 的相鄰色；"
                       "找不到符合條件的色號時會回傳空值。實際顏色仍可能受到光線、螢幕與上妝方式影響。"
                       if official else
                       "目前缺少品牌正式色階順序；替代色只在同品牌、同產品系列內依 L* 明度尋找，"
                       f"且與主推薦色號的 ΔE00 不得超過 {SHADE_ALTERNATIVE_MAX_DELTA_E:.1f}。"
                       "找不到符合條件的色號時會回傳空值，不會跨品牌補色，也不代表品牌定義的淺一階或深一階。"),
    }

def _diversify_categories(scored: List[dict], limit: int) -> List[dict]:
    from collections import defaultdict
    by_cat: Dict[str, List[dict]] = defaultdict(list)
    for item in scored: by_cat[item.get("coverageCategory") or item["category"]].append(item)

    # Foundation eligibility is a threshold, not a tie.  Within each
    # foundation product group, the full-precision ΔE00 is authoritative even
    # when style, behaviour or rounded match scores happen to be equal.
    for items in by_cat.values():
        if items and items[0].get("category") == "base":
            items.sort(key=lambda item: (
                float(item.get("_foundationDeltaE") if item.get("_foundationDeltaE") is not None
                      else (item.get("foundationSkinMatch") or {}).get("deltaE", float("inf"))),
                -float(item.get("score") or 0),
                str(item.get("candidateKey") or ""),
            ))

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
