import os
import time
import math
import uuid
import hashlib
import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from threading import Lock

from fastapi import FastAPI, Header, HTTPException, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from api_errors import error_payload, install_api_error_handling
import job_store
from dev_server_utils import get_cors_origins
from replicate_render import (
    GCS_BUCKET_NAME,
    GCS_RENDER_RETENTION_DAYS,
    IMAGE_PROVIDER,
    RENDER_STYLE_PROMPTS,
    REPLICATE_MODEL,
    SUGGESTION_SERVICE_URL,
    build_personalized_render_prompt,
    call_replicate_render,
    create_signed_storage_url,
    data_url_to_bytes,
    delete_permanent_storage_url,
    download_private_storage_url,
    retain_permanent_storage_url,
    storage_object_name_from_url,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)
install_api_error_handling(app, "replicate-render")

# 每次渲染都真的花 Replicate 錢，加 API key 擋掉直接掃到 Cloud Run URL 的濫用。
# 正式環境務必用環境變數設定 RENDER_API_KEY；沒設定時（本機開發）不擋，但會在 /health 標明。
RENDER_API_KEY = os.getenv("RENDER_API_KEY", "")
RENDER_RATE_LIMIT_WINDOW_SECONDS = max(1, int(os.getenv("RENDER_RATE_LIMIT_WINDOW_SECONDS", "3600")))
RENDER_RATE_LIMIT_MAX_REQUESTS = max(1, int(os.getenv("RENDER_RATE_LIMIT_MAX_REQUESTS", "10")))
RENDER_QUOTA_WINDOW_SECONDS = max(60, int(os.getenv("RENDER_QUOTA_WINDOW_SECONDS", "86400")))
RENDER_QUOTA_MAX_REQUESTS = max(1, int(os.getenv("RENDER_QUOTA_MAX_REQUESTS", "30")))
RENDER_LIMIT_MAX_KEYS = max(100, int(os.getenv("RENDER_LIMIT_MAX_KEYS", "10000")))
TRUST_FORWARDED_FOR = os.getenv("TRUST_FORWARDED_FOR", "0").strip().lower() in {"1", "true", "yes"}

_rate_limit_lock = Lock()
_rate_limit_hits: dict[str, deque[float]] = {}
_quota_lock = Lock()
_quota_hits: dict[str, deque[float]] = {}

# 去重：同一張圖 + 同一 prompt 在短時間內重複請求（例如使用者狂按），直接回上次結果，不重打 Replicate 燒錢。
RENDER_DEDUP_TTL_SECONDS = max(0, int(os.getenv("RENDER_DEDUP_TTL_SECONDS", "600")))
_dedup_lock = Lock()
_dedup_cache: dict[str, tuple[float, dict]] = {}
_dedup_inflight: set[str] = set()

# 非同步 job：/render 同步版會被 Cloud Run 的請求逾時砍掉（gpt-image-2 實測 50~150 秒），
# 所以另開一組 job 端點——送出後立刻回 jobId，前端輪詢進度，不再有 504。
# job 狀態走 Firestore（不是 process 記憶體），因為這個服務 maxScale=20、concurrency=4，
# 輪詢的請求很可能被導到另一個 instance，記憶體裡的 job 在那邊根本不存在。
RENDER_JOBS_COLLECTION = os.getenv("RENDER_JOBS_COLLECTION", "render_jobs")
# 進度條的預估總秒數。Replicate 轉手 OpenAI 的排隊時間浮動極大（實測 50~150 秒），拿不到真實進度，
# 這個值只是用來把「已經等了多久」映射成 1~95% 的估算百分比，跑完才跳 100。
RENDER_ESTIMATED_SECONDS = max(10, int(os.getenv("RENDER_ESTIMATED_SECONDS", "90")))
MAX_RENDER_IMAGE_CHARS = int(os.getenv("MAX_RENDER_IMAGE_CHARS", str(12 * 1024 * 1024)))
RENDER_JOB_TIMEOUT_SECONDS = max(60, int(os.getenv("RENDER_JOB_TIMEOUT_SECONDS", "600")))
RENDER_JOB_RETENTION_SECONDS = max(60, int(os.getenv("RENDER_JOB_RETENTION_SECONDS", "3600")))
RENDER_JOB_MAX_COUNT = max(1, int(os.getenv("RENDER_JOB_MAX_COUNT", "200")))
MAX_ANALYSIS_PACKAGE_CHARS = max(1024, int(os.getenv("MAX_ANALYSIS_PACKAGE_CHARS", str(64 * 1024))))
RENDER_DURABLE_DEDUP_ENABLED = os.getenv("RENDER_DURABLE_DEDUP_ENABLED", "1").strip().lower() in {"1", "true", "yes"}


class MediaUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=1000)


def _job_expiry(seconds_from_now: int) -> datetime:
    return datetime.fromtimestamp(time.time() + seconds_from_now, timezone.utc)


