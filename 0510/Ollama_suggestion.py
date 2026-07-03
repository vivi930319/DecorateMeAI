import os
import httpx
import logging
import json
from datetime import datetime, timezone
from typing import Any, Optional, Tuple
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
import uvicorn

# 1. 初始化日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("ollama-suggestion")

app = FastAPI(title="Ollama 妝容真實個人化修飾服務 (Llava + Gemma3 雙星版)", version="2026-06-v2-Pipeline")

# 2. 100% 允許跨網域測試
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. 環境變數與雙模型端點基本設定
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL_VISION = "llava"      # 第一階段：專職看圖提取特徵
MODEL_TEXT = "gemma3"       # 第二階段：專職高奢繁中推理建議
OLLAMA_TIMEOUT = 120.0      # 雙模型運算，放寬超時時間至 120 秒

# 新增男士風格『男士白開水』
VALID_STYLES = {"日常自然妝", "Soft baddie", "韓系亞裔妝", "日雜清透妝", "千金妝", "港風妝", "病嬌妝", "男士白開水"}

# 4. Request Body 結構
class SuggestRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    faceAnalysis: Optional[dict[str, Any]] = None
    analysisPackage: Optional[dict[str, Any]] = None
    style: str = "日常自然妝"
    language: str = "zh-TW"
    userNote: Optional[str] = None
    model: Optional[str] = None

def make_error_response(http_code: int, code: str, message: str, retryable: bool):
    return JSONResponse(
        status_code=http_code,
        content={"error": {"code": code, "message": message, "retryable": retryable}}
    )

# 5. 全域異常處理器
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print("\n" + "!"*20 + " 【組長看這裡】真實錯誤明細 " + "!"*20)
    print("DEBUG ERRORS:", exc.errors())
    print("!"*60 + "\n")
    logger.error(f"校驗失敗明細: {exc.errors()}")
    return make_error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "欄位型別、結構或不支援的系統特徵代碼", False
    )

# 6. 健康檢查路由
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "ollama-suggestion", "vision_model": MODEL_VISION, "text_model": MODEL_TEXT}

# 7. 第一階段：呼叫 Llava 進行多模態圖片特徵提取
async def extract_image_features_with_llava(base64_image_url: str) -> str:
    url = f"{OLLAMA_BASE_URL}/api/generate"
    pure_base64 = base64_image_url
    if "," in base64_image_url:
        pure_base64 = base64_image_url.split(",")[1]

    prompt = "Analyze this person's facial features, skin texture, tone, eye shape, and facial symmetry in detail for makeup application planning. Output a descriptive English paragraph under 150 words."
    
    payload = {
        "model": MODEL_VISION,
        "prompt": prompt,
        "images": [pure_base64],
        "stream": False
    }
    
    logger.info("⚡ [Pipeline 階段 1] 正在啟動 Llava 多模態看圖提取特徵...")
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        res = await client.post(url, json=payload)
        if res.status_code != 200:
            raise RuntimeError(f"Llava Vision Server 異常: {res.status_code}")
        return res.json().get("response", "").strip()

