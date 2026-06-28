import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from replicate_render import call_replicate_render, build_render_prompt, REPLICATE_MODEL

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


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "replicate-render",
        "model": REPLICATE_MODEL,
        "token_configured": bool(os.getenv("REPLICATE_API_TOKEN")),
        "storage_configured": False,
    }


@app.post("/render")
async def render(req: RenderRequest):
    try:
        result = call_replicate_render(req.image, req.prompt)
        return {
            "status": "completed",
            "afterImageUrl": result["afterImageUrl"],
            "model": result["model"],
            "error": None,
        }
    except Exception as e:
        return {
            "status": "failed",
            "afterImageUrl": None,
            "error": str(e),
        }
