import asyncio
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

from api_errors import (
    enforce_service_api_key,
    error_payload,
    install_api_error_handling,
    rate_limited_error,
    secret_equals,
)
import job_store
from dev_server_utils import get_cors_origins
from replicate_render import (
    SuggestionServiceUnavailable,
    GCS_BUCKET_NAME,
    GCS_RENDER_RETENTION_DAYS,
    IMAGE_PROVIDER,
    RENDER_STYLE_PROMPTS,
    REPLICATE_MODEL,
    SUGGESTION_SERVICE_URL,
    build_personalized_render_prompt,
    build_server_render_prompt,
    call_replicate_render,
    create_signed_storage_url,
    data_url_to_bytes,
    delete_permanent_storage_url,
    download_private_storage_url,
    retain_permanent_storage_url,
    storage_object_name_from_url,
    upload_bytes_to_permanent_storage,
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
# 缺金鑰就拒絕啟動（fail closed），檢查掛在啟動流程而非 import 時（P0-7）；
# /health 仍會標明是否啟用驗證。
RENDER_API_KEY = os.getenv("RENDER_API_KEY", "")
enforce_service_api_key(app, "RENDER_API_KEY")
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
    if RENDER_API_KEY and not secret_equals(x_api_key, RENDER_API_KEY):
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
    # 形狀統一在 api_errors.rate_limited_error（Retry-After 標頭＋回應內 retryAfterSeconds），
    # Gateway 的登入限流用的是同一個，前端只要寫一套解析。
    raise rate_limited_error(
        code,
        message,
        retry_after,
        windowSeconds=window,
        maxRequests=maximum,
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
    # 資料包裡的 generativeText.renderPromptEn 一律忽略 ——
    # 那是前端送來的，可以被竄改，而 renderApiKey 是明文寫在網頁裡的：
    # 一旦照著它渲染，任何人都能拿這把 key 送任意 prompt、用我們的 Replicate 額度生成任意圖片。
    # 要下給模型的 prompt，後端自己去跟建議服務要（build_personalized_render_prompt）。
    #
    # 若之後要讓前端送的 prompt 也能被信任，做法是請建議服務對 renderPromptEn 加 HMAC 簽章，
    # render 這邊驗簽 —— 前端就能送 prompt，但編不出有效簽章。那需要建議服務端配合改程式。
    analysisPackage: dict | None = None
    faceAnalysis: dict | None = None  # 舊前端相容：沒送資料包時，單獨給臉部分析也行

    # 這一次渲染對應到哪一個臉部分析 job。
    #
    # 用途只有一個：把使用者的五官修正接回它對應的那張臉。標註存在臉部分析端
    # （face_feedback），照片存在這一端（/media/render/{id}/before），兩邊 job id 不同，
    # 沒有這個欄位就永遠 join 不起來，issue #24 的重訓也就拿不到「標註＋影像」的配對。
    #
    # 這裡只存識別碼，不改變任何權限：照片仍然走原本那條需驗證的路徑。
    faceJobId: str | None = Field(default=None, max_length=64)


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
    刻意不讀資料包裡的 generativeText.renderPromptEn —— 見 RenderRequest 的說明。
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
    except SuggestionServiceUnavailable as exc:
        # Demo 的渲染不能被一台校外 Mac 或臨時 tunnel 拖垮。保留明確的 promptSource
        # 與 warning log，維運端仍看得出降級；使用者則可用白名單中的安全固定 prompt
        # 完成流程，不會因建議服務暫時離線而整個卡在 503。
        logging.warning("建議服務不可用，改用固定風格 prompt：%s", exc)
        return build_server_render_prompt(style_id), "style_allowlist_fallback"
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


def _response_from_completed_job(job: dict, image: str | None = None) -> dict:
    """把一個已完成的 job 轉成新 job 的內容（去重命中時用）。

    `beforeImageUrl` 一定要帶。少了它，命中去重的那次渲染會建立一個從出生就沒有
    妝前圖的 job，使用者收藏之後永遠只有一半的對比圖——而且因為妝後圖正常出現，
    看起來像是「妝前圖偶爾會壞」，很難查。

    舊 job 可能本來就沒有妝前圖（那個功能 2026-07-22 才上線）。這種情況用**這次請求
    的原圖補建**，而不是放棄快取重新渲染：去重存在的目的是省下昂貴又緩慢的模型呼叫，
    不是省一次圖片上傳。補建出來的是這個 job 自己的物件，不與舊 job 共用，
    所以刪除時各自獨立，不需要額外的引用計數。
    """
    before_url = job.get("beforeImageUrl")
    if not before_url and image:
        try:
            before_bytes, before_type = data_url_to_bytes(image)
            before_url = upload_bytes_to_permanent_storage(before_bytes, before_type)
        except Exception:  # noqa: BLE001 — 補建失敗只損失對比圖，不該讓整次渲染失敗
            logging.getLogger(__name__).exception("命中去重快取時補建妝前圖失敗")
            before_url = None
    return {
        "status": "completed",
        "afterImageUrl": job.get("afterImageUrl"),
        "beforeImageUrl": before_url,
        "beforeObjectName": storage_object_name_from_url(before_url),
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


def _artifact_is_shared(job: dict, field: str, url: str) -> bool:
    """有沒有別的 retained job 也指向這個物件（dedup 會讓多個 job 共用一張圖）。"""
    references = job_store.find_by_field(RENDER_JOBS_COLLECTION, field, url, limit=50)
    current_id = str(job.get("jobId") or "")
    return any(
        str(reference.get("jobId") or "") != current_id and reference.get("retained")
        for reference in references
    )


def _delete_job_artifact(job: dict, force: bool = False) -> bool:
    """刪掉這個 job 的圖片。**妝前圖與妝後圖都要刪。**

    妝前圖是使用者自己的臉。他刪掉收藏之後那張圖若留在 GCS 上，那不是浪費空間，
    是隱私事故——所以這裡兩個欄位都處理，任何新增的圖片欄位也必須加進來。
    """
    deleted = True
    after_url = job.get("afterImageUrl")
    if after_url and job.get("isPermanent"):
        if force or not _artifact_is_shared(job, "afterImageUrl", after_url):
            deleted = bool(delete_permanent_storage_url(after_url)) and deleted

    # 妝前圖沒有 isPermanent 這個旗標——它一律由本服務上傳到自己的 bucket，
    # 而 delete_permanent_storage_url 本身就只肯刪自己 bucket 裡的物件。
    before_url = job.get("beforeImageUrl")
    if before_url:
        if force or not _artifact_is_shared(job, "beforeImageUrl", before_url):
            deleted = bool(delete_permanent_storage_url(before_url)) and deleted
    return deleted


def _mark_artifact_delete_failure(job_id: str, message: str) -> None:
    job_store.patch(
        RENDER_JOBS_COLLECTION,
        job_id,
        {
            "deletionStatus": "failed",
            "deletionError": message[:500],
            "deletionLastAttemptAt": time.time(),
            "updatedAt": time.time(),
        },
    )


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
                if _delete_job_artifact(job):
                    to_delete.append(job_id)
                else:
                    _mark_artifact_delete_failure(job_id, "Expired render artifact deletion failed.")

    for job_id in to_delete:
        job_store.delete(RENDER_JOBS_COLLECTION, job_id)

    remaining = job_store.all_jobs(RENDER_JOBS_COLLECTION)
    if len(remaining) > RENDER_JOB_MAX_COUNT:
        removable = [job for job in remaining if not job.get("retained")]
        ordered = sorted(removable, key=lambda item: float(item.get("createdAt") or 0))
        for job in ordered[: max(0, len(remaining) - RENDER_JOB_MAX_COUNT)]:
            job_id = job.get("jobId")
            if job_id:
                if _delete_job_artifact(job):
                    job_store.delete(RENDER_JOBS_COLLECTION, job_id)
                else:
                    _mark_artifact_delete_failure(job_id, "Render capacity cleanup failed.")


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
    # 這裡可能呼叫同步 requests（建議服務 timeout 最長 90 秒）。放進 worker thread，
    # 避免阻塞 FastAPI event loop 與其他人的健康檢查／工作輪詢。
    prompt, prompt_source = await asyncio.to_thread(_server_render_prompt, req)
    # 同圖同後端產生的 prompt 短時間內重複 → 直接回上次結果，不重打 Replicate
    key = _dedup_key(req.image, prompt, req.strength, str(x_user_email or "").strip())
    cached = _dedup_get(key)
    if cached is not None:
        return {**cached, "deduped": True}
    durable = _durable_dedup_job(key)
    if durable is not None:
        response = _response_from_completed_job(durable, req.image)
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
    # Job token 一樣要固定時間比較，否則可以逐字元試探把別人的 token 猜出來（P0-7）。
    if expected and not secret_equals(x_job_token or result_token, expected):
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
        # 妝前圖：使用者送進來的原圖，先前渲染完就丟掉，所以收藏永遠只有妝後圖。
        # 存起來才有前後對比。它跟妝後圖共用同一個 job 的擁有者檢查與生命週期，
        # 不需要另開上傳端點，瀏覽器也不必重傳一次。
        #
        # 失敗不影響渲染：拿不到妝前圖只是少一半對比，讓整次渲染失敗才是本末倒置。
        before_url = None
        try:
            before_bytes, before_type = data_url_to_bytes(image)
            before_url = upload_bytes_to_permanent_storage(before_bytes, before_type)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("原圖上傳失敗，這次收藏只會有妝後圖")

        response = {
            "status": "completed",
            "afterImageUrl": result["afterImageUrl"],
            "beforeImageUrl": before_url,
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
                "beforeObjectName": storage_object_name_from_url(before_url),
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
            # 兩張都要刪——妝前圖是使用者的臉，留在 bucket 裡沒有任何紀錄指向它，
            # 之後也沒人會發現該刪。
            delete_permanent_storage_url(response.get("afterImageUrl"))
            delete_permanent_storage_url(response.get("beforeImageUrl"))
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
    prompt, prompt_source = await asyncio.to_thread(_server_render_prompt, req)
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
            **_response_from_completed_job(durable, req.image),
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
        # 對應的臉部分析 job。標註在那一端、照片在這一端，靠它把兩者接起來（issue #24）。
        # 前端可能送在頂層，也可能包在 analysisPackage 裡，兩處都看。
        "faceJobId": req.faceJobId or (req.analysisPackage or {}).get("faceJobId"),
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
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
):
    # 這支會被前端每兩秒打一次，所以不掛 rate limit，否則輪詢自己就會把配額燒光
    job = job_store.get(RENDER_JOBS_COLLECTION, job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "JOB_NOT_FOUND", "message": "Render job not found or expired.", "retryable": False}},
        )
    _verify_job_token(job, x_job_token=x_job_token, result_token=result_token)
    # token 對還不夠，擁有者也要對（P0-8）。建立 job 時沒有會員身分就會被擋成 401，
    # 所以每個 job 都有 ownerId；Gateway 也一律替 render-service 帶上 X-User-ID。
    # 少了這一段，一個外流的 job token 就足以讓別人讀到這位會員的渲染結果，
    # 而簽名網址那條路徑早就在檢查擁有者了——兩條路的門檻不該一鬆一緊。
    _require_job_owner(job, x_user_id, x_admin_request)
    view = _job_view(job)
    return {**view, "progress": _estimate_progress(job, time.time()), "estimatedSeconds": RENDER_ESTIMATED_SECONDS}


def _job_media_url(job: dict, variant: str) -> str | None:
    """取這個 job 的圖片網址。variant 只接受 "after"／"before"，不接受其他值。

    用 query 參數而不是新開路由，是為了不擴大 Gateway 的內部路徑白名單——
    這兩條端點刻意只有 Gateway 打得到（見 ai_gateway_test 的路由測試），
    多一條路徑就多一個要記得擋住的地方。
    """
    if variant == "before":
        return job.get("beforeImageUrl")
    return job.get("afterImageUrl")


@app.get("/render/jobs/{job_id}/signed-url")
async def get_render_signed_url(
    job_id: str,
    variant: str = Query("after", pattern="^(after|before)$"),
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
    _=Depends(require_api_key),
):
    """Issue a short-lived URL after checking the render's member owner."""
    job = job_store.get(RENDER_JOBS_COLLECTION, job_id)
    media_url = _job_media_url(job or {}, variant)
    if job is None or job.get("status") != "completed" or not media_url:
        raise HTTPException(
            status_code=404,
            detail=error_payload("JOB_NOT_FOUND", "Render image was not found.", retryable=False),
        )
    # 擁有者檢查對兩種 variant 完全相同——妝前圖是使用者的臉，
    # 保護只能更嚴，不能因為它「只是原圖」就放寬。
    _require_job_owner(job, x_user_id, x_admin_request)
    try:
        signed_url = create_signed_storage_url(media_url)
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
    variant: str = Query("after", pattern="^(after|before)$"),
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
    _=Depends(require_api_key),
):
    """Authenticated private-object fallback when IAM signBlob is unavailable."""
    job = job_store.get(RENDER_JOBS_COLLECTION, job_id)
    media_url = _job_media_url(job or {}, variant)
    if job is None or job.get("status") != "completed" or not media_url:
        raise HTTPException(
            status_code=404,
            detail=error_payload("JOB_NOT_FOUND", "Render image was not found.", retryable=False),
        )
    _require_job_owner(job, x_user_id, x_admin_request)
    try:
        content, content_type = download_private_storage_url(media_url)
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
    owner_id = str(job.get("ownerId") or "")
    try:
        retained_url = retain_permanent_storage_url(job.get("afterImageUrl"), owner_id, job_id)
    except Exception as exc:
        logging.getLogger(__name__).exception("retained render copy failed")
        raise HTTPException(
            status_code=503,
            detail=error_payload("RETAIN_FAILED", "Render image could not be retained.", retryable=True),
        ) from exc

    # 妝前圖也要搬進 retained/，否則它留在 temporary/，兩天後被生命週期規則刪掉——
    # 使用者過幾天回來看到半張對比圖。variant 不能省：目的地名稱只用 job_id 會與
    # 妝後圖撞名，而 retain 內部的 exists() 檢查會靜默略過，讓妝前圖指向妝後那張。
    #
    # 妝前圖是使用者收藏對比的一半，也是他的原始臉部照片。只保住妝後圖卻把
    # job 標成 retained 會讓 temporary/ 裡的妝前圖日後被生命週期清掉，形成永久
    # 的半筆收藏。因此任一張 retain 失敗都保持 job 可重試，不能回報成功。
    retained_before = None
    if not retained_url:
        raise HTTPException(
            status_code=503,
            detail=error_payload("RETAIN_INCOMPLETE", "Render image retention is incomplete.", retryable=True),
        )
    if job.get("beforeImageUrl"):
        try:
            retained_before = retain_permanent_storage_url(
                job.get("beforeImageUrl"), owner_id, job_id, variant="-before"
            )
            if not retained_before:
                raise RuntimeError("before image retention returned no URL")
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).exception("妝前圖 retain 失敗，保留 job 供後續重試")
            job_store.patch(
                RENDER_JOBS_COLLECTION,
                job_id,
                {"retainStatus": "failed", "retainLastAttemptAt": time.time(), "updatedAt": time.time()},
            )
            raise HTTPException(
                status_code=503,
                detail=error_payload("RETAIN_INCOMPLETE", "Before and after images could not both be retained.", retryable=True),
            ) from exc

    patch = {
        "retained": True,
        "afterImageUrl": retained_url,
        "objectName": storage_object_name_from_url(retained_url),
        "updatedAt": time.time(),
    }
    if retained_before:
        patch["beforeImageUrl"] = retained_before
        patch["beforeObjectName"] = storage_object_name_from_url(retained_before)
    job_store.patch(RENDER_JOBS_COLLECTION, job_id, patch)
    job_store.unset(RENDER_JOBS_COLLECTION, job_id, ["expiresAt", "retainStatus", "retainLastAttemptAt"])
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
    if not _delete_job_artifact(job):
        _mark_artifact_delete_failure(job_id, "Owned render artifact deletion failed.")
        raise HTTPException(
            status_code=503,
            detail=error_payload("ARTIFACT_DELETE_FAILED", "Render image deletion could not be completed.", retryable=True),
        )
    job_store.delete(RENDER_JOBS_COLLECTION, job_id)
    return {"status": "deleted", "jobId": job_id}


