import argparse
import base64
import json
import logging
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import replicate
import requests
from dotenv import load_dotenv


load_dotenv()


DEFAULT_REPLICATE_MODEL = "black-forest-labs/flux-kontext-max"
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "replicate").strip().lower() or "replicate"
REPLICATE_MODEL = os.getenv("REPLICATE_MODEL", DEFAULT_REPLICATE_MODEL).strip() or DEFAULT_REPLICATE_MODEL
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_IMAGE_API_BASE = os.getenv("OPENAI_IMAGE_API_BASE", "https://api.openai.com/v1").rstrip("/")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
# guidance 越高越會硬照 prompt 改圖，但太高會讓膚質塑膠、臉變 AI。妝容編輯優先保留真人照片質感，
# 所以預設收斂到 3.0；若 Cloud Run env 設了 RENDER_GUIDANCE，仍可覆蓋。
RENDER_GUIDANCE = float(os.getenv("RENDER_GUIDANCE", "3.0"))
# Replicate 回傳的 afterImageUrl 只是暫存網址（幾天內會失效），收藏功能需要永久網址才能長期使用。
# bucket 已經存在且 allUsers 有 objectViewer 權限（公開可讀），不需要額外簽名 URL。
GCS_BUCKET_NAME = os.getenv("GCS_RENDER_BUCKET", "decorate-me-renders")
REPLICATE_HTTP_TIMEOUT_SECONDS = max(60, int(os.getenv("REPLICATE_HTTP_TIMEOUT_SECONDS", "300")))
OPENAI_HTTP_TIMEOUT_SECONDS = max(60, int(os.getenv("OPENAI_HTTP_TIMEOUT_SECONDS", "300")))
REPLICATE_OPENAI_QUALITY = os.getenv("REPLICATE_OPENAI_QUALITY", "medium").strip().lower() or "medium"
MAX_RENDER_IMAGE_BYTES = int(os.getenv("MAX_RENDER_IMAGE_BYTES", str(8 * 1024 * 1024)))

OPENAI_MODEL_ALIASES = {
    "gpt-img2": "gpt-image-1",
    "gpt-image": "gpt-image-1",
}
REPLICATE_OPENAI_MODELS = {
    "openai/gpt-image-2",
}

# gpt-image-2 的 aspect_ratio 預設是 "1:1"。不指定的話，手機拍的直式人像會被硬塞成正方形
# （臉被裁掉或壓扁），而且妝前妝後兩張圖比例不一致，對比畫面會整個跑掉。
# 這裡從原圖算出最接近的比例送進去，讓輸出維持在同一個框裡。
GPT_IMAGE_ASPECT_RATIOS = {
    "1:1": 1.0,
    "3:2": 3 / 2,
    "2:3": 2 / 3,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
}
# 讀不出原圖尺寸時的退路：交給模型自己判斷，至少比寫死 1:1 安全
FALLBACK_ASPECT_RATIO = os.getenv("RENDER_FALLBACK_ASPECT_RATIO", "auto").strip() or "auto"

_replicate_client: replicate.Client | None = None


def upload_to_permanent_storage(temp_image_url: str) -> str | None:
    """把 Replicate 暫存網址的圖片下載後傳到 GCS，回傳永久公開網址；任何一步失敗都回傳 None，讓呼叫端 fallback 回暫存網址。"""
    try:
        from google.cloud import storage  # 延遲載入，沒裝套件或沒憑證時不應該讓整個渲染流程掛掉

        response = requests.get(temp_image_url, timeout=60)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
        ext = mimetypes.guess_extension(content_type) or ".jpg"

        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(f"rendered/{uuid.uuid4().hex}{ext}")
        blob.upload_from_string(response.content, content_type=content_type)

        return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob.name}"
    except Exception as exc:  # noqa: BLE001 — 儲存失敗不該讓渲染整支失敗，記錄後照舊回暫存網址
        print(f"[replicate_render] 上傳永久儲存失敗，fallback 回暫存網址：{exc}")
        return None


