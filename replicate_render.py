import argparse
import base64
import binascii
import json
import logging
import mimetypes
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

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
GCS_RENDER_RETENTION_DAYS = max(1, int(os.getenv("GCS_RENDER_RETENTION_DAYS", "30")))
GCS_RENDER_PREFIX = "temporary/"
GCS_RETAINED_PREFIX = "retained/"
GCS_LEGACY_PREFIX = "rendered/"
GCS_ALLOWED_PREFIXES = (GCS_RENDER_PREFIX, GCS_RETAINED_PREFIX, GCS_LEGACY_PREFIX)
GCS_SIGNED_URL_SECONDS = max(60, min(int(os.getenv("GCS_SIGNED_URL_SECONDS", "600")), 3600))
GCS_SIGNING_SERVICE_ACCOUNT = os.getenv("GCS_SIGNING_SERVICE_ACCOUNT", "").strip()
REPLICATE_HTTP_TIMEOUT_SECONDS = max(60, int(os.getenv("REPLICATE_HTTP_TIMEOUT_SECONDS", "300")))
OPENAI_HTTP_TIMEOUT_SECONDS = max(60, int(os.getenv("OPENAI_HTTP_TIMEOUT_SECONDS", "300")))
REPLICATE_OPENAI_QUALITY = os.getenv("REPLICATE_OPENAI_QUALITY", "medium").strip().lower() or "medium"
MAX_RENDER_IMAGE_BYTES = int(os.getenv("MAX_RENDER_IMAGE_BYTES", str(8 * 1024 * 1024)))
MAX_RENDER_IMAGE_PIXELS = max(1, int(os.getenv("MAX_RENDER_IMAGE_PIXELS", "16000000")))

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


# imageUrl 可能來自前端輸入（image_from_frontend_package），所以「伺服器去下載一個
# 網址」本身就是 SSRF 破口：精心構造的網址能讓渲染服務去讀雲端 metadata
# （169.254.169.254）或內網位址。因此只允許 https、只允許這些已知圖片 host、只允許
# 443 埠；其餘一律拒絕。Replicate 的輸出落在 replicate.delivery，永久圖在 GCS。
_DEFAULT_FETCH_HOSTS = "replicate.delivery,replicate.com,storage.googleapis.com"
RENDER_FETCH_ALLOWED_HOSTS = tuple(
    h.strip().lower()
    for h in os.getenv("RENDER_FETCH_ALLOWED_HOSTS", _DEFAULT_FETCH_HOSTS).split(",")
    if h.strip()
)


def _fetch_host_is_allowed(host: str) -> bool:
    host = (host or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in RENDER_FETCH_ALLOWED_HOSTS)


def fetch_remote_image_bytes(url: str) -> tuple[bytes, str]:
    """從白名單 host 抓一張圖，邊串流邊卡住位元組上限。

    一個函式擋兩種攻擊：host 白名單堵住 SSRF（前端塞進來的網址，不能再叫我們去
    讀內網或雲端 metadata 位址）；串流＋逐塊累加上限，代表超大或無限長的回應會在
    「下載到一半」就被切斷，而不是整包吞進記憶體之後才發現太大。
    """
    parsed = urlsplit(url or "")
    if parsed.scheme != "https" or not _fetch_host_is_allowed(parsed.hostname or ""):
        raise ValueError("Image URL host is not permitted.")
    if parsed.port not in (None, 443):
        raise ValueError("Image URL port is not permitted.")
    # 刻意 allow_redirects=False：白名單裡的 host 也可能 302 轉到內網位址，跟著轉
    # 就等於從轉址重新打開 SSRF 破口。Replicate 與 GCS 都是直接回物件，本來就不需要
    # 跟隨轉址。
    with requests.get(url, timeout=60, stream=True, allow_redirects=False) as response:
        if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
            raise ValueError("Image URL redirected to an unverified location.")
        response.raise_for_status()
        declared = response.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_RENDER_IMAGE_BYTES:
            raise ValueError(f"Rendered image is too large; limit is {MAX_RENDER_IMAGE_BYTES} bytes.")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RENDER_IMAGE_BYTES:
                raise ValueError(f"Rendered image is too large; limit is {MAX_RENDER_IMAGE_BYTES} bytes.")
            chunks.append(chunk)
    content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    return b"".join(chunks), content_type