def _require_legacy_media_owner(
    url: str,
    user_id: str | None,
    admin_request: str | None,
) -> tuple[dict, str]:
    """Resolve a legacy object back to an owned job; a valid bucket URL alone is not authorization."""
    candidates: list[tuple[dict, str]] = []
    for field in ("afterImageUrl", "beforeImageUrl"):
        for job in job_store.find_by_field(RENDER_JOBS_COLLECTION, field, url, limit=50):
            candidates.append((job, field))
    if str(admin_request or "").strip() == "1" and candidates:
        return candidates[0]
    supplied = str(user_id or "").strip()
    for job, field in candidates:
        if supplied and str(job.get("ownerId") or "").strip() == supplied:
            return job, field
    raise HTTPException(
        status_code=404,
        detail=error_payload("MEDIA_NOT_FOUND", "Render image was not found.", retryable=False),
    )


@app.post("/render/media/sign")
async def sign_legacy_render_media(
    req: MediaUrlRequest,
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
    _=Depends(require_api_key),
):
    """Refresh a legacy saved GCS URL after the Gateway verified DB ownership."""
    if not storage_object_name_from_url(req.url):
        raise HTTPException(
            status_code=400,
            detail=error_payload("INVALID_MEDIA_URL", "Render object URL is invalid.", retryable=False),
        )
    _require_legacy_media_owner(req.url, x_user_id, x_admin_request)
    return {"signedUrl": create_signed_storage_url(req.url), "expiresIn": 600}


