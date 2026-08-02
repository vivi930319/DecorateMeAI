"""臉部分析資料包格式。

這個模組只負責整理資料，不執行圖片分析，也不會自行呼叫其他服務。
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


# 2026-08-03：skinTone 新增 labReliable / labReliability（膚色取樣是否被頭髮遮擋）。
# 版本要跟著動——消費端靠它判斷自己拿到的是哪一版，欄位加了卻不動版本，
# 推薦端就無從得知「沒有這個欄位」是舊資料包還是新資料包漏送。
SCHEMA_VERSION = "2026-08-v2"

# 以下每張表都只列現行分類表的類別。已淘汰的名稱不放進來——
# 舊值一律在 `_code()` 入口用 LABEL_ALIASES 換成現行名稱再查表。
# 合併掉的類別不該在任何地方以「可用類別」的身分存在。
FACE_SHAPE_CODES = {
    "鵝蛋臉": "oval",
    "圓形臉": "round",
    "方形臉": "square",
    "長形臉": "oblong",
    "心形臉": "heart",
    "未知": "unknown",
}

BROW_SHAPE_CODES = {
    "一字眉": "straight",
    "彎月眉": "curved",
    "落尾眉": "drooping_tail",
    "未知": "unknown",
}

# 官方分類表（2026-07-31）：眼型四類。細長眼併入鳳眼。
EYE_SHAPE_CODES = {
    "桃杏眼": "peach_almond",
    "圓眼": "round",
    "鳳眼": "phoenix",
    "下垂眼": "downturned",
    "未知": "unknown",
}

NOSE_SHAPE_CODES = {
    "標準鼻": "standard",
    "寬鼻": "wide",
    "未知": "unknown",
}

LIP_SHAPE_CODES = {
    "厚唇": "full",
    "薄唇": "thin",
    "微笑唇": "smile",
    "花瓣唇": "petal",
    "未知": "unknown",
}

SEASON_CODES = {
    "春季": "spring",
    "夏季": "summer",
    "秋季": "autumn",
    "冬季": "winter",
}

# 已淘汰的中文標籤 → 合併後的現行標籤。
#
# 現行分類表是唯一基準：已經合併掉的類別不該再出現在任何顯示路徑上。
# 但舊資料是存在的——修正快取（face_corrections）存的是合併前的中文標籤，
# 而它套用時不會比對分類表，會把舊標籤原樣寫回結果。
#
# 處理方式是「進來就正規化」，不是讓每個下游對照表各自認得舊名：
# 下游只要認識現行類別，舊名在這裡就被換掉了。少一份要同步的清單，
# 就少一個會悄悄過期的地方（見發展歷程規格書 §7.8）。
#
# 這張表要跟 prepare_roi_cache.py 的 LABEL_ALIASES 一致——那是訓練側的同一組合併決定。
LABEL_ALIASES = {
    # 眼型（2026-07-24 / 07-30 / 07-31）
    # 注意：別名只查一次；瞇縫眼必須直接指向最終的鳳眼分類，
    # 必須跟著改成鳳眼，否則會產出一個不在分類表裡的值。
    "丹鳳眼": "鳳眼",
    "瞇縫眼": "鳳眼",
    "細長眼": "鳳眼",
    "杏仁眼": "桃杏眼",
    "桃花眼": "桃杏眼",
    # 鼻型（2026-07-24）
    "窄鼻": "標準鼻",
    "蒜頭鼻": "寬鼻",
    # 唇型（2026-07-30）
    "M型唇": "花瓣唇",
}


def canonical_label(label: Any) -> Any:
    """把已淘汰的標籤換成合併後的現行標籤；其餘原樣回傳。"""
    return LABEL_ALIASES.get(label, label) if isinstance(label, str) else label


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _code(mapping: dict[str, str], label: Any) -> str:
    """查代碼前先把已淘汰的標籤換成現行標籤。

    上面幾張表只列現行類別，所以舊值必須在這裡就被換掉，否則會落成 "unknown"。
    這是舊標籤進入系統的其中一個入口（另一個是 face_corrections.apply）。
    """
    return mapping.get(canonical_label(str(label)), "unknown")


def normalize_face_analysis(raw_result: dict[str, Any]) -> dict[str, Any]:
    """把 FaceAnalyzer 的中文輸出轉成前後端共用欄位。"""
    raw = deepcopy(raw_result)
    skin = raw.get("膚色") or {}
    version = str(raw.get("分析版本") or "BASIC").upper()

    normalized = {
        "version": version,
        "faceShape": _code(FACE_SHAPE_CODES, raw.get("臉型")),
        "browShape": _code(BROW_SHAPE_CODES, raw.get("眉型")),
        "eyeShape": _code(EYE_SHAPE_CODES, raw.get("眼型")),
        "noseFront": _code(NOSE_SHAPE_CODES, raw.get("鼻型")),
        "lipShape": _code(LIP_SHAPE_CODES, raw.get("嘴型")),
        "skinTone": {
            "season": _code(SEASON_CODES, skin.get("四季型")),
            "level": skin.get("膚色分級"),
            "lab": deepcopy(skin.get("LAB")),
            "labSource": skin.get("LAB來源", "正面照"),
            # 頭髮或陰影蓋住臉頰時膚色會算錯，而且不會報錯。推薦端拿 lab 去比色號之前
            # 要看這個旗標——缺欄位時視為可信，維持既有行為。
            "labReliable": bool((skin.get("可信度") or {}).get("reliable", True)),
            "labReliability": deepcopy(skin.get("可信度")),
        },
        "lipLab": deepcopy(raw.get("嘴唇_LAB")),
        "symmetry": deepcopy(raw.get("臉部對稱性")),
        "noseSide": None,
        "sidePhotoUsed": skin.get("LAB來源") == "正面+側面平均",
        "proStatus": deepcopy(raw.get("精細分析狀態")),
        "raw": raw,
    }
    return normalized


def build_image_info(
    original_name: str,
    content_type: str,
    size: int,
    *,
    width: int | None = None,
    height: int | None = None,
    image_url: str | None = None,
    data_url: str | None = None,
) -> dict[str, Any]:
    """建立單張圖片的描述資料；圖片本身可用 URL 或 data URL 傳遞。"""
    if size < 0:
        raise ValueError("圖片大小不能小於 0")
    return {
        "originalName": original_name,
        "originalType": content_type,
        "originalSize": size,
        "compressedImageUrl": image_url,
        "compressedDataUrl": data_url,
        "compressedWidth": width,
        "compressedHeight": height,
    }


def build_analysis_package(
    raw_result: dict[str, Any],
    front_image: dict[str, Any],
    *,
    client: str = "web",
    user_id: str | int | None = None,
    side_image: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """建立一份完整、可直接轉成 JSON 的 analysisPackage。"""
    if client not in {"web", "ios"}:
        raise ValueError("client 只接受 web 或 ios")

    now = _now_iso()
    mode = str(raw_result.get("分析版本") or "BASIC").upper()
    images = {"front": deepcopy(front_image)}
    if side_image is not None:
        images["side"] = deepcopy(side_image)

    return {
        "id": f"AN-{uuid4().hex[:12]}",
        "schemaVersion": SCHEMA_VERSION,
        "mode": mode,
        "client": client,
        "userId": user_id,
        "status": "completed",
        "createdAt": now,
        "updatedAt": now,
        "images": images,
        "faceAnalysis": normalize_face_analysis(raw_result),
        "generativeText": {
            "status": "pending",
            "provider": "ollama",
            "model": None,
            "suggestion": None,
            "renderPromptEn": None,
            "error": None,
        },
        "render": {
            "status": "pending",
            "provider": "replicate",
            "replicateTempUrl": None,
            "afterImageUrl": None,
            "savedImageId": None,
            "error": None,
        },
        "recommendations": {"products": [], "tips": [], "ads": []},
    }


def set_suggestion(
    package: dict[str, Any],
    suggestion: str,
    *,
    model: str,
    provider: str = "ollama",
    render_prompt_en: str | None = None,
) -> dict[str, Any]:
    """把中文建議與英文渲染指令寫回資料包，不改動傳入物件。"""
    result = deepcopy(package)
    result["generativeText"] = {
        "status": "completed",
        "provider": provider,
        "model": model,
        "suggestion": suggestion,
        "renderPromptEn": render_prompt_en,
        "error": None,
    }
    result["updatedAt"] = _now_iso()
    return result


def set_render_result(
    package: dict[str, Any],
    after_image_url: str,
    *,
    temporary_url: str | None = None,
    saved_image_id: str | None = None,
) -> dict[str, Any]:
    """把妝後圖片結果寫回資料包。"""
    result = deepcopy(package)
    result["render"] = {
        "status": "completed",
        "provider": "replicate",
        "replicateTempUrl": temporary_url,
        "afterImageUrl": after_image_url,
        "savedImageId": saved_image_id,
        "error": None,
    }
    result["updatedAt"] = _now_iso()
    return result