def upload_to_permanent_storage(temp_image_url: str) -> str | None:
    """把 Replicate 暫存網址的圖片下載後傳到 GCS，回傳永久公開網址；任何一步失敗都回傳 None，讓呼叫端 fallback 回暫存網址。"""
    try:
        from google.cloud import storage  # 延遲載入，沒裝套件或沒憑證時不應該讓整個渲染流程掛掉

        image_bytes, content_type = fetch_remote_image_bytes(temp_image_url)
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError(f"Unsupported rendered image content type: {content_type}")
        ext = mimetypes.guess_extension(content_type) or ".jpg"

        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(f"{GCS_RENDER_PREFIX}{uuid.uuid4().hex}{ext}")
        blob.metadata = {
            "retentionDays": str(GCS_RENDER_RETENTION_DAYS),
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        blob.upload_from_string(image_bytes, content_type=content_type)

        return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob.name}"
    except Exception:  # noqa: BLE001 — 儲存失敗不該讓渲染整支失敗，記錄後照舊回暫存網址
        logging.getLogger(__name__).exception("GCS upload failed; falling back to provider URL")
        return None


def upload_bytes_to_permanent_storage(image_bytes: bytes, content_type: str = "image/png") -> str | None:
    """把記憶體中的圖片位元組上傳到 GCS，回傳永久公開網址；失敗回 None。"""
    try:
        from google.cloud import storage

        ext = mimetypes.guess_extension(content_type) or ".png"
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(f"{GCS_RENDER_PREFIX}{uuid.uuid4().hex}{ext}")
        blob.metadata = {
            "retentionDays": str(GCS_RENDER_RETENTION_DAYS),
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        blob.upload_from_string(image_bytes, content_type=content_type)
        return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob.name}"
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("GCS byte upload failed")
        return None


def delete_permanent_storage_url(url: str | None) -> bool:
    """Delete only objects created by this service in its configured bucket."""
    if not url:
        return False
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "storage.googleapis.com":
        return False
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != GCS_BUCKET_NAME:
        return False
    blob_name = "/".join(parts[1:])
    if not blob_name.startswith(GCS_ALLOWED_PREFIXES):
        return False
    try:
        from google.cloud import storage

        storage.Client().bucket(GCS_BUCKET_NAME).blob(blob_name).delete()
        return True
    except Exception as exc:  # noqa: BLE001
        # GCS delete is idempotent for our workflow: an object that is already
        # gone satisfies the privacy deletion request and must not strand the
        # ownership record forever.
        try:
            from google.api_core.exceptions import NotFound

            if isinstance(exc, NotFound):
                return True
        except ImportError:
            pass
        logging.getLogger(__name__).warning("GCS object deletion failed: %s", exc)
        return False


def storage_object_name_from_url(url: str | None) -> str | None:
    """Return a validated object name for this service's private render bucket."""
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "storage.googleapis.com":
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != GCS_BUCKET_NAME:
        return None
    object_name = "/".join(parts[1:])
    if not object_name.startswith(GCS_ALLOWED_PREFIXES):
        return None
    return object_name


def retain_permanent_storage_url(url: str | None, owner_id: str, job_id: str, variant: str = "") -> str:
    """Copy a temporary object to the non-expiring member-owned prefix.

    `variant` 必須把同一個 job 的不同圖片分開。妝前圖與妝後圖共用 job_id，
    目的地名稱若只用 job_id 就會撞在一起——而且下面有 `destination.exists()` 檢查，
    撞到不會報錯，只會**靜默略過複製並回傳既有物件的網址**，
    結果妝前圖指向妝後圖那張。傳 "-before" 之類的後綴把它們分開。
    """
    object_name = storage_object_name_from_url(url)
    if not object_name:
        raise ValueError("Render object URL is invalid.")
    if not owner_id.startswith("actor_") or not job_id:
        raise ValueError("Render ownership is invalid.")
    if variant and not re.fullmatch(r"-[a-z]{1,16}", variant):
        # 這個值會直接進物件名稱，不能讓呼叫端塞入路徑片段
        raise ValueError("Render variant is invalid.")
    if object_name.startswith(GCS_RETAINED_PREFIX):
        return str(url)

    from google.cloud import storage

    suffix = Path(object_name).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    source = bucket.blob(object_name)
    destination_name = f"{GCS_RETAINED_PREFIX}{owner_id}/{job_id}{variant}{suffix}"
    destination = bucket.blob(destination_name)
    if not destination.exists(client=client):
        bucket.copy_blob(source, bucket, destination_name)
    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{destination_name}"


