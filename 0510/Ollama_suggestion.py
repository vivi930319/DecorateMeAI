import os
import httpx
import logging
from datetime import datetime, timezone
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from typing import Tuple, Optional

from analysis_package import (
    SuggestRequest, FaceAnalysis, MAKEUP_DATABASE,
    MAP_FACE, MAP_BROW, MAP_EYE, MAP_NOSE, MAP_LIP, MAP_SEASON,
    FACE_LOGIC, EYEBROW_LOGIC, EYE_LOGIC, NOSE_LOGIC, LIP_LOGIC, SKIN_LOGIC,
    FACE_METHOD, EYEBROW_METHOD
)

# 初始化日誌系統
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("ollama-suggestion")

app = FastAPI(title="Ollama 妝容建議服務 (外部合作方專用生產版)", version="2026-06-v1")

# 環境變數配置（合作方本機專用網路環境）
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120.0"))

def make_error_response(http_code: int, code: str, message: str, retryable: bool, pkg_id: str = None):
    """嚴格遵循規格書 4.0 節封裝的機器可辨識錯誤契約格式"""
    return JSONResponse(
        status_code=http_code,
        content={
            "status": "failed",
            "analysisPackageId": pkg_id,
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable
            }
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Pydantic 請求欄位校驗失敗: {exc.errors()}")
    return make_error_response(
        http_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="VALIDATION_ERROR",
        message="JSON 欄位型別結構或枚舉值錯誤，不符合 2026-06-v1 規格定義",
        retryable=False
    )

@app.get("/health")
async def health_check():
    """2.1 節規範：確認外層 API 存活，並實際探查內部 Ollama 推理引擎連通狀態"""
    url = f"{OLLAMA_BASE_URL}/api/tags"
    reachable = False
    error_msg = None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(url)
            if res.status_code == 200:
                reachable = True
            else:
                error_msg = f"Ollama 返回異常 HTTP 代碼: {res.status_code}"
    except Exception as e:
        error_msg = str(e)

    return {
        "status": "ok",
        "service": "ollama-suggestion",
        "ollama": {
            "baseUrl": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "reachable": reachable,
            "error": error_msg
        },
        "fallbackEnabled": False  # 正式規格硬性要求全面關閉本地備援假資料
    }

def compile_prompts(analysis: FaceAnalysis, style_name: str, user_note: Optional[str]) -> Tuple[str, str]:
    """將規格書的新制英文代碼映射轉換為 Prompt 組裝上下文"""
    # 查找特定妝容風格配置，查無則降級為日常自然妝
    style_cfg = MAKEUP_DATABASE.get(style_name, MAKEUP_DATABASE["日常自然妝"])
    
    # 執行特徵代碼中文標籤轉譯
    c_face = MAP_FACE.get(analysis.faceShape, "未知臉型")
    c_brow = MAP_BROW.get(analysis.browShape, "未知眉型")
    c_eye = MAP_EYE.get(analysis.eyeShape, "未知眼型")
    c_nose = MAP_NOSE.get(analysis.noseFront, "未知鼻型")
    c_lip = MAP_LIP.get(analysis.lipShape, "未知唇型")
    c_skin = MAP_SEASON.get(analysis.skinTone.season, "未知膚色屬性")
    
    # 組合去識別化的基礎特徵描述文案
    analysis_text = (
        f"臉型：{c_face}({FACE_LOGIC.get(c_face, '')})、"
        f"眉型：{c_brow}({EYEBROW_LOGIC.get(c_brow, '')})、"
        f"眼型：{c_eye}({EYE_LOGIC.get(c_eye, '')})、"
        f"鼻型：{c_nose}({NOSE_LOGIC.get(c_nose, '依照鼻型自然修飾')})、"
        f"唇型：{c_lip}({LIP_LOGIC.get(c_lip, '')})、"
        f"膚色：{c_skin}({SKIN_LOGIC.get(c_skin, '')})"
    )
    
    note_text = user_note if user_note else "無特別指定需求"

    # 1. 繁體中文五段式彩妝建議 Prompt (5.2 節規範)
    prompt_zh = f"""你是一位專業的彩妝整體造型總監。請根據特徵分析與目標風格，編寫一份流暢的繁體中文妝容建議報告。
[五官膚色特徵摘要]: {analysis_text}
[目標風格設定]: {style_name} (風格特點: {style_cfg['description']}, 推薦色彩方案: {style_cfg['tone']})
[使用者需求備註]: {note_text}

【專屬技法融合指引】:
- 底妝：針對 {c_skin} 特性，打造 {style_cfg['base_detail']}。
- 眉毛：執行 {EYEBROW_METHOD.get(c_brow, '順原生毛流填補空隙')}。
- 眼妝：步驟為 {style_cfg['eye_layers']}。
- 腮紅/修容：執行 {FACE_METHOD.get(c_face, '適度修飾輪廓')}。腮紅手法搭配 {style_cfg['blush_detail']}。鼻部修飾執行 {NOSE_LOGIC.get(c_nose, '依照鼻型自然修飾')}。
- 唇妝：手法為 {style_cfg['lip_detail']}。

【硬性格式限制】:
1. 必須且只能分為以下五個段落，並明確寫出標題，全程嚴禁使用星號「*」或任何 Markdown 符號標記：
1. 整體妝容方向
2. 底妝建議
3. 眉眼妝建議
4. 唇妝建議
5. 避免事項
2. 語氣客觀自然，不做醫療診斷，不宣稱分析結果100%精準。
3. 絕對不可自行編造側面鼻型、特定專櫃品牌、或特定商品色號。
4. 禁止輸出任何 Markdown 程式碼區塊（如 ```json）或內部思考鏈區塊（如 <think>）。
5. 總字數限制在 300 ~ 900 中文字。
"""

    # 2. 圖片渲染端專用正向英文 Prompt (5.3 節規範)
    prompt_en = f"""You are an expert AI prompt engineer optimizing descriptions for a face-makeup image generation diffusion model.
Based on features ({analysis.faceShape} face, {analysis.browShape} brows, {analysis.eyeShape} eyes, {analysis.skinTone.season} skin) and style '{style_name}', write a positive rendering instruction.

Strict requirements:
- Specify the lightweight foundation finish matching '{style_cfg['base_detail']}'.
- Describe eye shadow colors and placement technique based on: '{style_cfg['eye_layers']}'.
- Describe blush placement based on: '{style_cfg['blush_detail']}'.
- Describe lip gloss finish and style based on: '{style_cfg['lip_detail']}'.

Rules:
1. Output ONLY a single continuous English paragraph. No headers, no Markdown blocks, no introduction, no Chinese.
2. Word count must be between 50 and 180 words.
3. You MUST end the paragraph with this exact sentence: "Preserve the person's identity, facial structure, skin tone, hairstyle, pose, camera angle, background, and lighting. Change makeup only."
4. Do NOT attempt to alter face shape, age, ethnicity, or background.
"""
    return prompt_zh, prompt_en

async def call_ollama_generate(model: str, prompt: str) -> str:
    """透過 HTTP POST 呼叫原生本機 Ollama /api/generate 服務 (stream: false)"""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}
    
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        res = await client.post(url, json=payload)
        if res.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Ollama 返回錯誤狀態碼: {res.status_code}")
        
        data = res.json()
        output_text = data.get("response", "").strip()
        if not output_text:
            raise HTTPException(status_code=502, detail="Ollama 返回了空本文內容")
        return output_text

