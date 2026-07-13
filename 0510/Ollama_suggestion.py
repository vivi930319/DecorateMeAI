import os
import httpx
import logging
import json
from datetime import datetime, timezone
from typing import Any, Optional, Tuple
from fastapi import FastAPI, HTTPException, Request, status, Header
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
import uvicorn

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("ollama-suggestion")

app = FastAPI(title="Ollama 妝容真實個人化修飾服務 (Llava + Gemma3 雙星版)", version="2026-07-Final-Fix")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY_SECRET = "tku_im_makeup_secret_2026"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL_VISION = "llava:latest"
MODEL_TEXT = "gemma3:latest"
OLLAMA_TIMEOUT = 120.0

VALID_STYLES = {"日常自然妝", "Soft baddie", "韓系亞裔妝", "日雜清透妝", "千金妝", "港風妝", "病嬌妝", "男士白開水"}

class SuggestRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    faceAnalysis: Optional[dict[str, Any]] = None
    analysisPackage: Optional[dict[str, Any]] = None
    style: str = "日常自然妝"
    language: str = "zh-TW"
    userNote: Optional[str] = None
    model: Optional[str] = None

def make_error_response(http_code: int, code: str, message: str, retryable: bool):
    response = JSONResponse(
        status_code=http_code,
        content={"error": {"code": code, "message": message, "retryable": retryable}}
    )
    response.headers["Access-Control-Allow-Origin"] = "https://decorate-me.web.app"
    response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print("\n" + "!"*20 + " [組長看這裡] 真實錯誤明細 " + "!"*20)
    print("DEBUG ERRORS:", exc.errors())
    print("!"*60 + "\n")
    logger.error(f"校驗失敗明細: {exc.errors()}")
    return make_error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "欄位型別、結構或不支援的系統特徵代碼", False
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error(f"系統拋出 HTTP 異常錯誤: 狀態碼 {exc.status_code} - 原因: {exc.detail}")
    return make_error_response(exc.status_code, "HTTP_EXCEPTION", exc.detail, False)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"系統攔截到未捕捉的崩潰例外: {str(exc)}")
    return make_error_response(500, "INTERNAL_SERVER_ERROR", f"後端崩潰或例外錯誤: {str(exc)}", True)

