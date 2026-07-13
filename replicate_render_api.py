import os
import time
import math
import uuid
import hashlib
import logging
import threading
from collections import deque
from threading import Lock

from fastapi import FastAPI, Header, HTTPException, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import job_store
from dev_server_utils import get_cors_origins
from replicate_render import call_replicate_render, build_render_prompt, REPLICATE_MODEL, GCS_BUCKET_NAME, IMAGE_PROVIDER

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# 每次渲染都真的花 Replicate 錢，加 API key 擋掉直接掃到 Cloud Run URL 的濫用。
# 正式環境務必用環境變數設定 RENDER_API_KEY；沒設定時（本機開發）不擋，但會在 /health 標明。
RENDER_API_KEY = os.getenv("RENDER_API_KEY", "")
RENDER_RATE_LIMIT_WINDOW_SECONDS = max(1, int(os.getenv("RENDER_RATE_LIMIT_WINDOW_SECONDS", "3600")))
RENDER_RATE_LIMIT_MAX_REQUESTS = max(1, int(os.getenv("RENDER_RATE_LIMIT_MAX_REQUESTS", "10")))

_rate_limit_lock = Lock()
_rate_limit_hits: dict[str, deque[float]] = {}

# 去重：同一張圖 + 同一 prompt 在短時間內重複請求（例如使用者狂按），直接回上次結果，不重打 Replicate 燒錢。
RENDER_DEDUP_TTL_SECONDS = max(0, int(os.getenv("RENDER_DEDUP_TTL_SECONDS", "600")))
_dedup_lock = Lock()
_dedup_cache: dict[str, tuple[float, dict]] = {}

# 非同步 job：/render 同步版會被 Cloud Run 的請求逾時砍掉（gpt-image-2 實測 50~150 秒），
# 所以另開一組 job 端點——送出後立刻回 jobId，前端輪詢進度，不再有 504。
# job 狀態走 Firestore（不是 process 記憶體），因為這個服務 maxScale=20、concurrency=4，
# 輪詢的請求很可能被導到另一個 instance，記憶體裡的 job 在那邊根本不存在。
RENDER_JOBS_COLLECTION = os.getenv("RENDER_JOBS_COLLECTION", "render_jobs")
# 進度條的預估總秒數。Replicate 轉手 OpenAI 的排隊時間浮動極大（實測 50~150 秒），拿不到真實進度，
# 這個值只是用來把「已經等了多久」映射成 1~95% 的估算百分比，跑完才跳 100。
RENDER_ESTIMATED_SECONDS = max(10, int(os.getenv("RENDER_ESTIMATED_SECONDS", "90")))
MAX_RENDER_IMAGE_CHARS = int(os.getenv("MAX_RENDER_IMAGE_CHARS", str(12 * 1024 * 1024)))
MAX_RENDER_PROMPT_CHARS = int(os.getenv("MAX_RENDER_PROMPT_CHARS", "4000"))


def _dedup_key(image: str, prompt: str, strength: float) -> str:
    h = hashlib.sha256()
    h.update(image.encode("utf-8", "ignore"))
    h.update(b"|")
    h.update(prompt.encode("utf-8", "ignore"))
    h.update(f"|{strength}".encode("utf-8"))
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


def require_api_key(x_api_key: str | None = Header(default=None)):
    if RENDER_API_KEY and x_api_key != RENDER_API_KEY:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "FORBIDDEN", "message": "Invalid or missing API key.", "retryable": False}},
        )


def _client_ip(request: Request) -> str:
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


def enforce_render_rate_limit(request: Request, x_user_email: str | None = Header(default=None)):
    now = time.time()
    window_start = now - RENDER_RATE_LIMIT_WINDOW_SECONDS
    key = _rate_limit_key(request, x_user_email)

    with _rate_limit_lock:
        bucket = _rate_limit_hits.setdefault(key, deque())
        while bucket and bucket[0] <= window_start:
            bucket.popleft()
        if len(bucket) >= RENDER_RATE_LIMIT_MAX_REQUESTS:
            retry_after = max(1, int(bucket[0] + RENDER_RATE_LIMIT_WINDOW_SECONDS - now))
            raise HTTPException(
                status_code=429,
                detail={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": f"Render quota exceeded. Try again in {retry_after} seconds.",
                        "retryable": True,
                        "windowSeconds": RENDER_RATE_LIMIT_WINDOW_SECONDS,
                        "maxRequests": RENDER_RATE_LIMIT_MAX_REQUESTS,
                        "retryAfterSeconds": retry_after,
                    }
                },
            )
        bucket.append(now)


class RenderRequest(BaseModel):
    image: str
    prompt: str
    strength: float = 0.35  # flux-kontext-pro 不用 strength，保留欄位維持前端相容


def _validate_render_request(req: RenderRequest) -> None:
    image = req.image or ""
    prompt = req.prompt or ""
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
    if not prompt.strip():
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "EMPTY_PROMPT", "message": "prompt is required.", "retryable": False}},
        )
    if len(prompt) > MAX_RENDER_PROMPT_CHARS:
        raise HTTPException(
            status_code=413,
            detail={
                "error": {
                    "code": "PROMPT_TOO_LONG",
                    "message": "Render prompt is too long.",
                    "retryable": False,
                    "maxPromptChars": MAX_RENDER_PROMPT_CHARS,
                }
            },
        )


