import os
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dev_server_utils import run_dev_server


app = FastAPI(title="Ollama Suggestion API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
ALLOW_FALLBACK = os.getenv("OLLAMA_ALLOW_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}


class SuggestRequest(BaseModel):
    analysisPackage: dict[str, Any] | None = None
    faceAnalysis: dict[str, Any] | None = None
    style: str | None = Field(default="日常自然妝")
    language: str | None = Field(default="zh-TW")
    userNote: str | None = None
    model: str | None = None


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _extract_face_analysis(payload: SuggestRequest) -> dict[str, Any]:
    if payload.faceAnalysis:
        return payload.faceAnalysis
    if payload.analysisPackage:
        return payload.analysisPackage.get("faceAnalysis") or {}
    return {}


def _pick(face_analysis: dict[str, Any], english_key: str, chinese_key: str, default: str = "未提供") -> Any:
    if english_key in face_analysis:
        return face_analysis.get(english_key) or default
    if chinese_key in face_analysis:
        return face_analysis.get(chinese_key) or default
    raw = face_analysis.get("raw") or {}
    return raw.get(chinese_key) or default


def build_prompt(payload: SuggestRequest) -> str:
    face_analysis = _extract_face_analysis(payload)
    style = payload.style or "日常自然妝"
    user_note = payload.userNote or "無"

    face_shape = _pick(face_analysis, "faceShape", "臉型")
    brow_shape = _pick(face_analysis, "browShape", "眉型")
    eye_shape = _pick(face_analysis, "eyeShape", "眼型")
    nose_front = _pick(face_analysis, "noseFront", "鼻型")
    lip_shape = _pick(face_analysis, "lipShape", "嘴型")
    skin_tone = face_analysis.get("skinTone") or face_analysis.get("膚色") or {}

    return f"""你是專業彩妝建議助理。請使用繁體中文，給一般使用者看得懂的建議。

使用者想要的風格：{style}
使用者補充：{user_note}

臉部分析：
- 臉型：{face_shape}
- 眉型：{brow_shape}
- 眼型：{eye_shape}
- 鼻型：{nose_front}
- 嘴型：{lip_shape}
- 膚色資訊：{skin_tone}

請輸出：
1. 整體妝容方向
2. 底妝建議
3. 眉眼妝建議
4. 唇妝建議
5. 避免事項

語氣要像真的化妝師在提醒使用者，不要寫太艱深。"""


def fallback_suggestion(payload: SuggestRequest) -> str:
    face_analysis = _extract_face_analysis(payload)
    style = payload.style or "日常自然妝"
    face_shape = _pick(face_analysis, "faceShape", "臉型")
    eye_shape = _pick(face_analysis, "eyeShape", "眼型")
    lip_shape = _pick(face_analysis, "lipShape", "嘴型")

    return (
        f"這是 {style} 的基礎建議。整體可以走乾淨、自然、不要過重的妝感。"
        f"目前臉型判斷為「{face_shape}」，修容先以少量、邊界柔和為主；"
        f"眼型為「{eye_shape}」，眼妝可以加強眼尾和睫毛根部，讓眼神更集中；"
        f"嘴型為「{lip_shape}」，唇色建議先選日常玫瑰、豆沙或自然粉棕。"
        "底妝請避免太厚，先以均勻膚色和保留皮膚質感為主。"
    )


def call_ollama(prompt: str, model: str) -> str:
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=OLLAMA_TIMEOUT,
    )
    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    if not response.ok:
        raise RuntimeError(f"Ollama 回應失敗：{response.status_code} {data}")

    suggestion = data.get("response")
    if not suggestion:
        raise RuntimeError("Ollama 回應沒有 response 欄位")
    return suggestion.strip()


@app.get("/health")
async def health():
    reachable = False
    error = None
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        reachable = response.ok
        if not response.ok:
            error = f"HTTP {response.status_code}"
    except Exception as exc:
        error = str(exc)

    return {
        "status": "ok",
        "service": "ollama-suggestion",
        "ollama": {
            "baseUrl": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "reachable": reachable,
            "error": error,
        },
        "fallbackEnabled": ALLOW_FALLBACK,
    }


@app.post("/suggest")
async def suggest(payload: SuggestRequest):
    face_analysis = _extract_face_analysis(payload)
    if not face_analysis:
        raise HTTPException(status_code=400, detail={"error": {"message": "缺少 faceAnalysis 或 analysisPackage.faceAnalysis"}})

    model = payload.model or OLLAMA_MODEL
    prompt = build_prompt(payload)
    provider = "ollama"
    fallback_used = False

    try:
        suggestion = call_ollama(prompt, model)
    except Exception as exc:
        if not ALLOW_FALLBACK:
            raise HTTPException(status_code=502, detail={"error": {"message": str(exc)}})
        provider = "fallback"
        fallback_used = True
        suggestion = fallback_suggestion(payload)

    return {
        "status": "completed",
        "provider": provider,
        "model": model,
        "fallbackUsed": fallback_used,
        "createdAt": _now_iso(),
        "suggestion": suggestion,
    }


if __name__ == "__main__":
    run_dev_server(app, service_name="Ollama Suggestion API", env_prefix="OLLAMA_SUGGESTION", default_port=8010)