def upload_bytes_to_permanent_storage(image_bytes: bytes, content_type: str = "image/png") -> str | None:
    """把記憶體中的圖片位元組上傳到 GCS，回傳永久公開網址；失敗回 None。"""
    try:
        from google.cloud import storage

        ext = mimetypes.guess_extension(content_type) or ".png"
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(f"rendered/{uuid.uuid4().hex}{ext}")
        blob.upload_from_string(image_bytes, content_type=content_type)
        return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob.name}"
    except Exception as exc:  # noqa: BLE001
        print(f"[replicate_render] 上傳 bytes 永久儲存失敗：{exc}")
        return None


IMAGE_DATA_URL_KEYS = ("imageDataUrl", "image_data_url", "image")
IMAGE_URL_KEYS = ("imageUrl", "image_url", "photoUrl", "photo_url")
IMAGE_PATH_KEYS = ("imagePath", "image_path", "localImagePath", "local_image_path")
FACE_ANALYSIS_KEYS = ("faceAnalysis", "face_analysis", "analysis", "face")
SUGGESTION_KEYS = (
    "ollamaSuggestion",
    "ollama_suggestion",
    "textSuggestion",
    "text_suggestion",
    "suggestion",
)


def load_frontend_package(path: str) -> dict[str, Any]:
    package_path = Path(path)
    if not package_path.exists():
        raise FileNotFoundError(f"Frontend data package not found: {package_path}")
    with package_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("Frontend data package must be a JSON object.")
    return data