def _require_job_owner(job: dict, user_id: str | None, admin_request: str | None = None) -> None:
    if str(admin_request or "").strip() == "1":
        return
    expected = str(job.get("ownerId") or "").strip()
    supplied = str(user_id or "").strip()
    if not expected or not supplied or expected != supplied:
        raise HTTPException(
            status_code=403,
            detail=error_payload("FORBIDDEN", "This render belongs to another member.", retryable=False),
        )


def _dedup_key(image: str, prompt: str, strength: float, owner_id: str = "") -> str:
    h = hashlib.sha256()
    h.update(image.encode("utf-8", "ignore"))
    h.update(b"|")
    h.update(prompt.encode("utf-8", "ignore"))
    h.update(f"|{strength}".encode("utf-8"))
    h.update(b"|")
    h.update(owner_id.encode("utf-8", "ignore"))
    return h.hexdigest()


def _dedup_get(key: str):
    if RENDER_DEDUP_TTL_SECONDS <= 0:
        return None
    now = time.time()
    with _dedup_lock:
        entry = _dedup_cache.get(key)
        if entry and now - entry[0] <= RENDER_DEDUP_TTL_SECONDS:
            return entry[1]
        if entry:
            _dedup_cache.pop(key, None)
    return None


def _dedup_set(key: str, result: dict):
    if RENDER_DEDUP_TTL_SECONDS <= 0:
        return
    now = time.time()
    with _dedup_lock:
        # 清過期 + 限制總量，避免記憶體無限成長
        for k in [k for k, (ts, _) in _dedup_cache.items() if now - ts > RENDER_DEDUP_TTL_SECONDS]:
            _dedup_cache.pop(k, None)
        if len(_dedup_cache) > 200:
            for k in sorted(_dedup_cache, key=lambda k: _dedup_cache[k][0])[:50]:
                _dedup_cache.pop(k, None)
        _dedup_cache[key] = (now, result)


def _dedup_claim(key: str) -> bool:
    with _dedup_lock:
        if key in _dedup_inflight:
            return False
        _dedup_inflight.add(key)
        return True


def _dedup_release(key: str) -> None:
    with _dedup_lock:
        _dedup_inflight.discard(key)


def _prune_limit_buckets(buckets: dict[str, deque[float]], now: float, window_seconds: int) -> None:
    window_start = now - window_seconds
    for key in list(buckets):
        bucket = buckets[key]
        while bucket and bucket[0] <= window_start:
            bucket.popleft()
        if not bucket:
            buckets.pop(key, None)
    if len(buckets) > RENDER_LIMIT_MAX_KEYS:
        oldest_keys = sorted(buckets, key=lambda key: buckets[key][0])[: len(buckets) - RENDER_LIMIT_MAX_KEYS]
        for key in oldest_keys:
            buckets.pop(key, None)


def require_api_key(x_api_key: str | None = Header(default=None)):
    if RENDER_API_KEY and x_api_key != RENDER_API_KEY:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "FORBIDDEN", "message": "Invalid or missing API key.", "retryable": False}},
        )


def _client_ip(request: Request) -> str:
    if TRUST_FORWARDED_FOR:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _rate_limit_key(request: Request, x_user_email: str | None) -> str:
    ip = _client_ip(request)
    email = (x_user_email or "").strip().lower()
    return f"{ip}|{email}" if email else ip


def _raise_limit_error(code: str, message: str, retry_after: int, *, window: int, maximum: int) -> None:
    raise HTTPException(
        status_code=429,
        headers={"Retry-After": str(retry_after)},
        detail=error_payload(
            code,
            message,
            retryable=True,
            windowSeconds=window,
            maxRequests=maximum,
            retryAfterSeconds=retry_after,
        ),
    )


def enforce_render_rate_limit(request: Request, x_user_email: str | None = Header(default=None)):
    now = time.time()
    window_start = now - RENDER_RATE_LIMIT_WINDOW_SECONDS
    key = _rate_limit_key(request, x_user_email)

    with _rate_limit_lock:
        _prune_limit_buckets(_rate_limit_hits, now, RENDER_RATE_LIMIT_WINDOW_SECONDS)
        bucket = _rate_limit_hits.setdefault(key, deque())
        while bucket and bucket[0] <= window_start:
            bucket.popleft()
        if len(bucket) >= RENDER_RATE_LIMIT_MAX_REQUESTS:
            retry_after = max(1, int(bucket[0] + RENDER_RATE_LIMIT_WINDOW_SECONDS - now))
            _raise_limit_error(
                "RATE_LIMITED",
                f"Render rate limit exceeded. Try again in {retry_after} seconds.",
                retry_after,
                window=RENDER_RATE_LIMIT_WINDOW_SECONDS,
                maximum=RENDER_RATE_LIMIT_MAX_REQUESTS,
            )
        bucket.append(now)