def create_signed_storage_url(url: str | None, expires_seconds: int | None = None) -> str:
    """Create a short-lived V4 URL without making the bucket public.

    Cloud Run uses its own access token and IAM Credentials signBlob.  The
    service account therefore needs Service Account Token Creator on itself;
    no downloadable JSON key is stored in the container.
    """
    object_name = storage_object_name_from_url(url)
    if not object_name:
        raise ValueError("Render object URL is invalid.")

    import google.auth
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.cloud import storage

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(GoogleAuthRequest())
    service_account_email = GCS_SIGNING_SERVICE_ACCOUNT or getattr(
        credentials, "service_account_email", ""
    )
    if not service_account_email or service_account_email == "default":
        raise RuntimeError("GCS signing service account is not configured.")

    lifetime = GCS_SIGNED_URL_SECONDS if expires_seconds is None else max(
        60, min(int(expires_seconds), 3600)
    )
    blob = storage.Client(credentials=credentials).bucket(GCS_BUCKET_NAME).blob(object_name)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=lifetime),
        method="GET",
        service_account_email=service_account_email,
        access_token=credentials.token,
    )


def download_private_storage_url(url: str | None) -> tuple[bytes, str]:
    """Read a validated private render object for authenticated proxy fallback."""
    object_name = storage_object_name_from_url(url)
    if not object_name:
        raise ValueError("Render object URL is invalid.")
    from google.cloud import storage

    blob = storage.Client().bucket(GCS_BUCKET_NAME).blob(object_name)
    blob.reload()
    if blob.size is not None and int(blob.size) > MAX_RENDER_IMAGE_BYTES:
        raise ValueError("Stored render image is too large.")
    content_type = str(blob.content_type or "application/octet-stream").split(";")[0]
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("Stored render image type is invalid.")
    return blob.download_as_bytes(), content_type


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
    """解析 data URL，回傳「驗過、去掉 EXIF／GPS」的位元組與 MIME type。

    驗證細節（magic bytes 白名單、偽 MIME、解碼前先卡像素數、移除中繼資料）統一在
    `image_safety`，跟 Face BASIC／PRO 用同一份實作。這裡只負責 data URL 的外層拆解，
    並把 `ImageRejected` 翻成呼叫端既有的 `ValueError` 契約。

    回傳的是**清洗後**的位元組：這條路徑的下一站就是第三方渲染供應商，臉部照片的
    拍攝地點與機身序號不該跟著出去。
    """
    from image_safety import ImageRejected, sanitize_image_bytes

    if not data_url.startswith("data:") or ";base64," not in data_url:
        raise ValueError("Expected a base64 data URL.")
    header, encoded = data_url.split(",", 1)
    content_type = (header[5:].split(";", 1)[0] or "image/png").lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("Only JPEG, PNG, and WebP images are supported.")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Image data URL contains invalid base64.") from exc
    try:
        cleaned, detected_type = sanitize_image_bytes(
            image_bytes,
            max_bytes=MAX_RENDER_IMAGE_BYTES,
            max_pixels=MAX_RENDER_IMAGE_PIXELS,
            label="Render image",
        )
    except ImageRejected as exc:
        raise ValueError(exc.detail["error"]["message"]) from exc
    if detected_type != content_type:
        raise ValueError("Image content type does not match its encoded image format.")
    return cleaned, content_type


def sanitize_data_url(data_url: str) -> str:
    """回傳同一張圖、但已去除中繼資料的 data URL。

    走 Replicate 的路徑是把 data URL **原封不動**送出去的（`input_images`），所以清洗
    必須發生在字串本身，只清 `data_url_to_bytes` 的回傳值救不到那條路。
    """
    cleaned, content_type = data_url_to_bytes(data_url)
    encoded = base64.b64encode(cleaned).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def url_to_data_url(url: str) -> str:
    image_bytes, content_type = fetch_remote_image_bytes(url)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    # 直接回清洗過的版本：舊寫法是「驗一次、然後回傳未清洗的原字串」，驗證的結果
    # 等於被丟掉了。
    return sanitize_data_url(f"data:{content_type};base64,{encoded}")