@app.post("/suggest")
async def generate_makeup_suggestion(payload: SuggestRequest):
    """核心入口：接收資料包，調度模型，硬性實作 502 熔斷控制"""
    pkg_id = payload.analysisPackage.id if payload.analysisPackage else None
    
    # 1. 邊界條件硬性檢查：必須至少有一種分析特徵來源
    if not payload.faceAnalysis and not (payload.analysisPackage and payload.analysisPackage.faceAnalysis):
        return make_error_response(400, "MISSING_FACE_ANALYSIS", "缺少 faceAnalysis 或 analysisPackage.faceAnalysis 節點", False, pkg_id)
    
    # 2. 決定分析數據源（優先採用最外層相容模式節點）
    analysis_data = payload.faceAnalysis or payload.analysisPackage.faceAnalysis
    
    # 3. 確定使用的模型名稱
    chosen_model = payload.model or OLLAMA_MODEL
    
    try:
        # 4. 組裝提示詞
        p_zh, p_en = compile_prompts(analysis_data, payload.style, payload.userNote)
        
        # 5. 分別呼叫兩次 Ollama
        logger.info(f"[{pkg_id or 'COMPAT_MODE'}] 發送請求至本機 Ollama 產出繁中建議報告...")
        res_suggestion = await call_ollama_generate(chosen_model, p_zh)
        
        logger.info(f"[{pkg_id or 'COMPAT_MODE'}] 發送請求至本機 Ollama 產出英文渲染 Prompt...")
        res_render = await call_ollama_generate(chosen_model, p_en)
        
        # 過濾模型可能遺留的 Markdown Codeblock 髒標記
        if res_suggestion.startswith("```"):
            res_suggestion = res_suggestion.strip("`").replace("json", "", 1).strip()
            
        return {
            "status": "completed",
            "provider": "ollama",
            "model": chosen_model,
            "fallbackUsed": False,  # 3.0 節明確指示：成功時固定為 false
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "suggestion": res_suggestion,
            "renderPromptEn": res_render,
            "analysisPackageId": pkg_id,
            "schemaVersion": "2026-06-v1"
        }
        
    except Exception as e:
        logger.error(f"Ollama 核心推理異常或逾時: {str(e)}")
        # 依照最新規格 A3.2 / 4.0 規定：禁止提供假資料，一律返回 502 熔斷錯誤
        return make_error_response(
            http_code=502,
            code="OLLAMA_UNAVAILABLE",
            message=f"文字建議服務失敗。下游 Ollama 推理引擎離線、超時或回傳空字串：{str(e)}",
            retryable=True,
            pkg_id=pkg_id
        )

if __name__ == "__main__":
    import uvicorn
    # 本地測試或 Cloudflare Tunnel 對接時啟動 8010 連接埠
    uvicorn.run(app, host="127.0.0.1", port=8010)