def enforce_render_quota(request: Request, x_user_email: str | None = None) -> None:
    """Reserve one provider call for the configured user/IP quota."""
    now = time.time()
    key = _rate_limit_key(request, x_user_email)
    durable_result = job_store.consume_window_quota(
        "render_quota_counters",
        key,
        RENDER_QUOTA_WINDOW_SECONDS,
        RENDER_QUOTA_MAX_REQUESTS,
        now=now,
    )
    if durable_result is not None:
        allowed, _count, retry_after = durable_result
        if not allowed:
            _raise_limit_error(
                "QUOTA_EXCEEDED",
                f"Render daily quota exceeded. Try again in {retry_after} seconds.",
                retry_after,
                window=RENDER_QUOTA_WINDOW_SECONDS,
                maximum=RENDER_QUOTA_MAX_REQUESTS,
            )
        return
    window_start = now - RENDER_QUOTA_WINDOW_SECONDS
    with _quota_lock:
        _prune_limit_buckets(_quota_hits, now, RENDER_QUOTA_WINDOW_SECONDS)
        bucket = _quota_hits.setdefault(key, deque())
        while bucket and bucket[0] <= window_start:
            bucket.popleft()
        if len(bucket) >= RENDER_QUOTA_MAX_REQUESTS:
            retry_after = max(1, int(bucket[0] + RENDER_QUOTA_WINDOW_SECONDS - now))
            _raise_limit_error(
                "QUOTA_EXCEEDED",
                f"Render daily quota exceeded. Try again in {retry_after} seconds.",
                retry_after,
                window=RENDER_QUOTA_WINDOW_SECONDS,
                maximum=RENDER_QUOTA_MAX_REQUESTS,
            )
        bucket.append(now)


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    image: str = Field(min_length=32, max_length=MAX_RENDER_IMAGE_CHARS)
    styleId: str = Field(default="natural", min_length=1, max_length=64)
    strength: float = Field(default=0.35, ge=0, le=1)  # flux-kontext-pro 不用 strength，保留欄位維持前端相容

    # 全站串接統一走 analysisPackage，渲染也不例外。
    #
    # 但這裡只從資料包讀「結構化資料」（faceAnalysis、styleId），
    # **資料包裡的 generativeText.renderPromptEn 一律忽略** ——
    # 那是前端送來的，可以被竄改，而 renderApiKey 是明文寫在網頁裡的：
    # 一旦照著它渲染，任何人都能拿這把 key 送任意 prompt、用我們的 Replicate 額度生成任意圖片。
    # 要下給模型的 prompt，後端自己去跟建議服務要（build_personalized_render_prompt）。
    #
    # 若之後要讓前端送的 prompt 也能被信任，做法是請建議服務對 renderPromptEn 加 HMAC 簽章，
    # render 這邊驗簽 —— 前端就能送 prompt，但編不出有效簽章。那需要建議服務端配合改程式。
    analysisPackage: dict | None = None
    faceAnalysis: dict | None = None  # 舊前端相容：沒送資料包時，單獨給臉部分析也行


def _validate_render_request(req: RenderRequest) -> None:
    image = req.image or ""
    if not image.startswith("data:image/") or ";base64," not in image:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "INVALID_IMAGE", "message": "image must be a base64 image data URL.", "retryable": False}},
        )
    if len(image) > MAX_RENDER_IMAGE_CHARS:
        raise HTTPException(
            status_code=413,
            detail={
                "error": {
                    "code": "IMAGE_TOO_LARGE",
                    "message": "Render image payload is too large.",
                    "retryable": False,
                    "maxImageChars": MAX_RENDER_IMAGE_CHARS,
                }
            },
        )
    try:
        data_url_to_bytes(image)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=error_payload("INVALID_IMAGE", str(exc), retryable=False),
        ) from None
    for field_name, value in (
        ("analysisPackage", req.analysisPackage),
        ("faceAnalysis", req.faceAnalysis),
    ):
        if value is not None:
            try:
                encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail=error_payload("INVALID_ANALYSIS_PACKAGE", f"{field_name} must be JSON data.", retryable=False),
                ) from None
            if len(encoded) > MAX_ANALYSIS_PACKAGE_CHARS:
                raise HTTPException(
                    status_code=413,
                    detail=error_payload(
                        "ANALYSIS_PACKAGE_TOO_LARGE",
                        f"{field_name} is too large.",
                        retryable=False,
                        maxChars=MAX_ANALYSIS_PACKAGE_CHARS,
                    ),
                )


def _render_inputs(req: RenderRequest) -> tuple[str, dict | None]:
    """從請求裡取出組 prompt 需要的兩樣東西：styleId 與 faceAnalysis。

    優先讀 analysisPackage（全站串接統一走資料包），沒有的話才看單獨的欄位。
    **刻意不讀資料包裡的 generativeText.renderPromptEn** —— 見 RenderRequest 的說明。
    """
    package = req.analysisPackage or {}
    face = req.faceAnalysis or package.get("faceAnalysis")

    style_id = req.styleId
    if (not style_id or style_id == "natural") and isinstance(package.get("render"), dict):
        style_id = package["render"].get("styleId") or style_id

    return style_id, face