def image_from_frontend_package(frontend_package: dict[str, Any]) -> str:
    image_data_url = first_string(frontend_package, IMAGE_DATA_URL_KEYS)
    if image_data_url:
        if not image_data_url.startswith("data:"):
            raise ValueError("imageDataUrl/image must be a data URL when provided directly.")
        # 前端直接給的 data URL 是唯一沒經過我們解碼的入口，在這裡清一次，
        # 後面不管走 Replicate（送 data URL）或 OpenAI（送 bytes）都拿到乾淨的圖。
        return sanitize_data_url(image_data_url)

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


# 五官分類的中文標籤 -> 英文。分析模型的輸出是中文（見 models/basic_features_roi/
# *_classes.json），但送給影像模型的 prompt 是英文——不翻譯就等於把一串它讀不懂的字
# 塞進 prompt，還不如不放。這裡只收模型真的會產生的那些類別，翻不出來的整項略過，
# 寧可少一句，也不要把未知標籤原樣丟給影像模型。
#
# 這裡**只列現行分類表的類別**。已淘汰的名稱（M型唇、杏仁眼…）不放進來——
# 舊資料在 face_corrections.apply() 就已經用 analysis_package.canonical_label
# 換成合併後的名稱了，走到這裡的一律是現行類別。合併過的東西不該在下游復活。
FACE_TERM_EN = {
    # 臉型
    "圓形臉": "a round face", "心形臉": "a heart-shaped face", "方形臉": "a square face",
    "長形臉": "a long face", "鵝蛋臉": "an oval face",
    # 眼型（2026-07-30 起現行五類）
    "下垂眼": "downturned eyes", "圓眼": "round eyes", "桃杏眼": "soft almond eyes",
    "細長眼": "long narrow eyes", "鳳眼": "upturned eyes",
    # 眉型
    "一字眉": "straight brows", "彎月眉": "curved brows", "落尾眉": "downward-angled brows",
    # 鼻型
    "寬鼻": "a wide nose", "標準鼻": "a medium-width nose",
    # 唇型（2026-07-30 起現行四類；M型唇已併入花瓣唇）
    "厚唇": "full lips", "微笑唇": "upturned lips",
    "花瓣唇": "petal-shaped lips with a defined cupid's bow", "薄唇": "thin lips",
    # 膚色分級與四季型
    "白皙": "fair skin", "自然": "medium skin", "健康": "tan skin", "小麥": "deep skin",
    "春": "warm-toned", "夏": "cool-toned", "秋": "warm deep-toned", "冬": "cool clear-toned",
}


def compact_face_context(face_analysis: dict[str, Any]) -> str:
    """把臉部分析壓成一句英文的長相描述，給影像模型當上妝的依據。

    讀的是前端 AnalysisPackage.fromRawFaceAnalysis 產出的結構（faceShape / eyeShape /
    browShape / noseFront / lipShape / skinTone{season,level}），順便相容底線寫法。

    先前這裡只列了 faceShape / skinTone / eyeShape / lipShape 幾個 key，且直接把值
    f-string 進去：skinTone 其實是個物件，會印成整串 dict；中文類別名也原樣送給影像
    模型。加上 build_personalized_render_prompt 根本沒把 face_analysis 傳進來，
    這一句從頭到尾都是空的——所以無論 Ollama 有沒有接上，prompt 裡都沒有這個人的長相。
    """
    if not isinstance(face_analysis, dict):
        return ""

    def pick(*keys):
        for key in keys:
            value = face_analysis.get(key)
            if value:
                return value
        return None

    parts: list[str] = []
    for keys in (
        ("faceShape", "face_shape"),
        ("eyeShape", "eye_shape"),
        ("browShape", "brow_shape"),
        ("noseFront", "nose_front", "noseShape", "nose_shape"),
        ("lipShape", "lip_shape"),
    ):
        english = FACE_TERM_EN.get(str(pick(*keys) or "").strip())
        if english:
            parts.append(english)

    # skinTone 是物件：{season, level, lab}。要的是可讀的冷暖與深淺，不是整包 dict。
    skin = pick("skinTone", "skin_tone")
    if isinstance(skin, dict):
        tone = " ".join(filter(None, (
            FACE_TERM_EN.get(str(skin.get("season") or "").strip()),
            FACE_TERM_EN.get(str(skin.get("level") or "").strip()),
        )))
        if tone:
            parts.append(tone)
    elif skin:
        english = FACE_TERM_EN.get(str(skin).strip())
        if english:
            parts.append(english)

    return ", ".join(parts)