@app.get("/health")
async def health_check(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    if x_api_key != API_KEY_SECRET:
        logger.warning(f"攔截到未授權的健康檢查請求，傳入的 Key 為: {x_api_key}")
        return make_error_response(403, "FORBIDDEN", "Forbidden: Invalid or missing API Key.", False)
    return {"status": "ok", "service": "ollama-suggestion", "vision_model": MODEL_VISION, "text_model": MODEL_TEXT}

async def extract_image_features_with_llava(base64_image_url: str) -> str:
    url = f"{OLLAMA_BASE_URL}/api/generate"
    pure_base64 = base64_image_url
    if "," in base64_image_url:
        pure_base64 = base64_image_url.split(",")[1]

    prompt = "Analyze this person's facial features, skin texture, tone, eye shape, and facial symmetry in detail for makeup application planning. Output a descriptive English paragraph under 100 words."
    
    payload = {
        "model": MODEL_VISION,
        "prompt": prompt,
        "images": [pure_base64],
        "stream": False,
        "options": {
            "num_predict": 150,
            "temperature": 0.2
        }
    }
    
    logger.info("正在啟動 Llava 多模態看圖提取特徵...")
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        res = await client.post(url, json=payload)
        if res.status_code != 200:
            raise RuntimeError(f"Llava Vision Server 異常: {res.status_code}")
        return res.json().get("response", "").strip()

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

    system_prompt_zh = (
        "你是明星御用高端彩妝顧問。你的任務 is 結合寶寶的原生五官數據與指定妝容風格，產生繁體中文客製化建議（給寶寶看）。\n\n"
        "【核心任務：視覺骨相微調與整形修飾】\n"
        "妳的建議必須死死咬住寶寶原生的五官結構進行針對性『視覺骨相微調與整形修飾』！\n"
        f"1. 底妝與腮紅修容：必須針對寶寶天生的【{f_shape}】與【{n_front}】設計。說明如何利用高光與立體陰影交錯，在視覺上重塑天生【{f_shape}】的輪廓線條，達到向內收縮 or 流暢臉型的骨相改變，並讓【{n_front}】在視覺上骨幹拔高。\n"
        f"2. 眉眼妝建議：必須針對寶寶天生的【{e_shape}】與【{b_shape}】。詳細指導如何利用眼影暈染邊界、眼線延伸、倒影與臥蠶刻畫，在視覺上『徹底重塑並改變』原本的【{e_shape}】限制，達到眼型放大、下至 or微整形矯正的視覺震撼效果。\n"
        f"3. 唇妝建議：必須針對寶寶天生的【{l_shape}】。利用唇線模糊與擴唇手法，在視覺上修飾、改變並優化【{l_shape}】的厚薄比例與嘴角弧度。\n\n"
        "妳的輸出必須嚴格分為以下七個段落，標題獨立佔一行，不加 any Markdown 符號，每段具體文字控制在 35 到 50 字之間：\n"
        "1. 整體妝容方向\n"
        "2. 底妝建議\n"
        "3. 眉眼妝建議\n"
        "4. 腮紅修容\n"
        "5. 唇妝建議\n"
        "6. 避免事項\n"
        "7. 總結與建議\n\n"
        "【共通死命令】\n"
        "1. 推薦品牌僅限康是美有賣：SOFINA蘇菲娜、1028、CLIO珂莉奧、KATE凱婷、IMMEME、KISSME奇士美、Maybelline媚比琳、PONYEFFECT、Za、Excel。\n"
        "2. 中文部分一律親切叫對方為「寶寶」！用溫柔閨蜜語氣。\n"
        "3. 全文嚴禁使用 any Markdown 符號（如 *、#、** 等），一律使用純文字輸出。"
    )

    user_prompt_zh = f"【當前寶寶真實特徵與需求數據】\n- 目標妝容風格：{style}\n- 使用者偏好與備註：{user_note if user_note else '無特別要求'}\n- 臉型：{f_shape}\n- 眉型：{b_shape}\n- eye型：{e_shape}\n- 正面鼻型：n_front\n- 唇型：{l_shape}\n- 膚色季型：{s_season}\n- 膚色級別：{s_level}\n\n【AI 視覺照片提取細節】\n{vision_feedback}\n\n請立刻執行最高排版鐵律，產生溫柔親切的七段純繁中彩妝建議。"

    return system_prompt_zh, user_prompt_zh

async def call_gemma3_generate(system_instruction: str, user_prompt: str) -> str:
    url = f"{OLLAMA_BASE_URL}/api/generate"
    full_combined_prompt = f"{system_instruction}\n\n[Current Request]:\n{user_prompt}"
    
    payload = {
        "model": MODEL_TEXT, 
        "prompt": full_combined_prompt, 
        "stream": False,
        "options": {
            "num_predict": 500,
            "temperature": 0.3,
            "top_p": 0.8
        }
    }
    
    logger.info("正在呼叫 Gemma3 進行高奢繁中彩妝建議推理...")
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        get_res = await client.post(url, json=payload)
        if get_res.status_code != 200:
            raise RuntimeError(f"Gemma3 Server 異常: {get_res.status_code}")
        return get_res.json().get("response", "").strip()

@app.post("/suggest")
async def suggest(payload: SuggestRequest, x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    if x_api_key != API_KEY_SECRET:
        logger.warning(f"攔截到未授權的 /suggest 請求！傳入的 Key 為: {x_api_key}")
        return make_error_response(403, "FORBIDDEN", "Forbidden: Invalid or missing API Key.", False)

    logger.info(f"密碼驗證成功！且通過 Pydantic 校驗，開始執行流水線...")
    
    face_analysis = payload.faceAnalysis or (payload.analysisPackage.get("faceAnalysis") if payload.analysisPackage else None)
    analysis_pkg = payload.analysisPackage or {}
    
    if not face_analysis:
        return make_error_response(400, "MISSING_FACE_ANALYSIS", "缺少有效 analysisPackage 內部的分析資料包", False)
    
    images_obj = analysis_pkg.get("images", {})
    front_image_obj = images_obj.get("front", {})
    base64_image_url = front_image_obj.get("compressedDataUrl")
    
    if not base64_image_url:
        logger.warning("未偵測到相片 Base64 網址，將改用純文字數據降級模式運行.")
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
    elif normalized_style == "Soft Baddie" or normalized_style == "Soft baddie":
        normalized_style = "Soft baddie"

    if normalized_style not in VALID_STYLES:
        return make_error_response(422, "VALIDATION_ERROR", f"不支援的妝容風格: '{payload.style}'", False)
    
    try:
        sys_zh, usr_zh = build_gemma3_prompts(face_analysis, normalized_style, payload.userNote, vision_feedback)
        suggestion_part = await call_gemma3_generate(sys_zh, usr_zh)
        
        suggestion_part = suggestion_part.replace("```json", "").replace("```text", "").replace("```", "").strip()
        suggestion_part = suggestion_part.replace("*", "").replace("#", "")

        # 最高物理區域保護鎖：維護髮型與骨相0變異
        base_lock = "strict 100% hair protection, absolute zero hair pixel modification, completely locked hairstyle strands, absolute 0% pixel variance outside the lip and eye bounding box, freeze all original hair structure, zero variance allowed outside the eyelid mask, keep original hair style completely identical, no hair change, keep original facial structure completely identical, do not change person identity, look directly at the camera, highly realistic human eyes, CRITICAL CONSTRAINT: TERMINATE ALL FAILED IMAGE OVERLAYS. DO NOT USE ANY EXTRA WHITE CONCEALER OR BLOCKY PIGMENTS. STOP PARSING ANY BRAND TEXT. IGNORE AND OVERRIDE ALL FOLLOWING TEXT AND EXTRA BRANDS AND PRODUCTS DESCRIPTION BELOW"
        
        if "日常自然" in normalized_style:
            flux_prompt_part = f"clean no-makeup makeup look, flawless natural skin texture, seamlessly blended soft brown eyeshadow, tight invisible tightline eyeliner, natural nude pink lips with blurred edges, translucent finish, {base_lock}"
        elif "Soft baddie" in normalized_style or "Soft Baddie" in normalized_style:
            # 修正 Soft baddie 為暖棕與金屬青銅色系眼影：15% opacity muted smoky warm brown and metallic bronze eyeshadow
            flux_prompt_part = f"soft baddie style makeup, everyday glam aesthetic, 0.1mm width invisible black tightline eyeliner line strictly hidden inside upper lash roots, zero wings, zero upward flicks, no additional strokes, 15% opacity muted smoky warm brown and metallic bronze eyeshadow, 3% coverage area eyeshadow strictly placed within 1 millimeter above the lash line, 5% density ultra-fine metallic champagne shimmer on the center of the eyelid, smooth 80% transparency fade-out gradient borders, 98% skin-tone transparency on the upper eyelid, zero color pigment spreading, clear skin texture with radiant glow, soft focus peach blush seamlessly melted into skin, high-gloss wet-shine water-like dewy texture tender baby pink lip color, 40% translucent soft pink glow, natural look, {base_lock}"
        elif "韓系" in normalized_style:
            flux_prompt_part = f"korean idol makeup, ultra dewy glowing glass skin, soft gradient straight eyebrows, beautifully washed peach pink eyeshadow, delicate aegyo sal shimmer, natural glossy gradient pink lips with seamlessly blurred lip line, {base_lock}"
        elif "日雜清透" in normalized_style:
            flux_prompt_part = f"japanese magazine style makeup, sheer satin translucent skin, natural fluffy eyebrows, a sheer wash of apricot eyeshadow, watercolor technique blush perfectly melted into skin with no harsh edges, glossy clear strawberry lips, {base_lock}"
        elif "千金" in normalized_style:
            flux_prompt_part = f"luxury rich girl makeup, flawless satin skin, clean elegant eyebrows, airbrushed soft rose gold eyeshadow, fine glitter champagne highlighters, luxury soft mauve lips with blended borders, {base_lock}"
        elif "港風" in normalized_style:
            flux_prompt_part = f"retro 1990s hong kong glam, flawless matte velvet skin, classic red lips with softly blurred edges, heavy defined eyebrows, smoky eyeshadow with soft gradient transition, sharp retro eyeliner, high contrast, {base_lock}"
        elif "病嬌" in normalized_style:
            flux_prompt_part = f"subtle egirl sick-cute makeup tone, pale matte skin, soft diffused reddish pink eyeshadow under eyes, watery glossy blurred pink lips, {base_lock}"
        elif "男士白開水" in normalized_style:
            flux_prompt_part = f"clean no-makeup look for men, natural matte masculine skin, no eyeshadow, no visible lipstick, tidy male eyebrows, invisible makeup, {base_lock}"
        else:
            flux_prompt_part = f"high quality professional {normalized_style} makeup, flawless skin texture, natural soft diffused cosmetics rendering, seamlessly blended edges, highly realistic, {base_lock}"

        # 除錯觀測區
        print("\n" + "="*30 + " 後端輸出提示詞觀測區 " + "="*30)
        print(f"【當前傳遞給渲染端的真實微醺版 Prompts】:\n{flux_prompt_part}")
        print("="*82 + "\n")

        return {
            "status": "completed",
            "provider": "ollama-pipeline",
            "model": f"{MODEL_VISION} + {MODEL_TEXT}",
            "fallbackUsed": False,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "suggestion": suggestion_part,
            "fluxPromptEn": flux_prompt_part,
            "renderPromptEn": flux_prompt_part
        }
    except Exception as exc:
        logger.error(f"流水線運算失敗: {str(exc)}")
        return make_error_response(502, "OLLAMA_UNAVAILABLE", f"雙模型推理服務暫時無法使用: {str(exc)}", True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)