def _server_render_prompt(req: RenderRequest) -> tuple[str, str]:
    """回傳 (prompt, promptSource)。

    優先跟建議服務要個人化的 renderPromptEn；拿不到就退回 styleId 白名單的固定 prompt。
    無論走哪一條，prompt 都是後端組的 —— 前端送進來的只有結構化資料，不是指令。
    """
    style_id, face_analysis = _render_inputs(req)
    if not isinstance(style_id, str) or style_id not in RENDER_STYLE_PROMPTS:
        raise HTTPException(
            status_code=422,
            detail=error_payload(
                "INVALID_RENDER_STYLE",
                "Unsupported render style.",
                retryable=False,
                allowedStyleIds=sorted(RENDER_STYLE_PROMPTS),
            ),
        )
    if face_analysis is not None and not isinstance(face_analysis, dict):
        raise HTTPException(
            status_code=400,
            detail=error_payload("INVALID_FACE_ANALYSIS", "faceAnalysis must be an object.", retryable=False),
        )
    try:
        return build_personalized_render_prompt(style_id, face_analysis)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=error_payload("INVALID_RENDER_STYLE", "Unsupported render style.", retryable=False),
        ) from None


def _durable_dedup_job(key: str) -> dict | None:
    if not RENDER_DURABLE_DEDUP_ENABLED:
        return None
    try:
        matches = job_store.find_by_field(RENDER_JOBS_COLLECTION, "dedupKey", key, limit=5)
    except Exception as exc:
        logging.getLogger(__name__).warning("durable dedup lookup unavailable: %s", exc)
        return None
    for job in matches:
        if job.get("status") in {"queued", "running"}:
            raise HTTPException(
                status_code=409,
                detail=error_payload(
                    "DUPLICATE_IN_PROGRESS",
                    "An identical render is already in progress. Continue polling the original job.",
                    retryable=True,
                ),
            )
        if job.get("status") == "completed" and job.get("afterImageUrl"):
            return job
    return None


def _response_from_completed_job(job: dict) -> dict:
    return {
        "status": "completed",
        "afterImageUrl": job.get("afterImageUrl"),
        "replicateTempUrl": job.get("replicateTempUrl"),
        "isPermanent": job.get("isPermanent", False),
        "model": job.get("model"),
        "renderPrompt": job.get("renderPrompt"),
        "promptSource": job.get("promptSource"),
        "error": None,
    }


def _storage_configured() -> bool:
    # 輕量檢查：只確認套件裝好、預設憑證能建立 client，不會真的呼叫 GCS API（bucket() 是本地物件，不打網路）
    try:
        from google.cloud import storage

        client = storage.Client()
        return bool(client.bucket(GCS_BUCKET_NAME))
    except Exception:
        return False