# 每個風格拆成四個固定段落——底妝／眉眼／腮紅修容／唇妝——而不是一長串逗號句。
# 分段的用意：(1) 模型收到帶標籤的指令，比較不會把「腮紅」的顏色套到嘴唇上；
# (2) 校妝時看得出每個風格在四個面向各自的設定，改一段不會動到其他段；
# (3) 跟建議服務的資料包段落（人臉／妝容／推薦／渲染）對得起來。
# 對外仍提供攤平後的字串（RENDER_STYLE_PROMPTS），dedup key、/health 廣告與既有測試
# 都還是拿字串用，型別不變。
RENDER_STYLE_SECTIONS = {
    "natural": {
        "base": "a sheer natural base", "eyes": "softly defined eyes with neat natural brows",
        "cheeks": "subtle blush", "lips": "a natural lip color",
    },
    "softBaddie": {
        "base": "a natural matte base", "eyes": "softly smudged earthy eyes with a lifted liner and defined brows",
        "cheeks": "rosy mauve blush with soft contour", "lips": "muted mauve lips",
    },
    "richGirl": {
        "base": "a thin luminous base", "eyes": "muted taupe eyeshadow with softly defined brows",
        "cheeks": "restrained highlight and soft contour", "lips": "a nude rose lip",
    },
    "hongKong": {
        "base": "a natural matte base", "eyes": "warm brown smoky eyes with defined brows",
        "cheeks": "subtle contour", "lips": "a brick red lip",
    },
    "koreanClean": {
        "base": "a sheer dewy base", "eyes": "light neutral eyeshadow with softly defined straight brows",
        "cheeks": "peach pink blush", "lips": "a natural MLBB lip",
    },
    "yandere": {
        "base": "a natural pale base", "eyes": "a delicate downturned liner with airy brows",
        "cheeks": "restrained rosy under-eye blush", "lips": "a blurred berry red lip",
    },
    "japaneseClear": {
        "base": "a thin satin base", "eyes": "soft peach eyeshadow with airy brows",
        "cheeks": "translucent pink-orange blush", "lips": "a glossy coral lip",
    },
    "mensPlain": {
        "base": "natural skin texture with light spot concealing", "eyes": "subtle eye definition with neat original brows",
        "cheeks": "no visible blush, only the lightest natural contour", "lips": "a colorless or low-saturation lip",
    },
}

# 四段組成一句攤平的描述，給需要字串的舊呼叫端（dedup key、health 廣告、測試）。
_STYLE_LABEL = {"natural": "natural everyday", "softBaddie": "soft baddie", "richGirl": "refined rich girl",
                "hongKong": "Hong Kong retro", "koreanClean": "Korean clean", "yandere": "soft yandere-inspired",
                "japaneseClear": "Japanese clear", "mensPlain": "minimal men's grooming"}


def _flatten_style_sections(style_id: str, sections: dict[str, str]) -> str:
    label = _STYLE_LABEL.get(style_id, style_id)
    return (f"{label} makeup with {sections['base']}, {sections['eyes']}, "
            f"{sections['cheeks']}, and {sections['lips']}")


RENDER_STYLE_PROMPTS = {
    style_id: _flatten_style_sections(style_id, sections)
    for style_id, sections in RENDER_STYLE_SECTIONS.items()
}


def format_makeup_sections(sections: dict[str, str]) -> str:
    """把四個固定段落排成帶標籤的指令，讓模型分區套色、不會把腮紅色套到唇上。"""
    ordered = (
        ("Base", sections.get("base")),
        ("Brows and eyes", sections.get("eyes")),
        ("Cheeks and contour", sections.get("cheeks")),
        ("Lips", sections.get("lips")),
    )
    return "; ".join(f"{label}: {value}" for label, value in ordered if value)


