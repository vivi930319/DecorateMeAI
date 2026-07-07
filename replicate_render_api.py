import os
from fastapi import FastAPI
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
    }


@app.post("/render")
async def render(req: RenderRequest):
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