def _epoch(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _delete_job_artifact(job: dict, force: bool = False) -> None:
    url = job.get("afterImageUrl")
    if url and job.get("isPermanent"):
        if not force:
            references = job_store.find_by_field(
                RENDER_JOBS_COLLECTION, "afterImageUrl", url, limit=50
            )
            current_id = str(job.get("jobId") or "")
            if any(
                str(reference.get("jobId") or "") != current_id
                and reference.get("retained")
                for reference in references
            ):
                return
        delete_permanent_storage_url(url)


def _cleanup_render_jobs() -> None:
    now = time.time()
    jobs = job_store.all_jobs(RENDER_JOBS_COLLECTION)
    to_delete = []
    for job in jobs:
        job_id = job.get("jobId")
        status = job.get("status")
        if not job_id:
            continue
        if status in {"queued", "running"}:
            anchor = _epoch(job.get("startedAt") or job.get("createdAt"), now)
            if now - anchor > RENDER_JOB_TIMEOUT_SECONDS:
                did_timeout = job_store.patch_if_status(
                    RENDER_JOBS_COLLECTION,
                    job_id,
                    {"queued", "running"},
                    {
                        "status": "failed",
                        "progress": int(job.get("progress") or 0),
                        "afterImageUrl": None,
                        "error": {
                            "code": "RENDER_TIMEOUT",
                            "message": f"Render job timed out after {RENDER_JOB_TIMEOUT_SECONDS} seconds.",
                            "retryable": True,
                        },
                        "finishedAt": now,
                        "updatedAt": now,
                    },
                )
                if did_timeout:
                    logging.warning("render job timed out job_id=%s", job_id)
        elif status in {"completed", "failed"}:
            # A retained job is the ownership record behind /media/render/{id}.
            # It stays until the saved look or member is explicitly deleted.
            if job.get("retained"):
                continue
            finished_at = _epoch(job.get("finishedAt") or job.get("createdAt"), now)
            if now - finished_at > RENDER_JOB_RETENTION_SECONDS:
                _delete_job_artifact(job)
                to_delete.append(job_id)

    for job_id in to_delete:
        job_store.delete(RENDER_JOBS_COLLECTION, job_id)

    remaining = job_store.all_jobs(RENDER_JOBS_COLLECTION)
    if len(remaining) > RENDER_JOB_MAX_COUNT:
        removable = [job for job in remaining if not job.get("retained")]
        ordered = sorted(removable, key=lambda item: float(item.get("createdAt") or 0))
        for job in ordered[: max(0, len(remaining) - RENDER_JOB_MAX_COUNT)]:
            job_id = job.get("jobId")
            if job_id:
                _delete_job_artifact(job)
                job_store.delete(RENDER_JOBS_COLLECTION, job_id)


@app.get("/health")
def health():
    _cleanup_render_jobs()
    return {
        "status": "ok",
        "service": "replicate-render",
        "provider": IMAGE_PROVIDER,
        "model": REPLICATE_MODEL,
        "token_configured": bool(os.getenv("REPLICATE_API_TOKEN")),
        "openai_api_configured": bool(os.getenv("OPENAI_API_KEY")),
        "storage_configured": _storage_configured(),
        "storage_bucket": GCS_BUCKET_NAME,
        "storage_retention_days": GCS_RENDER_RETENTION_DAYS,
        "api_key_required": bool(RENDER_API_KEY),
        "rate_limit": {
            "enabled": True,
            "window_seconds": RENDER_RATE_LIMIT_WINDOW_SECONDS,
            "max_requests": RENDER_RATE_LIMIT_MAX_REQUESTS,
        },
        "quota": {
            "enabled": True,
            "window_seconds": RENDER_QUOTA_WINDOW_SECONDS,
            "max_requests": RENDER_QUOTA_MAX_REQUESTS,
            "key": "email+ip when supplied; otherwise ip",
        },
        "dedup": {
            "enabled": RENDER_DEDUP_TTL_SECONDS > 0,
            "ttl_seconds": RENDER_DEDUP_TTL_SECONDS,
            "durable_enabled": RENDER_DURABLE_DEDUP_ENABLED,
        },
        "limits": {
            "max_image_chars": MAX_RENDER_IMAGE_CHARS,
            "max_analysis_package_chars": MAX_ANALYSIS_PACKAGE_CHARS,
        },
        "render_prompt_policy": {
            # 前端永遠不能送自由文字 prompt —— renderApiKey 是明文公開的，
            # 開放的話任何人都能用它生成任意圖片、燒我們的 Replicate 額度。
            "client_prompt_accepted": False,
            "allowed_style_ids": sorted(RENDER_STYLE_PROMPTS),
            # prompt 由後端組：優先跟建議服務要個人化的 renderPromptEn，拿不到就退回 styleId 白名單。
            "personalized_prompt_enabled": bool(SUGGESTION_SERVICE_URL),
            "fallback": "style_allowlist",
        },
        "async_jobs": {
            "enabled": True,
            "submit": "POST /render/jobs",
            "poll": "GET /render/jobs/{job_id}",
            "delete": "DELETE /render/jobs/{job_id}",
            "estimated_seconds": RENDER_ESTIMATED_SECONDS,
            "timeout_seconds": RENDER_JOB_TIMEOUT_SECONDS,
            "retention_seconds": RENDER_JOB_RETENTION_SECONDS,
            "max_count": RENDER_JOB_MAX_COUNT,
        },
    }


@app.post("/render")
async def render(
    req: RenderRequest,
    request: Request,
    x_user_email: str | None = Header(default=None),
    _=Depends(require_api_key),
    __=Depends(enforce_render_rate_limit),
):
    _validate_render_request(req)
    prompt, prompt_source = _server_render_prompt(req)
    # 同圖同後端產生的 prompt 短時間內重複 → 直接回上次結果，不重打 Replicate
    key = _dedup_key(req.image, prompt, req.strength, str(x_user_email or "").strip())
    cached = _dedup_get(key)
    if cached is not None:
        return {**cached, "deduped": True}
    durable = _durable_dedup_job(key)
    if durable is not None:
        response = _response_from_completed_job(durable)
        _dedup_set(key, response)
        return {**response, "deduped": True}
    if not _dedup_claim(key):
        raise HTTPException(
            status_code=409,
            detail=error_payload(
                "DUPLICATE_IN_PROGRESS",
                "An identical render is already in progress. Please wait for it to finish.",
                retryable=True,
            ),
        )
    try:
        enforce_render_quota(request, x_user_email)
        result = call_replicate_render(req.image, prompt)
        response = {
            "status": "completed",
            "afterImageUrl": result["afterImageUrl"],
            "replicateTempUrl": result.get("replicateTempUrl"),
            "isPermanent": result.get("isPermanent", False),
            "model": result["model"],
            # 回傳實際送給模型的 prompt，讓前端可以顯示「這次到底下了什麼指令」。
            # prompt 一律由後端組（Ollama 個人化，或退回 styleId 白名單），不含使用者自由輸入。
            # 看不到它的話，渲染結果不如預期時根本無從判斷是 prompt 的問題還是模型的問題。
            "renderPrompt": prompt,
            "promptSource": prompt_source,  # 'ollama' 或 'style_allowlist'（建議服務掛掉時）
            "error": None,
        }
        _dedup_set(key, response)  # 只快取成功結果
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("render provider failed")
        raise HTTPException(
            status_code=502,
            detail=error_payload("RENDER_PROVIDER_ERROR", "渲染服務暫時無法完成，請稍後再試。", retryable=True),
        ) from exc
    finally:
        _dedup_release(key)


def _estimate_progress(job: dict, now: float) -> int:
    """把已經等待的秒數映射成 1~95 的估算進度。Replicate 不回報真實進度，這只是給進度條用的體感值。

    用指數曲線而不是線性：前段跑得快（使用者立刻看到動），越接近 95 越慢，
    這樣就算實際耗時衝到 150 秒也永遠不會提前塞滿、卡在 100% 空轉。
    """
    status = job.get("status")
    if status == "completed":
        return 100
    if status == "failed":
        return int(job.get("progress") or 0)

    created_at = float(job.get("createdAt") or now)
    elapsed = max(0.0, now - created_at)
    ratio = 1.0 - math.exp(-elapsed / (RENDER_ESTIMATED_SECONDS * 0.45))
    return max(1, min(95, int(round(1 + 94 * ratio))))


def _job_view(job: dict, include_token: bool = False) -> dict:
    if include_token:
        return {k: v for k, v in job.items() if k != "dedupKey"}
    return {k: v for k, v in job.items() if k not in {"resultToken", "dedupKey"}}


def _verify_job_token(job: dict, x_job_token: str | None = None, result_token: str | None = None) -> None:
    expected = job.get("resultToken")
    if expected and (x_job_token or result_token) != expected:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "FORBIDDEN", "message": "Invalid or missing job token.", "retryable": False}},
        )