def build_render_prompt(
    frontend_package: dict[str, Any],
    face_analysis: dict[str, Any],
    suggestion: str,
    *,
    makeup_sections: dict[str, str] | None = None,
) -> str:
    explicit_prompt = first_string(frontend_package, ("renderPrompt", "render_prompt", "imagePrompt", "image_prompt"))
    if explicit_prompt:
        return explicit_prompt

    style_hint = style_from_frontend_package(frontend_package)
    face_context = compact_face_context(face_analysis)

    face_desc = f"This person has {face_context}." if face_context else ""
    # 有四段結構時，用帶標籤的分段指令；否則沿用攤平字串（Ollama 自由 prompt 走這條）。
    if makeup_sections:
        makeup_detail = format_makeup_sections(makeup_sections)
    else:
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
    sections = RENDER_STYLE_SECTIONS.get(normalized_style_id)
    if sections is None:
        raise ValueError(f"Unsupported render style: {normalized_style_id}")
    # 走四段結構：模型會收到 Base/Brows and eyes/Cheeks and contour/Lips 的分段指令。
    return build_render_prompt({}, {}, "", makeup_sections=sections)


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


class SuggestionServiceUnavailable(RuntimeError):
    """建議服務有設定，但這一次要不到 prompt。

    刻意跟「沒設定建議服務」分開：沒設定時退回 styleId 的固定 prompt 是合理的預設行為；
    設定了卻失敗，代表使用者**應該**拿到個人化的妝，卻因為上游壞了而拿到罐頭——
    那件事必須講出來，不能靜靜降級。2026-07-29 就是這樣：Render 指向一條已死的 tunnel
    超過一天，沒有任何錯誤，只是所有人的妝都變得比較泛用（見 S60）。
    """


def fetch_ollama_render_prompt(style_id: str, face_analysis: dict[str, Any] | None) -> str | None:
    """跟建議服務要一段個人化的英文渲染指令。

    回 None **只有一種情況**：根本沒設定建議服務。
    設定了卻拿不到（連不上、401、逾時、回應沒有 renderPromptEn）一律丟
    SuggestionServiceUnavailable，由呼叫端決定怎麼告訴使用者。
    """
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
    except Exception as exc:
        logging.exception("建議服務取 renderPromptEn 失敗")
        raise SuggestionServiceUnavailable("建議服務目前無法連線") from exc

    if not prompt:
        logging.warning("建議服務有回應，但沒有 renderPromptEn")
        raise SuggestionServiceUnavailable("建議服務沒有回傳渲染指令")
    return prompt


def build_personalized_render_prompt(style_id: str, face_analysis: dict[str, Any] | None) -> tuple[str, str]:
    """回傳 (prompt, 來源)。來源是 'ollama' 或 'style_allowlist'，會回給前端顯示。

    **有設定建議服務就一定要用它的輸出。** 拿不到時往上拋，不要退回 styleId 的固定 prompt——
    那個 fallback 只保留給「沒有設定建議服務」的部署。
    """
    ollama_prompt = fetch_ollama_render_prompt(style_id, face_analysis)
    if not ollama_prompt:
        # 走到這裡代表 SUGGESTION_SERVICE_URL 是空的：這個部署本來就沒有建議服務。
        return build_server_render_prompt(style_id), "style_allowlist"

    # Ollama 只負責「要上什麼妝」，identity lock 一律由我們自己疊上去 ——
    # 不能讓外部模型決定「可不可以改變這個人的長相」。
    #
    # face_analysis 一定要傳下去。先前這裡寫死 {}，於是 prompt 裡「This person has ...」
    # 那一句永遠是空的：拿去問 Ollama 的臉部資料，組 prompt 時又被丟掉，
    # 個人化只剩 Ollama 那一句話，其餘 1200 多個字元跟預設完全一樣——
    # 這就是「渲染效果跟預設沒兩樣」的來源。
    return build_render_prompt(
        {"renderPrompt": None, "style": ollama_prompt}, face_analysis or {}, ""
    ), "ollama"


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
