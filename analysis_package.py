"""臉部分析資料包格式。

這個模組只負責整理資料，不執行圖片分析，也不會自行呼叫其他服務。
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = "2026-06-v1"

FACE_SHAPE_CODES = {
    "鵝蛋臉": "oval",
    "圓形臉": "round",
    "方形臉": "square",
    "長形臉": "oblong",
    "心形臉": "heart",
    "菱形臉": "diamond",
    "梯形臉": "trapezoid",
    "未知": "unknown",
}

BROW_SHAPE_CODES = {
    "一字眉": "straight",
    "彎月眉": "curved",
    "落尾眉": "drooping_tail",
    "未知": "unknown",
}

# 官方分類表（2026-07-24）：眼型六類。丹鳳眼併入鳳眼、瞇縫眼併入細長眼。
#
# 舊名稱保留成別名而不是刪掉：資料庫與既有分析包裡還存著用舊名稱寫的紀錄，
# 移除後那些會靜靜地變成 "unknown"。別名指向合併後的同一個代碼，讀舊資料才不會壞。
#
# 註：先前這張表**漏了「鳳眼」**，模型輸出鳳眼時會被 `_code` 落到 "unknown"。
# 一併補上。
EYE_SHAPE_CODES = {
    "細長眼": "slender",
    "桃杏眼": "peach_almond",
    "圓眼": "round",
    "鳳眼": "phoenix",
    "下垂眼": "downturned",
    "未知": "unknown",
    # ── 舊名稱別名（併入上面的類別，僅供讀取歷史資料）──
    "丹鳳眼": "phoenix",
    "瞇縫眼": "slender",
    "桃花眼": "peach_almond",
    "杏仁眼": "peach_almond",
}

NOSE_SHAPE_CODES = {
    "標準鼻": "standard",
    "寬鼻": "wide",
    "窄鼻": "narrow",
    "未知": "unknown",
}

LIP_SHAPE_CODES = {
    "厚唇": "full",
    "薄唇": "thin",
    "M型唇": "m_shape",
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _code(mapping: dict[str, str], label: Any) -> str:
    return mapping.get(str(label), "unknown")


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