def _run_render_job(
    job_id: str,
    image: str,
    prompt: str,
    prompt_source: str,
    dedup_key: str,
) -> None:
    now = time.time()
    if not job_store.patch_if_status(
        RENDER_JOBS_COLLECTION,
        job_id,
        {"queued"},
        {"status": "running", "startedAt": now, "updatedAt": now},
    ):
        _dedup_release(dedup_key)
        return
    try:
        result = call_replicate_render(image, prompt)
        response = {
            "status": "completed",
            "afterImageUrl": result["afterImageUrl"],
            "replicateTempUrl": result.get("replicateTempUrl"),
            "isPermanent": result.get("isPermanent", False),
            "model": result["model"],
            "renderPrompt": prompt,  # 同 /render：讓前端能顯示實際下給模型的指令
            "promptSource": prompt_source,
            "error": None,
        }
        did_complete = job_store.patch_if_status(
            RENDER_JOBS_COLLECTION,
            job_id,
            {"running"},
            {
                **response,
                "objectName": storage_object_name_from_url(response.get("afterImageUrl")),
                "progress": 100,
                "finishedAt": time.time(),
                "updatedAt": time.time(),
                "expiresAt": _job_expiry(RENDER_JOB_RETENTION_SECONDS),
            },
        )
        if did_complete:
            _dedup_set(dedup_key, response)  # 只快取成功結果
        else:
            # cleanup 可能已把 job 標成 timeout，避免 late result 留下永久圖片。
            delete_permanent_storage_url(response.get("afterImageUrl"))
    except Exception:  # 失敗要寫回 job，不能讓 thread 靜靜死掉
        logging.exception("渲染失敗（job %s）", job_id)
        job_store.patch_if_status(
            RENDER_JOBS_COLLECTION,
            job_id,
            {"running"},
            {
                "status": "failed",
                "afterImageUrl": None,
                "error": {
                    "code": "RENDER_PROVIDER_ERROR",
                    "message": "渲染服務暫時無法完成，請稍後再試。",
                    "retryable": True,
                },
                "finishedAt": time.time(),
                "updatedAt": time.time(),
            },
        )
    finally:
        _dedup_release(dedup_key)