@app.post("/render/media/content")
async def get_legacy_render_media(
    req: MediaUrlRequest,
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
    _=Depends(require_api_key),
):
    """Internal authenticated fallback for a legacy saved object URL."""
    if not storage_object_name_from_url(req.url):
        raise HTTPException(
            status_code=400,
            detail=error_payload("INVALID_MEDIA_URL", "Render object URL is invalid.", retryable=False),
        )
    _require_legacy_media_owner(req.url, x_user_id, x_admin_request)
    content, content_type = download_private_storage_url(req.url)
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.delete("/render/media")
async def delete_legacy_render_media(
    req: MediaUrlRequest,
    x_user_id: str | None = Header(default=None),
    x_admin_request: str | None = Header(default=None),
    _=Depends(require_api_key),
):
    """Delete a validated legacy object after its saved-look row was deleted."""
    if not storage_object_name_from_url(req.url):
        raise HTTPException(
            status_code=400,
            detail=error_payload("INVALID_MEDIA_URL", "Render object URL is invalid.", retryable=False),
        )
    job, field = _require_legacy_media_owner(req.url, x_user_id, x_admin_request)
    if _artifact_is_shared(job, field, req.url):
        return {"status": "retained_by_other_record"}
    deleted = delete_permanent_storage_url(req.url)
    if not deleted:
        job_id = str(job.get("jobId") or "")
        if job_id:
            _mark_artifact_delete_failure(job_id, "Legacy render artifact deletion failed.")
        raise HTTPException(
            status_code=503,
            detail=error_payload("ARTIFACT_DELETE_FAILED", "Render image deletion could not be completed.", retryable=True),
        )
    return {"status": "deleted"}


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
    # 刪除順序刻意是「先刪物件、再刪紀錄」。反過來的話，物件刪除失敗時 job 文件
    # 已經不見，那張圖就永遠沒有東西指向它——沒有人知道它存在、也沒有人會再嘗試刪。
    # 留著紀錄至少能重試。
    #
    # 一次只抓一批，刪完再抓下一批，直到沒有為止。先前是單次 limit=500，
    # 超過的部分完全不會被處理，而且會員資料那邊已經刪掉了，等於留下無主的臉部照片。
    deleted = 0
    batches = 0
    attempted: set[str] = set()
    failures: list[str] = []
    while batches < 200:  # 上限只是避免 job_store 異常時無限迴圈
        jobs = job_store.find_by_field(RENDER_JOBS_COLLECTION, "ownerId", owner_id, limit=200)
        pending = [job for job in jobs if str(job.get("jobId") or "") not in attempted]
        if not pending:
            break
        batches += 1
        for job in pending:
            job_id = job.get("jobId")
            if not job_id:
                continue
            attempted.add(str(job_id))
            # 妝後圖與妝前圖都要刪。妝前圖是使用者上傳的原始照片，
            # 帳號都刪了還把他的臉留在儲存空間裡，是這個系統最嚴重的一種失敗。
            # 妝後圖有 isPermanent 旗標（可能是外部暫存網址），妝前圖一律由本服務
            # 上傳到自己的 bucket，所以不需要那個判斷。
            try:
                artifacts_deleted = _delete_job_artifact(job, force=True)
            except Exception as exc:  # noqa: BLE001
                artifacts_deleted = False
                logging.getLogger(__name__).exception("member artifact deletion failed job_id=%s", job_id)
                failure_message = str(exc)
            else:
                failure_message = "One or more member render objects could not be deleted."
            if not artifacts_deleted:
                failures.append(str(job_id))
                _mark_artifact_delete_failure(str(job_id), failure_message)
                continue
            job_store.delete(RENDER_JOBS_COLLECTION, job_id)
            deleted += 1
    if failures:
        raise HTTPException(
            status_code=503,
            detail={
                **error_payload("MEMBER_ARTIFACT_DELETE_INCOMPLETE", "Some member images could not be deleted; the records were retained for retry.", retryable=True),
                "jobsDeleted": deleted,
                "failedJobIds": failures[:50],
            },
        )
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
    if not _delete_job_artifact(job):
        _mark_artifact_delete_failure(job_id, "Render job artifact deletion failed.")
        raise HTTPException(
            status_code=503,
            detail=error_payload("ARTIFACT_DELETE_FAILED", "Render image deletion could not be completed.", retryable=True),
        )
    job_store.delete(RENDER_JOBS_COLLECTION, job_id)
    return {"status": "deleted", "jobId": job_id}