def first_string(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def first_dict(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return {}


def file_to_data_url(path: str) -> str:
    image_path = Path(path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    content_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def data_url_to_bytes(data_url: str) -> tuple[bytes, str]:
    if not data_url.startswith("data:") or ";base64," not in data_url:
        raise ValueError("Expected a base64 data URL.")
    header, encoded = data_url.split(",", 1)
    content_type = header[5:].split(";", 1)[0] or "image/png"
    image_bytes = base64.b64decode(encoded, validate=True)
    if len(image_bytes) > MAX_RENDER_IMAGE_BYTES:
        raise ValueError(f"Render image is too large; limit is {MAX_RENDER_IMAGE_BYTES} bytes.")
    return image_bytes, content_type


def url_to_data_url(url: str) -> str:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
    encoded = base64.b64encode(response.content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def image_from_frontend_package(frontend_package: dict[str, Any]) -> str:
    image_data_url = first_string(frontend_package, IMAGE_DATA_URL_KEYS)
    if image_data_url:
        if not image_data_url.startswith("data:"):
            raise ValueError("imageDataUrl/image must be a data URL when provided directly.")
        return image_data_url

    image_url = first_string(frontend_package, IMAGE_URL_KEYS)
    if image_url:
        return url_to_data_url(image_url)

    image_path = first_string(frontend_package, IMAGE_PATH_KEYS)
    if image_path:
        return file_to_data_url(image_path)

    raise ValueError(
        "Frontend data package must include imageDataUrl, imageUrl, or imagePath."
    )


def face_analysis_from_frontend_package(frontend_package: dict[str, Any]) -> dict[str, Any]:
    return first_dict(frontend_package, FACE_ANALYSIS_KEYS)


def suggestion_from_frontend_package(frontend_package: dict[str, Any]) -> str:
    return first_string(frontend_package, SUGGESTION_KEYS)


def style_from_frontend_package(frontend_package: dict[str, Any]) -> str:
    return first_string(frontend_package, ("style", "styleHint", "style_hint", "makeupStyle", "makeup_style"))


def make_ollama_request_prompt(face_analysis: dict[str, Any], style_hint: str) -> str:
    return (
        "You are a professional makeup recommendation assistant. "
        "Create a concise English makeup suggestion for image generation. "
        "Use the face analysis data and requested style. "
        "Preserve the person's original identity, facial structure, age, ethnicity, and expression. "
        "Return only the makeup suggestion text.\n\n"
        f"Face analysis:\n{json.dumps(face_analysis, ensure_ascii=False, indent=2)}\n\n"
        f"Requested style:\n{style_hint or 'natural flattering makeup'}"
    )


def generate_ollama_suggestion(face_analysis: dict[str, Any], style_hint: str) -> str:
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": make_ollama_request_prompt(face_analysis, style_hint),
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    suggestion = response.json().get("response", "").strip()
    if not suggestion:
        raise RuntimeError("Ollama returned an empty suggestion.")
    return suggestion


def compact_face_context(face_analysis: dict[str, Any]) -> str:
    important_keys = (
        "faceShape", "face_shape",
        "skinTone", "skin_tone",
        "eyeShape", "eye_shape",
        "lipShape", "lip_shape",
        "skinType", "skin_type",
        "features",
    )
    parts: list[str] = []
    for key in important_keys:
        value = face_analysis.get(key)
        if value:
            label = key.replace("_", " ")
            parts.append(f"{label}: {value}")
    return ", ".join(parts)


RENDER_STYLE_PROMPTS = {
    "natural": "natural everyday makeup with a sheer base, softly defined eyes, subtle blush, and a natural lip color",
    "softBaddie": "soft baddie makeup with a natural matte base, softly smudged earthy eyes, lifted liner, rosy mauve blush, and muted mauve lips",
    "richGirl": "refined rich girl makeup with a thin luminous base, muted taupe eyeshadow, softly defined brows, restrained highlight, and a nude rose lip",
    "hongKong": "Hong Kong retro makeup with a natural matte base, defined brows, warm brown smoky eyes, subtle contour, and a brick red lip",
    "koreanClean": "Korean clean makeup with a sheer dewy base, softly defined straight brows, light neutral eyeshadow, peach pink blush, and a natural MLBB lip",
    "yandere": "soft yandere-inspired makeup with a natural pale base, delicate downturned liner, restrained rosy under-eye blush, and a blurred berry red lip",
    "japaneseClear": "Japanese clear makeup with a thin satin base, airy brows, soft peach eyeshadow, translucent pink-orange blush, and a glossy coral lip",
    "mensPlain": "minimal men's grooming makeup with natural skin texture, light spot concealing, neat original brows, subtle eye definition, and a colorless or low-saturation lip",
}


def build_render_prompt(frontend_package: dict[str, Any], face_analysis: dict[str, Any], suggestion: str) -> str:
    explicit_prompt = first_string(frontend_package, ("renderPrompt", "render_prompt", "imagePrompt", "image_prompt"))
    if explicit_prompt:
        return explicit_prompt

    style_hint = style_from_frontend_package(frontend_package)
    face_context = compact_face_context(face_analysis)

    face_desc = f"This person has {face_context}." if face_context else ""
    makeup_detail = ", ".join(filter(None, [style_hint, suggestion[:300]]))
    ollama_line = f"Makeup reference (translated from advisor): {suggestion[:300].strip()}." if suggestion else ""
    parts = [
        "This is a makeup-only edit on the exact person in the input photo.",
        "Keep the output photorealistic, natural, and camera-like, with the same image quality as the input photo.",
        "Do not make the person look like AI art, a beauty filter, a doll, an illustration, a painting, CGI, a 3D render, or a studio-generated portrait.",
        face_desc,
        f"The ONLY change allowed is adding this makeup: {makeup_detail or 'natural everyday makeup'}.",
        ollama_line,
        "Do not change anything else in the image.",
        "Keep this person's face shape, facial structure, eye shape, nose, lips, skin tone, skin texture, pores, fine lines, wrinkles, facial asymmetry, and hair completely identical to the original photo.",
        "Do not smooth, airbrush, whiten, reshape, slim, enlarge eyes, alter age, alter ethnicity, or beautify facial features beyond applying visible makeup.",
        "Keep the exact same pose, posture, body position, head angle, hand position, gesture, and action as the original photo — do not let the person move, turn, or change stance.",
        "Keep clothing, background, lighting, camera angle, camera framing, and expression completely identical to the original photo.",
        "This must look like the same person in the same moment, only wearing makeup — not a different person, not a different pose, not a different photo.",
    ]
    return " ".join(p for p in parts if p)


def build_server_render_prompt(style_id: str) -> str:
    """Build the public render API prompt from an allowlisted style only."""
    normalized_style_id = (style_id or "natural").strip()
    style_prompt = RENDER_STYLE_PROMPTS.get(normalized_style_id)
    if style_prompt is None:
        raise ValueError(f"Unsupported render style: {normalized_style_id}")
    return build_render_prompt({"style": style_prompt}, {}, "")


# ─── Ollama 個人化渲染指令 ──────────────────────────────────────────────────
#
# 白名單的 styleId prompt 是固定的：每個選 Soft Baddie 的人，送給模型的指令一模一樣，
# 跟他的臉型、膚色都無關。Ollama 的建議服務其實會針對個人產出一段 renderPromptEn
# （細到眼影暈染方向、眼線形狀），但一直沒有人用它。
#
# 這裡由 render 服務**自己**去跟建議服務要那段 prompt，而不是讓前端傳進來 ——
# renderApiKey 是明文寫在前端網頁裡的，一旦開放前端送任意 prompt，任何人都能拿它
# 生成任意圖片、燒我們的 Replicate 額度。styleId 白名單是目前唯一的濫用防線，不能拆。
#
# 建議服務不可用時（它跑在組員的 Mac 上、走 Cloudflare tunnel，網址一重啟就換），
# 一律靜默退回固定的 styleId prompt —— 渲染絕不能因為建議服務掛掉而失敗。

SUGGESTION_SERVICE_URL = os.getenv("SUGGESTION_SERVICE_URL", "").rstrip("/")
SUGGESTION_SERVICE_API_KEY = os.getenv("SUGGESTION_SERVICE_API_KEY", "")
SUGGESTION_SERVICE_TIMEOUT = int(os.getenv("SUGGESTION_SERVICE_TIMEOUT", "90"))

# styleId -> 建議服務認得的風格名稱。必須跟前端 data.js 的 STYLES 對得起來，
# 否則建議服務會退回它的預設風格，產出的 prompt 就跟使用者選的風格不符。
STYLE_ID_TO_NAME = {
    "natural": "日常自然妝",
    "softBaddie": "Soft Baddie",
    "richGirl": "千金",
    "hongKong": "港風",
    "koreanClean": "韓系亞裔",
    "yandere": "病嬌",
    "japaneseClear": "日雜清透",
    "mensPlain": "男士白開水",
}


def fetch_ollama_render_prompt(style_id: str, face_analysis: dict[str, Any] | None) -> str | None:
    """跟建議服務要一段個人化的英文渲染指令。拿不到就回 None（呼叫端退回 styleId prompt）。"""
    if not SUGGESTION_SERVICE_URL:
        return None

    headers = {"Content-Type": "application/json"}
    if SUGGESTION_SERVICE_API_KEY:
        headers["X-API-Key"] = SUGGESTION_SERVICE_API_KEY

    try:
        response = requests.post(
            f"{SUGGESTION_SERVICE_URL}/suggest",
            json={
                "faceAnalysis": face_analysis or {},
                "style": STYLE_ID_TO_NAME.get(style_id, style_id),
            },
            headers=headers,
            timeout=SUGGESTION_SERVICE_TIMEOUT,
        )
        response.raise_for_status()
        prompt = (response.json().get("renderPromptEn") or "").strip()
    except Exception:
        logging.exception("建議服務取 renderPromptEn 失敗，改用 styleId 的固定 prompt")
        return None

    if not prompt:
        logging.warning("建議服務沒有回 renderPromptEn，改用 styleId 的固定 prompt")
        return None
    return prompt


def build_personalized_render_prompt(style_id: str, face_analysis: dict[str, Any] | None) -> tuple[str, str]:
    """回傳 (prompt, 來源)。來源是 'ollama' 或 'style_allowlist'，會回給前端顯示。"""
    ollama_prompt = fetch_ollama_render_prompt(style_id, face_analysis)
    if not ollama_prompt:
        return build_server_render_prompt(style_id), "style_allowlist"

    # Ollama 只負責「要上什麼妝」，identity lock 一律由我們自己疊上去 ——
    # 不能讓外部模型決定「可不可以改變這個人的長相」。
    return build_render_prompt({"renderPrompt": None, "style": ollama_prompt}, {}, ""), "ollama"


def resolve_image_model() -> str:
    raw = OPENAI_IMAGE_MODEL if IMAGE_PROVIDER == "openai" and OPENAI_IMAGE_MODEL else REPLICATE_MODEL
    return OPENAI_MODEL_ALIASES.get(raw, raw)


def current_provider() -> str:
    if IMAGE_PROVIDER not in {"replicate", "openai"}:
        raise RuntimeError(f"Unsupported IMAGE_PROVIDER: {IMAGE_PROVIDER}. Use 'replicate' or 'openai'.")
    return IMAGE_PROVIDER


def is_replicate_openai_model(model_name: str) -> bool:
    return model_name in REPLICATE_OPENAI_MODELS


def pick_aspect_ratio(image_data_url: str) -> str:
    """讀出輸入圖的寬高，回傳 gpt-image-2 支援的最接近比例。讀不出來就回退到 FALLBACK_ASPECT_RATIO。"""
    try:
        import io

        from PIL import Image

        image_bytes, _ = data_url_to_bytes(image_data_url)
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size

        if not width or not height:
            return FALLBACK_ASPECT_RATIO

        target = width / height
        return min(GPT_IMAGE_ASPECT_RATIOS, key=lambda name: abs(GPT_IMAGE_ASPECT_RATIOS[name] - target))
    except Exception as exc:  # noqa: BLE001 — 比例判斷失敗不該讓整支渲染掛掉
        print(f"[replicate_render] 無法判斷輸入圖比例，改用 {FALLBACK_ASPECT_RATIO}：{exc}")
        return FALLBACK_ASPECT_RATIO


def get_replicate_client() -> replicate.Client:
    global _replicate_client
    if _replicate_client is None:
        api_token = os.getenv("REPLICATE_API_TOKEN", "").strip() or None
        timeout = httpx.Timeout(
            timeout=REPLICATE_HTTP_TIMEOUT_SECONDS,
            connect=10.0,
            read=float(REPLICATE_HTTP_TIMEOUT_SECONDS),
            write=60.0,
            pool=60.0,
        )
        _replicate_client = replicate.Client(api_token=api_token, timeout=timeout)
    return _replicate_client


def call_openai_render(image_data_url: str, prompt: str) -> dict[str, Any]:
    model_name = resolve_image_model()
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY 未設定，gpt-img2 / gpt-image-1 無法呼叫。")

    image_bytes, content_type = data_url_to_bytes(image_data_url)
    files = {
        "image": ("input.png", image_bytes, content_type),
    }
    data = {
        "model": model_name,
        "prompt": prompt,
        "size": "1024x1024",
        "quality": "high",
        "response_format": "b64_json",
    }
    response = requests.post(
        f"{OPENAI_IMAGE_API_BASE}/images/edits",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        data=data,
        files=files,
        timeout=OPENAI_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    data_items = payload.get("data") or []
    if not data_items:
        raise RuntimeError(f"OpenAI images API 沒有回傳 data：{payload}")

    first = data_items[0]
    b64_json = first.get("b64_json")
    if not b64_json:
        raise RuntimeError(f"OpenAI images API 沒有回傳 b64_json：{payload}")

    output_bytes = base64.b64decode(b64_json)
    permanent_url = upload_bytes_to_permanent_storage(output_bytes, "image/png")
    if not permanent_url:
        raise RuntimeError("OpenAI 圖片已生成，但上傳 GCS 失敗，無法提供永久 afterImageUrl。")

    return {
        "status": "completed",
        "afterImageUrl": permanent_url,
        "replicateTempUrl": None,
        "isPermanent": True,
        "model": model_name,
        "provider": "openai",
    }


def call_replicate_render(image_data_url: str, prompt: str) -> dict[str, Any]:
    model_name = resolve_image_model()
    if current_provider() == "openai":
        return call_openai_render(image_data_url, prompt)

    if is_replicate_openai_model(model_name):
        replicate_input = {
            "prompt": prompt,
            "input_images": [image_data_url],
            "aspect_ratio": pick_aspect_ratio(image_data_url),
            "quality": REPLICATE_OPENAI_QUALITY,
            "number_of_images": 1,
            "output_format": "jpeg",
            "background": "opaque",
            "moderation": "auto",
        }
    else:
        replicate_input = {
            "prompt": prompt,
            "input_image": image_data_url,
            "output_format": "jpg",
            "output_quality": 95,
            "guidance": RENDER_GUIDANCE,
        }

    output = get_replicate_client().run(
        model_name,
        input=replicate_input,
    )

    # replicate SDK 1.x: output.url 是字串屬性；舊版才是 callable
    if hasattr(output, "url"):
        url_val = output.url
        temp_image_url = url_val() if callable(url_val) else str(url_val)
    elif isinstance(output, list):
        temp_image_url = str(output[0])
    else:
        temp_image_url = str(output)

    permanent_url = upload_to_permanent_storage(temp_image_url)

    return {
        "status": "completed",
        "afterImageUrl": permanent_url or temp_image_url,
        "replicateTempUrl": temp_image_url,
        "isPermanent": permanent_url is not None,
        "model": model_name,
        "provider": "replicate",
    }


def render_from_frontend_package(frontend_package: dict[str, Any]) -> dict[str, Any]:
    image_data_url = image_from_frontend_package(frontend_package)
    face_analysis = face_analysis_from_frontend_package(frontend_package)
    style_hint = style_from_frontend_package(frontend_package)
    suggestion = suggestion_from_frontend_package(frontend_package)

    if not suggestion:
        suggestion = generate_ollama_suggestion(face_analysis, style_hint)

    render_prompt = build_render_prompt(frontend_package, face_analysis, suggestion)
    render_result = call_replicate_render(image_data_url, render_prompt)

    return {
        "status": "completed",
        "requestId": frontend_package.get("requestId") or frontend_package.get("request_id"),
        "userId": frontend_package.get("userId") or frontend_package.get("user_id"),
        "sourcePackageId": frontend_package.get("packageId") or frontend_package.get("package_id") or frontend_package.get("id"),
        "afterImageUrl": render_result["afterImageUrl"],
        "renderPrompt": render_prompt,
        "ollamaSuggestion": suggestion,
        "faceAnalysis": face_analysis,
        "model": render_result["model"],
        "renderBaseUrl": render_result.get("provider", "replicate"),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render makeup from the frontend data package using the configured Replicate model."
    )
    parser.add_argument("package", help="Path to frontend JSON data package.")
    parser.add_argument("--output", help="Optional path to write the output JSON package.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frontend_package = load_frontend_package(args.package)
    output_package = render_from_frontend_package(frontend_package)

    output_json = json.dumps(output_package, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
    print(output_json)


if __name__ == "__main__":
    main()