# 8. 第二階段：組裝最終發給 Gemma3 的「七大對照細節段落＋滿 50 字三要素」提示詞
def build_gemma3_prompts(face_analysis: dict, style: str, user_note: Optional[str], vision_feedback: str) -> Tuple[str, str]:
    f_shape = face_analysis.get('臉型', '未提供')
    b_shape = face_analysis.get('眉型', '未提供')
    e_shape = face_analysis.get('眼型', '未提供')
    n_front = face_analysis.get('鼻型', '未提供')
    l_shape = face_analysis.get('嘴型', '未提供')
    
    skin_obj = face_analysis.get('膚色', {})
    if isinstance(skin_obj, dict):
        s_season = skin_obj.get('四季型', '未提供')
        s_level = skin_obj.get('膚色分級', '未提供')
    else:
        s_season = '暖色調'
        s_level = str(skin_obj)

    # 系統提示詞：將前端所有寫法的對照細節完全灌輸給模型，並要求格式精準對齊
    system_prompt_zh = "你是明星御用高端彩妝顧問。你的任務是結合臉部數據與指定妝容風格，產生兼具「一眼識別康是美熱銷產品清單」與「溫暖閨蜜感特徵手法」的繁體中文客製化建議。\n\n【🏪 康是美品牌與商品嚴格限制】\n1. 妳所推薦的所有彩妝商品，必須是在「台灣康是美（Cosmed）官方網站或實體門市」真正有販售的品牌與品項。\n2. 允許且強烈推薦使用的熱門彩妝品牌範圍：SOFINA蘇菲娜、1028、CLIO珂莉奧、KATE凱婷、IMMEME、KISSME奇士美、Maybelline媚比琳、PONYEFFECT、Curel柯潤、Neogence霓淨思、Za、Excel、INTEGRATE、Too Cool For School。\n3. 絕對不准出現台灣康是美沒有販售的海外專櫃品牌。\n\n【👶 稱呼與語氣死命令】\n1. 嚴禁在回覆中使用任何「受試者」、「使用者」或「您」等冷冰冰的稱呼，一律親切地改叫對方為「寶寶」！用溫柔閨蜜聊天語氣說明。\n\n【🚫 符號禁用鐵律】\n1. 嚴禁在任何標題、文字中使用 Markdown 符號（如 *、#、** 等），請一律使用純文字輸出。\n\n【📋 輸出格式規定（必須嚴格分為以下七個段落，標題獨立佔一行，內容從下一行開始）】\n妳所輸出的標題必須完全符合以下其中一種前端能識別的指定寫法，每段開頭寫「數字. 標題」，不加任何符號：\n\n1. 整體妝容方向\n2. 底妝建議\n3. 眉眼妝建議\n4. 腮紅修容\n5. 唇妝建議\n6. 避免事項\n7. 總結與建議\n\n【🔥 各段落字數與內容核心要求】\n1. 字數底線：上述七個指定段落中，每一個標題下的具體建議內容「絕對不能低於 50 個字」，請盡量詳細擴寫說明。\n2. 建議核心三要素：第2、3、4、5段的彩妝細節內容中，必須明確且完整包含以下三個層面：\n   - 推薦產品：精準指定上述康是美有賣的品牌與具體品項名稱。\n   - 上妝手法：詳細指導寶寶該如何局部上妝（例如用量、塗抹手法、暈染方向等細節）。\n   - 個人化建議：緊緊扣住寶寶專屬的臉型、眉型、眼型、鼻型、嘴型、膚色條件及 AI 視覺提取特徵，解釋此技巧與產品如何修飾其天生條件。\n3. 必須使用標準台灣美妝術語。"

    user_prompt_zh = f"【當前寶寶真實特徵與需求數據】\n- 目標妝容風格：{style}\n- 使用者偏好與備註：{user_note if user_note else '無特別要求'}\n- 臉型：{f_shape}\n- 眉型：{b_shape}\n- 眼型：{e_shape}\n- 正面鼻型：{n_front}\n- 唇型：{l_shape}\n- 膚色季型：{s_season}\n- 膚色級別：{s_level}\n\n【AI 視覺照片提取細節】\n{vision_feedback}\n\n請立刻針對以上客觀數據，嚴格執行「固定七大段落、標題單獨佔一行且內容接在下一行、每段至少 50 字以上、必須包含推薦產品/上妝手法/個人化建議三要素、純文字無符號」的最高排版鐵律，產生豐富的繁體中文美妝客製化建議。"

    return system_prompt_zh, user_prompt_zh