def _storage_configured() -> bool:
    # 輕量檢查：只確認套件裝好、預設憑證能建立 client，不會真的呼叫 GCS API（bucket() 是本地物件，不打網路）
    try:
        from google.cloud import storage

        client = storage.Client()
        return bool(client.bucket(GCS_BUCKET_NAME))
    except Exception:
        return False


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "replicate-render",
        "provider": IMAGE_PROVIDER,
        "model": REPLICATE_MODEL,
        "token_configured": bool(os.getenv("REPLICATE_API_TOKEN")),
        "openai_api_configured": bool(os.getenv("OPENAI_API_KEY")),
        "storage_configured": _storage_configured(),
        "storage_bucket": GCS_BUCKET_NAME,
        "api_key_required": bool(RENDER_API_KEY),
        "rate_limit": {
            "enabled": True,
            "window_seconds": RENDER_RATE_LIMIT_WINDOW_SECONDS,
            "max_requests": RENDER_RATE_LIMIT_MAX_REQUESTS,
        },
        "dedup": {
            "enabled": RENDER_DEDUP_TTL_SECONDS > 0,
            "ttl_seconds": RENDER_DEDUP_TTL_SECONDS,
        },
        "limits": {
            "max_image_chars": MAX_RENDER_IMAGE_CHARS,
            "max_prompt_chars": MAX_RENDER_PROMPT_CHARS,
        },
        "async_jobs": {
            "enabled": True,
            "submit": "POST /render/jobs",
            "poll": "GET /render/jobs/{job_id}",
            "estimated_seconds": RENDER_ESTIMATED_SECONDS,
        },
    }


@app.post("/render")
async def render(req: RenderRequest, _=Depends(require_api_key), __=Depends(enforce_render_rate_limit)):
    _validate_render_request(req)
    # 同圖同 prompt 短時間內重複 → 直接回上次結果，不重打 Replicate
    key = _dedup_key(req.image, req.prompt, req.strength)
    cached = _dedup_get(key)
    if cached is not None:
        return {**cached, "deduped": True}
    try:
        result = call_replicate_render(req.image, req.prompt)
        response = {
            "status": "completed",
            "afterImageUrl": result["afterImageUrl"],
            "replicateTempUrl": result.get("replicateTempUrl"),
            "isPermanent": result.get("isPermanent", False),
            "model": result["model"],
            "error": None,
        }
        _dedup_set(key, response)  # 只快取成功結果
        return response
    except Exception as exc:
        logging.exception("渲染失敗")
        return {
            "status": "failed",
            "afterImageUrl": None,
            "error": f"渲染服務發生錯誤：{exc}",
        }


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
        return dict(job)
    return {k: v for k, v in job.items() if k != "resultToken"}


def _verify_job_token(job: dict, x_job_token: str | None = None, result_token: str | None = None) -> None:
    expected = job.get("resultToken")
    if expected and (x_job_token or result_token) != expected:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "FORBIDDEN", "message": "Invalid or missing job token.", "retryable": False}},
        )


def _run_render_job(job_id: str, image: str, prompt: str, dedup_key: str) -> None:
    job_store.patch(RENDER_JOBS_COLLECTION, job_id, {"status": "running", "startedAt": time.time()})
    try:
        result = call_replicate_render(image, prompt)
        response = {
            "status": "completed",
            "afterImageUrl": result["afterImageUrl"],
            "replicateTempUrl": result.get("replicateTempUrl"),
            "isPermanent": result.get("isPermanent", False),
            "model": result["model"],
            "error": None,
        }
        job_store.patch(
            RENDER_JOBS_COLLECTION,
            job_id,
            {**response, "progress": 100, "finishedAt": time.time()},
        )
        _dedup_set(dedup_key, response)  # 只快取成功結果
    except Exception as exc:  # noqa: BLE001 — 失敗要寫回 job，不能讓 thread 靜靜死掉
        logging.exception("渲染失敗（job %s）", job_id)
        job_store.patch(
            RENDER_JOBS_COLLECTION,
            job_id,
            {
                "status": "failed",
                "afterImageUrl": None,
                "error": f"渲染服務發生錯誤：{exc}",
                "finishedAt": time.time(),
            },
        )


@app.post("/render/jobs")
async def create_render_job(req: RenderRequest, _=Depends(require_api_key), __=Depends(enforce_render_rate_limit)):
    """送出渲染並立刻回 jobId；實際渲染在背景 thread 跑，前端用 GET /render/jobs/{id} 輪詢。

    注意：這需要 Cloud Run 開 --no-cpu-throttling，否則回應送出後 CPU 會被節流，背景 thread 形同停住。
    """
    _validate_render_request(req)
    job_id = uuid.uuid4().hex
    result_token = uuid.uuid4().hex
    now = time.time()
    key = _dedup_key(req.image, req.prompt, req.strength)

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
        }
        job_store.create(RENDER_JOBS_COLLECTION, job_id, job)
        return {**_job_view(job, include_token=True), "estimatedSeconds": RENDER_ESTIMATED_SECONDS}

    job = {
        "jobId": job_id,
        "resultToken": result_token,
        "status": "queued",
        "progress": 1,
        "afterImageUrl": None,
        "error": None,
        "createdAt": now,
    }
    job_store.create(RENDER_JOBS_COLLECTION, job_id, job)

    threading.Thread(
        target=_run_render_job,
        args=(job_id, req.image, req.prompt, key),
        daemon=True,
    ).start()

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
