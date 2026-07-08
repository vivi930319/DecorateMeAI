import os
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from replicate_render import call_replicate_render, build_render_prompt, REPLICATE_MODEL, GCS_BUCKET_NAME

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 每次渲染都真的花 Replicate 錢，加 API key 擋掉直接掃到 Cloud Run URL 的濫用。
# 正式環境務必用環境變數設定 RENDER_API_KEY；沒設定時（本機開發）不擋，但會在 /health 標明。
RENDER_API_KEY = os.getenv("RENDER_API_KEY", "")


def require_api_key(x_api_key: str | None = Header(default=None)):
    if RENDER_API_KEY and x_api_key != RENDER_API_KEY:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "FORBIDDEN", "message": "Invalid or missing API key.", "retryable": False}},
        )


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
    }


@app.post("/render")
async def render(req: RenderRequest, _=Depends(require_api_key)):
    try:
        result = call_replicate_render(req.image, req.prompt)
        return {
            "status": "completed",
            "afterImageUrl": result["afterImageUrl"],
            "replicateTempUrl": result.get("replicateTempUrl"),
            "isPermanent": result.get("isPermanent", False),
            "model": result["model"],
            "error": None,
        }
    except Exception as e:
        return {
            "status": "failed",
            "afterImageUrl": None,
            "error": str(e),
        }
