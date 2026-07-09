import os
import time
import hashlib
from collections import deque
from threading import Lock

from fastapi import FastAPI, Header, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dev_server_utils import get_cors_origins
from replicate_render import call_replicate_render, build_render_prompt, REPLICATE_MODEL, GCS_BUCKET_NAME

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
        "model": REPLICATE_MODEL,
        "token_configured": bool(os.getenv("REPLICATE_API_TOKEN")),
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
    }


@app.post("/render")
async def render(req: RenderRequest, _=Depends(require_api_key), __=Depends(enforce_render_rate_limit)):
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
    except Exception as e:
        return {
            "status": "failed",
            "afterImageUrl": None,
            "error": str(e),
        }