async def call_gemma3_generate(system_instruction: str, user_prompt: str) -> str:
    url = f"{OLLAMA_BASE_URL}/api/generate"
    full_combined_prompt = f"{system_instruction}\n\n[Current Request]:\n{user_prompt}"
    payload = {"model": MODEL_TEXT, "prompt": full_combined_prompt, "stream": False}
    
    logger.info("⚡ [Pipeline 階段 2] 正在呼叫 Gemma3 進行高奢繁中彩妝建議推理...")
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        res = await client.post(url, json=payload)
        if res.status_code != 200:
            raise RuntimeError(f"Gemma3 Server 異常: {res.status_code}")
        return res.json().get("response", "").strip()

# 9. 主幹业务路由
@app.post("/suggest")
async def suggest(payload: SuggestRequest):
    logger.info(f"成功通過 Pydantic 校驗！收到符合規格之資料")
    
    face_analysis = payload.faceAnalysis or (payload.analysisPackage.get("faceAnalysis") if payload.analysisPackage else None)
    analysis_pkg = payload.analysisPackage or {}
    
    if not face_analysis:
        return make_error_response(400, "MISSING_FACE_ANALYSIS", "缺少有效 analysisPackage 內部的分析資料包", False)
    
    images_obj = analysis_pkg.get("images", {})
    front_image_obj = images_obj.get("front", {})
    base64_image_url = front_image_obj.get("compressedDataUrl")
    
    if not base64_image_url:
        logger.warning("未偵測到相片 Base64 網址，將改用純文字數據降級模式運行。")
        vision_feedback = "No image context provided. Rely solely on structured JSON parameters."
    else:
        try:
            vision_feedback = await extract_image_features_with_llava(base64_image_url)
            logger.info(f"Llava 提取回傳成功: {vision_feedback}")
        except Exception as ve:
            logger.error(f"Llava 看圖失敗，原因: {str(ve)}。啟動自動降級容錯。")
            vision_feedback = "Vision analysis failed or timed out. Rely on JSON metrics."

    normalized_style = payload.style.strip()
    if normalized_style in {"韓系亞裔", "日雜清透", "千金", "港風", "病嬌", "男士白開水"}:
        if not normalized_style.endswith("妝") and normalized_style != "男士白開水":
            normalized_style = f"{normalized_style}妝"
    elif normalized_style == "Soft Baddie":
        normalized_style = "Soft baddie"

    if normalized_style not in VALID_STYLES:
        return make_error_response(422, "VALIDATION_ERROR", f"不支援的妝容風格: '{payload.style}'", False)
    
    try:
        # 2階段：組裝提示詞，呼叫 Gemma3
        sys_zh, usr_zh = build_gemma3_prompts(face_analysis, normalized_style, payload.userNote, vision_feedback)
        suggestion = await call_gemma3_generate(sys_zh, usr_zh)
        
        # 🛠️ 終極防排版摧毀解法：剔除 Markdown 區塊引號
        suggestion = suggestion.replace("```json", "").replace("```text", "").replace("```", "").strip()
        
        # ✨ 強力清除全文字串中所有頑皮的 Markdown 特殊符號（# 和 *）
        suggestion = suggestion.replace("*", "").replace("#", "")

        return {
            "status": "completed",
            "provider": "ollama-pipeline",
            "model": f"{MODEL_VISION} + {MODEL_TEXT}",
            "fallbackUsed": False,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "suggestion": suggestion,
            "renderPromptEn": f"Apply deep optimized individual layout for requested {normalized_style}."
        }
    except Exception as exc:
        logger.error(f"流水線運算失敗: {str(exc)}")
        return make_error_response(502, "OLLAMA_UNAVAILABLE", f"雙模型推理服務暫時無法使用: {str(exc)}", True)

if __name__ == "__main__":
    print("\n" + "="*60)
    print(" 【Llava 看圖 + Gemma3 推理】神級雙模型流水線後端已成功啟動！")
    print(" 本機請確保已安裝：ollama pull llava ＆ ollama pull gemma3")
    print("="*60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8010)