@app.post("/render/jobs")
async def create_render_job(
    req: RenderRequest,
    request: Request,
    x_user_email: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    _=Depends(require_api_key),
    __=Depends(enforce_render_rate_limit),
):
    """送出渲染並立刻回 jobId；實際渲染在背景 thread 跑，前端用 GET /render/jobs/{id} 輪詢。

    注意：這需要 Cloud Run 開 --no-cpu-throttling，否則回應送出後 CPU 會被節流，背景 thread 形同停住。
    """
    _cleanup_render_jobs()
    _validate_render_request(req)
    prompt, prompt_source = _server_render_prompt(req)
    job_id = uuid.uuid4().hex
    result_token = uuid.uuid4().hex
    now = time.time()
    owner_id = str(x_user_id or "").strip()
    if not owner_id:
        raise HTTPException(
            status_code=401,
            detail=error_payload("MEMBER_ID_REQUIRED", "A verified member identity is required.", retryable=False),
        )
    key = _dedup_key(req.image, prompt, req.strength, owner_id)

    cached = _dedup_get(key)
    if cached is not None:
        job = {
            **cached,
            "jobId": job_id,
            "progress": 100,
            "createdAt": now,
            "finishedAt": now,
            "deduped": True,
            "resultToken": result_token,
            "ownerId": owner_id,
            "retained": False,
            "expiresAt": _job_expiry(RENDER_JOB_RETENTION_SECONDS),
        }
        job_store.create(RENDER_JOBS_COLLECTION, job_id, job)
        return {**_job_view(job, include_token=True), "estimatedSeconds": RENDER_ESTIMATED_SECONDS}

    durable = _durable_dedup_job(key)
    if durable is not None:
        job = {
            **_response_from_completed_job(durable),
            "jobId": job_id,
            "progress": 100,
            "createdAt": now,
            "finishedAt": now,
            "updatedAt": now,
            "deduped": True,
            "dedupKey": key,
            "resultToken": result_token,
            "ownerId": owner_id,
            "retained": False,
            "expiresAt": _job_expiry(RENDER_JOB_RETENTION_SECONDS),
        }
        job_store.create(RENDER_JOBS_COLLECTION, job_id, job)
        return {**_job_view(job, include_token=True), "estimatedSeconds": RENDER_ESTIMATED_SECONDS}

    if not _dedup_claim(key):
        raise HTTPException(
            status_code=409,
            detail=error_payload(
                "DUPLICATE_IN_PROGRESS",
                "An identical render is already in progress. Continue polling the original job.",
                retryable=True,
            ),
        )
    try:
        enforce_render_quota(request, x_user_email)
    except Exception:
        _dedup_release(key)
        raise

    job = {
        "jobId": job_id,
        "resultToken": result_token,
        "status": "queued",
        "progress": 1,
        "afterImageUrl": None,
        "renderPrompt": prompt,  # 一開始就給，前端等待期間就能顯示這次下了什麼指令
        "promptSource": prompt_source,
        "error": None,
        "createdAt": now,
        "updatedAt": now,
        "dedupKey": key,
        "ownerId": owner_id,
        "retained": False,
        "expiresAt": _job_expiry(RENDER_JOB_TIMEOUT_SECONDS + RENDER_JOB_RETENTION_SECONDS),
    }
    try:
        job_store.create(RENDER_JOBS_COLLECTION, job_id, job)

        threading.Thread(
            target=_run_render_job,
            args=(job_id, req.image, prompt, prompt_source, key),
            daemon=True,
        ).start()
    except Exception:
        _dedup_release(key)
        raise

    return {**_job_view(job, include_token=True), "estimatedSeconds": RENDER_ESTIMATED_SECONDS}


@app.get("/render/jobs/{job_id}")
async def get_render_job(
    job_id: str,
    _=Depends(require_api_key),
    x_job_token: str | None = Header(default=None),
    result_token: str | None = Query(default=None),
):
    # 這支會被前端每兩秒打一次，所以不掛 rate limit，否則輪詢自己就會把配額燒光
    job = job_store.get(RENDER_JOBS_COLLECTION, job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "JOB_NOT_FOUND", "message": "Render job not found or expired.", "retryable": False}},
        )
    _verify_job_token(job, x_job_token=x_job_token, result_token=result_token)
    view = _job_view(job)
    return {**view, "progress": _estimate_progress(job, time.time()), "estimatedSeconds": RENDER_ESTIMATED_SECONDS}


@app.get("/render/jobs/{job_id}/signed-url")
async def get_render_signed_url(
    job_id: str,
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
    _=Depends(require_api_key),
):
    """Issue a short-lived URL after checking the render's member owner."""
    job = job_store.get(RENDER_JOBS_COLLECTION, job_id)
    if job is None or job.get("status") != "completed" or not job.get("afterImageUrl"):
        raise HTTPException(
            status_code=404,
            detail=error_payload("JOB_NOT_FOUND", "Render image was not found.", retryable=False),
        )
    _require_job_owner(job, x_user_id, x_admin_request)
    try:
        signed_url = create_signed_storage_url(job.get("afterImageUrl"))
    except Exception as exc:
        logging.getLogger(__name__).exception("signed render URL creation failed")
        raise HTTPException(
            status_code=503,
            detail=error_payload("SIGNED_URL_UNAVAILABLE", "Render image is temporarily unavailable.", retryable=True),
        ) from exc
    return {"signedUrl": signed_url, "expiresIn": 600}


@app.get("/render/jobs/{job_id}/content")
async def get_render_content(
    job_id: str,
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
    _=Depends(require_api_key),
):
    """Authenticated private-object fallback when IAM signBlob is unavailable."""
    job = job_store.get(RENDER_JOBS_COLLECTION, job_id)
    if job is None or job.get("status") != "completed" or not job.get("afterImageUrl"):
        raise HTTPException(
            status_code=404,
            detail=error_payload("JOB_NOT_FOUND", "Render image was not found.", retryable=False),
        )
    _require_job_owner(job, x_user_id, x_admin_request)
    try:
        content, content_type = download_private_storage_url(job.get("afterImageUrl"))
    except Exception as exc:
        logging.getLogger(__name__).exception("private render image download failed")
        raise HTTPException(
            status_code=503,
            detail=error_payload("MEDIA_UNAVAILABLE", "Render image is temporarily unavailable.", retryable=True),
        ) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/render/jobs/{job_id}/retain")
async def retain_render_job(
    job_id: str,
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
    _=Depends(require_api_key),
):
    """Keep the ownership record and object until the member deletes it."""
    job = job_store.get(RENDER_JOBS_COLLECTION, job_id)
    if job is None or job.get("status") != "completed":
        raise HTTPException(
            status_code=404,
            detail=error_payload("JOB_NOT_FOUND", "Render image was not found.", retryable=False),
        )
    _require_job_owner(job, x_user_id, x_admin_request)
    try:
        retained_url = retain_permanent_storage_url(
            job.get("afterImageUrl"),
            str(job.get("ownerId") or ""),
            job_id,
        )
    except Exception as exc:
        logging.getLogger(__name__).exception("retained render copy failed")
        raise HTTPException(
            status_code=503,
            detail=error_payload("RETAIN_FAILED", "Render image could not be retained.", retryable=True),
        ) from exc
    job_store.patch(
        RENDER_JOBS_COLLECTION,
        job_id,
        {
            "retained": True,
            "afterImageUrl": retained_url,
            "objectName": storage_object_name_from_url(retained_url),
            "updatedAt": time.time(),
        },
    )
    job_store.unset(RENDER_JOBS_COLLECTION, job_id, ["expiresAt"])
    return {"status": "retained", "jobId": job_id}


@app.delete("/render/jobs/{job_id}/artifact")
async def delete_owned_render_artifact(
    job_id: str,
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
    _=Depends(require_api_key),
):
    job = job_store.get(RENDER_JOBS_COLLECTION, job_id)
    if job is None:
        return {"status": "not_found", "jobId": job_id}
    _require_job_owner(job, x_user_id, x_admin_request)
    if job.get("status") in {"queued", "running"}:
        raise HTTPException(
            status_code=409,
            detail=error_payload("JOB_IN_PROGRESS", "A running render job cannot be deleted yet.", retryable=True),
        )
    _delete_job_artifact(job)
    job_store.delete(RENDER_JOBS_COLLECTION, job_id)
    return {"status": "deleted", "jobId": job_id}


@app.post("/render/media/sign")
async def sign_legacy_render_media(req: MediaUrlRequest, _=Depends(require_api_key)):
    """Refresh a legacy saved GCS URL after the Gateway verified DB ownership."""
    if not storage_object_name_from_url(req.url):
        raise HTTPException(
            status_code=400,
            detail=error_payload("INVALID_MEDIA_URL", "Render object URL is invalid.", retryable=False),
        )
    return {"signedUrl": create_signed_storage_url(req.url), "expiresIn": 600}


@app.post("/render/media/content")
async def get_legacy_render_media(req: MediaUrlRequest, _=Depends(require_api_key)):
    """Internal authenticated fallback for a legacy saved object URL."""
    if not storage_object_name_from_url(req.url):
        raise HTTPException(
            status_code=400,
            detail=error_payload("INVALID_MEDIA_URL", "Render object URL is invalid.", retryable=False),
        )
    content, content_type = download_private_storage_url(req.url)
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.delete("/render/media")
async def delete_legacy_render_media(req: MediaUrlRequest, _=Depends(require_api_key)):
    """Delete a validated legacy object after its saved-look row was deleted."""
    if not storage_object_name_from_url(req.url):
        raise HTTPException(
            status_code=400,
            detail=error_payload("INVALID_MEDIA_URL", "Render object URL is invalid.", retryable=False),
        )
    deleted = delete_permanent_storage_url(req.url)
    return {"status": "deleted" if deleted else "not_found"}


@app.delete("/render/users/{owner_id}")
async def delete_member_render_artifacts(
    owner_id: str,
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
    _=Depends(require_api_key),
):
    if str(x_admin_request or "").strip() != "1" and str(x_user_id or "").strip() != owner_id:
        raise HTTPException(
            status_code=403,
            detail=error_payload("FORBIDDEN", "Member artifact deletion is not allowed.", retryable=False),
        )
    jobs = job_store.find_by_field(RENDER_JOBS_COLLECTION, "ownerId", owner_id, limit=500)
    deleted = 0
    artifact_urls = {
        str(job.get("afterImageUrl"))
        for job in jobs
        if job.get("isPermanent") and job.get("afterImageUrl")
    }
    for job in jobs:
        job_id = job.get("jobId")
        if not job_id:
            continue
        job_store.delete(RENDER_JOBS_COLLECTION, job_id)
        deleted += 1
    for artifact_url in artifact_urls:
        delete_permanent_storage_url(artifact_url)
    return {"status": "deleted", "ownerId": owner_id, "jobsDeleted": deleted}


@app.delete("/render/jobs/{job_id}")
async def delete_render_job(
    job_id: str,
    _=Depends(require_api_key),
    x_job_token: str | None = Header(default=None),
    result_token: str | None = Query(default=None),
):
    """Explicitly delete a finished render job and its GCS artifact."""
    job = job_store.get(RENDER_JOBS_COLLECTION, job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=error_payload("JOB_NOT_FOUND", "Render job not found or expired.", retryable=False),
        )
    _verify_job_token(job, x_job_token=x_job_token, result_token=result_token)
    if job.get("status") in {"queued", "running"}:
        raise HTTPException(
            status_code=409,
            detail=error_payload("JOB_IN_PROGRESS", "A running render job cannot be deleted yet.", retryable=True),
        )
    _delete_job_artifact(job)
    job_store.delete(RENDER_JOBS_COLLECTION, job_id)
    return {"status": "deleted", "jobId": job_id}
